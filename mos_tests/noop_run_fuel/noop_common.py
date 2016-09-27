#    Copyright 2016 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging
import os
import random
import re
import yaml

from fuelclient.objects.task import Task as FuelTask

from mos_tests.functions import common


logger = logging.getLogger(__name__)


def run_noop_nodes_deploy(admin_remote, env, nodes):
    """This function executes 'deploy noop' for specified nodes"""
    # NOTE: API is not yet available
    node_ids = ' '.join(set(str(node.id) for node in nodes))
    cmd = "fuel2 env nodes deploy -e {0} -n {1} -f --noop".format(env.id,
                                                                  node_ids)
    output = admin_remote.check_call(cmd)['stdout'][0]
    # ex: Deployment task with id 13 for the nodes 1 within the environment 1
    # has been started.
    task_id = int(re.findall(r'Deployment task with id (\d+) ', output)[0])
    child_task = get_child_task(admin_remote, task_id)

    # pending -> running
    check_env_state_during_task(env, task=child_task, nodes=nodes)
    # running -> ready
    check_env_state_after_task(env, task=child_task, nodes=nodes)

    return child_task


def run_noop_env_deploy(admin_remote, env, command='deploy'):
    """This function executes 'deploy/redeploy noop' for the whole env"""
    # NOTE: API is not yet available
    if command == 'deploy':
        cmd = "fuel2 env deploy --noop --force {0}".format(env.id)
    else:
        cmd = "fuel2 env redeploy --noop {0}".format(env.id)
    output = admin_remote.check_call(cmd)['stdout'][0]
    # ex: Deployment task with id 23 for the environment 1 has been started.
    task_id = int(re.findall(r'Deployment task with id (\d+) ', output)[0])
    child_task = get_child_task(admin_remote, task_id)
    nodes = env.get_all_nodes()

    # pending -> running
    check_env_state_during_task(env, task=child_task)
    # running -> ready
    check_env_state_after_task(env, task=child_task, nodes=nodes)

    return child_task


def run_noop_graph_execute(admin_remote, env, nodes=None, g_type='default'):
    """This function executes 'graph noop'"""
    # NOTE: API is not yet available
    cmd = "fuel2 graph execute -t {0} -e {1} --force --noop".format(
        g_type, env.id)
    if nodes is not None:
        # duplicated ids are skipped
        node_ids = ' '.join(set(str(node.id) for node in nodes))
        cmd += " -n {0}".format(node_ids)
    output = admin_remote.check_call(cmd)['stdout'][0]
    task_id = int(re.findall(r'Deployment task with id (\d+) ', output)[0])
    child_task = get_child_task(admin_remote, task_id)
    nodes = nodes or env.get_all_nodes()

    # pending -> running
    check_env_state_during_task(env, task=child_task, nodes=nodes)
    # running -> ready
    check_env_state_after_task(env, task=child_task, nodes=nodes)

    return child_task


def get_child_task(admin_remote, parent_task_id, child_task_name='deployment'):
    """This function finds ID of the child task"""
    # ID of the child task should be max
    cmd = "fuel task list | grep {0}".format(child_task_name)
    cmd += " | awk '{print $1}'"  # split into 2 lines because of $1
    output = admin_remote.check_call(cmd).stdout_string
    child_task_id = max(map(int, output.split()))
    if child_task_id > parent_task_id:
        child_task = FuelTask(child_task_id)
    else:
        raise AssertionError("Unable to find child task for task id {0}"
                             .format(parent_task_id))
    return child_task


def create_and_upload_custom_graph(admin_remote, env, modify=None):
    """This function creates and uploads the custom graph.
    Custom graph can be copy of default graph (modify=None) or
    its copy without data for apache (modify='delete_apache')
    """

    # Download the default graph
    cmd = "fuel2 graph download -e {0} --all -t default".format(env.id)
    output = admin_remote.check_call(cmd).stdout_string
    # ex: Tasks were downloaded to /root/cluster_graph.yaml
    default_graph_file = re.findall(r'downloaded to (.*)$', output)[0]
    custom_graph_file = "/tmp/custom_graph.yaml"

    admin_remote.download(default_graph_file, custom_graph_file)
    with open(custom_graph_file) as f:
        graph_config = yaml.load(f)

    if modify == 'delete_apache':
        logger.info("Copying the default graph data to the custom ones "
                    "and deleting conditions with apache")
        new_graph_config = [g for g in graph_config if 'apache' not in
                            yaml.dump(g)]
    else:
        logger.info("Copying the default graph data to the custom ones")
        new_graph_config = graph_config

    with open(custom_graph_file, 'w') as f:
        f.write(yaml.dump(new_graph_config, default_flow_style=False))

    # Upload the custom graph
    admin_remote.upload(custom_graph_file, custom_graph_file)
    cmd = "fuel2 graph upload -t custom -e {0} -f {1}".format(
        env.id, custom_graph_file)
    output = admin_remote.check_call(cmd).stdout_string
    # ex: Deployment graph was successfully uploaded.
    assert "was successfully uploaded" in output

    # Check list of graphs
    cmd = "fuel2 graph list -f value -e {0}".format(env.id)
    output = admin_remote.check_call(cmd).stdout_string
    # 5 None allocate_hugepages, ... as "custom" to cluster(ID=1)
    assert 'as "custom" to cluster(ID={0})'.format(env.id) in output

    # Show differences
    cmd = "diff {0} {1}".format(default_graph_file, custom_graph_file)
    admin_remote.execute(cmd)


def are_nodes_in_state(env, nodes, expected_state):
    return all(x.data['status'] == expected_state
               for x in env.get_all_nodes() if x in nodes)


def check_env_state_during_task(env, task, nodes=None):
    """This function checks state of env and nodes after task starting"""
    common.wait(lambda: task.status == 'running', timeout_seconds=60,
                sleep_seconds=2, waiting_for='deployment task to be started')

    if nodes is not None:
        common.wait(lambda: are_nodes_in_state(env, nodes, 'deploying'),
                    timeout_seconds=60, sleep_seconds=2,
                    waiting_for='nodes in deploying state')

    assert env.status == 'operational', (
        "Env should be operational when noop run of fuel task is in progress, "
        "but current state is {0}".format(env.status))


def check_env_state_after_task(env, task, nodes):
    """This function checks state of env after task finishing"""
    common.wait(lambda: common.is_task_ready(task), timeout_seconds=60 * 120,
                sleep_seconds=30, waiting_for='deployment task to be finished')

    common.wait(lambda: are_nodes_in_state(env, nodes, 'ready'),
                timeout_seconds=60, sleep_seconds=2,
                waiting_for='nodes in ready state')

    assert env.status == 'operational', (
        "Env should be operational after noop run of fuel task execution, "
        "but current state is {0}".format(env.status))


def are_messages_in_summary_results(admin_remote, task_id, messages,
                                    is_expected=True):
    """This function checks that expected messages for correct nodes are
    present/missing in results of the noop run task

    :param admin_remote:
    :param task_id:
    :param messages: [(node_id1, msg1), (node_id2, msg2), ...]
    :param is_expected: True or False
    :return:
    """

    tmp_file = "/tmp/noop_results-{0}.txt".format(random.randint(1, 10000))
    cmd = "fuel deployment-tasks --tid {0} --include-summary > {1}".format(
        task_id, tmp_file)
    admin_remote.check_call(cmd)
    # NOTE: Results are written in tmp file because of big size
    #      (~ 4 Mbytes for every node). This solution is not optimal but
    #      anyway this function will be rewritten using API.

    admin_remote.download(tmp_file, tmp_file)
    admin_remote.check_call("rm {0}".format(tmp_file))

    logger.debug("Checking messages in results of noop run")
    found = dict.fromkeys(messages, False)
    with open(tmp_file, 'r') as f:
        for line in f:
            for node_id, message in messages:
                if not re.search("\| +{0} +\|".format(node_id), line):
                    # another node
                    continue
                if message in line:
                    found[(node_id, message)] = True
                    log_msg = ("Message for node {0} is found:\n{1}".
                               format(node_id, line.strip()))
                    if is_expected:
                        logger.info(log_msg)
                    else:
                        logger.error(log_msg)
            if all(found.values()):
                break
    for elem in messages:
        if not found[elem]:
            log_msg = ("Message for node {0} is not found:\n{1}".
                       format(elem[0], elem[1]))
            if is_expected:
                logger.error(log_msg)
            else:
                logger.info(log_msg)

    os.remove(tmp_file)
    return all(found.values())


def is_message_in_summary_results(admin_remote, task_id, node_id, message,
                                  is_expected=True):
    """This function checks that expected message for correct node is present/
    missing in results of the noop run task
    """
    return are_messages_in_summary_results(admin_remote, task_id,
                                           [(node_id, message)], is_expected)
