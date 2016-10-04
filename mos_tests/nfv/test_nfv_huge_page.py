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

from mos_tests.environment.os_actions import InstanceError
from mos_tests.functions.common import wait
from mos_tests.functions import network_checks
from mos_tests.nfv.base import page_1gb
from mos_tests.nfv.base import page_2mb
from mos_tests.nfv.base import TestBaseNFV
from mos_tests.nfv.conftest import computes_configuration
from mos_tests.nfv.conftest import get_hp_distribution_per_numa_node

logger = logging.getLogger(__name__)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_vlan')
class TestHugePages(TestBaseNFV):

    mixed_hp_computes = {'host_count': 2, 'count_2mb': 1024, 'count_1gb': 4}
    flavors_to_create = [
        {'name': 'm1.small.hpgs',
         'params': {'ram': 512, 'vcpu': 1, 'disk': 20},
         'keys': {'hw:mem_page_size': page_2mb}},

        {'name': 'm1.medium.hpgs',
         'params': {'ram': 2048, 'vcpu': 2, 'disk': 20},
         'keys': {'hw:mem_page_size': page_1gb}},

        {'name': 'old.flavor',
         'params': {'ram': 2048, 'vcpu': 1, 'disk': 20}}]

    @pytest.mark.check_env_('has_3_or_more_computes')
    @pytest.mark.parametrize('computes_with_hp_2mb',
                             [{'host_count': 2, 'hp_count_per_host': 512}],
                             indirect=['computes_with_hp_2mb'])
    @pytest.mark.testrail_id('838318')
    def test_cold_migration_for_huge_pages_2m(
            self, env, os_conn, networks, flavors, security_group,
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
        small_nfv_flavor = flavors[0]
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
            exp_free_2m = (initial_conf[host][page_2mb]['total'] -
                           nr_2mb * count_to_allocate_2mb)
            assert exp_free_2m == current_conf[host][page_2mb]['free']

        for vm in vms:
            assert self.get_instance_page_size(os_conn, vm) == page_2mb

        os_conn.wait_servers_ssh_ready(vms)
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
            exp_free_2m = (initial_conf[host][page_2mb]['total'] -
                           nr_2mb * count_to_allocate_2mb)
            assert exp_free_2m == final_conf[host][page_2mb]['free']

        assert self.get_instance_page_size(os_conn, vm_0_new) == page_2mb
        os_conn.wait_servers_ssh_ready(vms)
        network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.testrail_id('838297')
    @pytest.mark.parametrize('computes_with_hp_2mb',
                             [{'host_count': 2, 'hp_count_per_host': 1024}],
                             indirect=['computes_with_hp_2mb'])
    def test_allocation_huge_pages_2m_for_vms(self, env, os_conn, networks,
                                              computes_with_hp_2mb,
                                              flavors, security_group):
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
        small_nfv_flavor = flavors[0]
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
            assert self.get_instance_page_size(os_conn, vm) == page_2mb

        vms_distribution = [(hosts[0], 3), (hosts[1], 1), ]
        final_conf = computes_configuration(env)
        for (host, nr_2mb) in vms_distribution:
            exp_free_2m = (initial_conf[host][page_2mb]['total'] -
                           nr_2mb * count_to_allocate_2mb)
            assert exp_free_2m == final_conf[host][page_2mb]['free']

        os_conn.assign_floating_ip(vms[0])
        os_conn.wait_servers_ssh_ready(vms)
        network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.testrail_id('838313')
    def test_hp_distribution_1g_2m_for_vms(self, env, os_conn,
                                           computes_with_mixed_hp, networks,
                                           flavors, security_group):
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
        small_nfv_flavor, medium_nfv_flavor = flavors[0], flavors[1]
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
            assert self.get_instance_page_size(os_conn, vm) == exp_size

        vms_distribution = [(hosts[0], 1, 1), (hosts[1], 0, 1), ]
        final_conf = computes_configuration(env)
        for (host, nr_1gb, nr_2mb) in vms_distribution:
            exp_free_1g = (initial_conf[host][page_1gb]['total'] -
                           nr_1gb * count_to_allocate_1gb)
            exp_free_2m = (initial_conf[host][page_2mb]['total'] -
                           nr_2mb * count_to_allocate_2mb)
            assert exp_free_1g == final_conf[host][page_1gb]['free']
            assert exp_free_2m == final_conf[host][page_2mb]['free']

        os_conn.wait_servers_ssh_ready(vms.keys())
        network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.testrail_id('838316')
    def test_resizing_of_vms_with_huge_pages(self, env, os_conn,
                                             computes_with_mixed_hp,
                                             networks, flavors,
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
        small_nfv_flv, meduim_nfv_flv, old_flv = flavors
        hosts = computes_with_mixed_hp
        vms_params = [
            (hosts[0], networks[0], small_nfv_flv, page_2mb),
            (hosts[1], networks[1], old_flv, None), ]
        vms = {}
        for i, (host, network, flavor, size) in enumerate(vms_params):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=flavor.id,
                nics=[{'net-id': network}],
                availability_zone='nova:{}'.format(host),
                security_groups=[security_group.id])
            vms.update({vm: size})

        for vm, exp_size in vms.items():
            assert self.get_instance_page_size(os_conn, vm) == exp_size

        params = [(meduim_nfv_flv, page_1gb),
                  (old_flv, None),
                  (meduim_nfv_flv, page_1gb),
                  (small_nfv_flv, page_2mb), ]

        for (flavor, size) in params:
            self.resize(os_conn, vms.keys()[0], flavor_to_resize=flavor)
            assert self.get_instance_page_size(os_conn, vms.keys()[0]) == size
            os_conn.wait_servers_ssh_ready(vms.keys())
            network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.check_env_('has_3_or_more_computes')
    @pytest.mark.parametrize('computes_with_hp_1gb',
                             [{'host_count': 2, 'hp_count_per_host': 4}],
                             indirect=['computes_with_hp_1gb'])
    @pytest.mark.testrail_id('838315')
    def test_cold_migration_for_huge_pages_1g(
            self, env, os_conn, networks, flavors, security_group,
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
        medium_nfv_flavor = flavors[1]
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
            exp_free_1g = (initial_conf[host][page_1gb]['total'] -
                           nr_1gb * count_to_allocate_1gb)
            assert exp_free_1g == current_conf[host][page_1gb]['free']

        for vm in vms:
            assert self.get_instance_page_size(os_conn, vm) == page_1gb
        os_conn.wait_servers_ssh_ready(vms)
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
            exp_free_1g = (initial_conf[host][page_1gb]['total'] -
                           nr_1gb * count_to_allocate_1gb)
            assert exp_free_1g == final_conf[host][page_1gb]['free']
        assert self.get_instance_page_size(os_conn, vm) == page_1gb
        os_conn.wait_servers_ssh_ready(vms)
        network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.parametrize('computes_without_hp', [1],
                             indirect=['computes_without_hp'])
    @pytest.mark.testrail_id('838311')
    def test_allocation_huge_pages_2m_for_vms_with_old_flavor(
            self, env, os_conn, networks, computes_with_hp_2mb, flavors,
            computes_without_hp, security_group):
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
        small_nfv_flavor, old_flavor = flavors[0], flavors[2]
        count_to_allocate_2mb = small_nfv_flavor.ram * 1024 / page_2mb
        initial_conf = computes_configuration(env)
        hosts_hp = computes_with_hp_2mb
        hosts_no_hp = computes_without_hp

        vms_params = [
            (hosts_hp[0], networks[0], small_nfv_flavor, page_2mb),
            (hosts_no_hp[0], networks[1], old_flavor, None),
            (hosts_hp[0], networks[0], old_flavor, None)]
        vms = {}

        for i, (host, network, flavor, size) in enumerate(vms_params):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=flavor.id,
                nics=[{'net-id': network}],
                availability_zone='nova:{}'.format(host),
                security_groups=[security_group.id])
            vms.update({vm: size})

        for vm, exp_size in vms.items():
            assert self.get_instance_page_size(os_conn, vm) == exp_size

        vms_distribution = [(hosts_hp[0], 1), (hosts_no_hp[0], 0), ]
        final_conf = computes_configuration(env)
        for (host, nr_2mb) in vms_distribution:
            exp_free_2m = (initial_conf[host][page_2mb]['total'] -
                           nr_2mb * count_to_allocate_2mb)
            assert exp_free_2m == final_conf[host][page_2mb]['free']

        os_conn.wait_servers_ssh_ready(vms.keys())
        network_checks.check_vm_connectivity(env, os_conn)

    @pytest.mark.check_env_('is_ceph_enabled')
    @pytest.mark.parametrize('computes_with_hp_2mb',
                             [{'host_count': 2, 'hp_count_per_host': 512}],
                             indirect=['computes_with_hp_2mb'])
    @pytest.mark.testrail_id('838317')
    def test_evacuation_for_huge_pages_2m(
            self, env, os_conn, devops_env, networks, flavors,
            security_group, computes_with_hp_2mb):
        """This test checks that evacuation executed successfully for
            instances created on computes with huge pages 2M
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
               interfaces to both nets
            2. Launch instance vm1 in net1 with m1.small.hpgs on compute-1
            3. Launch instance vm2 in net2 with m1.small.hpgs on compute-2
            4. Check vms connectivity
            5. Kill the compute-1
            6. Evacuate vm1 from compute-1
            7. Check vms connectivity
            8. Make compute-1 alive
            9. Check that resources for vm1 were deleted from compute-1
        """
        small_nfv_flavor = flavors[0]
        count_to_allocate_2mb = small_nfv_flavor.ram * 1024 / page_2mb
        initial_conf = computes_configuration(env)
        hosts = computes_with_hp_2mb
        vms = []

        vm0_to_evacuate = os_conn.create_server(
            name='vm0_to_evacuate', flavor=small_nfv_flavor.id,
            availability_zone='nova:{}'.format(hosts[0]),
            security_groups=[security_group.id],
            nics=[{'net-id': networks[0]}])
        vms.append(vm0_to_evacuate)

        vm1 = os_conn.create_server(
            name='vm1', flavor=small_nfv_flavor.id,
            availability_zone='nova:{}'.format(hosts[1]),
            security_groups=[security_group.id],
            nics=[{'net-id': networks[1]}])
        vms.append(vm1)

        vms_distribution = [(hosts[0], 1), (hosts[1], 1)]
        current_conf = computes_configuration(env)
        for (host, nr_2mb) in vms_distribution:
            exp_free_2m = (initial_conf[host][page_2mb]['total'] -
                           nr_2mb * count_to_allocate_2mb)
            act_free_2m = current_conf[host][page_2mb]['free']
            assert exp_free_2m == act_free_2m, (
                "Unexpected count of free 2Mb huge pages: {0} instead of {1} "
                "for host {2}".format(act_free_2m, exp_free_2m, host))

        for vm in vms:
            assert self.get_instance_page_size(os_conn, vm) == page_2mb

        os_conn.wait_servers_ssh_ready(vms)
        network_checks.check_vm_connectivity(env, os_conn)

        with self.change_compute_state_to_down(os_conn, devops_env, hosts[0]):
            self.evacuate(os_conn, devops_env, vm0_to_evacuate, host=hosts[1])

            os_conn.wait_servers_ssh_ready(vms)
            network_checks.check_vm_connectivity(env, os_conn)
            for vm in vms:
                assert self.get_instance_page_size(os_conn, vm) == page_2mb

        vms_distribution = [(hosts[0], 0), (hosts[1], 2)]
        current_conf = computes_configuration(env)
        for (host, nr_2mb) in vms_distribution:
            exp_free_2m = (initial_conf[host][page_2mb]['total'] -
                           nr_2mb * count_to_allocate_2mb)
            act_free_2m = current_conf[host][page_2mb]['free']
            assert exp_free_2m == act_free_2m, (
                "Unexpected count of free 2Mb huge pages: {0} instead of {1} "
                "for host {2}".format(act_free_2m, exp_free_2m, host))


@pytest.mark.undestructive
@pytest.mark.check_env_('is_vlan')
class TestHugePagesScheduler(TestBaseNFV):

    created_flvs = []
    mixed_hp_computes = {'host_count': 1, 'count_2mb': 2048, 'count_1gb': 4}

    flavors_to_create = [
        {'name': 'm1.hpgs', 'params': {'ram': 2048, 'vcpu': 2, 'disk': 1}}]

    @pytest.yield_fixture
    def cleanup(self, os_conn):
        flavors = os_conn.nova.flavors.list()
        self.created_flvs = []
        yield
        os_conn.delete_servers()
        wait(lambda: len(os_conn.nova.servers.list()) == 0,
             timeout_seconds=5 * 60, waiting_for='instances cleanup')
        map(lambda flv: os_conn.nova.flavors.delete(flv.id), self.created_flvs)
        wait(lambda: len(os_conn.nova.flavors.list()) == len(flavors),
             timeout_seconds=5 * 60, waiting_for='flavors cleanup')

    def boot_vms_to_allocate_hp(self, os_conn, env, host, page_size, net,
                                ram_left_free=0):
        """Boot vms to allocate required count of huge pages

        :param os_conn: os_conn
        :param env: env
        :param host: fqdn hostname
        :param page_size: size of huge pages. Usually it's 1048576 or 2048
        :param net: network to vm
        :param ram_left_free: ram in MBs required to be free
        :return:
        """
        hps = get_hp_distribution_per_numa_node(env)[host]
        flv_sizes = [(numa, hps[numa][page_size]['free'] * page_size / 1024)
                     for numa, hp in hps.items() if hp[page_size]['free'] != 0]
        flv_sizes.sort(key=lambda i: i[1], reverse=True)

        for numa, size in flv_sizes:
            flv = os_conn.nova.flavors.create(
                name='flv_{0}_{1}'.format(numa, page_size),
                ram=size - ram_left_free, vcpus=1, disk=1)
            self.created_flvs.append(flv)
            flv.set_keys({'hw:mem_page_size': page_size})
            os_conn.create_server(name='vm_{0}'.format(numa), flavor=flv.id,
                                  nics=[{'net-id': net}],
                                  availability_zone='nova:{}'.format(host),
                                  wait_for_avaliable=False)

    @pytest.mark.testrail_id('1455758', mem_page_size='large',
                             vm_page_size=page_1gb, size_to_allocate=page_2mb)
    @pytest.mark.testrail_id('1455759', mem_page_size='any',
                             vm_page_size=page_1gb, size_to_allocate=page_2mb)
    @pytest.mark.testrail_id('1455756', mem_page_size='large',
                             vm_page_size=page_2mb, size_to_allocate=page_1gb)
    @pytest.mark.testrail_id('1455757', mem_page_size='any',
                             vm_page_size=page_2mb, size_to_allocate=page_1gb)
    @pytest.mark.parametrize('mem_page_size', ['large', 'any'])
    @pytest.mark.parametrize('vm_page_size, size_to_allocate',
                             [(page_1gb, page_2mb), (page_2mb, page_1gb)],
                             ids=['1Gb hps only', '2Mb hps only'])
    def test_vms_page_size_one_type_hps_available_only(
            self, env, os_conn, networks, computes_with_mixed_hp, flavors,
            security_group, keypair, mem_page_size, vm_page_size,
            size_to_allocate, cleanup):
        """This test checks that vms with any/large hw:mem_page_size uses 2Mb
        huge pages in case when only 2Mb pages are available

            Steps:
            1. Create net1 with subnet and router1 with interface to net1
            2. Allocate all 1Gb huge pages for each numa node
            3. Boot vm with any or large hw:mem_page_size
            4. Check that 2Mb huge pages are used for vm
        """
        host = computes_with_mixed_hp[0]
        self.boot_vms_to_allocate_hp(os_conn, env, host, size_to_allocate,
                                     networks[0])

        flavors[0].set_keys({'hw:mem_page_size': mem_page_size})
        vm = os_conn.create_server(name='vm', flavor=flavors[0].id,
                                   nics=[{'net-id': networks[0]}],
                                   key_name=keypair.name,
                                   security_groups=[security_group.id],
                                   availability_zone='nova:{}'.format(host))
        assert self.get_instance_page_size(os_conn, vm) == vm_page_size
        network_checks.check_ping_from_vm(env, os_conn, vm, vm_keypair=keypair)

    @pytest.mark.testrail_id('1455760', page_size='large',
                             allowed_sizes=[page_1gb])
    @pytest.mark.testrail_id('1455761', page_size='any',
                             allowed_sizes=[page_2mb, page_1gb])
    @pytest.mark.parametrize('page_size, allowed_sizes',
                             [('large', [page_1gb]),
                              ('any', [page_2mb, page_1gb])],
                             ids=['large', 'any'])
    def test_vms_page_size_2mb_and_1gb_available(self, env, os_conn, networks,
                                                 computes_with_mixed_hp,
                                                 flavors, security_group,
                                                 keypair, page_size,
                                                 allowed_sizes, cleanup):
        """This test checks vms with any/large hw:mem_page_size when both 2Mb
        and 1Gb huge pages are available

            Steps:
            1. Create net1 with subnet and router1 with interface to net1
            2. Check that both 2Mb and 1Gb huge pages are available
            3. Boot vm and check page size: should be 1Gb in case of 'large'
            and any (1Gb or 2Mb) for 'any' mem_page_size
        """
        host = computes_with_mixed_hp[0]
        flavors[0].set_keys({'hw:mem_page_size': page_size})
        vm = os_conn.create_server(name='vm', flavor=flavors[0].id,
                                   nics=[{'net-id': networks[0]}],
                                   key_name=keypair.name,
                                   security_groups=[security_group.id],
                                   availability_zone='nova:{}'.format(host))
        assert self.get_instance_page_size(os_conn, vm) in allowed_sizes
        network_checks.check_ping_from_vm(env, os_conn, vm, vm_keypair=keypair)

    @pytest.mark.testrail_id('864078')
    def test_vms_page_size_large_no_hp(self, env, os_conn, networks, keypair,
                                       computes_with_mixed_hp, flavors,
                                       security_group, cleanup):
        """This test checks vms with any/large hw:mem_page_size when both 2Mb
        and 1Gb huge pages are unavailable

            Steps:
            1. Create net1 with subnet and router1 with interface to net1
            2. Boot vms in order to allocate all huge pages
            3. Boot vm with required mem_page_size and check result:
            vm should be in error state for 'large', for 'any' mem_page_size
            vm is active and 4kb pages are used (i.e. no huge pages)
        """
        host = computes_with_mixed_hp[0]
        zone = 'nova:{}'.format(host)

        self.boot_vms_to_allocate_hp(os_conn, env, host, page_2mb, networks[0])
        self.boot_vms_to_allocate_hp(os_conn, env, host, page_1gb, networks[0])

        flavors[0].set_keys({'hw:mem_page_size': 'large'})
        with pytest.raises(InstanceError) as e:
            os_conn.create_server(name='vm', flavor=flavors[0].id,
                                  nics=[{'net-id': networks[0]}],
                                  key_name=keypair.name,
                                  security_groups=[security_group.id],
                                  availability_zone=zone)
        exp_message = "Insufficient compute resources"
        logger.info("Vm state  is error:\n{0}".format(str(e.value)))
        assert exp_message in str(e.value), "Unexpected reason of error"

    @pytest.mark.testrail_id('1295436')
    def test_vms_page_size_any_no_hp(self, env, os_conn, networks, keypair,
                                     computes_with_mixed_hp, flavors,
                                     security_group, cleanup):
        """This test checks vms with any/large hw:mem_page_size when both 2Mb
        and 1Gb huge pages are unavailable

            Steps:
            1. Create net1 with subnet and router1 with interface to net1
            2. Boot vms in order to allocate all huge pages
            3. Boot vm with required mem_page_size and check result:
            vm should be in error state for 'large', for 'any' mem_page_size
            vm is active and 4kb pages are used (i.e. no huge pages)
        """
        host = computes_with_mixed_hp[0]
        zone = 'nova:{}'.format(host)
        self.boot_vms_to_allocate_hp(os_conn, env, host, page_2mb, networks[0])
        self.boot_vms_to_allocate_hp(os_conn, env, host, page_1gb, networks[0])

        flavors[0].set_keys({'hw:mem_page_size': 'any'})
        vm = os_conn.create_server(name='vm', flavor=flavors[0].id,
                                   nics=[{'net-id': networks[0]}],
                                   key_name=keypair.name,
                                   security_groups=[security_group.id],
                                   availability_zone=zone)
        assert self.get_instance_page_size(os_conn, vm) is None
        network_checks.check_ping_from_vm(env, os_conn, vm, vm_keypair=keypair)

    @pytest.mark.testrail_id('1455764', scarce_page=page_1gb,
                             expected_size=page_2mb)
    @pytest.mark.testrail_id('1455765', scarce_page=page_2mb,
                             expected_size=page_1gb)
    @pytest.mark.parametrize('scarce_page, expected_size',
                             [(page_1gb, page_2mb), (page_2mb, page_1gb)],
                             ids=['1gb_pages_lack', '2mb_pages_lack'])
    def test_vms_page_size_less_hp_count(self, env, os_conn, networks,
                                         computes_with_mixed_hp, flavors,
                                         security_group, keypair, scarce_page,
                                         expected_size, cleanup):
        """This test checks vms with hw:mem_page_size=large when count of
        2Mb huge pages is not enough to boot vm while count of free 1Gb huge
        page allows it (and vice versa)

            Steps:
            1. Create net1 with subnet and router1 with interface to net1
            2. Check that hp count of the 1st type is not enough for vm
            3. Boot vm and check that it use hp of the 2nd type
        """
        host = computes_with_mixed_hp[0]
        flavors[0].set_keys({'hw:mem_page_size': 'large'})

        self.boot_vms_to_allocate_hp(os_conn, env, host, scarce_page,
                                     networks[0],
                                     ram_left_free=flavors[0].ram - 1024)

        vm = os_conn.create_server(name='vm', flavor=flavors[0].id,
                                   nics=[{'net-id': networks[0]}],
                                   key_name=keypair.name,
                                   security_groups=[security_group.id],
                                   availability_zone='nova:{}'.format(host))
        assert self.get_instance_page_size(os_conn, vm) == expected_size
        network_checks.check_ping_from_vm(env, os_conn, vm, vm_keypair=keypair)
