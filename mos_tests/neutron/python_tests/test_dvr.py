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
import time

import pytest

from mos_tests.neutron.python_tests import base


logger = logging.getLogger(__name__)


@pytest.mark.check_env_('has_1_or_more_computes', 'is_dvr')
@pytest.mark.usefixtures("setup")
class TestDVR(base.TestBase):
    """DVR specific test cases"""

    @pytest.fixture
    def variables(self, init):
        """Init Openstack variables"""
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')

    @pytest.mark.parametrize('floating_ip', (True, False),
                             ids=('with floating', 'without floating'))
    @pytest.mark.parametrize('dvr_router', (True, False),
                             ids=('distributed router', 'centralized_router'))
    def test_north_south_connectivity(self, variables, floating_ip,
                                         dvr_router):
        """Check North-South connectivity

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with external network and
                router type `dvr_router`
            3. Add interfaces to the router01 with net01__subnet
            4. Boot vm_1 in the net01
            5. Add floationg ip if case of `floating_ip` arg is True
            6. Go to the vm_1
            7. Ping 8.8.8.8
        """
        net, subnet = self.create_internal_network_with_subnet(1)
        router = self.os_conn.create_router(name='router01',
                                            distributed=dvr_router)
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])

        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])

        server = self.os_conn.create_server(
            name='server01',
            availability_zone=self.zone.zoneName,
            key_name=self.instance_keypair.name,
            nics=[{'net-id': net['network']['id']}],
            security_groups=[self.security_group.id])

        if floating_ip:
            self.os_conn.assign_floating_ip(server)

        self.check_ping_from_vm(server, vm_keypair=self.instance_keypair)

    @pytest.mark.check_env_('has_2_or_more_computes')
    def test_west_east_routing_after_ban_and_clear_l3_agent(self, variables):
        """Check West-East-Routing connectivity with floatingIP after ban
            and clear l3-agent on compute

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed and
                with gateway to external network
            4. Add interfaces to the router01_02 with net01_subnet
                and net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on different compute
            7. Ban l3-agent on the compute with vm_1: service l3-agent stop
            8. Wait 15 seconds
            9. Clear this l3-agent: service l3-agent stop
            10. Go to vm_1
            11. Ping vm_2 with internal IP
        """
        # Create router
        router = self.os_conn.create_router(name="router01", distributed=True)
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])
        # Create network and instance
        compute_nodes = self.zone.hosts.keys()[:2]
        for i, compute_node in enumerate(compute_nodes, 1):
            net, subnet = self.create_internal_network_with_subnet(suffix=i)
            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(self.zone.zoneName,
                                                 compute_node),
                key_name=self.instance_keypair.name,
                nics=[{'net-id': net['network']['id']}],
                security_groups=[self.security_group.id])

        # Ban l3 agent
        compute1 = self.env.find_node_by_fqdn(compute_nodes[0])
        with compute1.ssh() as remote:
            remote.check_call('service neutron-l3-agent stop')

        time.sleep(15)

        # Clear l3 agent
        with compute1.ssh() as remote:
            remote.check_call('service neutron-l3-agent start')

        server1 = self.os_conn.nova.servers.find(name="server01")
        server2 = self.os_conn.nova.servers.find(name="server02")
        server2_ip = self.os_conn.get_nova_instance_ips(server2).values()[0]
        self.check_ping_from_vm(vm=server1, vm_keypair=self.instance_keypair,
                                ip_to_ping=server2_ip)
