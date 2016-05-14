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
import pytest

from mos_tests.functions import network_checks
from mos_tests.nfv.base import page_1gb
from mos_tests.nfv.base import page_2mb
from mos_tests.nfv.base import TestBaseNFV
from mos_tests.nfv.conftest import computes_configuration
from mos_tests.nfv.conftest import get_cpu_distribition_per_numa_node
from mos_tests.nfv.conftest import get_hp_distribution_per_numa_node


@pytest.yield_fixture()
def flavors(os_conn, request):
    flvs = getattr(request.cls, 'flavors_to_create')
    created_flavors = []
    for flv in flvs:
        flavor = os_conn.nova.flavors.create(flv['name'], 1024, 2, 20)
        if 'numa_nodes' in flv.keys():
            flavor.set_keys({'hw:cpu_policy': 'dedicated'})
            flavor.set_keys({'aggregate_instance_extra_specs:pinned': 'true'})
            flavor.set_keys({'hw:numa_nodes': flv['numa_nodes']})
        if 'page_size' in flv.keys():
            flavor.set_keys({'hw:mem_page_size': flv['page_size']})
        created_flavors.append(flavor)
    yield created_flavors
    for flavor in created_flavors:
        os_conn.nova.flavors.delete(flavor.id)


@pytest.fixture()
def computes_for_mixed_cases(os_conn, env, computes_with_mixed_hp,
                             computes_with_numa_nodes):
    hosts = list(
        set(computes_with_mixed_hp) & set(computes_with_numa_nodes))
    conf_cpu = get_cpu_distribition_per_numa_node(env)
    conf_hp = get_hp_distribution_per_numa_node(env, numa_count=2)
    for host in hosts:
        cpu0 = len(conf_cpu[host]['numa0'])
        cpu1 = len(conf_cpu[host]['numa1'])
        if not ((cpu0 >= 4 and cpu1 >= 2) or (cpu0 >= 2 and cpu1 >= 4)):
            hosts.remove(host)
    for host in hosts:
        hp2mb_0 = conf_hp[host]['numa0'][page_2mb]['total']
        hp1gb_0 = conf_hp[host]['numa0'][page_1gb]['total']
        hp2mb_1 = conf_hp[host]['numa1'][page_2mb]['total']
        hp1gb_1 = conf_hp[host]['numa1'][page_1gb]['total']
        if hp2mb_0 < 512 or hp2mb_1 < 512 or hp1gb_0 < 1 or hp1gb_1 < 1:
            hosts.remove(host)
    if len(hosts) < 2:
        pytest.skip("Insufficient count of computes")
    return hosts


@pytest.mark.undestructive
@pytest.mark.check_env_('is_vlan')
class TestMixedFeatures(TestBaseNFV):

    flavors_to_create = [
        {'name': 'm1.small.old'},
        {'name': 'm1.small.hpgs', 'page_size': page_1gb},
        {'name': 'm1.small_hpgs_n1', 'numa_nodes': 1, 'page_size': page_2mb},
        {'name': 'm1.small_hpgs_n2', 'numa_nodes': 2, 'page_size': page_2mb},
        {'name': 'm1.small_perf_n2', 'numa_nodes': 2}]

    mixed_hp_computes = {'host_count': 2, 'count_2mb': 1024, 'count_1gb': 2}

    @pytest.mark.testrail_id('838319')
    def test_vms_connectivity_with_hp_and_numa(self, env, os_conn,
                                               computes_for_mixed_cases,
                                               aggregate, networks,
                                               security_group, flavors):
        """This test checks vms connectivity with huge pages and cpu pinning.

            At least 2 computes with mixed huge pages and cpu pinning are
            required. 2 numa nodes should be available per compute. 512 x 2Mb
            and 1 x 1Gb huge pages should be available for each numa node.
            Specific distribution of cpus per numa nodes is required for each
            compute: at least 4 cpus for one node and at least 2 cpus for
            another one.

            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Create vm1 in net1 on host1 using flavor m1.small.hpgs_n-2
             (hw:mem_page_size=2048 and hw:numa_nodes=2)
            3. Create vm2 in net1 on host1 using flavor m1.small.performance-2
             (hw:numa_nodes=2, without huge pages)
            4. Create vm3 in net2 on host2 using flavor m1.small.hpgs_n-1
             (hw:mem_page_size=2048 and hw:numa_nodes=1)
            5. Create vm4 in net2 on host2 using flavor m1.small.hpgs
             (hw:mem_page_size=1048576 without cpu pinning)
            6. Create vm5 in net1 on host1 using flavor m1.small.old
             (without features)
            7. Check cpus allocation for all vms
            8. Check page size for all vms
            9. Check free huge pages when all vms are running
            10. Check connectivity between all vms
        """
        hosts = computes_for_mixed_cases
        initial_conf_hp = computes_configuration(env)
        cpus = get_cpu_distribition_per_numa_node(env)

        vms = {}
        vms_params = [(flavors[3], hosts[0], networks[0], 2, page_2mb),
                      (flavors[4], hosts[0], networks[0], 2, None),
                      (flavors[2], hosts[1], networks[1], 1, page_2mb),
                      (flavors[1], hosts[1], networks[1], None, page_1gb),
                      (flavors[0], hosts[0], networks[0], None, None)]

        for i, (flv, host, net, numa_count, size) in enumerate(vms_params):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=flv.id,
                nics=[{'net-id': net}],
                availability_zone='nova:{}'.format(host),
                security_groups=[security_group.id], wait_for_active=False,
                wait_for_avaliable=False)
            vms.update({vm: {'numa': numa_count, 'size': size}})
        os_conn.wait_servers_active(vms)
        os_conn.wait_servers_ssh_ready(vms)

        for vm, param in vms.items():
            self.check_instance_page_size(os_conn, vm, param['size'])
            if param['numa'] is not None:
                host = getattr(vm, 'OS-EXT-SRV-ATTR:host')
                self.check_cpu_for_vm(os_conn, vm, param['numa'], cpus[host])

        network_checks.check_vm_connectivity(env, os_conn)

        final_conf = computes_configuration(env)
        vms_distribution = [(hosts[0], 0, 1), (hosts[1], 1, 1), ]
        for (host, nr_1gb, nr_2mb) in vms_distribution:
            exp_free_1g = initial_conf_hp[host][page_1gb]['total'] - nr_1gb * 1
            exp_free_2m = (
                initial_conf_hp[host][page_2mb]['total'] - nr_2mb * 512)
            assert exp_free_1g == final_conf[host][page_1gb]['free']
            assert exp_free_2m == final_conf[host][page_2mb]['free']
