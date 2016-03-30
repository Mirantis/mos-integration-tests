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

import json
import logging
import random
import re
import sys

import pytest
from six.moves import configparser

from mos_tests.functions.common import wait
from mos_tests import settings


logger = logging.getLogger(__name__)


def vars_config(remote):
    """Prepare variables and different paths
    :param remote: SSH connection point to controller.
    """
    config_vars = {
        'repo': settings.RABBITOSLO_REPO,
        'pkg': settings.RABBITOSLO_PKG,
        'repo_path': '/root/oslo_messaging_check_tool/',
        'nova_user': 'nova'}
    # like: /root/oslo_messaging_check_tool/oslo_msg_check.conf
    config_vars['cfg_file_path'] = '{}oslo_msg_check.conf'.format(
        config_vars['repo_path'])
    config_vars['sample_cfg_file_path'] = '{}oslo_msg_check.conf.sample'.\
        format(config_vars['repo_path'])
    # get password of nova user (the same on all controllers)
    cmd = "grep '^rabbit_password' /etc/nova/nova.conf | awk '{print $3}'"
    config_vars['nova_pass'] = remote.check_call(cmd)['stdout'][0].strip()
    return config_vars


def install_oslomessagingchecktool(remote, **kwargs):
    """Install 'oslo.messaging-check-tool' on controller.
    https://github.com/dmitrymex/oslo.messaging-check-tool
    :param remote: SSH connection point to controller
    """
    cmd1 = ("apt-get update ; "
            "apt-get install git python-pip python-dev -y && "
            "rm -rf {repo_path} && "
            "git clone {repo} {repo_path} && "
            "cd {repo_path} && "
            "pip install -r requirements.txt -r test-requirements.txt ;"
            ).format(**kwargs)
    cmd2 = ("cd {repo_path} && "
            "dpkg -i {pkg} || "
            "apt-get -f install -y").format(**kwargs)
    logger.debug('Install "oslo.messaging-check-tool" on controller %s.' %
                 remote.host)
    remote.check_call(cmd1)
    remote.check_call(cmd2)


def configure_oslomessagingchecktool(remote, ctrl_ips, nova_user, nova_pass,
                                     cfg_file_path, sample_cfg_file_path):
    """Write configuration file on controller.
    :param remote: SSH connection point to controller;
    :param ctrl_ips: List of controllers IPs;
    :param nova_user: Name of Rabbit admin;
    :param nova_pass: Password of Rabbit admin;
    :param cfg_file_path: Path where config file will be written;
    :param sample_cfg_file_path: Path for sample config file.
    """
    rabbit_port = ':5673'
    rabbit_hosts = ', '.join([(x + rabbit_port) for x in ctrl_ips])

    with remote.open(sample_cfg_file_path, 'r') as f:
        parser = configparser.RawConfigParser()
        parser.readfp(f)
        parser.set('oslo_messaging_rabbit', 'rabbit_hosts', rabbit_hosts)
        parser.set('oslo_messaging_rabbit', 'rabbit_userid', nova_user)
        parser.set('oslo_messaging_rabbit', 'rabbit_password', nova_pass)
        # Dump to cfg file to screen
        parser.write(sys.stdout)
        logger.debug('Write [{0}] config file to controller {1}.'.format(
            cfg_file_path, remote.host))
        # Write to new cfg file
        with remote.open(cfg_file_path, 'w') as new_f:
            parser.write(new_f)


def get_api_info(remote, api_path):
    """RabbitMQ HTTP API.
    Not stable in case of usage right after rabbit service restart
    """
    cmd = ('curl -u {nova_user}:{nova_pass} '
           'http://localhost:15672/api/{api_path}').format(
                api_path=api_path, **vars_config(remote))
    out = remote.check_call(cmd)['stdout']
    return json.loads(out[0])


def disable_enable_all_eth_interf(remote, sleep_sec=60):
    """Shutdown all eth interfaces on node and after sleep enable them back"""
    logger.debug('Stop/Start all eth interfaces on %s.' % remote.host)

    # Partial WA for interfaces down/up.
    #   https://bugs.launchpad.net/fuel/+bug/1563321
    cmd = 'ip route show | grep default'
    def_route = remote.check_call(cmd)['stdout'][0].strip()

    cmd = ("list_eth=$(ip link show|grep 'state UP'|awk -F': ' '{print $2}'); "
           "for i in $list_eth; do ifconfig $i down; done ; "
           "sleep %s ; "
           "for i in $list_eth; do ifconfig $i up; done ; "
           "ip -s -s neigh flush all ; "
           "ip route add %s ;") % (sleep_sec, def_route)
    # "ip route add ..." partial WA for
    #   https://bugs.launchpad.net/fuel/+bug/1563321
    remote.execute_async(cmd)


def restart_rabbitmq_serv(env, remote=None, sleep=10):
    """Restart rabbitmq-server service on one or all controllers.
    After each restart, check that rabbit is up and running.
    :param env: Environment
    :param remote: SSH connection point to controller.
        Leave empty if you want to restart service on all controllers.
    :param sleep: Seconds to wait after service restart
    """
    # 'sleep' is to wait for service startup. It'll be also checked later
    restart_cmd = 'service rabbitmq-server restart && sleep %s' % sleep
    controllers = env.get_nodes_by_role('controller')
    if remote is None:
        # restart on all controllers
        logger.debug('Restart RabbinMQ server on ALL controllers one-by-one')
        for controller in controllers:
            with controller.ssh() as remote:
                remote.check_call(restart_cmd)
                wait_for_rabbit_running_nodes(remote, len(controllers))
    else:
        # restart on one controller
        logger.debug('Restart RabbinMQ server on ONE controller %s.' %
                     remote.host)
        remote.check_call(restart_cmd)
        wait_for_rabbit_running_nodes(remote, len(controllers))


def num_of_rabbit_running_nodes(remote, timeout_min=5):
    """Get number of 'running_nodes' from 'rabbitmqctl cluster_status'
    :param remote: SSH connection point to controller.
    :param timeout_min: Timeout in minutes to wait for successful cmd execution
    """
    def rabbit_status():
        result = remote.execute('rabbitmqctl cluster_status')
        if result.is_ok and 'running_nodes' in result.stdout_string:
            return result['stdout']

    out = wait(rabbit_status,
               timeout_seconds=60 * timeout_min,
               sleep_seconds=20,
               waiting_for='RabbitMQ service start.')
    # Parse output to get only list with 'running_nodes'
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
    wait(lambda: num_of_rabbit_running_nodes(remote) == exp_nodes,
         timeout_seconds=60 * timeout_min,
         sleep_seconds=20,
         waiting_for='number of running nodes will be %s.' % exp_nodes)


def generate_msg(remote, cfg_file_path, num_of_msg_to_gen=10000):
    """Generate messages with oslo_msg_load_generator
    :param remote: SSH connection point to controller.
    :param cfg_file_path: Path to the config file.
    :param num_of_msg_to_gen: How many messages to generate.
    """
    cmd = ('oslo_msg_load_generator '
           '--config-file {0} '
           '--messages-to-send {1} '
           '--nodebug'.format(
                cfg_file_path, num_of_msg_to_gen))
    remote.check_call(cmd)


def consume_msg(remote, cfg_file_path):
    """Consume messages with oslo_msg_load_consumer
    :param remote: SSH connection point to controller.
    :param cfg_file_path: Path to the config file.
    """
    cmd = ('oslo_msg_load_consumer '
           '--config-file {0} '
           '--nodebug'.format(cfg_file_path))
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
    :param restart_controllers: Restart all OR one conrtoller.

    Actions:
    1. Install "oslo.messaging-check-tool" on controller;
    2. Prepare config file for it;
    3. Generate 10000 messages to RabbitMQ cluster;
    4. Restart RabbitMQ-server on one/all controller(s);
        If all - restart will be one-by-one, not all together.
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

    # Install tool on one controller and generate messages
    with controller.ssh() as remote:
        kwargs = vars_config(remote)
        install_oslomessagingchecktool(remote, **kwargs)
        configure_oslomessagingchecktool(
            remote, ctrl_ips, kwargs['nova_user'], kwargs['nova_pass'],
            kwargs['cfg_file_path'], kwargs['sample_cfg_file_path'])

        # Generate messages
        num_of_msg_to_gen = 10000
        generate_msg(remote, kwargs['cfg_file_path'], num_of_msg_to_gen)

        # Restart RabbinMQ server on one/all controller
        if restart_controllers == 'one':
            restart_rabbitmq_serv(env, remote=remote)
        elif restart_controllers == 'all':
            restart_rabbitmq_serv(env, remote=None)

        # Consume generated messages
        num_of_msg_consumed = consume_msg(remote, kwargs['cfg_file_path'])

    assert num_of_msg_to_gen == num_of_msg_consumed, \
        ('Generated and consumed number of messages is different for restart '
         'of %s controller(s).' % restart_controllers)


# Because of https://bugs.launchpad.net/fuel/+bug/1563321 it is DESTRUCTIVE
# For e.g. "pcs resource" is not working after test below.
# @pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('838286')
def test_load_messages_and_shutdown_eth_on_all(env):
    """Load 10000 messages to RabbitMQ cluster and shutdown eth interfaces on
    all controllers.

    :param env: Environment
    :return:

    Actions:
    1. Install "oslo.messaging-check-tool" on controller;
    2. Prepare config file for it;
    3. Generate 10000 messages to RabbitMQ cluster;
    4. Stop all eth interfaces on all controllers and wait several minutes;
    5. Start all eth interfaces on all controllers;
    6. Consume messages;
    7. Check that number of generated and consumed messages is equal.
    """
    sleep_min = 2  # (minutes) Time to shutdown eth interfaces on controllers
    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)

    # Get IPs of all controllers
    ctrl_ips = []
    for one in controllers:
        ip = [x['ip'] for x in one.data['network_data']
              if x['name'] == 'management'][0]
        ip = ip.split("/")[0]
        ctrl_ips.append(ip)

    # Install tool on one controller and generate messages
    with controller.ssh() as remote:
        kwargs = vars_config(remote)
        install_oslomessagingchecktool(remote, **kwargs)
        configure_oslomessagingchecktool(
            remote, ctrl_ips, kwargs['nova_user'], kwargs['nova_pass'],
            kwargs['cfg_file_path'], kwargs['sample_cfg_file_path'])
        # Generate messages
        num_of_msg_to_gen = 10000
        generate_msg(remote, kwargs['cfg_file_path'], num_of_msg_to_gen)

    # Shutdown all eth interfaces on all nodes and after sleep enable them
    for one in controllers:
        with one.ssh() as one_remote:
            disable_enable_all_eth_interf(one_remote,
                                          sleep_min * 60)

    # Wait when eth interface on controllers will be alive
    wait(lambda: controller.is_ssh_avaliable() is True,
         timeout_seconds=60 * (sleep_min + 2),
         sleep_seconds=30,
         waiting_for='controller to be available.')

    # Consume generated messages
    with controller.ssh() as remote:
        kwargs = vars_config(remote)
        num_of_msg_consumed = consume_msg(remote, kwargs['cfg_file_path'])

    assert num_of_msg_to_gen == num_of_msg_consumed, \
        ('Generated and consumed number of messages is different '
         'after eth interfaces shutdown.')
