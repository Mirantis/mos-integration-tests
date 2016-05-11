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
from mos_tests.nfv.base import page_1gb
from mos_tests.nfv.base import page_2mb
from mos_tests.nfv.base import TestBaseNFV
from mos_tests.nfv.conftest import computes_configuration

logger = logging.getLogger(__name__)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_vlan')
class TestHugePages(TestBaseNFV):

    mixed_hp_computes = {'host_count': 2, 'count_2mb': 1024, 'count_1gb': 4}

    @pytest.mark.check_env_('has_3_or_more_computes')
    @pytest.mark.parametrize('computes_with_hp_2mb',
                             [{'host_count': 2, 'hp_count_per_host': 512}],
                             indirect=['computes_with_hp_2mb'])
    @pytest.mark.testrail_id('838318')
    def test_cold_migration_for_huge_pages_2m(
            self, env, os_conn, networks, small_nfv_flavor, security_group,
            computes_with_hp_2mb):
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
        count_to_allocate_2mb = small_nfv_flavor.ram * 1024 / page_2mb
        initial_conf = computes_configuration(env)
        hosts = computes_with_hp_2mb

        vms = []
        vm_hosts = []
        for i in range(2):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=small_nfv_flavor.id,
                security_groups=[security_group.id],
                nics=[{'net-id': networks[i]}])
            vms.append(vm)
        for vm in vms:
            host = getattr(vm, "OS-EXT-SRV-ATTR:host")
            assert host in hosts
            vm_hosts.append(host)

        vms_distribution = [(hosts[0], vm_hosts.count(hosts[0])),
                            (hosts[1], vm_hosts.count(hosts[1])), ]
        current_conf = computes_configuration(env)
        for (host, nr_2mb) in vms_distribution:
            exp_free_2m = initial_conf[host][page_2mb][
                              'total'] - nr_2mb * count_to_allocate_2mb
            assert exp_free_2m == current_conf[host][page_2mb]['free']

        for vm in vms:
            self.check_instance_page_size(os_conn, vm, size=page_2mb)
        network_checks.check_vm_connectivity(env, os_conn)

        vm_0_new = self.migrate(os_conn, vms[0])
        vm_host_0_new = getattr(vm_0_new, "OS-EXT-SRV-ATTR:host")

        assert vm_host_0_new in hosts
        assert vm_host_0_new != vm_hosts.pop(0)
        vm_hosts.append(vm_host_0_new)

        vms_distribution = [(hosts[0], vm_hosts.count(hosts[0])),
                            (hosts[1], vm_hosts.count(hosts[1])), ]
        final_conf = computes_configuration(env)
        for (host, nr_2mb) in vms_distribution:
            exp_free_2m = initial_conf[host][page_2mb][
                              'total'] - nr_2mb * count_to_allocate_2mb
            assert exp_free_2m == final_conf[host][page_2mb]['free']
        self.check_instance_page_size(os_conn, vm_0_new, size=page_2mb)
        network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.testrail_id('838297')
    @pytest.mark.parametrize('computes_with_hp_2mb',
                             [{'host_count': 2, 'hp_count_per_host': 1024}],
                             indirect=['computes_with_hp_2mb'])
    def test_allocation_huge_pages_2m_for_vms(self, env, os_conn, networks,
                                              computes_with_hp_2mb,
                                              small_nfv_flavor,
                                              security_group):
        """This test checks allocation 2M HugePages for instances
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Launch vm1 and vm2 using net1 on the first compute
            3. Launch vm3 using net1 on the second compute
            4. Launch vm4 using net2 on the second compute
            5. Check instances configuration (about huge pages)
            6. Check quantity of HP on computes
            7. Associate floating to vm1
            8. Check pings from all vms to all vms by all ips
        """
        count_to_allocate_2mb = small_nfv_flavor.ram * 1024 / page_2mb
        initial_conf = computes_configuration(env)
        hosts = computes_with_hp_2mb

        vms = []
        vms_params = [
            (hosts[0], networks[0]),
            (hosts[0], networks[0]),
            (hosts[0], networks[1]),
            (hosts[1], networks[1]),
        ]
        for i, (host, network) in enumerate(vms_params):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=small_nfv_flavor.id,
                nics=[{'net-id': network}],
                availability_zone='nova:{}'.format(host),
                security_groups=[security_group.id])
            vms.append(vm)

        for vm in vms:
            self.check_instance_page_size(os_conn, vm, size=page_2mb)

        vms_distribution = [(hosts[0], 3), (hosts[1], 1), ]
        final_conf = computes_configuration(env)
        for (host, nr_2mb) in vms_distribution:
            exp_free_2m = initial_conf[host][page_2mb][
                              'total'] - nr_2mb * count_to_allocate_2mb
            assert exp_free_2m == final_conf[host][page_2mb]['free']

        os_conn.assign_floating_ip(vms[0])
        network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.testrail_id('838313')
    def test_hp_distribution_1g_2m_for_vms(self, env, os_conn,
                                           computes_with_mixed_hp, networks,
                                           small_nfv_flavor, medium_nfv_flavor,
                                           security_group):
        """This test checks huge pages 1Gb and 2Mb distribution for vms
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Create vm1 in net1 on compute1 with 1Gb flavor
            3. Create vm2 in net2 on compute2 with 2Mb flavor
            4. Create vm3 in net2 on compute1 with 2Mb flavor
            5. Check instances configuration (about huge pages)
            6. Check quantity of HP on computes
            7. Check pings from all vms to all vms by all ips
        """
        count_to_allocate_2mb = small_nfv_flavor.ram * 1024 / page_2mb
        count_to_allocate_1gb = medium_nfv_flavor.ram * 1024 / page_1gb

        initial_conf = computes_configuration(env)

        hosts = computes_with_mixed_hp
        vms_params = [
            (hosts[0], networks[0], medium_nfv_flavor, page_1gb),
            (hosts[1], networks[1], small_nfv_flavor, page_2mb),
            (hosts[0], networks[1], small_nfv_flavor, page_2mb), ]

        vms = {}

        for i, (host, network, flavor, size) in enumerate(vms_params):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=flavor.id,
                nics=[{'net-id': network}],
                availability_zone='nova:{}'.format(host),
                security_groups=[security_group.id])
            vms.update({vm: size})

        for vm, exp_size in vms.items():
            self.check_instance_page_size(os_conn, vm, size=exp_size)

        vms_distribution = [(hosts[0], 1, 1), (hosts[1], 0, 1), ]
        final_conf = computes_configuration(env)
        for (host, nr_1gb, nr_2mb) in vms_distribution:
            exp_free_1g = initial_conf[host][page_1gb][
                              'total'] - nr_1gb * count_to_allocate_1gb
            exp_free_2m = initial_conf[host][page_2mb][
                              'total'] - nr_2mb * count_to_allocate_2mb
            assert exp_free_1g == final_conf[host][page_1gb]['free']
            assert exp_free_2m == final_conf[host][page_2mb]['free']

        network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.testrail_id('838316')
    def test_resizing_of_vms_with_huge_pages(self, env, os_conn,
                                             computes_with_mixed_hp,
                                             networks, small_nfv_flavor,
                                             medium_nfv_flavor, flavor,
                                             security_group):
        """This test checks resizing of VM with flavor for 2M to flavor
            for 1G flavor and on old flavor
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Create vm1 in net1 on compute1 with 2Mb flavor
            3. Create vm2 in net2 on compute2 with old flavor
            4. Check instances configuration (about huge pages)
            5. Check pings from all vms to all vms by all ips
            6. Resize vm1 to 1Gb and check ping
            7. Resize vm1 to old and check ping
            8. Resize vm1 to 1Gb and check ping
            9. Resize vm1 to 2Mb and check ping
        """
        hosts = computes_with_mixed_hp
        vms_params = [
            (hosts[0], networks[0], small_nfv_flavor, page_2mb),
            (hosts[1], networks[1], flavor, None), ]
        vms = {}
        for i, (host, network, flavor, size) in enumerate(vms_params):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=flavor.id,
                nics=[{'net-id': network}],
                availability_zone='nova:{}'.format(host),
                security_groups=[security_group.id])
            vms.update({vm: size})

        for vm, exp_size in vms.items():
            self.check_instance_page_size(os_conn, vm, size=exp_size)

        params = [(medium_nfv_flavor, page_1gb),
                  (flavor, None),
                  (medium_nfv_flavor, page_1gb),
                  (small_nfv_flavor, page_2mb), ]

        for (flavor, size) in params:
            self.resize(os_conn, vms.keys()[0], flavor_to_resize=flavor)
            self.check_instance_page_size(os_conn, vms.keys()[0], size=size)
            network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.check_env_('has_3_or_more_computes')
    @pytest.mark.parametrize('computes_with_hp_1gb',
                             [{'host_count': 2, 'hp_count_per_host': 4}],
                             indirect=['computes_with_hp_1gb'])
    @pytest.mark.testrail_id('838315')
    def test_cold_migration_for_huge_pages_1g(
            self, env, os_conn, networks, medium_nfv_flavor, security_group,
            computes_with_hp_1gb):
        """This test checks that cold migration executed successfully for
            instances created on computes with huge pages 1G
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
        count_to_allocate_1gb = medium_nfv_flavor.ram * 1024 / page_1gb
        initial_conf = computes_configuration(env)

        hosts = computes_with_hp_1gb
        vms = []
        vm_hosts = []
        for i in range(2):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=medium_nfv_flavor.id,
                security_groups=[security_group.id],
                nics=[{'net-id': networks[i]}])
            vms.append(vm)
        for vm in vms:
            host = getattr(vm, "OS-EXT-SRV-ATTR:host")
            assert host in hosts
            vm_hosts.append(host)

        vms_distribution = [(hosts[0], vm_hosts.count(hosts[0])),
                            (hosts[1], vm_hosts.count(hosts[1])), ]
        current_conf = computes_configuration(env)
        for (host, nr_1gb) in vms_distribution:
            exp_free_1g = initial_conf[host][page_1gb][
                              'total'] - nr_1gb * count_to_allocate_1gb
            assert exp_free_1g == current_conf[host][page_1gb]['free']

        for vm in vms:
            self.check_instance_page_size(os_conn, vm, size=page_1gb)
        network_checks.check_vm_connectivity(env, os_conn)

        vm_0_new = self.migrate(os_conn, vms[0])
        vm_host_0_new = getattr(vm_0_new, "OS-EXT-SRV-ATTR:host")

        assert vm_host_0_new in hosts
        assert vm_host_0_new != vm_hosts.pop(0)
        vm_hosts.append(vm_host_0_new)

        vms_distribution = [(hosts[0], vm_hosts.count(hosts[0])),
                            (hosts[1], vm_hosts.count(hosts[1])), ]
        final_conf = computes_configuration(env)
        for (host, nr_1gb) in vms_distribution:
            exp_free_1g = initial_conf[host][page_1gb][
                              'total'] - nr_1gb * count_to_allocate_1gb
            assert exp_free_1g == final_conf[host][page_1gb]['free']
        self.check_instance_page_size(os_conn, vm_0_new, size=page_1gb)
        network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.parametrize('computes_without_hp', [1],
                             indirect=['computes_without_hp'])
    @pytest.mark.parametrize('flavor', [{"name": "old.flavor", "ram": 512,
                                         "vcpu": 1, "disk": 1}],
                             indirect=['flavor'])
    @pytest.mark.testrail_id('838311')
    def test_allocation_huge_pages_2m_for_vms_with_old_flavor(
            self, env, os_conn, networks, computes_with_hp_2mb,
            computes_without_hp, small_nfv_flavor, flavor, security_group):
        """This test checks that Huge pages set for vm1, vm2 and vm3 shouldn't
            use Huge pages, connectivity works properly
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Create vm1 in net1 on compute1 with 2Mb flavor
            3. Create vm2 in net2 on compute2 with old flavor
            4. Create vm3 in net1 on compute1 with old flavor
            5. Check huge pages. Check that it was allocated only HP for vm1
            6. Check pings from all vms to all vms by all ips
        """
        count_to_allocate_2mb = small_nfv_flavor.ram * 1024 / page_2mb
        initial_conf = computes_configuration(env)
        hosts_hp = computes_with_hp_2mb
        hosts_no_hp = computes_without_hp

        vms_params = [
            (hosts_hp[0], networks[0], small_nfv_flavor, page_2mb),
            (hosts_no_hp[0], networks[1], flavor, None),
            (hosts_hp[0], networks[0], flavor, None)]
        vms = {}

        for i, (host, network, flavor, size) in enumerate(vms_params):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=flavor.id,
                nics=[{'net-id': network}],
                availability_zone='nova:{}'.format(host),
                security_groups=[security_group.id])
            vms.update({vm: size})

        for vm, exp_size in vms.items():
            self.check_instance_page_size(os_conn, vm, size=exp_size)

        vms_distribution = [(hosts_hp[0], 1), (hosts_no_hp[0], 0), ]
        final_conf = computes_configuration(env)
        for (host, nr_2mb) in vms_distribution:
            exp_free_2m = initial_conf[host][page_2mb][
                              'total'] - nr_2mb * count_to_allocate_2mb
            assert exp_free_2m == final_conf[host][page_2mb]['free']

        network_checks.check_vm_connectivity(env, os_conn)
