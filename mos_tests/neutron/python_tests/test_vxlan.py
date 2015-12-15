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
import subprocess
import threading
import logging

from mos_tests.neutron.python_tests.base import TestBase

logger = logging.getLogger(__name__)


@pytest.mark.usefixtures("check_ha_env", "check_vxlan", "setup")
class TestVxlan(TestBase):
    """ Vxlan (tun) specific tests"""

    def test_tunnel_established(self, tshark):
        """Check that VxLAN is established on nodes and VNI matching
           the segmentation_id of a network

        Scenario:
            1. Create private network net01, subnet 10.1.1.0/24
            2. Create router01, add interface for net01 and set gateway to
                external network
            3. Boot instance vm1_1 in net01
            4. Look on what node l3 agent for this router01 is
            5. Check that tunnel is established on controller
            6. Check that tunnel is established on compute
            7. On node with l3 agent find namespace qrouter
            8. Add rules for ping and ssh connection
            9. Go to the compute with vm_1 and run
                tcpdump -vvni any port 4789 -w vxlan.log
            10. Ping from qrouter namespace vm1
            11. Copy vxlan.log for your computer and open it with Wireshark.
                Press right button, choose Decode as, Transport
                and choose VXLAN
        """
        # Init variables
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        compute_node = self.zone.hosts.keys()[0]
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')

        # Create router
        router = self.os_conn.create_router(name="router01")
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])

        # Create network and instance
        network = self.os_conn.create_network(name='net01')
        subnet = self.os_conn.create_subnet(
            network_id=network['network']['id'],
            name='net01__subnet',
            cidr="10.1.1.0/24")
        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])
        server = self.os_conn.create_server(
            name='server01',
            availability_zone='{}:{}'.format(self.zone.zoneName, compute_node),
            key_name=self.instance_keypair.name,
            nics=[{'net-id': network['network']['id']}],
            security_groups=[self.security_group.id])

        router_node = self.os_conn.get_l3_agent_hosts(
            router['router']['id'])[0]
        controller = self.env.find_node_by_fqdn(router_node)
        compute = self.env.find_node_by_fqdn(compute_node)

        # Check controller and compute
        for node in (controller, compute):
            with self.env.get_ssh_to_node(node.data['ip']) as remote:
                result = remote.execute('ovs-vsctl show | grep -q br-tun')
                assert result['exit_code'] == 0

        def tcpdump():
            ip = compute.data['ip']
            logger.info('Start tcpdump')
            with self.env.get_ssh_to_node(ip) as remote:
                result = remote.execute(
                    'tcpdump -U -vvni any port 4789 -w /tmp/vxlan.log')
                assert result['exit_code'] == 0

        # Start tcpdump
        thread = threading.Thread(target=tcpdump)

        try:
            thread.start()
            # Ping server01
            with self.env.get_ssh_to_node(controller.data['ip']) as remote:
                vm_ip = self.os_conn.get_nova_instance_ips(server)['fixed']
                result = remote.execute(
                    'ip netns exec qrouter-{router_id} ping -c1 {ip}'.format(
                        router_id=router['router']['id'],
                        ip=vm_ip))
        finally:
            ip = compute.data['ip']
            with self.env.get_ssh_to_node(ip) as remote:
                remote.execute('killall tcpdump')
            thread.join(0)

        # Download log
        with self.env.get_ssh_to_node(compute.data['ip']) as remote:
            remote.download('/tmp/vxlan.log', '/tmp/vxlan.log')

        # Check log
        vni = network['network']['provider:segmentation_id']
        output = subprocess.check_output([tshark, '-d', 'udp.port==4789,vxlan',
                                          '-r', '/tmp/vxlan.log', '-Y',
                                          'vxlan.vni!={0}'.format(vni)])
        assert not output.strip(), 'Log contains records with another VNI'
