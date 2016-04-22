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

import pytest

from mos_tests.functions import network_checks
from mos_tests.nfv.base import TestBaseNFV

logger = logging.getLogger(__name__)


@pytest.mark.check_env_('is_vlan')
class TestLiveMigration(TestBaseNFV):

    @pytest.mark.check_env_('has_2_or_more_computes', 'is_ceph_enabled')
    @pytest.mark.undestructive
    @pytest.mark.testrail_id('838327')
    def test_lm_ceph_for_huge_pages(
            self, env, os_conn, networks, volume, keypair, nfv_flavor,
            security_group, aggregate):
        """This test checks that live migration executed successfully for
            instances created on computes with ceph and huge pages
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Launch instance vm1 with volume vol1 on compute-1 in net1 with
            m1.small.hpgs
            3. Launch instance vm2 on compute-2 in net2 with m1.small.hpgs
            4. Make volume from vm2 volume_vm
            5. Launch instance vm3 on compute-2 in net2 with volume_vm
            with m1.small.hpgs
            6. Check vms connectivity
            7. Live migrate vm1 on compute-2 and check that vm moved to
            compute-2 with Active state
            8. Check vms connectivity
            9. Live migrate vm2 with block-migrate parameter on compute-1 and
            check that vm moved to compute-2 with Active state
            10. Check vms connectivity
            11. Live migrate vm3 on compute-1 and check that vm moved to
            compute-1 with Active state
            12. Check vms connectivity
        """
        hosts = aggregate.hosts

        vm_0 = os_conn.create_server(
            name='vm1', flavor=nfv_flavor[0].id, key_name=keypair.name,
            nics=[{'net-id': networks[0]}],
            availability_zone='nova:{}'.format(hosts[0]),
            security_groups=[security_group.id],
            block_device_mapping={'vda': volume.id})
        vm_1 = os_conn.create_server(
            name='vm2', flavor=nfv_flavor[0].id, key_name=keypair.name,
            availability_zone='nova:{}'.format(hosts[1]),
            security_groups=[security_group.id],
            nics=[{'net-id': networks[1]}])
        volume_vm = self.create_volume_from_vm(os_conn, vm_1)
        vm_2 = os_conn.create_server(
            name='vm3', flavor=nfv_flavor[0].id, key_name=keypair.name,
            nics=[{'net-id': networks[1]}],
            availability_zone='nova:{}'.format(hosts[1]),
            security_groups=[security_group.id],
            block_device_mapping={'vda': volume_vm})
        vms = [vm_0, vm_1, vm_2]

        self.check_pages(os_conn, hosts[0], total_pages=1024, free_pages=768)
        self.check_pages(os_conn, hosts[1], total_pages=1024, free_pages=512)
        for vm in vms:
            self.check_instance_page_size(os_conn, vm, size=2048)
        network_checks.check_vm_connectivity(env, os_conn)

        self.live_migrate(os_conn, vms[0], hosts[1], block_migration=False)
        self.check_pages(os_conn, hosts[0], total_pages=1024, free_pages=1024)
        self.check_pages(os_conn, hosts[1], total_pages=1024, free_pages=256)
        network_checks.check_vm_connectivity(env, os_conn)

        self.live_migrate(os_conn, vms[1], hosts[0])
        self.check_pages(os_conn, hosts[0], total_pages=1024, free_pages=768)
        self.check_pages(os_conn, hosts[1], total_pages=1024, free_pages=512)
        network_checks.check_vm_connectivity(env, os_conn)

        self.live_migrate(os_conn, vms[2], hosts[0], block_migration=False)
        self.check_pages(os_conn, hosts[0], total_pages=1024, free_pages=512)
        self.check_pages(os_conn, hosts[1], total_pages=1024, free_pages=768)
        for vm in vms:
            self.check_instance_page_size(os_conn, vm, size=2048)
        network_checks.check_vm_connectivity(env, os_conn)
