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
from mos_tests.functions import service
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


@pytest.yield_fixture
def disable_nova_config_drive(env):
    # WA for bug https://bugs.launchpad.net/mos/+bug/1589460/
    # This should be removed in MOS 10.0
    config = [('DEFAULT', 'force_config_drive', False)]
    for step in service.nova_patch(env, config):
        yield step


@pytest.fixture
def hosts_hyper_threading(aggregate, hosts_with_hyper_threading):
    hosts = list(set(hosts_with_hyper_threading) & set(aggregate.hosts))
    if len(hosts) == 0:
        pytest.skip("At least one compute with cpu_pinning and "
                    "hyper_threading is required")
    return hosts


@pytest.fixture
def hosts_without_hyper_threading(aggregate, hosts_with_hyper_threading):
    hosts = list(set(aggregate.hosts) - set(hosts_with_hyper_threading))
    if len(hosts) == 0:
        pytest.skip("At least one compute with cpu_pinning and "
                    "without hyper_threading is required")
    return hosts


@pytest.mark.undestructive
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

    @pytest.mark.testrail_id('838340')
    @pytest.mark.usefixtures('disable_nova_config_drive')
    def test_vms_connectivity_after_evacuation(self, env, os_conn, networks,
                                               flavors, aggregate,
                                               security_group, devops_env):
        """This test checks vms connectivity for vms with cpu pinning with 1
        NUMA after evacuation

        Steps:
            1. Create net1 with subnet, net2 with subnet and router1 with
            interfaces to both nets
            2. Boot vm0 with cpu flavor on host0 and net0
            3. Boot vm1 with old flavor on host1 and net1
            4. Check vms connectivity
            5. Kill compute0 and evacuate vm0 to compute1 with
            --on-shared-storage parameter
            6. Check vms connectivity
            7. Check numa nodes for vm0
            8. Make compute0 alive
            9. Check that resources for vm0 were deleted from compute0
        """
        cpus = get_cpu_distribition_per_numa_node(env)
        hosts = aggregate.hosts
        vms = []

        for i in range(2):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=flavors[i].id,
                nics=[{'net-id': networks[i]}],
                availability_zone='nova:{}'.format(hosts[i]),
                security_groups=[security_group.id])
            vms.append(vm)
        network_checks.check_vm_connectivity(env, os_conn)
        self.check_cpu_for_vm(os_conn, vms[0], 1, cpus[hosts[0]])

        with self.change_compute_state_to_down(os_conn, devops_env, hosts[0]):
            vm0_new = self.evacuate(os_conn, devops_env, vms[0])
            new_host = getattr(vm0_new, "OS-EXT-SRV-ATTR:host")
            assert new_host in hosts, "Unexpected host after evacuation"
            assert new_host != hosts[0], "Host didn't change after evacuation"
            os_conn.wait_servers_ssh_ready(vms)
            network_checks.check_vm_connectivity(env, os_conn)
            self.check_cpu_for_vm(os_conn, vm0_new, 1, cpus[new_host])

        old_hv = os_conn.nova.hypervisors.find(hypervisor_hostname=hosts[0])
        assert old_hv.running_vms == 0, (
            "Old hypervisor {0} shouldn't have running vms").format(hosts[0])

        instance_name = getattr(vm0_new, "OS-EXT-SRV-ATTR:instance_name")
        assert instance_name in self.get_instances(os_conn, new_host), (
            "Instance should be in the list of instances on the new host")
        assert instance_name not in self.get_instances(os_conn, hosts[0]), (
            "Instance shouldn't be in the list of instances on the old host")


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
         'params': {'ram': 2000, 'vcpus': 4, 'disk': 1},
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
                    vm = self.resize(os_conn, vm, object_flavor.id)
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
            os_conn.wait_servers_ssh_ready(vms)
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

            os_conn.wait_servers_ssh_ready(vms)
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


@pytest.mark.check_env_('is_vlan')
@pytest.mark.undestructive
class TestCpuPinningWithCpuThreadPolicy(TestBaseNFV):

    flavors_to_create = [
        {'name': 'm1.small.perfomance',
         'params': {'ram': 2048, 'vcpu': 2, 'disk': 1},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 1}}]

    @pytest.mark.testrail_id('864071', policy='prefer', expected_count=1)
    @pytest.mark.testrail_id('864073', policy='isolate', expected_count=2)
    @pytest.mark.testrail_id('864075', policy='require', expected_count=1)
    @pytest.mark.parametrize('policy, expected_count',
                             [('prefer', 1), ('isolate', 2), ('require', 1)],
                             ids=['prefer - same core',
                                  'isolate - different cores',
                                  'require - same core'])
    def test_vms_with_custom_threading_policy(self, env, os_conn,
                                              hosts_hyper_threading,
                                              flavors, networks, keypair,
                                              security_group, policy,
                                              expected_count):
        """This test checks vcpu allocation for vms with different values of
        flavor cpu_thread_policy

        Steps:
            1. Create net1 with subnet and router1 with interface to net1
            2. Create cpu pinning flavor with hw:numa_nodes=1 and required
            cpu_thread_policy
            3. Boot vm
            4. Check that both cpu are on the different cores in case of
            cpu_thread_policy = isolate and on the same core in case of prefer
            or require
            5. Check ping 8.8.8.8 from vm
        """

        host = hosts_hyper_threading[0]
        cpus = get_cpu_distribition_per_numa_node(env)[host]

        flavors[0].set_keys({'hw:cpu_thread_policy': policy})
        vm = os_conn.create_server(name='vm', flavor=flavors[0].id,
                                   key_name=keypair.name,
                                   nics=[{'net-id': networks[0]}],
                                   security_groups=[security_group.id],
                                   availability_zone='nova:{}'.format(host),
                                   wait_for_avaliable=False)
        self.check_cpu_for_vm(os_conn, vm, 1, cpus)

        used_ts = self.get_vm_thread_siblings_lists(os_conn, vm)
        assert len(used_ts) == expected_count, (
            "Unexpected count of used cores. It should be {0} for '{1}' "
            "threading policy, but actual it's {2}").format(
            expected_count, policy, len(used_ts))

        network_checks.check_ping_from_vm(env, os_conn, vm, vm_keypair=keypair)


@pytest.mark.check_env_('is_vlan')
@pytest.mark.undestructive
class TestCpuPinningLessResourcesWithCpuThreadPolicy(TestBaseNFV):

    keys = [('aggregate_instance_extra_specs:pinned', 'true'),
            ('hw:cpu_policy', 'dedicated'),
            ('hw:numa_nodes', 1)]
    params = {'ram': 1024, 'vcpu': 2, 'disk': 1}

    flavors_to_create = [
        {'name': 'm1.small.prefer', 'params': params,
         'keys': dict(keys + [('hw:cpu_thread_policy', 'prefer')])},
        {'name': 'm1.small.isolate', 'params': params,
         'keys': dict(keys + [('hw:cpu_thread_policy', 'isolate')])},
        {'name': 'm1.small.require', 'params': params,
         'keys': dict(keys + [('hw:cpu_thread_policy', 'require')])},
        {'name': 'm1.small.prefer_1_vcpu',
         'params': {
             'ram': 1024,
             'vcpu': 1,
             'disk': 1},
         'keys': dict(keys + [('hw:cpu_thread_policy', 'prefer')])}]

    @pytest.mark.testrail_id('864074')
    def test_vms_with_isolate_cpu_thread_policy_less_resources(
            self, env, os_conn, hosts_hyper_threading, flavors, networks,
            keypair, security_group):
        """This test checks vms with cpu_thread_policy isolate parameter with
        less resources

        Steps:
            1. Create net1 with subnet and router1 with interface to net1
            2. Create cpu pinning flavor with hw:numa_nodes=1 and required
            cpu_thread_policy
            3. Boot vms to have no ability to create vm on different cores
            4. Boot vm with cpu pinning flavor (cpu_thread_policy = isolate)
            5. Check that vm is in error state
        """
        host = hosts_hyper_threading[0]
        cpus = get_cpu_distribition_per_numa_node(env)[host]
        zone = 'nova:{}'.format(host)

        # Get total pairs of cpus
        numa_nodes_count = len(cpus.keys())
        ts = set()
        for i in range(numa_nodes_count):
            ts.update(self.get_thread_siblings_lists(os_conn, host, i))
        ts_lsts = list(ts)

        # Boot vms to allocate vcpus in order to have no change to use cpus
        # from different cores: N-1 vms with 'require' flavor if N is total
        # count of vcps pairs
        count_require = len(ts_lsts) - 1
        for i in range(count_require):
            os_conn.create_server(name='vm{0}'.format(i),
                                  flavor=flavors[2].id,
                                  key_name=keypair.name,
                                  nics=[{'net-id': networks[0]}],
                                  security_groups=[security_group.id],
                                  wait_for_avaliable=False,
                                  availability_zone=zone)

        with pytest.raises(InstanceError) as e:
            os_conn.create_server(name='vm_isolate',
                                  flavor=flavors[1].id,
                                  key_name=keypair.name,
                                  nics=[{'net-id': networks[0]}],
                                  security_groups=[security_group.id],
                                  wait_for_avaliable=False,
                                  availability_zone=zone)
        exp_message = ("Insufficient compute resources: "
                       "Requested instance NUMA topology cannot fit the "
                       "given host NUMA topology")
        logger.info("Instance status is error:\n{0}".format(str(e.value)))
        assert exp_message in str(e.value), "Unexpected reason of error"

    @pytest.mark.testrail_id('864072', policy='prefer')
    @pytest.mark.testrail_id('864076', policy='require')
    @pytest.mark.parametrize('policy', ['prefer', 'require'])
    def test_vms_with_custom_cpu_thread_policy_less_resources(
            self, env, os_conn, hosts_hyper_threading, flavors, networks,
            keypair, security_group, policy):
        """This test checks vms with cpu_thread_policy prefer/require parameter
         with less resources

        Steps:
            1. Create net1 with subnet and router1 with interface to net1
            2. Create cpu pinning flavor with hw:numa_nodes=1 and required
            cpu_thread_policy
            3. Boot vms to have no ability to create vm on one core
                Steps are:
                1) boot M + N - 1 vms with flavor_require
                    N = count of thread siblings list is on numa0
                    M = count of thread siblings list is on numa0
                    As result 1 core is free
                2) create 2 vms with 1 vcpu and 'prefer' policy
                3) delete 1 vm with 2 vcpu from step 1 or 2
                4) create 1 vm with 1 vcpu and 'prefer' policy
                5) delete 1 vm with 1 vpcu from step 3
            4. Boot vm with cpu pinning flavor with required cpu_thread_policy
            5. For 'require' policy check that vm is in error state, for
            policy 'prefer' vm should be active and available
        """

        host = hosts_hyper_threading[0]
        cpus = get_cpu_distribition_per_numa_node(env)[host]
        zone = 'nova:{}'.format(host)
        flv_prefer, _, flv_require, flv_prefer_1_vcpu = flavors

        numa_count = len(cpus.keys())
        ts_lists = [list(set(self.get_thread_siblings_lists(os_conn, host, i)))
                    for i in range(numa_count)]
        if ts_lists[0] <= 1 and ts_lists[1] <= 1:
            pytest.skip("Configuration is NOK since instance should be on the "
                        "one numa node and use cpus from the different cores")

        def create_server_with_flavor(prefix, flavor):
            return os_conn.create_server(
                name='vm{0}_{1}'.format(prefix, flavor.name),
                flavor=flavor.id,
                key_name=keypair.name,
                nics=[{'net-id': networks[0]}],
                security_groups=[security_group.id],
                wait_for_avaliable=False,
                availability_zone=zone)

        # Boot vms to have no ability to create vm on one core
        for i in range(len(ts_lists[0]) + len(ts_lists[1]) - 1):
            vm_2_vcpu = create_server_with_flavor(prefix=i, flavor=flv_require)

        for i in range(2):
            vm_1_vcpu = create_server_with_flavor(prefix="{0}_vcpu1".format(i),
                                                  flavor=flv_prefer_1_vcpu)
        vm_2_vcpu.delete()
        os_conn.wait_servers_deleted([vm_2_vcpu])
        create_server_with_flavor(prefix="_vcpu1_prefer",
                                  flavor=flv_prefer_1_vcpu)
        vm_1_vcpu.delete()
        os_conn.wait_servers_deleted([vm_1_vcpu])

        # Boot vm with cpu pinning flavor with required cpu_thread_policy
        if policy == 'prefer':
            vm = os_conn.create_server(name='vm_{0}'.format(flv_prefer.name),
                                       flavor=flv_prefer.id,
                                       key_name=keypair.name,
                                       nics=[{'net-id': networks[0]}],
                                       security_groups=[security_group.id],
                                       wait_for_avaliable=False,
                                       availability_zone=zone)
            os_conn.wait_servers_ssh_ready(os_conn.get_servers())
            network_checks.check_ping_from_vm(env, os_conn, vm,
                                              vm_keypair=keypair)
        else:
            with pytest.raises(InstanceError) as e:
                os_conn.create_server(name='vm', flavor=flv_require.id,
                                      nics=[{'net-id': networks[0]}],
                                      key_name=keypair.name,
                                      security_groups=[security_group.id],
                                      availability_zone='nova:{}'.format(host),
                                      wait_for_avaliable=False)
            expected_message = ("Insufficient compute resources: "
                                "Requested instance NUMA topology cannot fit "
                                "the given host NUMA topology")
            logger.info("Instance status is error:\n{0}".format(str(e.value)))
            assert expected_message in str(e.value), (
                "Unexpected reason of instance error")

    @pytest.mark.testrail_id('864077')
    def test_vms_with_cpu_thread_policy_wo_hyper_threading(
            self, env, os_conn, hosts_without_hyper_threading, flavors,
            networks, keypair, security_group):
        """This test checks vms with cpu_thread_policy parameter in case of
        disabled hyper-threading

        Steps:
            1. Create net1 with subnet and router1 with interface to net1
            2. Create cpu pinning flavors with hw:numa_nodes=1 and
            cpu_thread_policy
            3. Boot vm and check that all vcpus are on the different core
            4. Redo for all flavors
            5. Check vms connectivity
        """

        host = hosts_without_hyper_threading[0]
        zone = 'nova:{}'.format(host)

        for flv in flavors:
            vm = os_conn.create_server(name='vm{}'.format(flv.name),
                                       flavor=flv.id,
                                       key_name=keypair.name,
                                       nics=[{'net-id': networks[0]}],
                                       security_groups=[security_group.id],
                                       availability_zone=zone)

            used_ts_list = self.get_vm_thread_siblings_lists(os_conn, vm)
            assert len(used_ts_list) == flv.vcpus, (
                "vcpus should be on the different cores")

        network_checks.check_vm_connectivity(env, os_conn)
