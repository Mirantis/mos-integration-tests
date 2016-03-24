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
from random import randint
import re

import pytest


logger = logging.getLogger(__name__)


def vars_config(remote):
    """Prepare variables and different paths
    :param remote: SSH connection point to controller.
    """
    config_vars = {
        'repo': 'https://github.com/dmitrymex/oslo.messaging-check-tool.git',
        'pkg': 'oslo.messaging-check-tool_1.0-1~u14.04+mos1_all.deb',
        'root_path': '/root/',
        'repo_path': '/root/oslo.messaging-check-tool/',
        'nova_user': 'nova'}
    config_vars['conf_file_path'] = '{}oslo_msg_check.conf'.format(
        config_vars['repo_path'])
    # get password of nova user (the same on all controllers)
    cmd = "grep '^rabbit_password' /etc/nova/nova.conf | awk '{print $3}'"
    config_vars['nova_pass'] = remote.check_call(cmd)['stdout'][0].strip()
    return config_vars


def install_oslomessagingchecktool(remote, **kwargs):
    """Install tool on controller
    https://github.com/dmitrymex/oslo.messaging-check-tool
    """
    cmd = ("apt-get update && "
           "apt-get install git python-pip -y && "
           "cd {root_path} && "
           "git clone {repo} && "
           "cd {repo_path} && "
           "pip install -r requirements.txt -r test-requirements.txt && "
           "dpkg -i {pkg} || "
           "apt-get -f install -y".format(root_path=kwargs['root_path'],
                                          repo=kwargs['repo'],
                                          repo_path=kwargs['repo_path'],
                                          pkg=kwargs['pkg']))
    logger.debug('Install "oslo.messaging-check-tool" on controller')
    return remote.check_call(cmd)


def configure_oslomessagingchecktool(remote, ctrl_ips, **kwargs):
    """Write configuration file on controller"""
    # Create config file for "oslo.messaging-check-tool"
    configs = (
        "[DEFAULT]\n"
        "debug=true\n"
        "[oslo_messaging_rabbit]\n"
        "rabbit_hosts = {rabbit_hosts}\n"
        "rabbit_userid = {nova_user}\n"
        "rabbit_password = {nova_pass}\n".format(
            rabbit_hosts=":5673, ".join(ctrl_ips),
            nova_user=kwargs['nova_user'],
            nova_pass=kwargs['nova_pass']))
    # Write config to file on controller
    logger.debug('Write "oslo.messaging-check-tool" config file to controller')
    with remote.open(kwargs['conf_file_path'], 'w') as f:
        f.write(configs)


def restart_rabbitmq_serv(env, remote=None, restart_all=False):
    """Restart rabbitmq-server service on one or all controllers
    :param env: Environment
    :param remote: SSH connection point to controller.
        Leave empty if you want to restart service on all controllers.
    :param restart_all: Set True to restart on service on all controllers.
    :return: None
    """
    restart_cmd = 'service rabbitmq-server restart'
    # if certain controller not set --> restart rabbitmq on all controllers
    if remote is None:
        restart_all = True
    # restart on one controller
    if remote is not None:
        logger.debug('Restart RabbinMQ server on one controller')
        remote.check_call(restart_cmd)
    # restart on all controllers
    if restart_all is True:
        controllers = env.get_nodes_by_role('controller')
        logger.debug('Restart RabbinMQ server on all controllers')
        for controller in controllers:
            with controller.ssh() as remote:
                remote.check_call(restart_cmd)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('838284')
def test_load_messages_and_restart_one_controller(env):
    """Load 10000 messages to RabbitMQ cluster and restart RabbitMQ
    on one controller.

    Actions:
    1. Install "oslo.messaging-check-tool" on controller;
    2. Prepare config file for it;
    3. Generate 10000 messages to RabbitMQ cluster;
    4. Restart RabbitMQ-server on one controller;
    5. Consume messages;
    6. Check that number of generated and consumed messages is equal.
    """
    controllers = env.get_nodes_by_role('controller')
    controller = controllers[(randint(0, len(controllers) - 1))]

    # Get IPs of all controllers
    ctrl_ips = []
    for one in controllers:
        with one.ssh() as remote:
            out = remote.check_call('hostname -i')['stdout'][0].strip()
            ctrl_ips.append(out)

    # Execute all on one controller
    with controller.ssh() as remote:
        kwargs = vars_config(remote)
        install_oslomessagingchecktool(remote, **kwargs)
        configure_oslomessagingchecktool(remote, ctrl_ips, **kwargs)

        # Generate messages
        num_of_msg_to_gen = 10000
        cmd = ('oslo_msg_load_generator --config-file {0} '
               '--messages-to-send {1} --nodebug'.format(
                    kwargs['conf_file_path'], num_of_msg_to_gen))
        remote.check_call(cmd)

        # Restart RabbinMQ server on one controller
        restart_rabbitmq_serv(env, remote=remote)

        # Consume generated messages
        cmd = 'oslo_msg_load_consumer --config-file {0} --nodebug'.format(
            kwargs['conf_file_path'])
        out_consume = remote.check_call(cmd)['stdout'][0]
        num_of_msg_consumed = re.findall('\d+', out_consume)[0]

    assert (num_of_msg_to_gen == num_of_msg_consumed,
            "generated != consumed\n"
            "{0} != {1}".format(
                num_of_msg_to_gen,
                num_of_msg_consumed))
