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

import pytest

import logging

from mos_tests.neutron.python_tests.base import TestBase
from mos_tests.environment.devops_client import DevopsClient

logger = logging.getLogger(__name__)


@pytest.mark.usefixtures("check_ha_env", "check_several_computes", "setup")
class TestRestarts(TestBase):

    @pytest.fixture(autouse=True)
    def prepare_openstack(self, setup):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create network1, network2
            2. Create router1 and connect it with network1, network2 and
                external net
            3. Boot vm1 in network1 and associate floating ip
            4. Boot vm2 in network2
            5. Add rules for ping
            6. Ping 8.8.8.8, vm1 (both ip) and vm2 (fixed ip) from each other
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
        server1 = self.os_conn.nova.servers.find(name="server01")
        self.os_conn.assign_floating_ip(server1)

        # check pings
        self.check_vm_connectivity()

        # Find a primary contrloller
        for node in self.env.get_all_nodes():
            # TBD this is a temp solution.
            # Te be replaced by 'heira role' in next commit
            if node.data['name'] == 'slave-01_controller':
                self.primary_node =\
                    DevopsClient.get_devops_node(
                        node.data['name'].split('_')[0])
                self.primary_host = node.data['fqdn']
                break

        # make a list of all l3 agent ids
        self.l3_agent_ids =\
            [agt['id'] for agt in self.os_conn.neutron.list_agents(
                                       binary='neutron-l3-agent')['agents']]

    def test_shutdown_primary_controller_with_l3_agt(self):

        # Get current L3 agent on router01
        router_agt =\
            self.os_conn.neutron.list_l3_agent_hosting_routers(
                self.router['id'])['agents'][0]
        # Check if the agent is not on the prmary controller
        # Resceduler if needed
        if router_agt['host'] != self.primary_host:

            self.os_conn.reschedule_router_to_primary_host(self.router['id'],
                                                      self.primary_host)
            router_agt =\
                self.os_conn.neutron.list_l3_agent_hosting_routers(
                    self.router['id'])['agents'][0]

        # virsh destroy of the primary controller
        self.env.destroy_nodes([self.primary_node])

        # Excluding the id of the router_agt from the list
        # since it will stay on the destroyed controller
        # and remain disabled
        self.l3_agent_ids.remove(router_agt['id'])

        # Then check that the rest l3 agents are alive
        self.os_conn.wait_agents_alive(self.l3_agent_ids)

        # Check that tere are no routers on the first agent
        assert(not self.os_conn.neutron.list_routers_on_l3_agent(
                router_agt['id'])['routers'])

        self.os_conn.add_server(self.networks[0],
                                self.instance_keypair.name,
                                self.hosts[0],
                                self.security_group.id)
        # Create one more server and check connectivity
        self.check_vm_connectivity()

    def test_restart_primary_controller_with_l3_agt(self):

        # Get current L3 agent on router01
        router_agt =\
            self.os_conn.neutron.list_l3_agent_hosting_routers(
                self.router['id'])['agents'][0]
        # Check if the agent is not on the prmary controller
        # Resceduler if needed
        if router_agt['host'] != self.primary_host:
            self.os_conn.reschedule_router_to_primary_host(self.router['id'],
                                                      self.primary_host)
            router_agt =\
                self.os_conn.neutron.list_l3_agent_hosting_routers(
                    self.router['id'])['agents'][0]

        # virsh destroy of the primary controller
        self.env.warm_restart_nodes([self.primary_node])

        # Check that the all l3 are alive
        self.os_conn.wait_agents_alive(self.l3_agent_ids)

        # Check that tere are no routers on the first agent
        assert(not self.os_conn.neutron.list_routers_on_l3_agent(
                        router_agt['id'])['routers'])

        # Create one more server and check connectivity
        self.os_conn.add_server(self.networks[0],
                                self.instance_keypair.name,
                                self.hosts[0],
                                self.security_group.id)
        self.check_vm_connectivity()
