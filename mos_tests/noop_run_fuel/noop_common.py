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

from fuelclient.objects.task import Task as FuelTask

from mos_tests.functions import common


logger = logging.getLogger(__name__)


def run_noop_nodes_deploy(admin_remote, env, nodes):
    """This function executes 'deploy noop' for specified nodes"""
    # NOTE: API is not yet available
    node_ids = ' '.join(str(node.id) for node in nodes)
    cmd = "fuel2 env nodes deploy -e {0} -n {1} -f --noop".format(env.id,
                                                                  node_ids)
    output = admin_remote.check_call(cmd)['stdout'][0]
    # ex: Deployment task with id 13 for the nodes 1 within the environment 1
    # has been started.
    task_id = int(re.findall(r'Deployment task with id (\d+) ', output)[0])
    task = FuelTask(task_id)

    check_env_state_during_task(env, task, nodes)
    check_env_state_after_task(env, task)

    return task


def run_noop_graph_execute(admin_remote, env, nodes=None, g_type='default'):
    """This function executes 'graph noop'"""
    # NOTE: API is not yet available
    cmd = "fuel2 graph execute -t {0} -e {1} -f --noop".format(g_type, env)
    if nodes is not None:
        nodes = ' '.join(str(i) for i in nodes)
        cmd = cmd + " -n {0}".format(nodes)
    output = admin_remote.check_call(cmd)['stdout'][0]
    task_id = int(re.findall(r'Deployment task with id (\d+) ', output)[0])
    task = FuelTask(task_id)

    check_env_state_after_task(env, task)

    return task


def check_env_state_during_task(env, task, nodes):
    """This function checks state of env and nodes after task starting"""
    common.wait(lambda: task.status == 'running', timeout_seconds=60,
                sleep_seconds=2, waiting_for='deploy task to be started')
    assert env.status == 'operational', (
        "Env should be operational when noop run of fuel task is in progress, "
        "but current state is {0}".format(env.status))
    for node in nodes:
        assert node.data['status'] == 'ready'


def check_env_state_after_task(env, task):
    """This function checks state of env after task finishing"""
    common.wait(lambda: common.is_task_ready(task), timeout_seconds=60 * 120,
                sleep_seconds=30, waiting_for='deploy task to be finished')
    assert env.status == 'operational', (
        "Env should be operational after noop run of fuel task execution, "
        "but current state is {0}".format(env.status))


def are_messages_in_summary_results(admin_remote, task_id, expected_messages):
    """This function checks that expected messages for correct nodes are
    present in results of the noop run task

    :param admin_remote:
    :param task_id:
    :param expected_messages: [(node_id1, msg1), (node_id2, msg2), ...]
    :return:
    """

    tmp_file = "/tmp/noop_results-{0}.txt".format(random.randint(1, 10000))
    cmd = "fuel deployment-tasks --tid {0} --include-summary > {1}".format(
        task_id, tmp_file)
    admin_remote.check_call(cmd)
    # NOTE: Results are written in tmp file because of big size
    #      (~ 4 Mbytes for every node). This solution is not optimal but
    #      anyway this function will be updated using API.

    admin_remote.download(tmp_file, tmp_file)
    admin_remote.check_call("rm {0}".format(tmp_file))

    logger.debug("Checking expected messages in results of noop run")
    found = dict.fromkeys(expected_messages, False)
    with open(tmp_file, 'r') as f:
        for line in f:
            for node_id, expected_message in expected_messages:
                if not re.search("\| +{0} +\|".format(node_id), line):
                    # another node
                    continue
                if expected_message in line:
                    found[(node_id, expected_message)] = True
                    logger.debug(line.strip())
            if all(found.values()):
                break
    for elem in expected_messages:
        if not found[elem]:
            logger.error("Expected message for node {0} is not found:\n{1}".
                         format(elem[0], elem[1]))

    os.remove(tmp_file)
    return all(found.values())


def is_message_in_summary_results(admin_remote, task_id, node_id,
                                  expected_message):
    """This function checks that expected message for correct node is present
    in results of the noop run task
    """
    return are_messages_in_summary_results(admin_remote, task_id,
                                           [(node_id, expected_message)])
