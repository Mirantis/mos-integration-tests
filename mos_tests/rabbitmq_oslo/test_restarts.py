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
import requests
import sys

import pytest
from six.moves import configparser
from six.moves import range

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
            "apt-get install git dpkg-dev debhelper dh-systemd "
            "openstack-pkg-tools po-debconf python-all python-pbr "
            "python-setuptools python-sphinx python-babel "
            "python-eventlet python-flask python-oslo.config "
            "python-oslo.log python-oslo.messaging python-oslosphinx -y && "
            "rm -rf {repo_path} && "
            "git clone {repo} {repo_path} ;").format(**kwargs)
    cmd2 = ("cd {repo_path} && "
            "dpkg -i {pkg} || "
            "apt-get -f install -y").format(**kwargs)
    logger.debug('Install "oslo.messaging-check-tool" on %s.' %
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
        logger.debug('Write [{0}] config file to {1}.'.format(
            cfg_file_path, remote.host))
        # Write to new cfg file
        with remote.open(cfg_file_path, 'w') as new_f:
            parser.write(new_f)


def get_api_info(remote, api_path, host='localhost', port='15672'):
    """RabbitMQ HTTP API.
    Not stable in case of usage right after rabbit service restart
    """
    cmd = ('curl -u {nova_user}:{nova_pass} '
           'http://{host}:{port}/api/{api_path}').format(
                api_path=api_path, host=host, port=port, **vars_config(remote))
    out = remote.check_call(cmd)['stdout']
    return json.loads(out[0])


def get_mngmnt_ip_of_ctrllrs(env):
    """Get host IP of management network from all controllers"""
    controllers = env.get_nodes_by_role('controller')
    ctrl_ips = []
    for one in controllers:
        ip = [x['ip'] for x in one.data['network_data']
              if x['name'] == 'management'][0]
        ip = ip.split("/")[0]
        ctrl_ips.append(ip)
    return ctrl_ips


def disable_enable_all_eth_interf(remote, sleep_sec=60):
    """Shutdown all eth interfaces on node and after sleep enable them back"""
    logger.debug('Stop/Start all eth interfaces on %s.' % remote.host)
    background = '<&- >/dev/null 2>&1 &'
    cmd = ('(ifdown -a ; ip -s -s neigh flush all ; '
           'sleep {0} ; ifup -a) {1}'.format(
                sleep_sec, background))
    remote.execute(cmd)


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
                # Before and after restart check that rabbit is ok.
                # Useful if we as restarting all controllers.
                wait_for_rabbit_running_nodes(remote, len(controllers))
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
        result = remote.execute('rabbitmqctl cluster_status', verbose=False)
        if result.is_ok and 'running_nodes' in result.stdout_string:
            return result['stdout']

    out = wait(rabbit_status,
               timeout_seconds=60 * timeout_min,
               sleep_seconds=30,
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
         sleep_seconds=30,
         waiting_for='number of running nodes will be %s.' % exp_nodes)


def generate_msg(remote, cfg_file_path, num_of_msg_to_gen=10000):
    """Generate messages with oslo_msg_load_generator
    :param remote: SSH connection point to controller.
    :param cfg_file_path: Path to the config file.
    :param num_of_msg_to_gen: How many messages to generate.
    """
    # Clean if some messages were left after previous failed tests
    cmd = ('oslo_msg_load_consumer '
           '--config-file {0} '
           '--nodebug'.format(cfg_file_path))
    remote.execute(cmd)
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


def rabbit_rpc_server_start(remote, cfg_file_path):
    logger.debug('Start [oslo_msg_check_server] on %s.' % remote.host)
    background = '<&- >/dev/null 2>&1 &'
    cmd = 'oslo_msg_check_server --nodebug --config-file {0} {1}'.format(
        cfg_file_path, background)
    remote.execute(cmd)


def rabbit_rpc_client_start(remote, cfg_file_path):
    logger.debug('Start [oslo_msg_check_client] on %s.' % remote.host)
    background = '<&- >/dev/null 2>&1 &'
    cmd = 'oslo_msg_check_client --nodebug --config-file {0} {1}'.format(
        cfg_file_path, background)
    remote.execute(cmd)
    return remote.host


def get_http_code(host_ip, port=5000):
    # curl to client
    url = 'http://{host}:{port}'.format(host=host_ip, port=port)
    try:  # server may not be ready yet
        status_code = requests.get(url).status_code
        return status_code
    except Exception:
        return False


def wait_rabbit_ok_on_all_ctrllrs(env, timeout_min=7):
    """Wait untill rabbit will be OK on all controllers"""
    controllers = env.get_nodes_by_role('controller')
    for one in controllers:
        with one.ssh() as remote:
            wait_for_rabbit_running_nodes(
                remote, len(controllers), timeout_min=timeout_min)


def kill_rabbitmq_on_node(remote, timeout_min=7):
    """Waiting for rabbit startup and got pid, then kill-9 it"""
    def get_pid():
        cmd = "rabbitmqctl status | grep '{pid' | tr -dc '0-9'"
        try:
            return remote.check_call(cmd)['stdout'][0].strip()
        except Exception:
            return None
    wait(get_pid,
         timeout_seconds=60 * timeout_min,
         sleep_seconds=30,
         waiting_for='Rabbit get its pid on %s.' % remote.host)
    cmd = "kill -9 %s" % get_pid()
    remote.check_call(cmd)

# ----------------------------------------------------------------------------


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

    # Get management IPs of all controllers
    ctrl_ips = get_mngmnt_ip_of_ctrllrs(env)

    # Install tool on one controller and generate messages
    with controller.ssh() as remote:
        kwargs = vars_config(remote)
        # wait when rabbit will be ok after snapshot revert
        wait_for_rabbit_running_nodes(remote, len(controllers))
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
    6. Wait until RabbitMQ service will be up and cluster synchronised;
    7. Consume messages;
    8. Check that number of generated and consumed messages is equal.
    """
    sleep_min = 2  # (minutes) Time to shutdown eth interfaces on controllers
    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)

    # Get management IPs of all controllers
    ctrl_ips = get_mngmnt_ip_of_ctrllrs(env)

    # Install tool on one controller and generate messages
    with controller.ssh() as remote:
        kwargs = vars_config(remote)
        # wait when rabbit will be ok after snapshot revert
        wait_for_rabbit_running_nodes(remote, len(controllers))
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

    # Wait when rabbit will be ok after interfaces down/up
    with controller.ssh() as remote:
        wait_for_rabbit_running_nodes(remote, len(controllers))

    # Consume generated messages
    with controller.ssh() as remote:
        kwargs = vars_config(remote)
        num_of_msg_consumed = consume_msg(remote, kwargs['cfg_file_path'])

    assert num_of_msg_to_gen == num_of_msg_consumed, \
        ('Generated and consumed number of messages is different '
         'after eth interfaces shutdown.')


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('838288', params={'restart_ctrlr': 'primary'})
@pytest.mark.testrail_id('838287', params={'restart_ctrlr': 'non_primary'})
@pytest.mark.parametrize('restart_ctrlr', ['primary', 'non_primary'])
def test_load_messages_and_restart_prim_nonprim_ctrlr(restart_ctrlr, env):
    """Load 10000 messages to RabbitMQ cluster and restart primary OR
    non-primary controller.

    Actions:
    1. Install "oslo.messaging-check-tool" on primary OR non-primary ctrllr;
    2. Prepare config file for it;
    3. Generate 10000 messages to RabbitMQ cluster;
    4. Restart RabbitMQ-server on primary OR non-primary controller;
    5. Wait until RabbitMQ service will be up and cluster synchronised;
    6. Consume messages;
    7. Check that number of generated and consumed messages is equal.
    """
    controllers = env.get_nodes_by_role('controller')
    if restart_ctrlr == 'primary':
        controller = env.primary_controller
    elif restart_ctrlr == 'non_primary':
        controller = random.choice(env.non_primary_controllers)

    # Get management IPs of all controllers
    ctrl_ips = get_mngmnt_ip_of_ctrllrs(env)

    # Install tool on one controller and generate messages
    with controller.ssh() as remote:
        kwargs = vars_config(remote)
        # wait when rabbit will be ok after snapshot revert
        wait_for_rabbit_running_nodes(remote, len(controllers))
        install_oslomessagingchecktool(remote, **kwargs)
        configure_oslomessagingchecktool(
            remote, ctrl_ips, kwargs['nova_user'], kwargs['nova_pass'],
            kwargs['cfg_file_path'], kwargs['sample_cfg_file_path'])
        # Generate messages
        num_of_msg_to_gen = 10000
        generate_msg(remote, kwargs['cfg_file_path'], num_of_msg_to_gen)

        # Restart RabbinMQ server on (non)primary controller
        restart_rabbitmq_serv(env, remote=remote)

        # Consume generated messages
        num_of_msg_consumed = consume_msg(remote, kwargs['cfg_file_path'])

    assert num_of_msg_to_gen == num_of_msg_consumed, \
        ('Generated and consumed number of messages is different for restart '
         'of %s controller.' % restart_ctrlr)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('838289', params={'restart_ctrlr': 'one'})
@pytest.mark.testrail_id('838290', params={'restart_ctrlr': 'all'})
@pytest.mark.testrail_id('838293', params={'restart_ctrlr': 'prim'})
@pytest.mark.testrail_id('838292', params={'restart_ctrlr': 'non_prim'})
@pytest.mark.parametrize('restart_ctrlr', ['one', 'all', 'prim', 'non_prim'])
def test_start_rpc_srv_client_restart_rabbit_one_all_ctrllr(
        env, restart_ctrlr, fixt_open_5000_port_on_nodes,
        fixt_kill_rpc_server_client):
    """Tests:
    Start RabbitMQ RPC server and client and restart RabbitMQ on one controller
    Start RabbitMQ RPC server and client and restart RabbitMQ on all
        controllers one-by-one.

    Actions:
    1. Install "oslo.messaging-check-tool" on controller and compute;
    2. Prepare config file for both nodes above;
    3. Run 'oslo_msg_check_client' on compute node;
    4. Run 'oslo_msg_check_server' on controller node;
    5. To be able to use port 5000 from any node open it in IPTables;
    6. Send GET curl request from any node to 'oslo_msg_check_client'
        located on compute node and check that response will '200';
    7. Restart RabbitMQ-server on one OR all controller(s) one-by-one;
    8. Wait until RabbitMQ service will be up and cluster synchronised;
    9. Send GET curl request from any node to 'oslo_msg_check_client'
        located on compute node and check that response will '200';
    10. Remove rule from step (5) from IPTables.
    """
    exp_resp = 200   # expected response code from curl from RPC client
    timeout_min = 2  # (minutes) time to wait for RPC server/client start

    controllers = env.get_nodes_by_role('controller')
    compute = random.choice(env.get_nodes_by_role('compute'))

    if restart_ctrlr == 'prim':
        controller = env.primary_controller
    elif restart_ctrlr == 'non_prim':
        controller = random.choice(env.non_primary_controllers)
    else:
        controller = random.choice(controllers)

    # Get management IPs of all controllers
    ctrl_ips = get_mngmnt_ip_of_ctrllrs(env)

    # Install and configure tool on controller and compute
    for node in (controller, compute):
        with node.ssh() as remote:
            kwargs = vars_config(remote)
            if 'controller' in node.data['roles']:
                # wait when rabbit will be ok after snapshot revert
                wait_for_rabbit_running_nodes(remote, len(controllers))
            install_oslomessagingchecktool(remote, **kwargs)
            configure_oslomessagingchecktool(
                remote, ctrl_ips, kwargs['nova_user'], kwargs['nova_pass'],
                kwargs['cfg_file_path'], kwargs['sample_cfg_file_path'])

    # client: run 'oslo_msg_check_client' on compute
    with compute.ssh() as remote:
        rpc_client_ip = rabbit_rpc_client_start(
            remote, kwargs['cfg_file_path'])
    # server: run 'oslo_msg_check_server' on controller
    with controller.ssh() as remote:
        rabbit_rpc_server_start(remote, kwargs['cfg_file_path'])

    # host srv -> client: Check GET before controller(s) restart
    logger.debug('GET: [host server] -> [{0}]'.format(rpc_client_ip))
    # need to wait for server/client start
    wait(lambda: get_http_code(rpc_client_ip) == exp_resp,
         timeout_seconds=60 * timeout_min,
         sleep_seconds=20,
         waiting_for='RPC server/client to start')

    # Restart RabbinMQ server on one/all controller(s)
    with controller.ssh() as remote:
        if restart_ctrlr in ('one', 'prim', 'non_prim'):
            restart_rabbitmq_serv(env, remote=remote)
        elif restart_ctrlr == 'all':
            restart_rabbitmq_serv(env, remote=None)

    # host srv -> client: Check GET after controller(s) restart
    logger.debug('GET: [host server] -> [{0}]'.format(rpc_client_ip))
    assert get_http_code(rpc_client_ip) == exp_resp


# Because of https://bugs.launchpad.net/fuel/+bug/1563321 it is DESTRUCTIVE
# For e.g. "pcs resource" is not working after test below.
# @pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('838291')
def test_start_rpc_srv_client_shutdown_eth_on_all(
        env, fixt_open_5000_port_on_nodes, fixt_kill_rpc_server_client):
    """Tests:
    Start RabbitMQ RPC server and client and shutdown eth interfaces on
        all controllers.

    Actions:
    2. To be able to use port 5000 from any node open it in IPTables;
    3. Install 'oslo.messaging-check-tool' on controller and compute;
    4. Prepare config file for both nodes above;
    5. Run 'oslo_msg_check_client' on compute node;
    6. Run 'oslo_msg_check_server' on controller node;
    7. Shutdown all eth interfaces on all controllers and after sleep
        enable them.
    8. Send GET curl request from host server to 'oslo_msg_check_client'
        located on compute node and check that response will '200';
    9. Remove all modifications of rules from IPTables and kill serv/client.
    """
    exp_resp = 200   # expected response code from curl from RPC client
    timeout_min = 2  # (minutes) time to wait for RPC server/client start
    sleep_min = 2    # (minutes) Time to shutdown eth interfaces on controllers

    controllers = env.get_nodes_by_role('controller')
    compute = random.choice(env.get_nodes_by_role('compute'))
    controller = random.choice(controllers)

    # Get management IPs of all controllers
    ctrl_ips = get_mngmnt_ip_of_ctrllrs(env)

    # Install and configure tool on controller and compute
    for node in (controller, compute):
        with node.ssh() as remote:
            kwargs = vars_config(remote)
            if 'controller' in node.data['roles']:
                # wait when rabbit will be ok after snapshot revert
                wait_for_rabbit_running_nodes(remote, len(controllers))
            install_oslomessagingchecktool(remote, **kwargs)
            configure_oslomessagingchecktool(
                remote, ctrl_ips, kwargs['nova_user'], kwargs['nova_pass'],
                kwargs['cfg_file_path'], kwargs['sample_cfg_file_path'])

    # Client: Run 'oslo_msg_check_client' on compute
    with compute.ssh() as remote:
        rpc_client_ip = rabbit_rpc_client_start(
            remote, kwargs['cfg_file_path'])
    # Server: Run 'oslo_msg_check_server' on controller
    with controller.ssh() as remote:
        rabbit_rpc_server_start(remote, kwargs['cfg_file_path'])

    # host srv -> client: Check GET before any actions
    logger.debug('GET: [host server] -> [{0}]'.format(rpc_client_ip))
    # need to wait for server/client start
    wait(lambda: get_http_code(rpc_client_ip) == exp_resp,
         timeout_seconds=60 * timeout_min,
         sleep_seconds=20,
         waiting_for='RPC server/client to start')

    # Shutdown all eth interfaces on all cntrllrs and after sleep enable them
    for one in controllers:
        with one.ssh() as one_remote:
            disable_enable_all_eth_interf(one_remote, sleep_min * 60)

    # Wait when eth interface on controllers will be alive
    wait(controller.is_ssh_avaliable,
         timeout_seconds=60 * (sleep_min + 2),
         sleep_seconds=30,
         waiting_for='controller to be available.')

    # Wait when rabbit will be ok after interfaces down/up
    with controller.ssh() as remote:
        wait_for_rabbit_running_nodes(remote, len(controllers))

    # host srv -> client: Check GET after controller(s) restart
    logger.debug('GET: [host server] -> [{0}]'.format(rpc_client_ip))
    assert get_http_code(rpc_client_ip) == exp_resp


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('838294', params={'patch_iptables': 'drop'})
@pytest.mark.testrail_id('838295', params={'patch_iptables': 'reject'})
@pytest.mark.parametrize('patch_iptables', ['drop', 'reject'],
                         indirect=['patch_iptables'])
def test_start_rpc_srv_client_iptables_modify(
        env, fixt_open_5000_port_on_nodes, fixt_kill_rpc_server_client,
        patch_iptables, controller):
    """Tests:
    Start RabbitMQ RPC server and client and apply IPTABLES DROP rules
        for RabbitMQ ports on one controller.

    Actions:
    1. Apply IPTables Drop OR Reject rules to controller where
        'oslo_msg_check_server' will be launched;
    2. To be able to use port 5000 from any node open it in IPTables;
    3. Install 'oslo.messaging-check-tool' on controller and compute;
    4. Prepare config file for both nodes above;
    5. Run 'oslo_msg_check_client' on compute node;
    6. Run 'oslo_msg_check_server' on controller node (remember point 1);
    7. Send GET curl request from host server to 'oslo_msg_check_client'
        located on compute node and check that response will '200';
    8. Remove all modifications of rules from IPTables and kill serv/client.
    """
    exp_resp = 200   # expected response code from curl from RPC client
    timeout_min = 2  # (minutes) time to wait for RPC server/client start

    compute = random.choice(env.get_nodes_by_role('compute'))

    # Get management IPs of all controllers
    ctrl_ips = get_mngmnt_ip_of_ctrllrs(env)

    # Install and configure tool on controller and compute
    for node in (controller, compute):
        with node.ssh() as remote:
            kwargs = vars_config(remote)
            install_oslomessagingchecktool(remote, **kwargs)
            configure_oslomessagingchecktool(
                remote, ctrl_ips, kwargs['nova_user'], kwargs['nova_pass'],
                kwargs['cfg_file_path'], kwargs['sample_cfg_file_path'])

    # Client: Run 'oslo_msg_check_client' on compute
    with compute.ssh() as remote:
        rpc_client_ip = rabbit_rpc_client_start(
            remote, kwargs['cfg_file_path'])
    # Server: Run 'oslo_msg_check_server' on controller
    with controller.ssh() as remote:
        rabbit_rpc_server_start(remote, kwargs['cfg_file_path'])

    # host srv -> client: Check GET
    logger.debug('GET: [host server] -> [{0}]'.format(rpc_client_ip))
    # need to wait for server/client start
    wait(lambda: get_http_code(rpc_client_ip) == exp_resp,
         timeout_seconds=60 * timeout_min,
         sleep_seconds=20,
         waiting_for='RPC server/client to start')

    assert get_http_code(rpc_client_ip) == exp_resp


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('838296')
def test_start_rpc_srv_client_gen_msg_kill_rabbit_service(
        env, fixt_open_5000_port_on_nodes, fixt_kill_rpc_server_client):
    """Tests:
    Start RabbitMQ RPC server and client and kill RabbitMQ service
        with 'kill -9' on different nodes many times.

    Actions:
    1. To be able to use port 5000 from any node open it in IPTables;
    2. Install 'oslo.messaging-check-tool' on controller and compute;
    3. Prepare config file for both nodes above;
    4. Run 'oslo_msg_check_client' on compute node;
    5. Run 'oslo_msg_check_server' on controller node;
    6. Generate 10 000 messages to RabbitMQ cluster;
    7. Select (num of controllers - 1) controllers and kill several times
        rabbitmq server process on them;
    8. Wait when rabbit will be up and running on all controllers;
    9. Send GET curl request from host server to 'oslo_msg_check_client'
        located on compute node and check that response will '200';
    10. Consume messages and check that number of generated and consumed
        messages is equal;
    11. Remove all modifications of rules from IPTables and kill serv/client.

    BUG: https://bugs.launchpad.net/mos/+bug/1561894
    """
    num_of_rabbit_kill = 3     # how many times kill rabbit on one node
    num_of_msg_to_gen = 10000  # number of messages to generate with oslo_tool
    exp_resp = 200   # expected response code from curl from RPC client
    timeout_min = 3  # (minutes) time to wait for RPC server/client start

    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)
    compute = random.choice(env.get_nodes_by_role('compute'))

    # Get management IPs of all controllers
    ctrl_ips = get_mngmnt_ip_of_ctrllrs(env)

    # Wait when rabbit will be ok on all controllers
    wait_rabbit_ok_on_all_ctrllrs(env)

    # Install and configure oslo_tool on controller and compute
    for node in (controller, compute):
        with node.ssh() as remote:
            kwargs = vars_config(remote)
            install_oslomessagingchecktool(remote, **kwargs)
            configure_oslomessagingchecktool(
                remote, ctrl_ips, kwargs['nova_user'], kwargs['nova_pass'],
                kwargs['cfg_file_path'], kwargs['sample_cfg_file_path'])

    # Client: Run 'oslo_msg_check_client' on compute
    with compute.ssh() as remote:
        rpc_client_ip = rabbit_rpc_client_start(
            remote, kwargs['cfg_file_path'])

    # Server: Run 'oslo_msg_check_server' on controller and generate messages
    with controller.ssh() as remote:
        rabbit_rpc_server_start(remote, kwargs['cfg_file_path'])
        generate_msg(remote, kwargs['cfg_file_path'], num_of_msg_to_gen)

    # Wait for oslo_tool server/client is ready
    logger.debug('GET: [host server] -> [{0}]'.format(rpc_client_ip))
    wait(lambda: get_http_code(rpc_client_ip) == exp_resp,
         timeout_seconds=60 * timeout_min,
         sleep_seconds=20,
         waiting_for='RPC server/client to start')

    # Randomly select [num of controllers - 1] controllers for kill-9 actions
    ctrlls_for_kill = []
    for i in range(0, (len(controllers) - 1)):
        ctrl = random.choice(controllers)
        while ctrl in ctrlls_for_kill:
            ctrl = random.choice(controllers)
        ctrlls_for_kill.append(ctrl)

    # Kill rabbit several times on selected controllers
    for i in range(0, num_of_rabbit_kill):
        for ctrl in ctrlls_for_kill:
            logger.debug('Round %s of kill-9 on %s' % (i, ctrl.data['ip']))
            with ctrl.ssh() as remote:
                kill_rabbitmq_on_node(remote)

    # Wait when rabbit will be ok on all controllers after kills
    wait_rabbit_ok_on_all_ctrllrs(env)

    # Check oslo_tool server/client
    assert exp_resp == get_http_code(rpc_client_ip)

    # Check number of consumed messages
    with controller.ssh() as remote:
        num_of_msg_consumed = consume_msg(remote, kwargs['cfg_file_path'])
    assert num_of_msg_to_gen == num_of_msg_consumed
