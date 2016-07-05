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
from time import sleep
import xml.etree.ElementTree as ElementTree

import pytest

from mos_tests.functions.common import wait
from mos_tests.neutron.python_tests.base import TestBase

logger = logging.getLogger(__name__)


@pytest.yield_fixture
def admin_remote(fuel):
    with fuel.ssh_admin() as remote:
        yield remote


@pytest.mark.check_env_("has_3_or_more_standalone_rabbitmq_nodes")
class TestDetachRabbitPlugin(TestBase):

    rabbit_plugin_name = 'detach-rabbitmq'

    def rabbit_plugin_ver(self, admin_remote):
        """Returns str with version of detached rabbitmq plugin"""
        cmd = "fuel plugins --list | grep '{0}' | awk '{{print $5}}'".format(
            self.rabbit_plugin_name)
        return admin_remote.check_call(cmd).stdout_string.strip()

    def is_rabbit_plugin_installed(self, admin_remote):
        cmd = "fuel plugins --list | grep '{0}'".format(
            self.rabbit_plugin_name)
        out = admin_remote.execute(cmd)
        return out.is_ok

    def alive_standalone_rabbitmq_node(self):
        """Returns one alive rabbit node"""
        rabbit_node = None
        rabbit_nodes = self.env.get_nodes_by_role('standalone-rabbitmq')
        for node in rabbit_nodes:
            if node.is_ssh_avaliable():
                rabbit_node = node
                break
        if not rabbit_node:
            raise Exception('No alive standalone-rabbitmq nodes')
        return rabbit_node

    def rabbit_nodes_roles(self):
        """Return dict with mapping between alive rabbit node FQDN and its role
        :return: Dict with roles and nodes's FQDNs. Like:
        :    {'master': ['node-1.test.domain.local'],
        :    'slave': ['node-3.test.domain.local', 'node-5.test.domain.local']}
        """
        counted_roles = ('master', 'slave')
        get_cluster_status_cmd = 'pcs status xml'

        nodes_roles = {}
        for role in counted_roles:
            nodes_roles[role] = []

        # Get cmd output from rabbit node
        rabbit_node = self.alive_standalone_rabbitmq_node()
        with rabbit_node.ssh() as remote:
            status = remote.check_call(get_cluster_status_cmd, verbose=False)

        status = ElementTree.fromstring(status.stdout_string)
        for node in status.findall('./resources//resource'):
            node_resource_agent = node.attrib.get('resource_agent', '')
            node_role = node.attrib.get('role', '').lower()
            if ('rabbitmq-server' in node_resource_agent and
                    node_role in counted_roles):
                node_fqdn = node.find('node').get('name')
                nodes_roles[node_role].append(node_fqdn)
        return nodes_roles

    def rabbit_nodes_statuses(self):
        """Returns dict of nodes' FQDNs with statuses based on 'pcs status xml'
        performed from standalone rabbit node.
        :return: Like:
        :   {'node-1.test.domain.local': 'offline',
        :    'node-3.test.domain.local': 'online'}
        """
        get_cluster_status_cmd = 'pcs status xml'
        alive_mapping = {'true': 'online', 'false': 'offline'}

        # Get cmd output from rabbit node
        rabbit_node = self.alive_standalone_rabbitmq_node()
        with rabbit_node.ssh() as remote:
            status = remote.check_call(get_cluster_status_cmd, verbose=False)

        nodes_statuses = {}
        status = ElementTree.fromstring(status.stdout_string)
        for node in status.findall('nodes/node'):
            node_fqdn = node.attrib.get('name', '')
            node_status = node.attrib.get('online', '')
            nodes_statuses[node_fqdn] = alive_mapping[node_status]
        return nodes_statuses

    def rabbit_node(self, role='slave'):
        """Return rabbit master node
        :param role: Role of a node: 'slave' or 'master'
        :return: Node
        """
        roles = self.rabbit_nodes_roles()
        rabbit_nodes = self.env.get_nodes_by_role('standalone-rabbitmq')
        # Check that we have nodes with that role
        assert len(roles[role]) > 0, "No %s roles" % role
        # Find node with required role
        role_node_fqdn = roles[role][0]
        return [x for x in rabbit_nodes if x.data['fqdn'] == role_node_fqdn][0]

    def disable_node(self, node):
        """Performs 'halt' on provided node. Waits till it'll be offline"""
        with node.ssh() as remote:
            remote.check_call('halt')

        wait(lambda: not node.is_ssh_avaliable(),
             timeout_seconds=60 * 2,
             sleep_seconds=10,
             waiting_for="Env reset finish")

    def check_rabbit_cluster_is_ok(self):
        """Check that exit_code of rabbitmqctl is 0. Runs OSTF tests"""
        rabbit_node = self.alive_standalone_rabbitmq_node()
        with rabbit_node.ssh() as remote:
            remote.check_call('rabbitmqctl cluster_status')
        self.env.wait_for_ostf_pass()

    def get_rabbit_pid_on_node(self, node):
        """Returns pid of rabbitmq running on provided node
        :return: pid OR None if exit_code of rabbitmqctl is not 0 or grep
        can't find pattern.
        """
        get_pid_cmd = "rabbitmqctl status | grep pid | grep -o '[0-9]*'"
        with node.ssh() as remote:
            pid = remote.execute(get_pid_cmd)
        if pid.is_ok:
            return int(pid.stdout_string.strip())
        else:
            return None

    def kill_rabbit_on_node(self, node):
        kill_cmd = 'kill -9 {pid}'
        pid = self.get_rabbit_pid_on_node(node)
        with node.ssh() as remote:
            remote.check_call(kill_cmd.format(pid=pid))

    def wait_rabbit_respawn_on_node(self, node, timeout=5, fast_check=False):
        node_fqdn = node.data['fqdn']

        if fast_check:
            assert self.get_rabbit_pid_on_node(node) is not None
            assert node_fqdn in str(self.rabbit_nodes_roles().values())
            assert self.rabbit_nodes_statuses()[node_fqdn] == 'online'
        else:
            wait(lambda: self.get_rabbit_pid_on_node(node) is not None,
                 timeout_seconds=60 * timeout,
                 sleep_seconds=30,
                 waiting_for="RabbitMQ has pid on {0}".format(node_fqdn))

            wait(lambda: node_fqdn in str(self.rabbit_nodes_roles().values()),
                 timeout_seconds=60 * timeout,
                 sleep_seconds=30,
                 waiting_for="RabbitMQ has any role on {0}".format(node_fqdn))

            wait(lambda: self.rabbit_nodes_statuses()[node_fqdn] == 'online',
                 timeout_seconds=60 * timeout,
                 sleep_seconds=30,
                 waiting_for="RabbitMQ became online on {0}".format(node_fqdn))

    def delete_env(self, timeout=2):
        self.env.reset()
        wait(lambda: self.env.status == 'new',
             timeout_seconds=60 * timeout,
             sleep_seconds=20,
             waiting_for="Env reset finish")
        self.env.delete()

    # ------------------------------------------------------------------------

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('1455768')
    def test_check_installed_plugin(self, env, admin_remote):
        """Checks that plugin installed successfully.

        Actions:
        1. Check that fuel node has installed rabbit plugin;
        2. Check that detahed rabbitmq nodes has rabbitmq_server role.
        """
        get_rabbit_nodes_cmd = ("pcs status --full | grep p_rabbitmq-server |"
                                "grep ocf | grep -o 'node-.*'")
        grep_plugin_list_cmd = (
            "fuel plugins --list | grep {0}".format(self.rabbit_plugin_name))

        # Check plugin present on fuel node
        admin_remote.check_call(grep_plugin_list_cmd)

        rabbit_nodes = env.get_nodes_by_role('standalone-rabbitmq')
        rabbit_nodes_fqdns = [x.data['fqdn'] for x in rabbit_nodes]

        # Check roles on rabbit node
        with rabbit_nodes[0].ssh() as remote:
            out = remote.check_call(get_rabbit_nodes_cmd).stdout_string
        assert all(i in out for i in rabbit_nodes_fqdns)

    # Destructive
    @pytest.mark.testrail_id('1455771')
    def test_uninstall_plugin(self, env, admin_remote):
        """Uninstall of plugin with deployed environment.

        Actions:
        1. Try to delete plugin from fuel node with deployed env;
        2. Ensure that the following output is present in cli alert:
        "400 Client Error: Bad Request (Can't delete plugin which is enabled
        for some environment.)";
        3. Reset and remove environment;
        4. Remove plugin one more time;
        5. Check that it was successfully removed.
        """
        plugin_ver = self.rabbit_plugin_ver(admin_remote)
        plugin_name_ver = '{0}=={1}'.format(
            self.rabbit_plugin_name, plugin_ver)
        del_plugin_cmd = 'fuel plugins --remove {0}'.format(plugin_name_ver)

        err_words = (
            "400 Client Error",
            "Can't delete plugin which is enabled for some environment")
        removed_ok_words = (
            "Complete!",
            "Plugin {0} was successfully removed".format(plugin_name_ver))

        # Try to delete rabbit plugin on deployed env
        del_out = admin_remote.execute(del_plugin_cmd)
        # Check that deletion was not successful
        assert not del_out.is_ok, 'Enabled plugin deletion should fail'
        assert all(i in del_out.stderr_string for i in err_words), (
            'Stderr should contain certain words in it: {0}').format(err_words)

        # Reset and delete env
        self.delete_env()

        # Delete plugin after env reset
        del_out = admin_remote.check_call(del_plugin_cmd)
        assert all(i in del_out.stdout_string for i in removed_ok_words), (
            'Stdout should contain certain words in it: {0}').format(
            removed_ok_words)

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('1455773')
    def test_check_rabbit_runs_on_proper_nodes(self, env):
        """Check that RabbitMQ runs on proper nodes.

        Actions:
        1. Check controllers has no RabbitMQ roles;
        2. Check standalone rabbit has them.
        """
        rabbit_service_cmd = 'pcs status --full | grep rabbitmq-server'
        rabbit_cluster_status_cmd = 'rabbitmqctl cluster_status'

        rabbit_nodes = env.get_nodes_by_role('standalone-rabbitmq')
        controllers = env.get_nodes_by_role('controller')

        # Check no rabbit on controllers
        for controller in controllers:
            with controller.ssh() as remote:
                assert not remote.execute(rabbit_service_cmd).is_ok
                assert not remote.execute(rabbit_cluster_status_cmd).is_ok

        # Check rabbit present on standalone nodes
        for rabbit_node in rabbit_nodes:
            with rabbit_node.ssh() as remote:
                assert remote.execute(rabbit_service_cmd).is_ok
                assert remote.execute(rabbit_cluster_status_cmd).is_ok

    # Destructive
    @pytest.mark.testrail_id('1455775')
    def test_destroy_master_rabbit_node(self):
        """Destroy one of RabbitMQ nodes .

        Actions:
        1. Poweroff master standalone rabbitmq node;
        2. Wait some time for rabbitmq cluster to recover;
        3. Check RabbitMQ health with rabbitmqctl;
        4. Check that old master is offline;
        5. Check that new master != old master;
        """
        timeout = 4  # minutes, wait for rabbit recover

        # Get master standalone rabbit node for disabling
        old_master = self.rabbit_node('master')
        old_master_fqdn = old_master.data['fqdn']

        # Disable master rabbit node
        self.disable_node(old_master)

        # Wait for rabbit cluster to recover
        logger.debug("Sleeping for %s minutes" % timeout)
        sleep(60 * timeout)

        # Check rabbit status,
        self.check_rabbit_cluster_is_ok()

        # Check that old master now offline
        assert self.rabbit_nodes_statuses()[old_master_fqdn] == 'offline'
        # Check that now we have a new master
        assert old_master_fqdn not in self.rabbit_nodes_roles()

    # Destructive
    @pytest.mark.testrail_id('1455774')
    def test_rabbitmq_failover(self):
        """Test RabbitMQ failover.

        Actions:
        1. Log into RabbitMQ slave node and kill running rabbitmq process;
        2. Wait for RabbitMQ to respawn on that node. Check that node has been
        restored;
        3. Wait for 1 more minute and repeat checks;
        4. Run OSTF;
        5. Perform 1-4 steps for RabbitMQ master node.
        """
        rabbit_slave = self.rabbit_node('slave')
        rabbit_master = self.rabbit_node('master')

        # Kill and check Rabbit Slave node
        self.kill_rabbit_on_node(rabbit_slave)
        self.wait_rabbit_respawn_on_node(rabbit_slave)
        sleep(60 * 1)
        self.wait_rabbit_respawn_on_node(rabbit_slave, fast_check=True)
        self.check_rabbit_cluster_is_ok()

        # Kill and check Rabbit Master node
        self.kill_rabbit_on_node(rabbit_master)
        self.wait_rabbit_respawn_on_node(rabbit_master)
        sleep(60 * 1)
        self.wait_rabbit_respawn_on_node(rabbit_master, fast_check=True)

    # Destructive
    @pytest.mark.testrail_id('1455772')
    def test_uninstall_install_plugin(self, admin_remote):
        """Uninstall of plugin.

        Actions:
        1. Remove rabbitmq plugin;
        2. Check that it was successfully removed;
        3. Install plugin;
        4. Check that it was installed successfully.
        """
        plugin_ver = self.rabbit_plugin_ver(admin_remote)

        # Find plugin's file location on master node
        plugin_path_cmd = 'find / -name "{0}*.rpm" -type f | tail -1'.format(
            self.rabbit_plugin_name)
        plugin_path = (admin_remote.check_call(plugin_path_cmd)
                       .stdout_string.strip())
        assert len(plugin_path) > len(self.rabbit_plugin_name)

        self.delete_env()

        # Remove plugin
        remove_plugin_cmd = "fuel plugins --remove {0}=={1}".format(
            self.rabbit_plugin_name, plugin_ver)
        admin_remote.check_call(remove_plugin_cmd)
        assert not self.is_rabbit_plugin_installed(admin_remote)

        # Install plugin
        install_plugin_cmd = "fuel plugins --install {}".format(plugin_path)
        admin_remote.check_call(install_plugin_cmd)
        assert self.is_rabbit_plugin_installed(admin_remote)
