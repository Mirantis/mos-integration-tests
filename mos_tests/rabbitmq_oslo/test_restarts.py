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
import random
import re
import time

import pytest

from mos_tests import settings


logger = logging.getLogger(__name__)


def vars_config(remote):
    """Prepare variables and different paths
    :param remote: SSH connection point to controller.
    """
    config_vars = {
        'repo': settings.RABBITOSLO_REPO,
        'pkg': settings.RABBITOSLO_PKG,
        'root_path': '/root/',
        'nova_user': 'nova'}
    # like: /root/oslo.messaging-check-tool/
    config_vars['repo_path'] = '{0}{1}/'.format(
        config_vars['root_path'], config_vars['repo'].split('/')[-1][:-4])
    # like: /root/oslo.messaging-check-tool/oslo_msg_check.conf
    config_vars['conf_file_path'] = '{}oslo_msg_check.conf'.format(
        config_vars['repo_path'])
    # get password of nova user (the same on all controllers)
    cmd = "grep '^rabbit_password' /etc/nova/nova.conf | awk '{print $3}'"
    config_vars['nova_pass'] = remote.check_call(cmd)['stdout'][0].strip()
    return config_vars


def install_oslomessagingchecktool(remote, **kwargs):
    """Install 'oslo.messaging-check-tool' on controller.
    https://github.com/dmitrymex/oslo.messaging-check-tool
    :param remote: SSH connection point to controller
    """
    cmd = ("apt-get update && "
           "apt-get install git python-pip python-dev -y && "
           "cd {root_path} && "
           "git clone {repo} && "
           "cd {repo_path} && "
           "pip install -r requirements.txt -r test-requirements.txt && "
           "dpkg -i {pkg} || "
           "apt-get -f install -y".format(**kwargs))
    logger.debug('Install "oslo.messaging-check-tool" on controller')
    return remote.check_call(cmd)


def configure_oslomessagingchecktool(remote, ctrl_ips, nova_user, nova_pass,
                                     conf_file_path):
    """Write configuration file on controller
    :param remote: SSH connection point to controller;
    :param ctrl_ips: List of controllers IPs;
    :param nova_user: Name of Rabbit admin;
    :param nova_pass: Password of Rabbit admin;
    :param conf_file_path: Path where config file will be written.
    """
    # Create config file for "oslo.messaging-check-tool"
    configs = (
        "[DEFAULT]\n"
        "debug=true\n"
        "[oslo_messaging_rabbit]\n"
        "rabbit_hosts = {rabbit_hosts}\n"
        "rabbit_userid = {nova_user}\n"
        "rabbit_password = {nova_pass}\n".format(
            rabbit_hosts=', '.join([(x + ':5673') for x in ctrl_ips]),
            nova_user=nova_user,
            nova_pass=nova_pass))
    # Write config to file on controller
    logger.debug('Write "oslo.messaging-check-tool" config file to controller')
    with remote.open(conf_file_path, 'w') as f:
        f.write(configs)


def restart_rabbitmq_serv(env, remote=None, sleep=10):
    """Restart rabbitmq-server service on one or all controllers.
    After each restart, check that rabbit is up and running.
    :param env: Environment
    :param remote: SSH connection point to controller.
        Leave empty if you want to restart service on all controllers.
    :param sleep: Seconds to wait after service restart
    """
    # 'sleep' is to wait for service startup. I'll be also checked later
    restart_cmd = 'service rabbitmq-server restart && sleep %s' % sleep
    controllers = env.get_nodes_by_role('controller')
    if remote is None:
        # restart on all controllers
        logger.debug('Restart RabbinMQ server on all controllers one-by-one')
        for controller in controllers:
            with controller.ssh() as remote:
                remote.check_call(restart_cmd)
                wait_for_rabbit_running_nodes(remote, len(controllers))
    else:
        # restart on one controller
        logger.debug('Restart RabbinMQ server on one controller')
        remote.check_call(restart_cmd)
        wait_for_rabbit_running_nodes(remote, len(controllers))


def num_of_rabbit_running_nodes(remote, timeout_min=5):
    """Get number of 'running_nodes' from 'rabbitmqctl cluster_status'
    :param remote: SSH connection point to controller.
    :param timeout_min: Timeout in minutes to wait for successful cmd execution
    """
    timeout = time.time() + 60 * timeout_min
    cmd = 'rabbitmqctl cluster_status'
    while True:
        out = remote.execute(cmd)
        if out['exit_code'] == 0 and 'running_nodes' in ''.join(out['stdout']):
            break
        elif time.time() > timeout:
            raise AssertionError('Timeout: "rabbitmqctl cluster_status"')
        time.sleep(15)
    # Parse output to get only list with 'running_nodes'
    out = out['stdout']
    out = map(str.strip, out)
    out = out[1:]
    out = ''.join(out)
    out = re.sub('["\']', '', out)
    running_nodes = re.findall('{running_nodes,\[(.*?)\]}', out)
    running_nodes = running_nodes[0].split(',')
    return len(running_nodes)


def wait_for_rabbit_running_nodes(remote, exp_nodes, timeout_min=5):
    """Waits until number of 'running_nodes' from 'rabbitmqctl cluster_status'
    will be as expected number of controllers.
    :param remote: SSH connection point to controller.
    :param exp_nodes: Expected number of rabbit nodes.
    :param timeout_min: Timeout in minutes to wait.
    """
    timeout = time.time() + 60 * timeout_min
    while True:
        running_nodes = num_of_rabbit_running_nodes(remote, timeout_min)
        logger.debug('Get running rabbit nodes. [Got: {0}, Exp: {1}]'.format(
            running_nodes, exp_nodes))
        if running_nodes == exp_nodes:
            break
        elif time.time() > timeout:
            raise AssertionError('Expected RabbitMQ running nodes is {0}.\n'
                                 'Current is {1}'.format(exp_nodes,
                                                         running_nodes))
        time.sleep(15)


def generate_msg(remote, conf_file_path, num_of_msg_to_gen=10000):
    """Generate messages with oslo_msg_load_generator
    :param remote: SSH connection point to controller.
    :param conf_file_path: Path to the config file.
    :param num_of_msg_to_gen: How many messages to generate.
    """
    cmd = ('oslo_msg_load_generator '
           '--config-file {0} '
           '--messages-to-send {1} '
           '--nodebug'.format(
                conf_file_path, num_of_msg_to_gen))
    remote.check_call(cmd)


def consume_msg(remote, conf_file_path):
    """Consume messages with oslo_msg_load_consumer
    :param remote: SSH connection point to controller.
    :param conf_file_path: Path to the config file.
    """
    cmd = ('oslo_msg_load_consumer '
           '--config-file {0} '
           '--nodebug'.format(conf_file_path))
    out_consume = remote.check_call(cmd)['stdout'][0]
    num_of_msg_consumed = int(re.findall('\d+', out_consume)[0])
    return num_of_msg_consumed


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('838284', params={'restart_controllers': 'one'})
@pytest.mark.testrail_id('838285', params={'restart_controllers': 'all'})
@pytest.mark.parametrize('restart_controllers', ['one', 'all'])
def test_load_messages_and_restart_one_all_controller(
        restart_controllers, env):
    """Load 10000 messages to RabbitMQ cluster and restart RabbitMQ
    on one/all controller(s).

    :param env: Environment
    :param restart_controllers: Restart all or one conrtoller.

    Actions:
    1. Install "oslo.messaging-check-tool" on controller;
    2. Prepare config file for it;
    3. Generate 10000 messages to RabbitMQ cluster;
    4. Restart RabbitMQ-server on one/all controller(s);
    5. Wait until RabbitMQ service will be up and cluster synchronised;
    6. Consume messages;
    7. Check that number of generated and consumed messages is equal.

    In case of all controllers restart we have a bug:
    https://bugs.launchpad.net/mos/+bug/1561894
    """
    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)

    # Get IPs of all controllers
    ctrl_ips = []
    for one in controllers:
        ip = [x['ip'] for x in one.data['network_data']
              if x['name'] == 'management'][0]
        ip = ip.split("/")[0]
        ctrl_ips.append(ip)

    # Execute everything on one controller
    with controller.ssh() as remote:
        kwargs = vars_config(remote)
        install_oslomessagingchecktool(remote, **kwargs)
        configure_oslomessagingchecktool(
            remote, ctrl_ips, kwargs['nova_user'], kwargs['nova_pass'],
            kwargs['conf_file_path'], )

        # Generate messages
        num_of_msg_to_gen = 10000
        generate_msg(remote, kwargs['conf_file_path'], num_of_msg_to_gen)

        # Restart RabbinMQ server on one/all controller
        if restart_controllers == 'one':
            restart_rabbitmq_serv(env, remote=remote)
        elif restart_controllers == 'all':
            restart_rabbitmq_serv(env)

        # Consume generated messages
        num_of_msg_consumed = consume_msg(remote, kwargs['conf_file_path'])

    assert num_of_msg_to_gen == num_of_msg_consumed, \
        ('Generated and consumed number of messages is different for restart '
         'of %s controller(s).' % restart_controllers)
