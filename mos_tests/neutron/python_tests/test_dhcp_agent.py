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

logger = logging.getLogger(__name__)


@pytest.mark.check_env_('is_ha', 'has_2_or_more_computes')
@pytest.mark.usefixtures("setup")
class TestDHCPAgent(TestBase):

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

    def get_all_dhcp_agents(self):
        dhcp_agts = [agt for agt in self.os_conn.neutron.list_agents(
                                       binary='neutron-dhcp-agent')['agents']]
        return dhcp_agts

    def isclose(self, a, b, rel_tol=1e-9, abs_tol=0.0):
        return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

    def test_to_check_dhcp_agents_work(self):

        tenant = self.os_conn.neutron.get_quotas_tenant()
        tenant_id = tenant['tenant']['tenant_id']
        self.os_conn.neutron.update_quota(tenant_id, {'quota':
                                                      {'network': 1000,
                                                       'router': 1000,
                                                       'subnet': 1000,
                                                       'port': 1000}})
        # According to the test requirements 50 networks should be created
        # However during implementation found that only about 34 nets
        # can be creaed for one tenant. Need to clarify that situation.
        for x in range(30):
            net_id = self.os_conn.add_net(self.router['id'])
            self.networks.append(net_id)
            logger.info(len(self.networks))
            srv = self.os_conn.create_server(
                      name='instanseNo{}'.format(x),
                      key_name=self.instance_keypair.name,
                      nics=[{'net-id': net_id}])
            self.os_conn.nova.servers.delete(srv)
        networks_amount_on_each_agt = []
        for agt in self.get_all_dhcp_agents():
            amount = len(self.os_conn.neutron.list_networks_on_dhcp_agent(
                         agt['id'])['networks'])
            networks_amount_on_each_agt.append(amount)
            logger.info('the dhcp agent {0} has {1} networks'.
                        format(agt['id'], amount))
        max_value = max(networks_amount_on_each_agt)
        networks_amount_on_each_agt.remove(max_value)
        for value in networks_amount_on_each_agt:
            assert(self.isclose(value, max_value, abs_tol=3))
