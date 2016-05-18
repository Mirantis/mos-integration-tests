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
from mos_tests.nfv.conftest import get_cpu_distribition_per_numa_node

logger = logging.getLogger(__name__)


@pytest.yield_fixture()
def cpu_flavor(os_conn, cleanup, request):
    numa_count = getattr(request.cls, 'numa_count')
    flavor = os_conn.nova.flavors.create(name='m1.small.perfomance', ram=2048,
                                         vcpus=2, disk=20)
    flavor.set_keys({'hw:cpu_policy': 'dedicated',
                     'aggregate_instance_extra_specs:pinned': 2048,
                     'aggregate_instance_extra_specs': 1,
                     'hw:numa_nodes': numa_count})
    yield flavor
    os_conn.nova.flavors.delete(flavor.id)


@pytest.mark.check_env_('is_vlan')
class TestCpuPinningOneNuma(TestBaseNFV):

    numa_count = 1

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('838318')
    def test_cpu_pinning_one_numa_cell(
            self, env, os_conn, networks, cpu_flavor, security_group,
            aggregate):
        """This test checks that cpu pinning executed successfully for
        instances created on computes with 1 NUMA
        Steps:
            1. Create net1 with subnet, net2 with subnet and router1 with
            interfaces to both nets
            2. Launch instances vm1, vm3 in net1 with m1.small.performance on
            compute-1, vm2 on compute-2.
            3. Check numa nodes for all vms
            4. Check parameter in /etc/defaults/grub
            5. Check vms connectivity
        """
        hosts = aggregate.hosts
        vms = []
        network_for_instances = [networks[0], networks[1], networks[0]]
        hosts_for_instances = [hosts[0], hosts[1], hosts[0]]
        cpus = get_cpu_distribition_per_numa_node(env)

        for i in range(2):
            vms.append(os_conn.create_server(
                name='vm{}'.format(i),
                flavor=cpu_flavor.id,
                nics=[{'net-id': network_for_instances[i]}],
                availability_zone='nova:{}'.format(hosts_for_instances[i]),
                security_groups=[security_group.id]))

        for vm in vms:
            host = getattr(vm, "OS-EXT-SRV-ATTR:host")
            assert host in hosts
            self.check_cpu_for_vm(os_conn, vm, 1, cpus[host])

        network_checks.check_vm_connectivity(env, os_conn)


@pytest.mark.check_env_('is_vlan')
class TestCpuPinningTwoNumas(TestBaseNFV):

    numa_count = 2

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('838321')
    def test_cpu_pinning_two_numas_cell(
            self, env, os_conn, networks, cpu_flavor, security_group,
            aggregate):
        """This test checks that cpu pinning executed successfully for
        instances created on computes with 2 NUMAs
        Steps:
            1. Create net1 with subnet, net2 with subnet and router1 with
            interfaces to both nets
            2. Launch instances vm1, vm3 in net1 with m1.small.performance on
            compute-1, vm2 on compute-2.
            3. Check numa nodes for all vms
            4. Check parameter in /etc/defaults/grub
            5. Check vms connectivity
        """
        hosts = aggregate.hosts
        vms = []
        network_for_instances = [networks[0], networks[1], networks[0]]
        hosts_for_instances = [hosts[0], hosts[1], hosts[0]]
        cpus = get_cpu_distribition_per_numa_node(env)

        for i in range(2):
            vms.append(os_conn.create_server(
                name='vm{}'.format(i),
                flavor=cpu_flavor.id,
                nics=[{'net-id': network_for_instances[i]}],
                availability_zone='nova:{}'.format(hosts_for_instances[i]),
                security_groups=[security_group.id]))

        for vm in vms:
            host = getattr(vm, "OS-EXT-SRV-ATTR:host")
            assert host in hosts
            self.check_cpu_for_vm(os_conn, vm, 2, cpus[host])

        network_checks.check_vm_connectivity(env, os_conn)
