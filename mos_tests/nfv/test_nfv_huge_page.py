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
class TestHugePages(TestBaseNFV):

    @pytest.mark.check_env_('has_3_or_more_computes')
    @pytest.mark.undestructive
    @pytest.mark.testrail_id('838318')
    def test_cold_migration_for_huge_pages_2m(
            self, env, os_conn, networks, nfv_flavor, security_group,
            aggregate):
        """This test checks that cold migration executed successfully for
            instances created on computes with huge pages 2M
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Launch instance vm1 in net1 with m1.small.hpgs
            3. Check that vm1 is created on compute with huge pages
            4. Launch instance vm2 in net2 with m1.small.hpgs
            5. Check that vm2 is created on compute with huge pages
            6. Check vms connectivity
            7. Cold migrate vm1 and check that vm moved to other compute with
            huge pages
            8. Check vms connectivity
        """
        free_pages = {0: 1024, 1: 768, 2: 512}
        hosts = aggregate.hosts
        vms = []
        vm_hosts = []
        for i in range(2):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=nfv_flavor[0].id,
                security_groups=[security_group.id],
                nics=[{'net-id': networks[i]}])
            vms.append(vm)
        for vm in vms:
            host = getattr(vm, "OS-EXT-SRV-ATTR:host")
            assert host in hosts
            vm_hosts.append(host)
        for host in hosts:
            self.check_pages(os_conn, host, total_pages=1024,
                             free_pages=free_pages[vm_hosts.count(host)])
        for vm in vms:
            self.check_instance_page_size(os_conn, vm, size=2048)
        network_checks.check_vm_connectivity(env, os_conn)

        vm_0_new = self.migrate(os_conn, vms[0])
        vm_host_0_new = getattr(vm_0_new, "OS-EXT-SRV-ATTR:host")
        assert vm_host_0_new in hosts
        assert vm_host_0_new != vm_hosts.pop(0)
        vm_hosts.append(vm_host_0_new)
        for host in hosts:
            self.check_pages(os_conn, host, total_pages=1024,
                             free_pages=free_pages[vm_hosts.count(host)])
        self.check_instance_page_size(os_conn, vm_0_new, size=2048)
        network_checks.check_vm_connectivity(env, os_conn)
