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
import uuid

import pytest

from mos_tests.environment import ssh
from mos_tests.neutron.python_tests.base import TestBase
from mos_tests.rabbitmq_oslo.utils import BashCommand

logger = logging.getLogger(__name__)


class RabbitRestartsFunctions(TestBase):

    @pytest.fixture(autouse=True)
    def tools(self, rabbitmq, check_tool):
        self.rabbitmq = rabbitmq
        self.oslo_tool = check_tool
        self.cmd = BashCommand

    TIMEOUT_LONG = 7    # minutes
    TIMEOUT_SHORT = 3   # minutes

    def vars_config(self, remote):
        """Prepare variables and different paths.
        :param remote: SSH connection point to node
        """
        self.oslo_tool._get_rabbit_creds_from_nova(remote=remote)
        config_vars = {
            'repo': self.oslo_tool.config_vars['repo'],
            'pkg': self.oslo_tool.config_vars['pkg'],
            'nova_config': self.oslo_tool.config_vars['nova_config'],
            'repo_path': self.oslo_tool.config_vars['repo_path'],
            'rpc_port': self.oslo_tool.config_vars['rpc_port'],
            'rabbit_userid': self.oslo_tool.config_vars['rabbit_userid'],
            'rabbit_password': self.oslo_tool.config_vars['rabbit_password'],
            'rabbit_hosts': self.oslo_tool.config_vars['rabbit_hosts'],
            'cfg_file_path': self.oslo_tool.config_vars['cfg_file_path'],
            'sample_cfg_file_path':
                self.oslo_tool.config_vars['sample_cfg_file_path']}
        return config_vars

    def install_oslomessagingchecktool(self, remote):
        """Install 'oslo.messaging-check-tool' on controller.
        https://github.com/dmitrymex/oslo.messaging-check-tool
        :param remote: SSH connection point to node
        """
        self.oslo_tool.install(remote=remote)

    def configure_oslomessagingchecktool(
            self, remote,
            rabbit_message_is_event=True,
            rabbit_custom_topic=None,
            rabbit_custom_hosts=None,
            custom_tool_rpc_port=None,
            custom_cfg_filename=None):
        """Write configuration file on host.
        :param remote: SSH connection point to host;
        :param rabbit_message_is_event: Set type of messages (True-For events);
        :param rabbit_custom_topic: Set custom topic for rabbitmq (by default:
        oslo_messaging_checktool);
        :param rabbit_custom_hosts: Set custom rabbitmq hosts (by default used
        hosts from nova.conf);
        :param custom_tool_rpc_port: Set custom port for checktool RPC (default
        value current on RABBITOSLO_TOOL_PORT);
        :param custom_cfg_filename: Set custom config filename (default:
        oslo_msg_check.conf);
        """
        self.oslo_tool.configure_oslomessagingchecktool(
            remote=remote,
            rabbit_message_is_event=rabbit_message_is_event,
            rabbit_custom_topic=rabbit_custom_topic,
            rabbit_custom_hosts=rabbit_custom_hosts,
            custom_tool_rpc_port=custom_tool_rpc_port,
            custom_cfg_filename=custom_cfg_filename)

    def get_mngmnt_ip_of_ctrllrs(self):
        """Get host IP of management network from all controllers"""
        controllers = self.env.get_nodes_by_role('controller')
        ctrl_ips = []
        for one in controllers:
            ip = [x['ip'] for x in one.data['network_data']
                  if x['name'] == 'management'][0]
            ip = ip.split("/")[0]
            ctrl_ips.append(ip)
        return ctrl_ips

    def get_mngmnt_ip_of_computes(self):
        """Get host IP of management network from all computes"""
        computes = self.env.get_nodes_by_role('compute')
        computes_ips = []
        for one in computes:
            ip = [x['ip'] for x in one.data['network_data']
                  if x['name'] == 'management'][0]
            ip = ip.split("/")[0]
            computes_ips.append(ip)
        return computes_ips

    def get_mngmnt_ip_of_node(self, node):
        """Get host IP of management network from current host"""
        ip = [x['ip'] for x in node.data['network_data']
              if x['name'] == 'management'][0]
        ip = ip.split("/")[0]
        return ip

    def num_of_rabbit_running_nodes(self):
        """Get number of 'Started/Master' hosts from pacemaker.
        """
        return self.rabbitmq.num_of_running_nodes(node_type='all')

    def num_of_rabbit_primary_running_nodes(self):
        """Get number of 'Master' hosts from pacemaker.
        """
        return self.rabbitmq.num_of_running_nodes(node_type='master')

    def wait_for_rabbit_running_nodes(
            self, exp_nodes, primary_nodes=1):
        """Waits until number of 'Started/Master' hosts from pacemaker
        will be as expected number of controllers.
        :param exp_nodes: Expected number of rabbit nodes.
        :param primary_nodes: Count of rabbitmq primary nodes, by default = 1.
        """
        self.rabbitmq.wait_for_rabbit_running_nodes(
            exp_nodes=exp_nodes,
            primary_nodes=primary_nodes)

    def generate_msg(self, remote, cfg_file_path, num_of_msg_to_gen=10000):
        """Generate messages with oslo_msg_load_generator
        :param remote: SSH connection point to controller.
        :param cfg_file_path: Path to the config file.
        :param num_of_msg_to_gen: How many messages to generate.
        """
        self.oslo_tool.generate_msg(
            remote=remote,
            cfg_file_path=cfg_file_path,
            num_of_msg_to_gen=num_of_msg_to_gen)

    def consume_msg(self, remote, cfg_file_path):
        """Consume messages with oslo_msg_load_consumer
        :param remote: SSH connection point to controller.
        :param cfg_file_path: Path to the config file.
        """
        return self.oslo_tool.consume_msg(
            remote=remote,
            cfg_file_path=cfg_file_path)

    def rabbit_rpc_server_start(self, remote, cfg_file_path):
        """Starts in background 'oslo_msg_check_server' on remote.
        :param remote: SSH connection point to controller.
        :param cfg_file_path: Path to the config file.
        """
        self.oslo_tool.rpc_server_start(
            remote=remote,
            cfg_file_path=cfg_file_path)

    def rabbit_rpc_client_start(self, remote, cfg_file_path):
        """Starts in background 'oslo_msg_check_client' on remote.
        :param remote: SSH connection point to controller.
        :param cfg_file_path: Path to the config file.
        """
        self.oslo_tool.rpc_client_start(
            remote=remote,
            cfg_file_path=cfg_file_path)

    def get_http_code(self, remote, host="127.0.0.1", port=80):
        """Send request by curl to return 'http_code' of oslo messaging tool.
        :param remote: SSH connection point to controller.
        :param host: IP of host where tool launched.
        :param port: Port where send curl requests.
        """
        return self.oslo_tool.get_http_code(
            remote=remote,
            host=host,
            port=port)

    def wait_oslomessagingchecktool_is_ok(
            self, remote, host="127.0.0.1", port=80):
        """Wait till curl response from tool will be not 000
        :param remote: SSH connection point to controller.
        :param host: IP of host where tool launched.
        :param port: Port where send curl requests.
        """
        self.oslo_tool.wait_oslomessagingchecktool_is_ok(
            remote=remote,
            host=host,
            port=port)

    def wait_rabbit_ok_on_all_ctrllrs(self):
        """Wait till rabbit will be OK on all controllers"""
        controllers = self.env.get_nodes_by_role('controller')
        for _ in controllers:
            self.wait_for_rabbit_running_nodes(len(controllers))

    def restart_rabbitmq_serv(self, remote=None):
        """Restart RabbitMQ by pacemaker on one or all controllers.
        After each restart, check that rabbit is up and running.
        :param remote: SSH connection point to controller, if None - restart
        rabbitmq on controllers one by one or together.
        """
        if remote:
            logger.debug('Restart RabbitMQ server on ONE controller')
            fqdn = remote.check_call('hostname').stdout_string
            self.rabbitmq.restart_rabbitmq_node(fqdn=fqdn)
        else:
            logger.debug(
                'Restart RabbitMQ server on ALL controllers one-by-one')
            self.rabbitmq.restart_rabbitmq_cluster(step_by_step=True)

    def restart_rabbitmq_cluster(self):
        """Restart RabbitMQ cluster by pacemaker.
        After each restart, check that rabbit is up and running.
        """
        self.rabbitmq.restart_rabbitmq_cluster(step_by_step=False)

    def migrate_rabbitmq_primary_node(self):
        """Migrate primary node in RabbitMQ cluster.
        :param wait_time: Delay for ban command rabbitmq.
        """
        controllers = self.env.get_nodes_by_role('controller')

        self.wait_for_rabbit_running_nodes(len(controllers))
        # Get master fqdn
        current_primary_fqdn = self.rabbitmq.nodes_list()['master'][0]
        # Stop master
        self.rabbitmq.stop_rabbitmq_node(fqdn=current_primary_fqdn)
        self.wait_for_rabbit_running_nodes(len(controllers) - 1)
        # Start master
        self.rabbitmq.start_rabbitmq_node(fqdn=current_primary_fqdn)
        self.wait_for_rabbit_running_nodes(len(controllers))

    def kill_rabbitmq_on_node(self, remote=None, node=None):
        """Waiting for rabbit startup and got pid, then kill it.
        :param remote: SSH connection point to controller.
        :param node: Node.
        """
        if not remote and not node:
            raise ValueError("Provide 'remote' OR 'node'")

        if not node:
            node = self.rabbitmq.node_by_remote(remote)
        return self.rabbitmq.kill_rabbitmq_node(node)


@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
class TestRabbitRestarts(RabbitRestartsFunctions):

    NUM_OF_MSG_TO_GEN = 10000
    RPC_TOOL_PORT = 12400

    @classmethod
    @pytest.fixture(autouse=True)
    def wait_rabbit_is_ok(cls):
        logger.debug("Wait till RabbitMQ will be ok after snapshot revert")
        cls.rabbitmq.wait_rabbit_cluster_is_ok()

    @pytest.mark.undestructive
    @pytest.mark.testrail_id(
        '857390', params={'consume_message_from': 'same'})
    @pytest.mark.testrail_id(
        '857391', params={'consume_message_from': 'other'})
    @pytest.mark.parametrize('consume_message_from', ['same', 'other'])
    def test_check_send_and_receive_messages_from_the_same_nodes(
            self, env, consume_message_from):
        """[Undestructive] Send/receive messages to all rabbitmq nodes.
        :param env: Environment
        :param consume_message_from: Consume message the same or other node
        (which upload messages).

        Actions:
        1. Install "oslo.messaging-check-tool" on compute;
        2. Prepare config files for all controllers;
        3. Generate 10000 messages for all controllers;
        4. Consume messages;
        5. Check that number of generated and consumed messages is equal.
        """
        computes = env.get_nodes_by_role('compute')
        compute = random.choice(computes)
        topic = str(uuid.uuid4())

        # Get management IPs of all controllers
        ctrl_ips = self.get_mngmnt_ip_of_ctrllrs()

        # Install tool on one compute and make configs
        with compute.ssh() as remote:
            kwargs = self.vars_config(remote)
            self.install_oslomessagingchecktool(remote)
            # configure tool
            for ctrl_ip in ctrl_ips:
                self.configure_oslomessagingchecktool(
                    remote,
                    rabbit_message_is_event=False,
                    rabbit_custom_topic=topic,
                    rabbit_custom_hosts=[ctrl_ip],
                    custom_cfg_filename='oslo_msg_check_%s.conf' % ctrl_ip)

            for ctrl_ip in ctrl_ips:
                # Generate messages
                config_path = "{path}{config_name}".format(
                    path=kwargs['repo_path'],
                    config_name='oslo_msg_check_%s.conf' % ctrl_ip)
                self.generate_msg(remote, config_path, self.NUM_OF_MSG_TO_GEN)

                # Consume messages
                if consume_message_from == 'same':
                    num_of_msg_consumed = self.consume_msg(remote, config_path)
                    logger.debug("Host %s messages[%s/%s]." % (
                        ctrl_ip, num_of_msg_consumed, self.NUM_OF_MSG_TO_GEN))

                elif consume_message_from == 'other':
                    custom_ctrl_ips = ctrl_ips
                    custom_ctrl_ips.remove(ctrl_ip)
                    custom_ctrl_ip = random.choice(custom_ctrl_ips)
                    config_path = "{path}{config_name}".format(
                        path=kwargs['repo_path'],
                        config_name='oslo_msg_check_%s.conf' % custom_ctrl_ip)

                    num_of_msg_consumed = self.consume_msg(remote, config_path)
                    logger.debug("Upload to %s, download from %s. "
                                 "Stats messages[%s/%s]." %
                                 (ctrl_ip, custom_ctrl_ip, num_of_msg_consumed,
                                  self.NUM_OF_MSG_TO_GEN))

                assert self.NUM_OF_MSG_TO_GEN == num_of_msg_consumed, (
                    'Generated and consumed number of messages is different '
                    'on %s host.' % ctrl_ip)

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('857392', params={'node_type': 'compute'})
    @pytest.mark.testrail_id('857393', params={'node_type': 'controller'})
    @pytest.mark.parametrize('node_type', ['compute', 'controller'])
    def test_check_send_and_receive_messages_from_diff_type_nodes(
            self, env, node_type):
        """[Undestructive] Send/receive messages to rabbitmq
        cluster for different types of fuel nodes.
        :param env: Enviroment
        :param node_type: Select type of nodes for send/recv messages.

        Actions:
        1. Install "oslo.messaging-check-tool" on compute;
        2. Prepare config files for current fuel node types;
        3. Generate and consume 10000 messages from RabbitMQ cluster.
        4. Check that number of generated and consumed messages is equal.
        """

        controllers = env.get_nodes_by_role('controller')
        controller = random.choice(controllers)
        computes = env.get_nodes_by_role('compute')
        compute = random.choice(computes)

        # Install tool on one compute and make configs
        if node_type == 'compute':
            host = compute
        elif node_type == 'controller':
            host = controller

        with host.ssh() as remote:
            kwargs = self.vars_config(remote)
            self.install_oslomessagingchecktool(remote)
            # Configure
            self.configure_oslomessagingchecktool(
                remote, rabbit_message_is_event=False)
            # Generate messages
            self.generate_msg(
                remote, kwargs['cfg_file_path'], self.NUM_OF_MSG_TO_GEN)
            # Consume messages
            num_of_msg_consumed = self.consume_msg(
                remote, kwargs['cfg_file_path'])

        assert self.NUM_OF_MSG_TO_GEN == num_of_msg_consumed, (
            'Generated and consumed number of messages is different')

    @pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
    @pytest.mark.testrail_id('857394', params={'restart_type': 'single'})
    @pytest.mark.testrail_id('857395', params={'restart_type': 'one_by_one'})
    @pytest.mark.parametrize('restart_type', ['single', 'one_by_one'])
    def test_upload_10000_events_to_cluster_and_restart_controllers(
            self, env, restart_type):
        """Load 10000 events to RabbitMQ cluster and restart controllers single
        or one-by-one.
        :param env: Enviroment
        :param restart_type: Parameter specifies the node restart strategy.

        Actions:
        1. Install "oslo.messaging-check-tool" on compute;
        2. Prepare config files for current fuel node types;
        3. Generate 10000 events to RabbitMQ cluster.
        4. Restart one random rabbitmq node or all(one-by-one).
        5. Consume 10000 events from RabbitMQ cluster.
        6. Check that number of generated and consumed messages is equal.
        """

        controllers = env.get_nodes_by_role('controller')
        controller = random.choice(controllers)

        with controller.ssh() as remote:
            kwargs = self.vars_config(remote)
            self.install_oslomessagingchecktool(remote)
            self.configure_oslomessagingchecktool(remote)

            # Generate messages and consume
            self.generate_msg(
                remote, kwargs['cfg_file_path'], self.NUM_OF_MSG_TO_GEN)

            if restart_type == 'single':
                logger.debug("Restarting RabbitMQ on one random node")
                self.restart_rabbitmq_serv(remote)

            elif restart_type == 'one_by_one':
                logger.debug("Restarting RabbitMQ on all nodes "
                             "(with one-by-one strategy)")
                self.restart_rabbitmq_serv()

            # Consume messages
            num_of_msg_consumed = self.consume_msg(
                remote, kwargs['cfg_file_path'])

        assert self.NUM_OF_MSG_TO_GEN == num_of_msg_consumed, (
            'Generated and consumed number of messages is different '
            'after RabbitMQ cluster restarting.')

    # destructive
    @pytest.mark.testrail_id('857396')
    def test_upload_messages_on_one_restart_and_receive_on_other(self, env):
        """"[Destructive] Send messages to one rabbitmq node, restart other and
        receive messages on them.

        :param env: Environment.

        Actions:
        1. Install "oslo.messaging-check-tool" on compute;
        2. Prepare config files;
        3. Generate 10000 messages to current RabbitMQ node.
        4. Restart all other rabbitmq nodes.
        5. Consume 10000 messages from one of other RabbitMQ node.
        6. Check that number of generated and consumed messages is equal.
        """

        controllers = env.get_nodes_by_role('controller')
        controller = random.choice(controllers)
        controller_ip = self.get_mngmnt_ip_of_node(controller)
        other_controllers = controllers[:]
        other_controllers.remove(controller)

        # Get management IPs of all controllers
        ctrl_ips_exclude_current = self.get_mngmnt_ip_of_ctrllrs()
        ctrl_ips_exclude_current.remove(controller_ip)

        with controller.ssh() as remote:
            kwargs = self.vars_config(remote)
            self.install_oslomessagingchecktool(remote)
            self.configure_oslomessagingchecktool(
                remote, False, rabbit_custom_hosts=[controller_ip])

            # Generate messages
            self.generate_msg(
                remote, kwargs['cfg_file_path'], self.NUM_OF_MSG_TO_GEN)

        for current in other_controllers:
            with current.ssh() as current_remote:
                self.restart_rabbitmq_serv(current_remote)

        with controller.ssh() as remote:
            kwargs = self.vars_config(remote)
            self.configure_oslomessagingchecktool(
                remote, False,
                rabbit_custom_hosts=[random.choice(ctrl_ips_exclude_current)])

            num_of_msg_consumed = self.consume_msg(
                remote, kwargs['cfg_file_path'])

        assert self.NUM_OF_MSG_TO_GEN == num_of_msg_consumed, (
            'Generated and consumed number of messages is different '
            'after RabbitMQ cluster restarting.')

    @pytest.mark.testrail_id('857397', params={'action': 'restart_all'})
    @pytest.mark.testrail_id('857398', params={'action': 'migrate_primary'})
    @pytest.mark.parametrize('action', ['restart_all', 'migrate_primary'])
    def test_verify_cnnct_after_full_restart_rabbitmq_or_migrate_primary_node(
            self, env, action):
        """"[Destructive] Verify connectivity after full-restart RabbitMQ
        cluster or ban primary node.

        :param env: Environment.
        :param action: Action restarts rabbitmq cluster on migrate primary node

        Actions:
        1. Install "oslo.messaging-check-tool" on controller;
        2. Prepare config file;
        3. Restart Rabbitmq cluster or migrate primary node.
        4. Check rabbitmq connectivity by OSLO RPC Client/Server app.
        """

        controllers = env.get_nodes_by_role('controller')
        controller = random.choice(controllers)

        with controller.ssh() as remote:
            kwargs = self.vars_config(remote)
            self.install_oslomessagingchecktool(remote)
            self.configure_oslomessagingchecktool(
                remote, custom_tool_rpc_port=self.RPC_TOOL_PORT)

            if action == 'restart_all':
                self.restart_rabbitmq_cluster()

            elif action == 'migrate_primary':
                self.migrate_rabbitmq_primary_node()

            self.rabbit_rpc_server_start(remote, kwargs['cfg_file_path'])
            self.rabbit_rpc_client_start(remote, kwargs['cfg_file_path'])

            self.wait_oslomessagingchecktool_is_ok(
                remote, port=self.RPC_TOOL_PORT)

            response_status_code = self.get_http_code(remote,
                                                      port=self.RPC_TOOL_PORT)
        assert 200 == response_status_code, (
            'Verify RabbitMQ connection was failed')

    # destructive
    @pytest.mark.testrail_id('857422')
    def test_kill_all_rabbit_nodes_and_check_connectivity_many_times(
            self, env):
        """"[Destructive] Kill all rabbitmq nodes and check connectivity (x10).

        :param env: Environment.

        Actions:
        1. Install "oslo.messaging-check-tool" on controller;
        2. Prepare config file;
        3. Kill all rabbitmq nodes and wait when rabbit will be up and running;
        4. Check rabbitmq connectivity by OSLO RPC Client/Server app.
        5. Retry step 3-4 (x10)
        """

        controllers = env.get_nodes_by_role('controller')
        controller = random.choice(controllers)

        with controller.ssh() as remote:
            kwargs = self.vars_config(remote)
            self.install_oslomessagingchecktool(remote)
            self.configure_oslomessagingchecktool(
                remote, custom_tool_rpc_port=self.RPC_TOOL_PORT)

            self.rabbit_rpc_server_start(remote, kwargs['cfg_file_path'])
            self.rabbit_rpc_client_start(remote, kwargs['cfg_file_path'])

            self.wait_oslomessagingchecktool_is_ok(
                remote, port=self.RPC_TOOL_PORT)

        max_attempt = 10
        for attempt in range(1, max_attempt + 1):
            logger.debug("\n\n--- Retry [{0}/{1}] ---".format(
                attempt, max_attempt))

            # Kill rabbit on all controllers almost at the same time
            for current_controller in controllers:
                assert (self.kill_rabbitmq_on_node(node=current_controller)
                        is True), (
                    'Rabbit process not killed')

            # Wait till it'll be up
            self.wait_rabbit_ok_on_all_ctrllrs()
            self.rabbitmq.wait_rabbit_cluster_is_ok(
                timeout=self.TIMEOUT_LONG * 2 * 60)

            with controller.ssh() as remote:
                self.wait_oslomessagingchecktool_is_ok(
                    remote, port=self.RPC_TOOL_PORT)
                response_status_code = self.get_http_code(
                    remote, port=self.RPC_TOOL_PORT)

            assert 200 == response_status_code, (
                'Retry [%d/%d] - Verify rabbitmq connection was failed' %
                (attempt, max_attempt))

    # destructive
    @pytest.mark.testrail_id('857428')
    def test_check_primary_node_migration_many_times(self, env):
        """"[Destructive] Stop rabbitmq primary node, wait migration
        finished, start same slave node (x10).

        :param env: Environment.

        Actions:
        1. Install "oslo.messaging-check-tool" on controller;
        2. Prepare config file;
        3. Check rabbitmq connectivity by OSLO RPC Client/Server app.
        4. Ban primary rabbitmq node and wait while migration was finished.
        5. Check rabbitmq connectivity by OSLO RPC Client/Server app.
        6. Retry step 4-5 (x10)

        Bug: https://bugs.launchpad.net/fuel/+bug/1614508
        """

        controllers = env.get_nodes_by_role('controller')
        controller = random.choice(controllers)

        with controller.ssh() as remote:
            kwargs = self.vars_config(remote)
            self.install_oslomessagingchecktool(remote)
            self.configure_oslomessagingchecktool(
                remote, custom_tool_rpc_port=self.RPC_TOOL_PORT)
            self.rabbit_rpc_server_start(remote, kwargs['cfg_file_path'])
            self.rabbit_rpc_client_start(remote, kwargs['cfg_file_path'])

            self.wait_oslomessagingchecktool_is_ok(
                remote, port=self.RPC_TOOL_PORT)

            max_retry = 10
            for current_retry in range(1, max_retry + 1):
                logger.debug("\n\n--- Retry [{0}/{1}] ---".format(
                    current_retry, max_retry))
                self.migrate_rabbitmq_primary_node()

                self.wait_oslomessagingchecktool_is_ok(
                    remote, port=self.RPC_TOOL_PORT)

    # destructive
    @pytest.mark.testrail_id('844792')
    def test_check_logs_for_epmd_successfully_restarted(self, env):
        """"[Destructive] Restart rabbitmq by pcs and check logs in all nodes.

        :param env: Enviroment.

        Actions:
        1. Make SSH to one of controller;
        2. Restart rabbitmq cluster by pcs;
        3. Check logs for "already running" error messages in all controllers.
        """
        cmd = "grep 'already running' /var/log/rabbitmq/*"

        controllers = env.get_nodes_by_role('controller')
        self.restart_rabbitmq_cluster()

        for controller in controllers:
            with controller.ssh() as remote:
                grep_out = remote.execute(cmd)

                assert not grep_out.is_ok, (
                    'Find error in logs on %s host.' %
                    self.get_mngmnt_ip_of_node(controller))

    # destructive
    @pytest.mark.testrail_id('844791')
    def test_check_rabbitmqctl_on_segfaults(self, env):
        """"[Destructive] Check rabbitmqctl segfaults on controller.

        :param env: Environment.

        Actions:
        1. Make SSH to one of controller;
        2. Ban rabbitmq node by pcs on current controller;
        3. Call 'rabbitmqctl status' command and verify that stdout+stderr
        don't contain 'segfault' word. (x30)
        """

        def check_rabbitmqctl_segfault(remote):
            max_retry = 30
            grep_segfault_code = 0
            for step in range(1, max_retry + 1):
                logger.debug("Retry[%s/%s]: Call rabbitmqctl status."
                             % (step, max_retry))
                try:
                    grep_segfault_out = remote.execute(
                        self.cmd.rabbitmqctl.grep_segfault)
                    grep_segfault_code = grep_segfault_out['exit_code']
                except ssh.CalledProcessError:
                    logger.info(
                        "Ignore none-zero exit code for "
                        "'rabbitmqctl status' command")
                assert 0 != grep_segfault_code, 'Found segfault message'

        controllers = env.get_nodes_by_role('controller')
        controller = random.choice(controllers)

        with controller.ssh() as remote:
            check_rabbitmqctl_segfault(remote)
            self.rabbitmq.stop_rabbitmq_node(node=controller)

            check_rabbitmqctl_segfault(remote)

            self.wait_for_rabbit_running_nodes(len(controllers) - 1)

            self.rabbitmq.start_rabbitmq_node(node=controller)
            self.wait_for_rabbit_running_nodes(len(controllers))

            check_rabbitmqctl_segfault(remote)
