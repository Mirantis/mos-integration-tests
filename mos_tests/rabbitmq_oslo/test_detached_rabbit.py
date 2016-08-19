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
from time import sleep

import pytest

from mos_tests.functions.common import is_task_ready
from mos_tests.functions.common import wait
from mos_tests.ironic.scale_test import map_interfaces
from mos_tests.neutron.python_tests.base import TestBase
from mos_tests.rabbitmq_oslo.utils import BashCommand

logger = logging.getLogger(__name__)


class DetachRabbitPluginFunctions(TestBase):

    @pytest.fixture(autouse=True)
    def tools(self, rabbitmq):
        self.rabbitmq = rabbitmq
        self.cmd = BashCommand
        self.rabbit_plugin_name = self.cmd.detach_rabbitmq.plugin_name

    TIMEOUT_FOR_DEPLOY = 120
    TIMEOUT_SHORT = 3

    def rabbit_plugin_ver(self, admin_remote):
        """Returns str with version of detached rabbitmq plugin"""
        cmd = self.cmd.detach_rabbitmq.grep_plugin_version.format(
            plugin_name=self.cmd.detach_rabbitmq.plugin_name)
        return admin_remote.check_call(cmd).stdout_string

    def alive_standalone_rabbitmq_node(self):
        """Returns one alive rabbit node"""
        return self.rabbitmq.alive_node()

    def rabbit_nodes_roles(self):
        """Return dict with mapping between alive rabbit node FQDN and its role
        :return: Dict with roles and nodes's FQDNs. Like:
        :  {'all':    ['node-1.test.domain.local','node-4...'],
        :   'master': ['node-1.test.domain.local'],
        :   'slave':  ['node-2.test.domain.local', 'node-4...']}
        """
        return self.rabbitmq.nodes_list()

    def rabbit_nodes_statuses(self):
        """Returns dict of nodes' FQDNs with statuses based on 'pcs status xml'
        performed from standalone rabbit node.
        :return: Like:
        :   {'node-1.test.domain.local': 'offline',
        :    'node-3.test.domain.local': 'online'}
        """
        return self.rabbitmq.nodes_statuses()

    def rabbit_node(self, role='slave'):
        """Returns one rabbit master or slave node.
        :param role: Role of a node: 'slave' or 'master'
        :return: Node
        """
        return self.rabbitmq.rabbit_node_by_role(role=role)

    def disable_node(self, node):
        """Performs 'halt' on provided node. Waits till it'll be offline"""
        with node.ssh() as remote:
            remote.check_call(self.cmd.system.halt)

        wait(lambda: not node.is_ssh_avaliable(),
             timeout_seconds=60 * 2,
             sleep_seconds=10,
             waiting_for="Node to became unavailable")

    def is_rabbit_plugin_installed(self, admin_remote):
        """Checks if plugin installed on admin node
        :param admin_remote: connection point to admin node
        :return: True of False
        """
        cmd = self.cmd.detach_rabbitmq.grep_plugin.format(
            plugin_name=self.cmd.detach_rabbitmq.plugin_name)
        out = admin_remote.execute(cmd)
        return out.is_ok

    def is_rabbit_cluster_ok(self, rabbit_node=None):
        """Performs execution of commands below on node.
        If successful - Runs OSTF tests and returns True.
        :param rabbit_node: Provide node if you want to perform check on this
        certain node.
        :return: True of False
        """
        return self.rabbitmq.rabbit_cluster_is_ok(node=rabbit_node)

    def wait_rabbit_cluster_is_ok(self, rabbit_node=None):
        return self.rabbitmq.wait_rabbit_cluster_is_ok(node=rabbit_node)

    def is_rabbit_running_on_node(self, node):
        """Checks if rabbitmq is running or not on provided node.
        :param node: Node
        :return: True of False
        """
        return self.rabbitmq.is_rabbit_running_on_node(node=node)

    def get_rabbit_pid_on_node(self, node):
        """Returns pid of rabbitmq running on provided node
        :return: pid OR None if exit_code of rabbitmqctl is not 0 or grep
        can't find pattern.
        """
        return self.rabbitmq.get_rabbit_pid_on_node(node=node)

    def kill_rabbit_on_node(self, node, pid=None):
        """Kill process by PID on provided node
        :param node: Node
        :param pid: Optional. Kill this PID.
        """
        self.rabbitmq.kill_rabbit_on_node_by_pid(node=node, pid=pid)

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

    def reset_env(self, timeout=2):
        self.env.reset()
        wait(lambda: self.env.status == 'new',
             timeout_seconds=60 * timeout,
             sleep_seconds=20,
             waiting_for="Env reset finish")

    def delete_env(self, timeout=2):
        self.env.reset()
        wait(lambda: self.env.status == 'new',
             timeout_seconds=60 * timeout,
             sleep_seconds=20,
             waiting_for="Env reset finish")
        self.env.delete()

    def deploy_env(self):
        """Deploy env and wait till it will be deployed"""
        deploy_task = self.env.deploy_changes()
        wait(lambda: is_task_ready(deploy_task),
             timeout_seconds=60 * self.TIMEOUT_FOR_DEPLOY,
             sleep_seconds=60,
             waiting_for='changes to be deployed')

    def map_devops_to_fuel_net(self, env, devops_env, fuel_node):
        # Make devops network.id -> fuel networks mapping
        controller = env.get_nodes_by_role('controller')[0]
        interfaces_map = {}
        for fuel_if, devop_if in map_interfaces(devops_env, controller):
            interfaces_map[devop_if.network_id] = fuel_if['assigned_networks']

        # Assign fuel networks to corresponding interfaces
        interfaces = []
        for fuel_if, devop_if in map_interfaces(devops_env, fuel_node):
            fuel_if['assigned_networks'] = interfaces_map[devop_if.network_id]
            interfaces.append(fuel_if)
        return interfaces

    def is_network_verification_ok(self):
        """Run network verification in fuel.
        :return: boolean
        """
        result = self.env.wait_network_verification()
        return result.status == 'ready'


@pytest.mark.check_env_("has_3_or_more_standalone_rabbitmq_nodes")
class TestDetachRabbitPlugin3nodes(DetachRabbitPluginFunctions):

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('1455768')
    def test_check_installed_plugin(self, env, admin_remote):
        """Checks that plugin installed successfully.

        Actions:
        1. Check that fuel node has installed rabbit plugin;
        2. Check that detahed rabbitmq nodes has rabbitmq_server role.
        """
        # Check plugin present on fuel node
        assert self.is_rabbit_plugin_installed(admin_remote)
        assert self.is_rabbit_cluster_ok()

        rabbit_nodes = env.get_nodes_by_role('standalone-rabbitmq')
        rabbit_nodes_fqdns = [x.data['fqdn'] for x in rabbit_nodes]

        # Check roles on rabbit node
        assert all(i in str(self.rabbitmq.nodes_list()['all'])
                   for i in rabbit_nodes_fqdns)

    # Destructive
    @pytest.mark.testrail_id('1455771')
    def test_uninstall_plugin(self, admin_remote):
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

        del_plugin_cmd = self.cmd.detach_rabbitmq.del_plugin.format(
            full_name=plugin_name_ver)

        err_words = (
            "400 Client Error",
            "Can't delete plugin which is enabled for some environment")
        removed_ok_words = (
            "Complete!",
            "Plugin {0} was successfully removed".format(plugin_name_ver))

        # Try to delete rabbit plugin on deployed env
        del_out = admin_remote.execute(del_plugin_cmd)
        # Check that deletion was NOT successful
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
        rabbit_service_cmd = self.cmd.pacemaker.grep_rabbit_in_status
        rabbit_cluster_status_cmd = self.cmd.rabbitmqctl.cluster_status

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
        timeout = 5  # minutes, wait for rabbit recover

        # Get master standalone rabbit node for disabling
        old_master = self.rabbit_node('master')
        old_master_fqdn = old_master.data['fqdn']

        # Disable master rabbit node
        logger.debug("Disabling RabbitMQ master node")
        self.disable_node(old_master)

        # Wait for rabbit cluster to recover
        logger.debug("Sleeping for %s minutes" % timeout)
        sleep(60 * timeout)

        # Check rabbit status,
        wait(lambda: self.is_rabbit_cluster_ok(),
             timeout_seconds=60 * timeout,
             sleep_seconds=30,
             waiting_for="RabbitMQ became online")

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

        for node in (rabbit_slave, rabbit_master):
            self.kill_rabbit_on_node(node)
            self.wait_rabbit_respawn_on_node(node)
            sleep(60 * 1)
            self.wait_rabbit_respawn_on_node(node, fast_check=True)
            assert self.wait_rabbit_cluster_is_ok() is True, (
                "RabbitMQ cluster is not OK")

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
        plugin_name_with_version = "{0}=={1}".format(
            self.rabbit_plugin_name, plugin_ver)
        remove_plugin_cmd = self.cmd.detach_rabbitmq.del_plugin.format(
            full_name=plugin_name_with_version)

        admin_remote.check_call(remove_plugin_cmd)
        assert not self.is_rabbit_plugin_installed(admin_remote)

        # Install plugin
        install_plugin_cmd = self.cmd.detach_rabbitmq.install_plugin.format(
            plugin_path=plugin_path)
        admin_remote.check_call(install_plugin_cmd)
        assert self.is_rabbit_plugin_installed(admin_remote)


@pytest.mark.check_env_("is_ha", "has_1_standalone_rabbitmq_node")
class TestDetachRabbitPlugin1node(DetachRabbitPluginFunctions):

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('1616815')
    def test_check_installed_plugin_1node(self, env, admin_remote):
        """Checks that plugin installed successfully.(1 RabbitMQ node)

        Actions:
        1. Check that fuel node has installed rabbit plugin;
        2. Check that detached rabbitmq nodes has rabbitmq_server role.
        """
        # Check plugin present on fuel node
        assert self.is_rabbit_plugin_installed(admin_remote)
        assert self.is_rabbit_cluster_ok()

        rabbit_nodes = env.get_nodes_by_role('standalone-rabbitmq')
        rabbit_nodes_fqdns = [x.data['fqdn'] for x in rabbit_nodes]

        # Check roles on rabbit node
        assert all(i in str(self.rabbitmq.nodes_list()['all'])
                   for i in rabbit_nodes_fqdns)

    @pytest.mark.undestructive
    @pytest.mark.check_env_("has_3_or_more_mongo_nodes")
    @pytest.mark.testrail_id('1616821')
    def test_check_ceilometer_with_detached_plugin(self, admin_remote):
        """Check that Ceilometer successfully worked with detached RabbitMQ.

        Actions:
        1. Check RabbitMQ health on RabbitMQ standalone node;
        2. Run OSFT tests;
        3. Check RabbitMQ is running on RabbitMQ standalone node;
        4. Check RabbitMQ is not running on controller.
        """
        rabbit_node = self.alive_standalone_rabbitmq_node()
        controller = random.choice(self.env.get_nodes_by_role('controller'))

        assert self.is_rabbit_plugin_installed(admin_remote)

        assert self.is_rabbit_cluster_ok(rabbit_node)
        assert self.is_rabbit_running_on_node(rabbit_node)

        assert not self.is_rabbit_cluster_ok(controller)
        assert not self.is_rabbit_running_on_node(controller)


# destructive
@pytest.mark.need_devops
@pytest.mark.check_env_("has_3_or_more_standalone_rabbitmq_nodes")
class TestDetachRabbitPluginRedeploy3nodes(DetachRabbitPluginFunctions):

    @pytest.mark.testrail_id('1455769')
    def test_remove_add_rabbit_nodes_to_env(self, env, devops_env):
        """Modify env with enabled plugin (removing/adding RabbitMQ nodes).

        Actions:
        1. Find node with RabbitMQ master role and remove it from fuel env.
        2. Deploy changes.
        3. Check RabbitMQ health and run OSFT tests.
        4. Add back old node with RabbitMQ role to fuel env.
        5. Run network verification.
        6. Deploy changes.
        7. Check RabbitMQ health and run OSFT tests.

        Duration: ~ 30 min
        """
        master_fuel_node = self.rabbit_node(role='master')
        master_devops_node = devops_env.get_node_by_fuel_node(master_fuel_node)

        # Unassign rabbit master node
        logger.debug("Unassign rabbit master node.")
        env.unassign([master_fuel_node.id])

        # Deploy env without old rabbit master node
        logger.debug("Deploy env without old rabbit master node.")
        self.deploy_env()
        assert self.is_rabbit_cluster_ok(), 'RabbitMQ cluster is not OK'

        # Add back old rabbit master node to env
        logger.debug("Add back old rabbit master node to env.")

        # for some reasons there is a need to give test some time for this
        master_fuel_node = wait(
            lambda: env.get_node_by_devops_node(master_devops_node),
            timeout_seconds=60 * self.TIMEOUT_SHORT,
            sleep_seconds=10,
            waiting_for="Master fuel node to located")

        master_fuel_node.set(
            {'name': master_devops_node.name + '_standalone-rabbitmq_new'})
        env.assign([master_fuel_node], ['standalone-rabbitmq'])

        # Restore network interfaces for old master rabbit node
        logger.debug("Restore network interfaces for old master rabbit node.")
        interfaces = self.map_devops_to_fuel_net(env, devops_env,
                                                 master_fuel_node)
        master_fuel_node.upload_node_attribute('interfaces', interfaces)

        # Run network verification
        logger.debug("Run network verification.")
        assert self.is_network_verification_ok(), "Network verification failed"

        # Deploy env with old rabbit master node
        logger.debug("Deploy env with old rabbit master node.")
        self.deploy_env()

        # Check env and rabbit is ok
        env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)
        assert self.is_rabbit_cluster_ok(), 'RabbitMQ cluster is not OK'

    @pytest.mark.testrail_id('1455776')
    def test_plugin_is_not_enabled(self, env):
        """Check that plugin does not affect environment if the plugin
        is not enabled.

        Actions:
        1. Check that rabbitmq is not running on controller nodes.
        2. Reset environment.
        3. Unassign 'standalone-rabbitmq' role from all standalone-rabbitmq
        nodes.
        4. Turn off "Detach RabbitMQ Plugin" option in Fuel settings.
        5. Run network verification.
        6. Deploy env without standalone rabbit nodes.
        7. Check rabbit cluster status is OK and it is running on controllers.

        Duration: ~ 60 min
        """
        controllers = env.get_nodes_by_role('controller')
        rabbit_nodes = env.get_nodes_by_role('standalone-rabbitmq')

        # Check rabbit is not running on controllers
        for controller in controllers:
            assert self.is_rabbit_running_on_node(controller) is False, (
                "Rabbit is running on controller node, but it should not")

        self.reset_env()

        # Unassign all standalone rabbit nodes
        for node in rabbit_nodes:
            logger.debug("Unassign node with roles %s" % node.data['roles'])
            env.unassign([node.id])

        # Turn off "Detach RabbitMQ Plugin" in Fuel
        data = env.get_settings_data()
        data['editable']['detach-rabbitmq']['metadata']['enabled'] = False
        env.set_settings_data(data)

        # Run network verification.
        # wait() required as it'll not always pass after the first attempt
        logger.debug("Run network verification.")
        wait(self.is_network_verification_ok,
             timeout_seconds=60 * 12,
             sleep_seconds=60 * 4,
             waiting_for="network verification will pass")

        # Deploy env without standalone rabbit nodes
        logger.debug("Deploy env without standalone rabbit nodes.")
        self.deploy_env()
        assert self.env.status == 'operational', "Env is not operational"
        env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)

        # Check rabbit is running on controllers
        controllers = env.get_nodes_by_role('controller')
        for controller in controllers:
            assert self.is_rabbit_running_on_node(controller), (
                "Rabbit is NOT running on controller node, but it should")

            assert self.is_rabbit_cluster_ok(rabbit_node=controller), (
                "Rabbit cluster status is not OK")


# destructive
@pytest.mark.need_devops
@pytest.mark.check_env_("is_ha", "has_1_standalone_rabbitmq_node")
class TestDetachRabbitPluginRedeploy1node(DetachRabbitPluginFunctions):

    @pytest.mark.testrail_id('1455770')
    def test_remove_add_compute_controller_nodes_to_env(self, env, devops_env):
        """Modify env with enabled plugin
        (removing/adding compute and controller node).

        Actions:
        1. Find and remove controller node from the environment.
        2. Run network verification.
        3. Deploy environment.
        4. Check that env and rabbitMQ cluster is OK.
        5. Perform steps 1-4 for compute node.
        6. Add back controller node to the environment.
        7. Run network verification.
        8. Deploy environment.
        9. Check that env and rabbitMQ cluster is OK.
        10. Perform steps 6-10 for compute node.

        Duration: ~ 90 min
        """
        controller_fuel = self.env.get_nodes_by_role('controller')[0]
        controller_devops = devops_env.get_node_by_fuel_node(controller_fuel)

        compute_fuel = self.env.get_nodes_by_role('compute')[0]
        compute_devops = devops_env.get_node_by_fuel_node(compute_fuel)

        # Unassign controller and compute from env and deploy changes
        for node in (controller_fuel, compute_fuel):

            # Unassign node
            logger.debug("Unassign node with roles %s" % node.data['roles'])
            env.unassign([node.id])
            assert self.is_network_verification_ok(), "Net verification failed"

            # Deploy changes
            logger.debug("Deploy changes and check rabbit is OK.")
            self.deploy_env()

            # Check env and rabbit is OK
            assert self.env.status == 'operational', "Env is not operational"
            env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)
            assert self.is_rabbit_cluster_ok(), 'RabbitMQ cluster is not OK'

        # Add back deleted controller and compute from env and deploy changes
        for devops_node, fuel_node in ((controller_devops, controller_fuel),
                                       (compute_devops, compute_fuel)):
            # Assign node
            node_name = fuel_node.data['name']
            node_roles = fuel_node.data['roles']

            logger.debug("Assign back node with roles %s" % node_roles)

            # Update info about fuel node
            fuel_node = env.get_node_by_devops_node(devops_node)
            fuel_node.set({'name': node_name + '_new'})

            # Assign roles to node
            env.assign([fuel_node], node_roles)

            # Restore network interfaces for old master rabbit node
            logger.debug("Restore network interfaces for node.")
            interfaces = self.map_devops_to_fuel_net(env, devops_env,
                                                     fuel_node)
            fuel_node.upload_node_attribute('interfaces', interfaces)

            # Run network verification
            logger.debug("Run network verification.")
            assert self.is_network_verification_ok(), "Net verification failed"

            # Deploy env with new node
            logger.debug("Deploy env with old rabbit master node.")
            self.deploy_env()

            # Check env and rabbit is ok
            assert self.env.status == 'operational', "Env is not operational"
            env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)
            assert self.is_rabbit_cluster_ok(), 'RabbitMQ cluster is not OK'
