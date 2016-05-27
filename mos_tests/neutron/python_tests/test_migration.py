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

from mos_tests.functions import common as common_functions
from mos_tests.neutron.python_tests.base import TestBase

logger = logging.getLogger(__name__)


class TestLiveMigration(TestBase):

    @pytest.fixture(autouse=True)
    def prepare_openstack(self):

        self.instances = []
        self.floating_ips = []
        self.keys = []
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.compute_hosts = self.zone.hosts.keys()
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')

    @pytest.mark.testrail_id('')
    @pytest.mark.check_env_('has_2_or_more_computes', 'not is_ceph_enabled')
    def test_check_rarp_during_live_migration(self):
        """Test checks RARP packets isn't dropped during live migration of VM

        Steps:
            1. Create net01, net01__subnet, attach it to router.
            2. Create vm1 and vm2 in net01 on different computes
            3. Send pings from vm1 to vm2
            4. Send pings from vm2 to 8.8.8.8
            5. Run tcpdump on compute where vm2 will be live-migrated to:
            tcpdump -i br-mesh > rarp.log
            6. Initiate live migration for vm2
            7. Check that vm2 is hosted on a new compute now and grep rarp.log
             for Reverse ARP packets: cat rarp.log | grep 'ARP, Reverse'
        """
        def start_tcpdump_in_background(node):
            """Start tcpdump on specified node.

            :param node: node on which start tcpdump
            """
            logger.info('Start tcpdump on {0}'.format(node.data['fqdn']))
            cmd_for_tcpdump = ('tcpdump -i br-aux')
            with node.ssh() as remote:
                remote.background_call(cmd_for_tcpdump)

        def get_rarp_packages(node):
            """Get rarp packages from tcpdump log on provided node

            :param node: node on which we need to analyze log
            :return: last time from log or None, if log is empty
            """
            with node.ssh() as remote:
                return remote.execute(
                    "cat /tmp/rarp.log | grep 'ARP, Reverse'")

        networks = self.os_conn.neutron.list_networks()['networks']
        net = [net['id'] for net in networks if not net['router:external']][0]
        image_id = self.os_conn.nova.images.find(name='TestVM').id

        vm1 = self.os_conn.create_server(
            name='server01',
            image_id=image_id,
            availability_zone='nova:{}'.format(self.compute_hosts[0]),
            nics=[{'net-id': net}],
            security_groups=[self.security_group.id],
            key_name=self.instance_keypair.name)

        vm2 = self.os_conn.create_server(
            name='server02',
            image_id=image_id,
            availability_zone='nova:{}'.format(self.compute_hosts[1]),
            nics=[{'net-id': net}],
            security_groups=[self.security_group.id],
            key_name=self.instance_keypair.name)

        self.instances.append(vm1.id)
        self.instances.append(vm2.id)
        floating_ip_vm1 = self.os_conn.nova.floating_ips.create()
        self.floating_ips.append(floating_ip_vm1)
        vm1.add_floating_ip(floating_ip_vm1.ip)
        ping = common_functions.ping_command(floating_ip_vm1.ip)
        assert ping, "VM1 is not reachable"

        floating_ip_vm2 = self.os_conn.nova.floating_ips.create()
        self.floating_ips.append(floating_ip_vm2)
        vm2.add_floating_ip(floating_ip_vm2.ip)
        ping = common_functions.ping_command(floating_ip_vm2.ip)
        assert ping, "VM2 is not reachable"

        self.check_ping_from_vm(vm=vm1, vm_keypair=self.instance_keypair,
                                ip_to_ping=floating_ip_vm2.ip)

        self.check_ping_from_vm(vm=vm2, vm_keypair=self.instance_keypair,
                                ip_to_ping='8.8.8.8')

        # Start tcpdump on compute node
        vm1_host = getattr(vm1, 'OS-EXT-SRV-ATTR:host')
        vm1_hypervisor = getattr(vm1, "OS-EXT-SRV-ATTR:hypervisor_hostname")
        vm1_compute = self.env.find_node_by_fqdn(vm1_host)
        start_tcpdump_in_background(vm1_compute)

        self.os_conn.live_migration(vm2, floating_ip_vm2.ip,
                                    new_hyper=vm1_hypervisor)

        # Kill tcpdump on compute node
        logger.info('Killing tcpdump on {0}'.format(vm1_host))
        with vm1_compute.ssh() as remote:
            remote.execute('cat /tmp/tcpdumpchild | xargs kill')
        err_msg = "No RARP packets in log"
        assert get_rarp_packages(vm1_compute)['exit_code'] == 0, err_msg
