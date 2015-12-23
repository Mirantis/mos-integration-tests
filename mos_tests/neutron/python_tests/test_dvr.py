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

    def test_vm_connectivity_wo_floating(self, variables):
        """Check North-South connectivity (without floating IP)

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with external network and
                router type Distributed
            3. Add interfaces to the router01 with net01__subnet
            4. Boot vm_1 in the net01
            5. Go to the vm_1
            6. Ping 8.8.8.8
        """
        net, subnet = self.create_internal_network_with_subnet(1)
        router = self.os_conn.create_router(name='router01', distributed=True)
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

        self.check_ping_from_vm(server, vm_keypair=self.instance_keypair)
