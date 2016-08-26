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

import itertools
import logging
import re
import sys

from six.moves import configparser
import xml.etree.ElementTree as ElementTree

from mos_tests.functions.common import wait
from mos_tests.rabbitmq_oslo.utils import BashCommand
from mos_tests import settings

logger = logging.getLogger(__name__)


class MessagingCheckTool(object):

    def __init__(self, repo_path=None):

        self.remote = None
        self.cmd = BashCommand

        self.config_vars = {
            'repo': settings.RABBITOSLO_REPO,
            'pkg': settings.RABBITOSLO_PKG,
            'rpc_port': settings.RABBITOSLO_TOOL_PORT,
            'nova_config': '/etc/nova/nova.conf',
            'repo_path': repo_path or '/root/oslo_messaging_check_tool/'}

        # like: /root/oslo_messaging_check_tool/oslo_msg_check.conf
        self.config_vars['cfg_file_path'] = (
            '{}oslo_msg_check.conf'.format(self.config_vars['repo_path']))
        self.config_vars['sample_cfg_file_path'] = (
            '{}oslo_msg_check.conf.sample'.format(
                self.config_vars['repo_path']))

        self.TIMEOUT_LONG = 8 * 60
        self.TIMEOUT_SHORT = 4 * 60

    def _get_rabbit_creds_from_nova(self, remote):
        """Open nova cfg on remote and read info from it"""
        with remote.open(self.config_vars['nova_config']) as f:
            parser = configparser.RawConfigParser()
            parser.readfp(f)
            self.config_vars['rabbit_userid'] = (
                parser.get('oslo_messaging_rabbit', 'rabbit_userid'))
            self.config_vars['rabbit_password'] = (
                parser.get('oslo_messaging_rabbit', 'rabbit_password'))
            self.config_vars['rabbit_hosts'] = (
                parser.get('oslo_messaging_rabbit', 'rabbit_hosts'))

    def is_installed(self, remote):
        """Checks if 'oslo.messaging-check-tool' already installed on remote.
        :param remote: SSH connection point to node
        """
        host = remote.host
        logger.debug("Check if 'oslo.messaging-check-tool' is already "
                     "installed on %s" % host)

        is_installed = remote.execute(
            self.cmd.oslo_messaging_check_tool.is_installed)

        if is_installed.is_ok:
            logger.debug(
                '"oslo.messaging-check-tool" already installed on %s.' % host)
            return True
        else:
            logger.debug(
                '"oslo.messaging-check-tool" not installed on %s.' % host)
            return False

    def install(self, remote=None):
        """Install 'oslo.messaging-check-tool' on controller.
        https://github.com/dmitrymex/oslo.messaging-check-tool
        :param remote: SSH connection point to node
        """
        remote = remote or self.remote
        msg = 'Install "oslo.messaging-check-tool" on %s.' % remote.host

        if self.is_installed(remote) is True:
            return

        logger.debug(msg + '... Start')
        remote.check_call(
            self.cmd.oslo_messaging_check_tool.install.format(
                repo_path=self.config_vars['repo_path'],
                repo=self.config_vars['repo']),
            verbose=False)
        logger.debug(msg + '... Done')

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
        self._get_rabbit_creds_from_nova(remote)

        if rabbit_custom_hosts:
            rabbit_port = ':5673'
            rabbit_hosts = ', '.join([(x + rabbit_port)
                                      for x in rabbit_custom_hosts])
        else:
            rabbit_hosts = self.config_vars['rabbit_hosts']

        rabbit_topic = rabbit_custom_topic or 'oslo_messaging_checktool'
        if rabbit_message_is_event:
            rabbit_topic = "event.%s" % rabbit_topic

        if custom_tool_rpc_port:
            rabbit_rpc_port = str(custom_tool_rpc_port)
        else:
            rabbit_rpc_port = self.config_vars['rpc_port']

        tool_config = self.config_vars['repo_path']
        if custom_cfg_filename:
            tool_config = '{path}{filename}'.format(
                path=tool_config,
                filename=custom_cfg_filename)
        else:
            tool_config = '%soslo_msg_check.conf' % tool_config

        with remote.open(self.config_vars['sample_cfg_file_path'], 'r') as fr:
            parser = configparser.RawConfigParser()
            parser.readfp(fr)
            parser.set('DEFAULT', 'notif_topic_name', rabbit_topic)
            parser.set('DEFAULT', 'listen_port', rabbit_rpc_port)
            parser.set('oslo_messaging_rabbit', 'rabbit_hosts', rabbit_hosts)
            parser.set('oslo_messaging_rabbit', 'rabbit_userid',
                       self.config_vars['rabbit_userid'])
            parser.set('oslo_messaging_rabbit', 'rabbit_password',
                       self.config_vars['rabbit_password'])
            # Dump cfg file to screen
            logger.debug("\n%s" % ('-' * 70))
            parser.write(sys.stdout)
            logger.debug("\n%s" % ('-' * 70))
            # Write to new cfg file
            logger.debug('Write [{0}] config file to {1}.'.format(
                tool_config, remote.host))
            with remote.open(tool_config, 'w') as fw:
                parser.write(fw)

    def generate_msg(
            self, remote=None, cfg_file_path=None, topic=None,
            num_of_msg_to_gen=10000):
        """Generate messages with a help of oslo tool.
        :param remote: SSH connection point to host.
        :param cfg_file_path: Path to oslo tool config.
        :param topic: Set custom topic for rabbitmq.
        :param num_of_msg_to_gen: Number of generated messages.
        """
        remote = remote or self.remote
        cfg_file_path = cfg_file_path or self.config_vars['cfg_file_path']

        notif_topic_name = topic or ''
        if notif_topic_name:
            notif_topic_name = " --notif_topic_name '%s'" % notif_topic_name

        # Clean if some messages were left after previous failed tests
        logger.debug("Clean generated messages if any on %s" % remote.host)
        remote.check_call(
            self.cmd.oslo_messaging_check_tool.messages_single_consume.format(
                config=cfg_file_path))

        logger.debug("Generate messages on %s" % remote.host)
        if num_of_msg_to_gen >= 0:
            remote.check_call(
                self.cmd.oslo_messaging_check_tool.messages_single_load.format(
                    config=cfg_file_path,
                    count=num_of_msg_to_gen) + notif_topic_name)
        else:
            execute_command = "{command} {topic} {background}".format(
                command=(self.cmd.oslo_messaging_check_tool.
                         messages_loop_load.format(config=cfg_file_path)),
                topic=notif_topic_name,
                background=self.cmd.system.background)
            remote.check_call(execute_command)

    def consume_msg(
            self, remote=None, cfg_file_path=None, infinite=None, topic=None):
        """Consume generated messages with a help of oslo tool"""
        remote = remote or self.remote
        cfg_file_path = cfg_file_path or self.config_vars['cfg_file_path']
        infinite_loop = infinite or False
        logger.debug("Consume messages on %s" % remote.host)

        notif_topic_name = topic or ''
        if notif_topic_name:
            notif_topic_name = " --notif_topic_name '%s'" % notif_topic_name

        ci = self.cmd.oslo_messaging_check_tool.messages_loop_consume.format(
            config=cfg_file_path)

        if infinite_loop:
            cmd = '{0} {1} {2}'.format(
                ci, notif_topic_name, self.cmd.system.background)
            remote.check_call(cmd)
            return -1
        else:
            cmd = self.cmd.oslo_messaging_check_tool.messages_single_consume
            out_consume = remote.check_call(
                cmd.format(config=cfg_file_path) +
                notif_topic_name).stdout_string

            num_of_msg_consumed = int(re.findall('\d+', out_consume)[0])
            return num_of_msg_consumed

    def rpc_server_start(self, remote=None, cfg_file_path=None, topic=None):
        """Starts [oslo_msg_check_server] on remote"""
        remote = remote or self.remote
        logger.debug(
            "Start RPC server [oslo_msg_check_server] on %s" % remote.host)
        cfg_file_path = cfg_file_path or self.config_vars['cfg_file_path']

        topic = topic or ''
        if topic:
            topic = "--rpc_topic_name '%s'" % topic

        cmd = '{0} {1} {2}'.format(
            self.cmd.oslo_messaging_check_tool.rpc_server.format(
                config=cfg_file_path),
            topic,
            self.cmd.system.background)
        remote.execute(cmd)

    def rpc_server_stop(self, remote=None):
        """Stops [oslo_msg_check_server] on remote"""
        remote = remote or self.remote
        logger.debug(
            "Stop RPC server [oslo_msg_check_server] on %s" % remote.host)

        remote.execute(self.cmd.system.kill_by_name.format(
            process_name="oslo_msg_check_server"))

    def rpc_client_start(self, remote=None, cfg_file_path=None, topic=None):
        """Starts [oslo_msg_check_client] on remote"""
        remote = remote or self.remote
        logger.debug(
            "Start RPC client [oslo_msg_check_client] on %s" % remote.host)

        cfg_file_path = cfg_file_path or self.config_vars['cfg_file_path']

        topic = topic or ''
        if topic:
            topic = "--rpc_topic_name '%s'" % topic

        cmd = '{0} {1} {2}'.format(
            self.cmd.oslo_messaging_check_tool.rpc_client.format(
                config=cfg_file_path),
            topic,
            self.cmd.system.background)
        remote.execute(cmd)

    def rpc_client_stop(self, remote=None):
        """Stops [oslo_msg_check_client] on remote"""
        remote = remote or self.remote
        logger.debug(
            "Stop RPC client [oslo_msg_check_client] on %s" % remote.host)

        remote.execute(self.cmd.system.kill_by_name.format(
            process_name="oslo_msg_check_client"))

    def get_http_code(self, remote, host="127.0.0.1", port=12400):
        """Send request by curl to return 'http_code' of oslo messaging tool.
        :param remote: SSH connection point to controller.
        :param host: IP of host where tool launched.
        :param port: Port where send curl requests.
        """
        result = remote.execute(
            self.cmd.oslo_messaging_check_tool.curl_get_status.format(
                host=host,
                port=port))
        result = result.stdout_string

        if result.isdigit():
            return int(result)
        else:
            return 000

    def wait_oslomessagingchecktool_is_ok(
            self, remote, host="127.0.0.1", port=12400, timeout=None):
        """Wait till curl response from tool will be not 000
        :param remote: SSH connection point to controller.
        :param host: IP of host where tool launched.
        :param port: Port where send curl requests.
        :param timeout: Timeout for waiting.
        """
        timeout = timeout or self.TIMEOUT_LONG
        return wait(
            lambda: self.get_http_code(
                remote,
                host=host,
                port=port) != 000,
            timeout_seconds=timeout,
            sleep_seconds=30,
            waiting_for='start of "oslo.messaging-check-tool" '
                        'RPC server/client app on %s' % remote.host)


class RabbitMQWrapper(object):

    def __init__(self, env, datached_rabbit=False):

        if datached_rabbit:
            self.rabbit_role_node = 'standalone-rabbitmq'
        else:
            self.rabbit_role_node = 'controller'

        self.env = env
        self.cmd = BashCommand
        self.name_slave = BashCommand.pacemaker.rabbit_slave_name
        self.name_master = BashCommand.pacemaker.rabbit_master_name
        self.nodes = self.nodes_list()
        self.TIMEOUT_LONG = 8 * 60
        self.TIMEOUT_SHORT = 4 * 60

    def alive_node(self):
        """Returns one alive rabbit host node"""
        rabbit_hosts = self.env.get_nodes_by_role(self.rabbit_role_node)
        rabbit_host = None
        for node in rabbit_hosts:
            if node.is_ssh_avaliable():
                rabbit_host = node
                break
        if not rabbit_host:
            raise Exception('No alive standalone-rabbitmq nodes')
        return rabbit_host

    def all_nodes(self):
        """Returns list with all rabbitmq nodes"""
        return self.env.get_nodes_by_role(self.rabbit_role_node)

    def all_alive_nodes(self):
        """Returns all alive rabbit host node"""
        rabbit_hosts = self.all_nodes()
        alive_nodes = []
        for node in rabbit_hosts:
            if node.is_ssh_avaliable():
                alive_nodes.append(node)
        if not len(alive_nodes):
            raise Exception('No alive standalone-rabbitmq nodes')
        return alive_nodes

    def get_status(self, node=None):
        """Return xml obj with 'pcs status' content"""
        node = node or self.alive_node()
        get_xml_pcm_status_cmd = self.cmd.pacemaker.full_status + " xml"

        with node.ssh() as remote:
            out = remote.execute(get_xml_pcm_status_cmd, verbose=False)
        if out.is_ok:
            return ElementTree.fromstring(out.stdout_string)
        else:
            return None

    def nodes_list(self, node=None):
        """Return dict with mapping between alive rabbit node FQDN and its role
        :return: Dict with roles and nodes's FQDNs. Like:
        :  {'all':    ['node-1.test.domain.local','node-4...'],
        :   'master': ['node-1.test.domain.local'],
        :   'slave':  ['node-2.test.domain.local', 'node-4...']}
        """
        status = self.get_status(node)
        counted_roles = ('master', 'slave')

        nodes_roles = {}
        for role in counted_roles:
            nodes_roles[role] = []

        for node in status.findall('./resources//resource'):
            node_resource_agent = node.attrib.get('resource_agent', '')
            node_role = node.attrib.get('role', '').lower()
            if ('rabbitmq-server' in node_resource_agent and
                    node_role in counted_roles):
                node_fqdn = node.find('node').get('name')
                nodes_roles[node_role].append(node_fqdn)

        nodes_roles['all'] = list(itertools.chain.from_iterable(
            nodes_roles.values()))
        return nodes_roles

    def nodes_statuses(self, node=None):
        """Returns dict of nodes' FQDNs with statuses based on 'pcs status xml'
        performed from standalone rabbit node.
        :return: Like:
        :   {'node-1.test.domain.local': 'offline',
        :    'node-3.test.domain.local': 'online'}
        """
        alive_mapping = {'true': 'online', 'false': 'offline'}
        all_rabbit_nodes = self.nodes['all']
        status = self.get_status(node)

        nodes_statuses = {}
        for node in status.findall('nodes/node'):
            node_fqdn = node.attrib.get('name', '')
            if node_fqdn not in all_rabbit_nodes:
                continue
            node_status = node.attrib.get('online', '')
            nodes_statuses[node_fqdn] = alive_mapping[node_status]
        return nodes_statuses

    def rabbit_node_by_role(self, role='slave'):
        """Returns one rabbit master or slave node.
        :param role: Role of a node: 'slave' or 'master'
        :return: Node
        """
        roles = self.nodes_list()
        rabbit_nodes = self.env.get_nodes_by_role(self.rabbit_role_node)

        # Check that we have nodes with that role
        if len(rabbit_nodes) == 1 and role == 'slave':
            raise ValueError('Single node has only "Master" role')
        assert len(roles[role]) > 0, "No %s roles" % role

        # Find node with required role
        role_node_fqdn = roles[role][0]
        return [x for x in rabbit_nodes if x.data['fqdn'] == role_node_fqdn][0]

    def rabbit_node_by_fqdn(self, fqdn):
        """Return rabbit node by it's FQDN.
        :param fqdn: 'node-2.test.domain.local'
        :return: Node
        """
        rabbit_nodes = self.env.get_nodes_by_role(self.rabbit_role_node)
        return [x for x in rabbit_nodes if x.data['fqdn'] == fqdn][0]

    def node_by_remote(self, remote):
        fqdn = remote.check_call('hostname').stdout_string
        return self.rabbit_node_by_fqdn(fqdn)

    def num_of_running_nodes(self, node_type='all'):
        """Returns number of rabbit running nodes
        :param node_type: all, slave, master
        :return: int
        """
        nodes_list = self.nodes_list()
        return len(nodes_list[node_type])

    def wait_for_rabbit_running_nodes(
            self, exp_nodes=None, primary_nodes=None):
        """Waits until number of 'Started/Master' hosts from pacemaker
        will be as expected number of controllers.
        :param exp_nodes: Expected number of rabbit nodes.
        :param primary_nodes: Count of rabbitmq primary nodes, by default = 1.
        """
        if exp_nodes is None:
            exp_nodes = len(self.nodes['all'])
        if primary_nodes is None:
            primary_nodes = len(self.nodes['master'])

        if exp_nodes >= 0:
            wait(lambda: self.num_of_running_nodes() == exp_nodes,
                 timeout_seconds=self.TIMEOUT_LONG,
                 sleep_seconds=30,
                 waiting_for='number of running nodes will be %s.' % exp_nodes)

        if primary_nodes >= 0:
            wait(lambda:
                 self.num_of_running_nodes("master") == primary_nodes,
                 timeout_seconds=self.TIMEOUT_LONG,
                 sleep_seconds=30,
                 waiting_for='number of running primary nodes will be %s.'
                             % primary_nodes)

    def start_rabbitmq_node(self, fqdn="$(hostname)", node=None, verify=True):
        """pcs resource clear"""
        exp_nodes = len(self.nodes_list()['all']) + 1
        cmd = self.cmd.pacemaker.clear.format(
            fqdn=fqdn,
            service=self.name_slave,
            timeout=self.TIMEOUT_SHORT)

        node = node or self.alive_node()
        logger.debug("Start RabbitMQ on %s" % node.data['fqdn'])

        with node.ssh() as remote:
            remote.check_call(cmd)

        if verify:
            self.wait_for_rabbit_running_nodes(exp_nodes)

    def stop_rabbitmq_node(self, fqdn="$(hostname)", node=None, verify=True):
        """pcs resource ban"""
        exp_nodes = len(self.nodes_list()['all']) - 1
        cmd = self.cmd.pacemaker.ban.format(
            fqdn=fqdn,
            service=self.name_slave,
            timeout=self.TIMEOUT_SHORT)

        node = node or self.alive_node()
        logger.debug("Stop RabbitMQ on %s" % node.data['fqdn'])

        with node.ssh() as remote:
            remote.check_call(cmd)

        if verify:
            if exp_nodes > 0:
                primary_nodes = 1
            else:
                primary_nodes = 0
            self.wait_for_rabbit_running_nodes(exp_nodes, primary_nodes)

    def restart_rabbitmq_node(self, fqdn="$(hostname)", node=None):
        """pcs resource ban + clear"""
        if node:
            fqdn = node.data['fqdn']
        self.stop_rabbitmq_node(fqdn)
        self.start_rabbitmq_node(fqdn)

    def kill_rabbitmq_node(self, node):
        """kill rabbit process by name on node"""
        cmd_kill = self.cmd.system.kill_by_name.format(
            process_name=self.cmd.pacemaker.rabbit_process_name)
        cmd_check = self.cmd.system.check_run_process_by_name.format(
            process_name=self.cmd.pacemaker.rabbit_process_name)

        logger.debug("Kill RabbitMQ on %s" % node.data['fqdn'])
        with node.ssh() as remote:
            # Process re-spawn may be very fast.
            # So kill and check commands should be together.
            wait(
                lambda: int(
                    remote.execute(
                        cmd_kill + ' ; ' + cmd_check,
                        verbose=False).stdout_string) == 0,
                timeout_seconds=10,
                sleep_seconds=1,
                waiting_for='RabbitMQ process will be killed on %s'
                            % node.data['fqdn'])
            return True
            # otherwise there will be exception from wait()

    def kill_rabbit_on_node_by_pid(self, node, pid=None):
        """Kill process by PID on provided node
        :param node: Node
        :param pid: Optional. Kill this PID.
        """
        if not pid:
            pid = self.get_rabbit_pid_on_node(node)

        logger.debug("Kill RabbitMQ on %s" % node.data['fqdn'])
        with node.ssh() as remote:
            remote.check_call(self.cmd.system.kill_by_pid.format(pid=pid))

    def start_rabbitmq_cluster(self, verify=True):
        """pcs resource enable"""
        cmd = self.cmd.pacemaker.enable.format(
            fqdn="$(hostname)",
            service=self.name_slave,
            timeout=self.TIMEOUT_LONG)

        logger.debug("Enable RabbitMQ cluster")
        with self.alive_node().ssh() as remote:
            remote.check_call(cmd)

        if verify:
            self.wait_for_rabbit_running_nodes()

    def stop_rabbitmq_cluster(self, verify=True):
        """pcs resource disable"""
        cmd = self.cmd.pacemaker.disable.format(
            fqdn="$(hostname)",
            service=self.name_slave,
            timeout=self.TIMEOUT_LONG)

        logger.debug("Disable RabbitMQ cluster")
        with self.alive_node().ssh() as remote:
            remote.check_call(cmd)

        if verify:
            self.wait_for_rabbit_running_nodes(0, 0)

    def restart_rabbitmq_cluster(self, step_by_step=True):
        """Restarts nodes one by one OR whole cluster.
        :param step_by_step: Boolean. Stop one node, waits till it'll be
        offline. Then start node and waits till it'll be online.
        """
        if step_by_step:
            for fqdn in self.nodes['all']:
                self.restart_rabbitmq_node(fqdn=fqdn)
        else:
            self.stop_rabbitmq_cluster()
            self.start_rabbitmq_cluster()

    def rabbit_cluster_is_ok(self, node=None, exclude_node=None):
        """Execute on all nodes cluster status command.
        :param node: Provide node if you want to perform check on this certain
        node.
        :param exclude_node: Exclude this one node from cluster status check.
        :returns: Boolean
        """

        def check_cluster_is_ok(nodes):
            for one in nodes:
                with one.ssh() as remote:
                    logger.debug("%s" % '-' * 10)
                    for cmd in commands:
                        result = remote.execute(cmd, verbose=False)
                        logger.debug("{0}: [{1}] is OK: {2} ".format(
                            one.data['fqdn'], cmd, result.is_ok))
                        all_results.append(result.is_ok)
                    return all(all_results)

        commands = [self.cmd.rabbitmqctl.cluster_status,
                    self.cmd.rabbitmqctl.status,
                    self.cmd.pacemaker.show.format(
                        service=self.cmd.pacemaker.rabbit_slave_name,
                        timeout=self.TIMEOUT_SHORT,
                        fqdn='')]

        all_results = []
        if node:
            # check on one certain node
            logger.debug(
                "Check Rabbit cluster status on %s" % node.data['fqdn'])
            return check_cluster_is_ok([node])

        if exclude_node:
            logger.debug("--- Check cluster status from all rabbit nodes "
                         "EXCEPT %s ---" % exclude_node.data['fqdn'])
            rabbit_hosts = [x for x in self.all_alive_nodes()
                            if x.data['fqdn'] != exclude_node.data['fqdn']]
            return check_cluster_is_ok(rabbit_hosts)

        else:
            logger.debug("--- Check cluster status from all rabbit nodes ---")
            rabbit_hosts = self.all_alive_nodes()
            return check_cluster_is_ok(rabbit_hosts)

    def wait_rabbit_cluster_is_ok(
            self, node=None, timeout=None, exclude_node=None):
        timeout = timeout or self.TIMEOUT_SHORT
        return wait(
            lambda: self.rabbit_cluster_is_ok(
                node=node, exclude_node=exclude_node),
            timeout_seconds=timeout,
            sleep_seconds=60,
            waiting_for='RabbitMQ cluster will be ok')

    def is_rabbit_running_on_node(self, node):
        """Checks if rabbitmq is running or not on provided node.
        :param node: Node
        :return: True of False
        """
        grep_pcs_cmd = self.cmd.pacemaker.grep_rabbit_in_resource
        grep_ps_cmd = self.cmd.pacemaker.grep_rabbit_in_ps.format(
            rabbit_process_name=self.cmd.pacemaker.rabbit_process_name)

        with node.ssh() as remote:
            grep_ps_out = remote.execute(grep_ps_cmd)
            grep_pcs_out = remote.execute(grep_pcs_cmd)

        return all((grep_ps_out.is_ok, grep_pcs_out.is_ok))

    def get_rabbit_pid_on_node(self, node):
        """Returns pid of rabbitmq running on provided node.
        :param node: Node
        :return: Int PID OR None if exit_code of rabbitmqctl is not 0 or grep
        can't find pattern.
        """
        with node.ssh() as remote:
            pid = remote.execute(self.cmd.rabbitmqctl.get_pid)
        if pid.is_ok:
            return int(pid.stdout_string)
        else:
            return None
