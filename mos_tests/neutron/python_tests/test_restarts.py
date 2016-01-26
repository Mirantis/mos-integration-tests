#    Copyright 2015 Mirantis, Inc.
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

import pytest

from mos_tests.environment.devops_client import DevopsClient
from mos_tests.functions.common import wait
from mos_tests.neutron.python_tests.base import TestBase

logger = logging.getLogger(__name__)


@pytest.mark.check_env_('is_ha', 'has_2_or_more_computes')
@pytest.mark.usefixtures("setup")
class TestRestarts(TestBase):

    @pytest.fixture(autouse=True)
    def prepare_openstack(self, setup, env_name):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create network1, network2
            2. Create router1 and connect it with network1, network2 and
                external net
            3. Boot vm1 in network1 and associate floating ip
            4. Boot vm2 in network2
            5. Add rules for ping
            6. ping 8.8.8.8 from vm2
            7. ping vm1 from vm2 and vm1 from vm2
        """

        # init variables
        exist_networks = self.os_conn.list_networks()['networks']
        ext_network = [x for x in exist_networks
                       if x.get('router:external')][0]
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.hosts = self.zone.hosts.keys()[:2]
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.networks = []

        # create router
        self.router = self.os_conn.create_router(name="router01")['router']
        self.os_conn.router_gateway_add(router_id=self.router['id'],
                                        network_id=ext_network['id'])
        logger.info('router {} was created'.format(self.router['id']))

        # create networks by amount of the compute hosts
        for hostname in self.hosts:
            net_id = self.os_conn.add_net(self.router['id'])
            self.networks.append(net_id)
            self.os_conn.add_server(net_id,
                                    self.instance_keypair.name,
                                    hostname,
                                    self.security_group.id)

        # add floating ip to first server
        self.server1 = self.os_conn.nova.servers.find(name="server01")
        self.os_conn.assign_floating_ip(self.server1)

        # check pings
        self.check_vm_connectivity()

        # Find a primary controller
        primary_controller = self.env.primary_controller
        mac = primary_controller.data['mac']
        self.primary_node = DevopsClient.get_node_by_mac(env_name=env_name,
                                                         mac=mac)
        self.primary_host = primary_controller.data['fqdn']

        # Find a non-primary controller
        non_primary_controller = self.env.non_primary_controllers[0]
        mac = non_primary_controller.data['mac']
        self.non_primary_node = DevopsClient.get_node_by_mac(env_name=env_name,
                                                             mac=mac)
        self.non_primary_host = non_primary_controller.data['fqdn']

        # make a list of all l3 agent ids
        self.l3_agent_ids = [agt['id'] for agt in
                             self.os_conn.neutron.list_agents(
                                binary='neutron-l3-agent')['agents']]

        self.dhcp_agent_ids = [agt['id'] for agt in
                               self.os_conn.neutron.list_agents(
                                   binary='neutron-dhcp-agent')['agents']]

    @pytest.mark.testrail_id('542612')
    def test_shutdown_primary_controller_with_l3_agt(self):
        """[Neutron VLAN and VXLAN] Shut down primary controller
           and check l3-agent

        Steps:
            1. Check on what agents is router1:
                neutron l3-agent-list-hosting-router router1
            2. If there isn't agent on the primary controller:
                neutron l3-agent-router-remove non_on_primary_agent_id router1
                neutron l3-agent-router-add on_primary_agent_id router1
            3. Destroy primary controller
                virsh destroy <primary_controller>
            4. Wait some time until all agents are up
                neutron-agent-list
            5. Check that all routers reschedule from primary controller:
                neutron router-list-on-l3-agent <on_primary_agent_id>
            6. Boot vm3 in network1
            7. ping 8.8.8.8 from vm3
            8. ping between vm1 and vm3 by internal ip
            9. ping between vm1 and vm2 by floating ip
        """

        # Get current L3 agent on router01
        router_agt = self.os_conn.neutron.list_l3_agent_hosting_routers(
                        self.router['id'])['agents'][0]
        # Check if the agent is not on the primary controller
        # Reschedule if needed
        if router_agt['host'] != self.primary_host:

            self.os_conn.reschedule_router_to_primary_host(self.router['id'],
                                                           self.primary_host)
            router_agt = self.os_conn.neutron.list_l3_agent_hosting_routers(
                            self.router['id'])['agents'][0]

        # virsh destroy of the primary controller
        self.env.destroy_nodes([self.primary_node])

        # Excluding the id of the router_agt from the list
        # since it will stay on the destroyed controller
        # and remain disabled
        self.l3_agent_ids.remove(router_agt['id'])

        # Then check that the rest l3 agents are alive
        self.os_conn.wait_agents_alive(self.l3_agent_ids)

        # Check that there are no routers on the first agent
        assert not self.os_conn.neutron.list_routers_on_l3_agent(
            router_agt['id'])['routers']

        self.os_conn.add_server(self.networks[0],
                                self.instance_keypair.name,
                                self.hosts[0],
                                self.security_group.id)
        # Create one more server and check connectivity
        self.check_vm_connectivity()

    @pytest.mark.testrail_id('542611')
    def test_restart_primary_controller_with_l3_agt(self):
        """[Neutron VLAN and VXLAN] Reset primary controller and check l3-agent

        Steps:
            1. Check on what agents is router1:
                neutron l3-agent-list-hosting-router router1
            2. If there isn't agent on the primary controller:
                neutron l3-agent-router-remove non_on_primary_agent_id router1
                neutron l3-agent-router-add on_primary_agent_id router1
            3. Restart primary controller
            4. Wait some time until all agents are up
                neutron-agent-list
            5. Check that all routers reschedule from primary controller:
                neutron router-list-on-l3-agent <on_primary_agent_id>
            6. Boot vm3 in network1
            7. ping 8.8.8.8 from vm3
            8. ping between vm1 and vm3 by internal ip
            9. ping between vm1 and vm2 by floating ip
        """

        # Get current L3 agent on router01
        router_agt = self.os_conn.neutron.list_l3_agent_hosting_routers(
                        self.router['id'])['agents'][0]
        # Check if the agent is not on the primary controller
        # Reschedule if needed
        if router_agt['host'] != self.primary_host:
            self.os_conn.reschedule_router_to_primary_host(self.router['id'],
                                                           self.primary_host)
            router_agt = self.os_conn.neutron.list_l3_agent_hosting_routers(
                            self.router['id'])['agents'][0]

        # virsh destroy of the primary controller
        self.env.warm_restart_nodes([self.primary_node])

        # Check that the all l3 are alive
        self.os_conn.wait_agents_alive(self.l3_agent_ids)

        # Check that there are no routers on the first agent
        assert not self.os_conn.neutron.list_routers_on_l3_agent(
                        router_agt['id'])['routers']

        # Create one more server and check connectivity
        self.os_conn.add_server(self.networks[0],
                                self.instance_keypair.name,
                                self.hosts[0],
                                self.security_group.id)
        self.check_vm_connectivity()

    @pytest.mark.testrail_id('542613')
    def test_kill_active_l3_agt(self):
        """[Neutron VLAN and VXLAN] Kill l3-agent process

            8. get node with l3 agent where is the router1:
                neutron l3-agent-hosting-router router1
            9. on this node find l3-agent process:
                ps aux | grep l3-agent
            10. Kill it:
                kill -9 <pid>
            11. Wait some time until all agents are up
                neutron-agent-list
            12. Boot vm3 in network1
            13. ping 8.8.8.8 from vm3
            14. ping between vm1 and vm3 by internal ip
            15. ping between vm1 and vm2 by floating ip
        """

        # Get current L3 agent on router01
        router_agt = self.os_conn.neutron.list_l3_agent_hosting_routers(
                self.router['id'])['agents'][0]

        # Find the current controller ip with the router01
        controller_ip = ''
        for node in self.env.get_all_nodes():
            if node.data['fqdn'] == router_agt['host']:
                controller_ip = node.data['ip']
                break

        # If ip is empty than no controller with the router was found
        assert controller_ip, "No controller with the router was found"

        with self.env.get_ssh_to_node(controller_ip) as remote:
            cmd = "ps -aux | grep [n]eutron-l3-agent | awk '{print $2}'"
            result = remote.execute(cmd)
            pid = result['stdout'][0]
            logger.info('Got l3 agent pid  {}'.format(pid))
            logger.info('Now going to kill it on the controller {}'.format(
                        controller_ip))
            result = remote.execute('kill -9 {}'.format(pid))
            assert not result['exit_code'], "kill failed {}".format(result)

        self.os_conn.wait_agents_alive(self.l3_agent_ids)

        # Create one more server and check connectivity
        self.os_conn.add_server(self.networks[0],
                                self.instance_keypair.name,
                                self.hosts[0],
                                self.security_group.id)
        self.check_vm_connectivity()

    @pytest.mark.testrail_id('542625')
    def test_shutdown_primary_controller_dhcp_agent(self):
        """Shutdown primary controller and check dhcp-agent

        Scenario:
            2. Create network1, subnet1, router1
            3. Launch instances vm1 in network1
            4. Find primary controller
            5. Check on what agents is network1
            6. Run udhcp on vm1
            7. Reset primary controller
            8. Check that all networks reschedule from primary controller
            9. Run udhcp on vm1

        Duration 10m

        """
        agents_hosts = self.os_conn.get_node_with_dhcp_for_network(
            self.networks[0])

        # Check if the agent is not on the primary controller
        # Reschedule if needed
        if not any(self.primary_host in host for host in agents_hosts):
            self.os_conn.reschedule_dhcp_agent(self.networks[0],
                                               self.primary_host)

        # Get primary controller agent id
        agent_ids = [agt['id'] for agt in self.os_conn.neutron.list_agents(
            binary='neutron-dhcp-agent')['agents']
            if self.primary_host in agt['host']]

        # Run udhcp on vm
        self.run_udhcpc_on_vm(self.server1)

        # Destroy primary controller
        self.env.destroy_nodes([self.primary_node])

        # Wait some time while agents become down
        self.os_conn.wait_agents_down(agent_ids)

        # Check that all networks reschedule from primary controller
        wait(
            lambda: len(self.os_conn.neutron.list_networks_on_dhcp_agent(
                agent_ids[0])['networks']) == 0,
            timeout_seconds=60 * 5, sleep_seconds=(1, 60, 5),
            waiting_for="migrating all networks from died dhcp agent"
        )

        # Run udhcp on vm
        self.run_udhcpc_on_vm(self.server1)

    @pytest.mark.testrail_id('542628')
    def test_reset_primary_controller_dhcp_agent(self):
        """Reset primary controller and check dhcp-agent

        Scenario:
            2. Create network1, subnet1, router1
            3. Launch instances vm1 in network1
            4. Find primary controller
            5. Check on what agents is network1
            6. Run udhcp on vm1
            7. Reset primary controller
            8. Check that all networks reschedule from primary controller
            9. Run udhcp on vm1

        Duration 10m

        """
        agents_hosts = self.os_conn.get_node_with_dhcp_for_network(
            self.networks[0])

        # Check if the agent is not on the primary controller
        # Reschedule if needed
        if not any(self.primary_host in host for host in agents_hosts):
            self.os_conn.reschedule_dhcp_agent(self.networks[0],
                                               self.primary_host)

        # Get primary controller agent id
        agent_ids = [agt['id'] for agt in self.os_conn.neutron.list_agents(
            binary='neutron-dhcp-agent')['agents']
            if self.primary_host in agt['host']]

        # Run udhcp on vm
        self.run_udhcpc_on_vm(self.server1)

        # Reset primary controller
        self.env.warm_restart_nodes([self.primary_node])

        # Wait some time while agents become down
        self.os_conn.wait_agents_down(agent_ids)

        # Check that all networks reschedule from primary controller
        wait(
            lambda: len(self.os_conn.neutron.list_networks_on_dhcp_agent(
                agent_ids[0])['networks']) == 0,
            timeout_seconds=60 * 5, sleep_seconds=(1, 60, 5),
            waiting_for="migrating all networks from died dhcp agent"
        )

        # Run udhcp on vm
        self.run_udhcpc_on_vm(self.server1)

    @pytest.mark.testrail_id('542626')
    def test_shutdown_non_primary_controller_dhcp_agent(self):
        """Shutdown non-primary controller and check dhcp-agent

        Scenario:
            2. Create network1, subnet1, router1
            3. Launch instances vm1 in network1
            4. Find non-primary controller
            5. Check on what agents is network1. Reschedule agents if needed.
            6. Run udhcp on vm1
            7. Shutdown non-primary controller
            8. Check that all networks reschedule from non-primary controller
            9. Run udhcp on vm1

        Duration 10m

        """
        agents_hosts = self.os_conn.get_node_with_dhcp_for_network(
            self.networks[0])

        # Check if the agent is not on the non-primary controller
        # Reschedule if needed
        if not any(self.non_primary_host in host for host in agents_hosts):
            self.os_conn.reschedule_dhcp_agent(self.networks[0],
                                               self.non_primary_host)

        # Get non-primary controller agent id
        agent_ids = [agt['id'] for agt in self.os_conn.neutron.list_agents(
            binary='neutron-dhcp-agent')['agents']
            if self.non_primary_host in agt['host']]

        # Run udhcp on vm
        self.run_udhcpc_on_vm(self.server1)

        # Destroy non-primary controller
        self.env.destroy_nodes([self.non_primary_node])

        # Wait some time while agents become down
        self.os_conn.wait_agents_down(agent_ids)

        # Check that all networks reschedule from non-primary controller
        wait(
            lambda: len(self.os_conn.neutron.list_networks_on_dhcp_agent(
                agent_ids[0])['networks']) == 0,
            timeout_seconds=60 * 5, sleep_seconds=(1, 60, 5),
            waiting_for="migrating all networks from died dhcp agent"
        )

        # Run udhcp on vm
        self.run_udhcpc_on_vm(self.server1)
