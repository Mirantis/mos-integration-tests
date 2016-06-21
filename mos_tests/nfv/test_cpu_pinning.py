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

import csv
import logging
import math

from novaclient.exceptions import BadRequest
import pytest

from mos_tests.environment.os_actions import InstanceError
from mos_tests.functions.common import wait
from mos_tests.functions import network_checks
from mos_tests.nfv.base import TestBaseNFV
from mos_tests.nfv.conftest import get_cpu_distribition_per_numa_node
from mos_tests.nfv.conftest import get_memory_distribition_per_numa_node

logger = logging.getLogger(__name__)


@pytest.yield_fixture
def aggregate_n(os_conn):
    numa_computes = []
    for compute in os_conn.env.get_nodes_by_role('compute'):
        with compute.ssh() as remote:
            res = remote.check_call("lscpu -p=cpu,node | "
                                    "grep -v '#'")["stdout"]
        reader = csv.reader(res)
        numas = {int(numa[1]) for numa in reader}
        if len(numas) > 1:
            numa_computes.append(compute)
    if len(numa_computes) < 2:
        pytest.skip("Insufficient count of compute with Numa Nodes")
    aggr = os_conn.nova.aggregates.create('performance_n', 'nova')
    os_conn.nova.aggregates.set_metadata(aggr, {'pinned': 'false'})
    for host in numa_computes:
        os_conn.nova.aggregates.add_host(aggr, host.data['fqdn'])
    yield aggr
    for host in numa_computes:
        os_conn.nova.aggregates.remove_host(aggr, host.data['fqdn'])
    os_conn.nova.aggregates.delete(aggr)


@pytest.mark.check_env_('is_vlan')
class TestCpuPinningOneNuma(TestBaseNFV):

    flavors_to_create = [
        {'name': 'm1.small.perfomance',
         'params': {'ram': 2048, 'vcpus': 2, 'disk': 20},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 1}},
        {'name': 'm1.small.old',
         'params': {'ram': 2048, 'vcpus': 2, 'disk': 20},
         'keys': {'aggregate_instance_extra_specs:pinned': 'false'}}]

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('838320')
    def test_cpu_pinning_one_numa_cell(
            self, env, os_conn, networks, flavors, security_group,
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
                flavor=flavors[0].id,
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

    flavors_to_create = [
        {'name': 'm1.small.perfomance',
         'params': {'ram': 2048, 'vcpus': 2, 'disk': 20},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 2}}]

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('838321')
    def test_cpu_pinning_two_numas_cell(
            self, env, os_conn, networks, flavors, security_group,
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
                flavor=flavors[0].id,
                nics=[{'net-id': network_for_instances[i]}],
                availability_zone='nova:{}'.format(hosts_for_instances[i]),
                security_groups=[security_group.id]))

        for vm in vms:
            host = getattr(vm, "OS-EXT-SRV-ATTR:host")
            assert host in hosts
            self.check_cpu_for_vm(os_conn, vm, 2, cpus[host])

        network_checks.check_vm_connectivity(env, os_conn)


@pytest.mark.check_env_('is_vlan')
class TestCpuPinningOldFlavor(TestBaseNFV):

    flavors_to_create = [
        {'name': 'm1.small.perfomance',
         'params': {'ram': 2048, 'vcpus': 2, 'disk': 20},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 1}},
        {'name': 'm1.small.old',
         'params': {'ram': 2048, 'vcpus': 2, 'disk': 20},
         'keys': {'aggregate_instance_extra_specs:pinned': 'false'}}]

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('838324')
    def test_cpu_pinning_old_flavor(
            self, env, os_conn, networks, flavors, security_group,
            aggregate, aggregate_n):
        """This test checks that cpu pinning executed successfully for
        instances created on computes with 1 NUMA
        Steps:
            1. Create net1 with subnet, net2 with subnet and router1 with
            interfaces to both nets
            2. Launch instances vm0 in net1 with m1.small.performance,
            with m1.small.old vm2 on compute-2, vm3 on compute-1.
            3. Check numa nodes for vms
            4. Check parameter in /etc/defaults/grub
            5. Check vms connectivity
        """
        hosts = aggregate.hosts
        hosts_n = aggregate_n.hosts
        vms = []
        flavors_for_instances = [flavors[0], flavors[1], flavors[0]]
        network_for_instances = [networks[0], networks[1], networks[0]]
        hosts_for_instances = [hosts[0], hosts[1], hosts_n[0]]
        cpus = get_cpu_distribition_per_numa_node(env)

        for i in range(2):
            vms.append(os_conn.create_server(
                name='vm{}'.format(i),
                flavor=flavors_for_instances[i].id,
                nics=[{'net-id': network_for_instances[i]}],
                availability_zone='nova:{}'.format(hosts_for_instances[i]),
                security_groups=[security_group.id]))

        for vm in vms:
            host = getattr(vm, "OS-EXT-SRV-ATTR:host")
            assert host in hosts
            if vm.name != 'vm1':
                self.check_cpu_for_vm(os_conn, vm, 1, cpus[host])

        network_checks.check_vm_connectivity(env, os_conn)


@pytest.mark.check_env_('is_vlan')
class TestCpuPinningResize(TestBaseNFV):

    flavors_to_create = [
        {'name': 'm1.small.perfomance-1',
         'params': {'ram': 512, 'vcpus': 1, 'disk': 1},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 1}},
        {'name': 'm1.small.old',
         'params': {'ram': 512, 'vcpus': 1, 'disk': 1},
         'keys': {'aggregate_instance_extra_specs:pinned': 'false'}},
        {'name': 'm1.small.perfomance-2',
         'params': {'ram': 512, 'vcpus': 2, 'disk': 1},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 2}},
        {'name': 'm1.small.perfomance-3',
         'params': {'ram': 2000, 'vcpus': 3, 'disk': 1},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 2}},
        {'name': 'm1.small.perfomance-4',
         'params': {'ram': 512, 'vcpus': 2, 'disk': 1},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 1}}]

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('838339')
    def test_cpu_pinning_resize(
            self, env, os_conn, networks, flavors, security_group,
            aggregate, aggregate_n):
        """This test checks that cpu pinning executed successfully for
        instances created on computes with 1 NUMA
        Steps:
            1. Create net1 with subnet, net2 with subnet and router1 with
            interfaces to both nets
            2. Launch vm1 using m1.small.performance-1 flavor on compute-1 and
            vm2 on compute-2 with m1.small.old flavor.
            3. Resize vm1 to m1.small.performance-2
            4. Ping vm1 from vm2
            5. Resize vm1 to m1.small.performance-3
            6. Ping vm1 from vm2
            7. Resize vm1 to m1.small.performance-1
            8. Ping vm1 from vm2
            9. Resize vm1 to m1.small.old
            10. Ping vm1 from vm2
            11. Resize vm1 to m1.small.performance-4
            12. Ping vm1 from vm2
            13. Resize vm1 to m1.small.performance-1
            14. Ping vm1 from vm2
        """
        hosts = aggregate.hosts
        vms = []
        cpus = get_cpu_distribition_per_numa_node(env)
        flavors_for_resize = ['m1.small.perfomance-2',
                              'm1.small.perfomance-3',
                              'm1.small.perfomance-1',
                              'm1.small.old', 'm1.small.perfomance-4',
                              'm1.small.perfomance-1']

        for i in range(2):
            vms.append(os_conn.create_server(
                name='vm{}'.format(i),
                flavor=flavors[i].id,
                nics=[{'net-id': networks[i]}],
                availability_zone='nova:{}'.format(hosts[i]),
                security_groups=[security_group.id]))

        vm = vms[0]

        for flavor in flavors_for_resize:
            numas = 2
            for object_flavor in flavors:
                if object_flavor.name == flavor:
                    self.resize(os_conn, vm, object_flavor.id)
                    break
            if flavor is not 'm1.small.old':
                if flavor in ['m1.small.perfomance-4',
                              'm1.small.perfomance-1']:
                    numas = 1
                host = getattr(vm, "OS-EXT-SRV-ATTR:host")
                assert host in hosts
                self.check_cpu_for_vm(os_conn,
                                      os_conn.get_instance_detail(vm),
                                      numas, cpus[host])
            network_checks.check_vm_connectivity(env, os_conn)


@pytest.mark.check_env_('is_vlan')
class TestCpuPinningMigration(TestBaseNFV):

    flavors_to_create = [
        {'name': 'm1.small.perfomance',
         'params': {'ram': 2000, 'vcpus': 2, 'disk': 20},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 2}}]

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('838338')
    def test_cpu_pinning_migration(
            self, env, os_conn, networks, flavors, security_group,
            aggregate):
        """This test checks that cpu pinning executed successfully for
        instances created on computes with 1 NUMA
        Steps:
            1. Create net1 with subnet, net2 with subnet and router1 with
            interfaces to both nets
            2. Launch vm1 using m1.small.performance flavor on compute-1 and
            vm2 on compute-2.
            3. Migrate vm1 from compute-1
            4. Check CPU Pinning
        """
        hosts = aggregate.hosts

        vms = []
        cpus = get_cpu_distribition_per_numa_node(env)

        for i in range(2):
            vms.append(os_conn.create_server(
                name='vm{}'.format(i),
                flavor=flavors[0].id,
                nics=[{'net-id': networks[0]}],
                availability_zone='nova:{}'.format(hosts[i]),
                security_groups=[security_group.id]))
        for i in range(5):
            vm_host = getattr(vms[0], "OS-EXT-SRV-ATTR:host")

            vm_0_new = self.migrate(os_conn, vms[0])
            vm_host_0_new = getattr(vm_0_new, "OS-EXT-SRV-ATTR:host")

            assert vm_host_0_new != vm_host

            for vm in vms:
                host = getattr(vm, "OS-EXT-SRV-ATTR:host")
                self.check_cpu_for_vm(os_conn,
                                      os_conn.get_instance_detail(vm), 2,
                                      cpus[host])

            network_checks.check_vm_connectivity(env, os_conn)


@pytest.mark.check_env_('is_vlan')
@pytest.mark.undestructive
class TestResourceDistribution(TestBaseNFV):
    mem_numa0, mem_numa1 = 512, 1536
    cpu_numa0, cpu_numa1 = '0, 2, 3', '1'

    flavors_to_create = [
        {'name': 'm1.small.perfomance',
         'params': {'ram': 2048, 'vcpu': 4, 'disk': 1},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated'}}]

    @pytest.mark.testrail_id('857418')
    def test_cpu_and_memory_distribution(self, env, os_conn, networks, flavors,
                                         security_group, aggregate, keypair):
        """This test checks distribution of cpu for vm with cpu pinning
        Steps:
            1. Create flavor with custom numa_cpu and numa_mem distribution
            2. Create net1 with subnet, net2 with subnet and router1 with
                interfaces to both nets
            3. Launch vm using created flavor
            4. Check memory allocation per numa node
            5. Check CPU allocation
            6. Ping 8.8.8.8 from vm1
        """

        host = aggregate.hosts[0]
        numa_count = 2
        cpus = get_cpu_distribition_per_numa_node(env)

        flavors[0].set_keys({'hw:numa_nodes': numa_count,
                             'hw:numa_cpus.0': self.cpu_numa0,
                             'hw:numa_cpus.1': self.cpu_numa1,
                             'hw:numa_mem.0': self.mem_numa0,
                             'hw:numa_mem.1': self.mem_numa1})

        exp_mem = {'0': self.mem_numa0, '1': self.mem_numa1}
        exp_pin = {'numa0': [int(cpu) for cpu in self.cpu_numa0.split(',')],
                   'numa1': [int(cpu) for cpu in self.cpu_numa1.split(',')]}
        vm = os_conn.create_server(name='vm', flavor=flavors[0].id,
                                   nics=[{'net-id': networks[0]}],
                                   key_name=keypair.name,
                                   security_groups=[security_group.id],
                                   availability_zone='nova:{}'.format(host))

        self.check_cpu_for_vm(os_conn, vm, numa_count, cpus[host], exp_pin)
        act_mem = self.get_memory_allocation_per_numa(os_conn, vm, numa_count)
        assert act_mem == exp_mem, "Actual memory allocation is not OK"
        network_checks.check_ping_from_vm(env, os_conn, vm, vm_keypair=keypair)

    @pytest.mark.testrail_id('857419')
    def test_negative_distribution_one_numa(self, os_conn, networks,
                                            flavors, security_group, keypair,
                                            aggregate):
        """This test checks distribution of cpu for vm with cpu pinning
        Steps:
            1. Create flavor with custom numa_cpu and numa_mem distribution,
                set hw:numa_nodes to 1 in flavor metatada, but allocate memory
                and cpu to two numa nodes
            2. Create net1 with subnet, net2 with subnet and router1 with
                interfaces to both nets
            3. Launch vm using created flavor
            4. Check that vm is not created
        """
        host = aggregate.hosts[0]
        numa_count = 1
        flavors[0].set_keys({'hw:numa_nodes': numa_count,
                             'hw:numa_cpus.0': self.cpu_numa0,
                             'hw:numa_cpus.1': self.cpu_numa1,
                             'hw:numa_mem.0': self.mem_numa0,
                             'hw:numa_mem.1': self.mem_numa1})

        with pytest.raises(BadRequest) as e:
            os_conn.create_server(name='vm', flavor=flavors[0].id,
                                  key_name=keypair.name,
                                  nics=[{'net-id': networks[0]}],
                                  security_groups=[security_group.id],
                                  availability_zone='nova:{}'.format(host))
        logger.info("Unable to create vm due to bad request:\n"
                    "{0}".format(str(e.value)))


@pytest.mark.check_env_('is_vlan')
@pytest.mark.undestructive
class TestResourceDistributionWithLessResources(TestBaseNFV):

    created_flvs = []

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

    def get_flavor_cpus(self, cpus_list):
        """Convert cpus list to string (format for flavor metadata)"""
        flv_cpus = ','.join([str(i) for i in cpus_list])
        return flv_cpus

    @pytest.mark.testrail_id('857420', resource='ram')
    @pytest.mark.testrail_id('857477', resource='cpu')
    @pytest.mark.parametrize('resource', ['cpu', 'ram'])
    def test_negative_distribution_less_resources(self, env, os_conn, networks,
                                                  security_group, resource,
                                                  aggregate, keypair, cleanup):
        """This test checks that vm is in error state if at least one numa node
        has insufficient resources
        Steps:
            1. Create flavor with numa_cpu and numa_mem distribution
            2. Create net1 with subnet, net2 with subnet and router1 with
                interfaces to both nets
            3. Launch vm using created flavor
            4. Check that vm in error state
        """
        host = aggregate.hosts[0]
        host_cpus = get_cpu_distribition_per_numa_node(env)[host]
        host_mem = get_memory_distribition_per_numa_node(env)[host]
        total_cpu = len(host_cpus['numa0']) + len(host_cpus['numa1'])
        host_mem0 = math.ceil(host_mem['numa0'] / 1024)
        host_mem1 = math.ceil(host_mem['numa1'] / 1024)

        # Calculate flavor metadata values that would lead to the error by
        # allocating more resources than available for numa node
        if resource == 'cpu':
            cnt_to_exceed = len(host_cpus['numa0']) + 1
            cpu_numa0 = self.get_flavor_cpus(range(total_cpu)[:cnt_to_exceed])
            cpu_numa1 = self.get_flavor_cpus(range(total_cpu)[cnt_to_exceed:])
            mem_numa0 = int(host_mem0 / 2)
            mem_numa1 = int(host_mem1 / 2)
        else:
            correct_cnt = len(host_cpus['numa0'])
            cpu_numa0 = self.get_flavor_cpus(range(total_cpu)[:correct_cnt])
            cpu_numa1 = self.get_flavor_cpus(range(total_cpu)[correct_cnt:])
            mem_numa0 = int(max(host_mem0, host_mem1) +
                            min(host_mem0, host_mem1) / 2)
            mem_numa1 = int(host_mem1 - mem_numa0)

        # Create flavor with params and metadata depending on resources
        flv = os_conn.nova.flavors.create(name='flv',
                                          ram=mem_numa0 + mem_numa1,
                                          vcpus=total_cpu, disk=1)
        self.created_flvs.append(flv)
        flv.set_keys({
            'aggregate_instance_extra_specs:pinned': 'true',
            'hw:cpu_policy': 'dedicated', 'hw:numa_nodes': 2,
            'hw:numa_cpus.0': cpu_numa0, 'hw:numa_cpus.1': cpu_numa1,
            'hw:numa_mem.0': mem_numa0, 'hw:numa_mem.1': mem_numa1})

        # Boot instance
        with pytest.raises(InstanceError) as e:
            os_conn.create_server(name='vm', flavor=flv.id,
                                  nics=[{'net-id': networks[0]}],
                                  key_name=keypair.name,
                                  security_groups=[security_group.id],
                                  availability_zone='nova:{}'.format(host),
                                  wait_for_avaliable=False)
        expected_message = ("Insufficient compute resources: "
                            "Requested instance NUMA topology cannot fit the "
                            "given host NUMA topology")
        logger.info("Instance status is error:\n{0}".format(str(e.value)))
        assert expected_message in str(e.value), (
            "Unexpected reason of instance error")
