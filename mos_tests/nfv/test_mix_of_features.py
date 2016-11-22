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


@pytest.fixture()
def computes_for_mixed_hp_and_numa(os_conn, env, computes_with_mixed_hp,
                                   computes_with_numa_nodes):
    hosts = list(
        set(computes_with_mixed_hp) & set(computes_with_numa_nodes))
    conf_cpu = get_cpu_distribition_per_numa_node(env)
    conf_hp = get_hp_distribution_per_numa_node(env)
    for host in hosts:
        cpu0 = len(conf_cpu[host]['numa0'])
        cpu1 = len(conf_cpu[host]['numa1'])
        if cpu0 < 4 or cpu1 < 4:
            hosts.remove(host)
    for host in hosts:
        hp2mb_0 = conf_hp[host]['numa0'][page_2mb]['total']
        hp1gb_0 = conf_hp[host]['numa0'][page_1gb]['total']
        hp2mb_1 = conf_hp[host]['numa1'][page_2mb]['total']
        hp1gb_1 = conf_hp[host]['numa1'][page_1gb]['total']
        if hp2mb_0 < 1024 or hp2mb_1 < 1024 or hp1gb_0 < 2 or hp1gb_1 < 2:
            hosts.remove(host)
    if len(hosts) < 2:
        pytest.skip("Insufficient count of computes")
    return hosts


@pytest.yield_fixture()
def vf_ports(os_conn, security_group, networks):
    ports = []
    for i in range(4):
        vf_port = os_conn.neutron.create_port(
            {'port': {'network_id': networks[0],
                      'name': 'sriov-port{0}'.format(i),
                      'binding:vnic_type': 'direct',
                      'device_owner': 'nova-compute',
                      'security_groups': [security_group.id]}})
        ports.append(vf_port['port']['id'])
    yield ports
    for port in ports:
        os_conn.neutron.delete_port(port)


@pytest.mark.undestructive
class TestMixedHugePagesAndNuma(TestBaseNFV):

    flavors_to_create = [
        {'name': 'm1.small.old'},
        {'name': 'm1.small.hpgs', 'keys': {'hw:mem_page_size': page_1gb}},
        {'name': 'm1.small_hpgs_n1',
         'keys': {'hw:mem_page_size': page_2mb,
                  'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 1}},
        {'name': 'm1.small_hpgs_n2',
         'keys': {'hw:mem_page_size': page_2mb,
                  'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 2}},
        {'name': 'm1.small_perf_n2',
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 2}}]

    mixed_hp_computes = {'host_count': 2, 'count_2mb': 1024, 'count_1gb': 2}

    @pytest.mark.testrail_id('838319')
    def test_vms_connectivity_with_hp_and_numa(self, env, os_conn,
                                               computes_for_mixed_hp_and_numa,
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
        hosts = computes_for_mixed_hp_and_numa
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
            act_size = self.get_instance_page_size(os_conn, vm)
            assert act_size == param['size'], (
                "Unexpected package size. Should be {0} instead of {1}".format(
                    param['size'], act_size))
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


@pytest.mark.undestructive
class TestMixedAllFeatures(TestBaseNFV):

    flavors_to_create = [
        {'name': 'm1.small_hpgs_n1',
         'keys': {'hw:mem_page_size': page_2mb,
                  'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 1}},
        {'name': 'm1.small.hpgs_1_n2',
         'params': {'ram': 2048, 'vcpu': 2, 'disk': 20},
         'keys': {'hw:mem_page_size': page_1gb,
                  'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated',
                  'hw:numa_nodes': 2}},
        {'name': 'm1.small_hpgs_1',
         'keys': {'hw:mem_page_size': page_1gb}},
        {'name': 'm1.small_hpgs',
         'keys': {'hw:mem_page_size': page_2mb}},
        {'name': 'm1.small_old'}]

    mixed_hp_computes = {'host_count': 2, 'count_2mb': 2048, 'count_1gb': 4}

    @pytest.mark.testrail_id('838352')
    def test_vms_connectivity(self, env, os_conn, sriov_hosts,
                              computes_for_mixed_hp_and_numa, networks,
                              vf_ports, security_group, flavors,
                              ubuntu_image_id, keypair):
        """This test checks vms connectivity with all features
            Steps:
            1. Create net1 with subnet, router1 with interface to net1
            2. Create vm1 on vf port with flavor m2.small.hpgs_n-1 on host1
            3. Create vm2 on vf port with old flavor on host1
            4. Create vm3 with flavor m1.small.hpgs-1_n-2 on host1
            5. Create vm4 on vf port with m1.small.hpgs-1 on host2
            6. Create vm5 on vf port with old flavor on host2
            7. Create vm6 with m1.small.hpgs on host2
            8. Check that vms are on right numa-node
            9. Check page size for all vms
            10. Check vms connectivity
        """
        hosts = list(set(computes_for_mixed_hp_and_numa) & set(sriov_hosts))
        if len(hosts) < 2:
            pytest.skip("At least 2 hosts with all features are required")
        cpus = get_cpu_distribition_per_numa_node(env)
        vms = {}
        net = networks[0]
        vms_params = [(flavors[0], hosts[0], vf_ports[0], 1, page_2mb),
                      (flavors[4], hosts[0], vf_ports[1], None, None),
                      (flavors[1], hosts[0], None, 2, page_1gb),
                      (flavors[2], hosts[1], vf_ports[2], None, page_1gb),
                      (flavors[4], hosts[1], vf_ports[3], None, None),
                      (flavors[3], hosts[1], None, None, page_2mb)]
        for i, (flv, host, port, numa_count, size) in enumerate(vms_params):
            nics = [{'net-id': net}]
            if port is not None:
                nics = [{'port-id': port}]
            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                flavor=flv.id, nics=nics, key_name=keypair.name,
                availability_zone='nova:{}'.format(host),
                security_groups=[security_group.id], wait_for_active=False,
                wait_for_avaliable=False)
            vms.update({vm: {'numa': numa_count, 'size': size}})

        os_conn.wait_servers_active(vms.keys())
        os_conn.wait_servers_ssh_ready(vms.keys())
        for vm, param in vms.items():
            act_size = self.get_instance_page_size(os_conn, vm)
            assert act_size == param['size'], (
                "Unexpected package size. Should be {0} instead of {1}".format(
                    param['size'], act_size))
            if param['numa'] is not None:
                host = getattr(vm, 'OS-EXT-SRV-ATTR:host')
                self.check_cpu_for_vm(os_conn, vm, param['numa'], cpus[host])
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms.keys())


@pytest.mark.undestructive
class TestMixedSriovAndNuma(TestBaseNFV):

    flavors_to_create = [
        {'name': 'm1.small.performance',
         'params': {'ram': 2048, 'vcpu': 2, 'disk': 40},
         'keys': {'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:cpu_policy': 'dedicated', 'hw:numa_nodes': 1}}]

    def create_vm(self, os_conn, host, flavor, keypair, vf_port, image):
        vm = os_conn.create_server(
            name='vm', image_id=image, flavor=flavor.id,
            nics=[{'port-id': vf_port}], key_name=keypair.name,
            availability_zone='nova:{}'.format(host))
        return vm

    @pytest.mark.testrail_id('838351')
    def test_vms_connectivity_sriov_numa(self, env, os_conn, sriov_hosts,
                                         aggregate, vf_ports, flavors,
                                         ubuntu_image_id, keypair):
        """This test checks vms connectivity with all features
            Steps:
            1. Create net1 with subnet, router1 with interface to net1
            2. Create vm1 on vf port with m1.small.performance on 1 NUMA-node
            3. Check that vm is on one numa-node
            4. Check Ping 8.8.8.8 from vm1
        """
        hosts = list(set(sriov_hosts) & set(aggregate.hosts))
        if len(hosts) < 1:
            pytest.skip(
                "At least one host is required with SR-IOV and 2 numa nodes")
        vm = self.create_vm(os_conn, hosts[0], flavors[0], keypair,
                            vf_ports[0], ubuntu_image_id)
        cpus = get_cpu_distribition_per_numa_node(env)
        self.check_cpu_for_vm(os_conn, vm, 1, cpus[hosts[0]])
        network_checks.check_ping_from_vm(env, os_conn, vm,
                                          vm_keypair=keypair,
                                          vm_login='ubuntu')

    @pytest.mark.testrail_id('842973')
    def test_vms_connectivity_sriov_numa_after_resize(self, env, os_conn,
                                                      sriov_hosts, aggregate,
                                                      ubuntu_image_id, keypair,
                                                      vf_ports, flavors):
        """This test checks vms between VMs launched on vf port after resizing
            Steps:
            1. Create net1 with subnet, router1 with interface to net1
            2. Create vm1 on vf port with m1.small.performance on 1 NUMA-node
            3. Resize vm1 to m1.medium flavor
            4. Wait and ping 8.8.8.8 from vm1
            5. Resize vm1 to m1.small.performance flavor
            6. Wait and ping 8.8.8.8 from vm1
            7. Resize vm1 to m1.small
            8. Wait and ping 8.8.8.8 from vm1
        """
        hosts = list(set(sriov_hosts) & set(aggregate.hosts))
        if len(hosts) < 1:
            pytest.skip(
                "At least one host is required with SR-IOV and 2 numa nodes")
        m1_cpu_flavor = flavors[0]
        m1_medium = os_conn.nova.flavors.find(name='m1.medium')
        m1_large = os_conn.nova.flavors.find(name='m1.large')

        vm = self.create_vm(os_conn, hosts[0], m1_cpu_flavor, keypair,
                            vf_ports[0], ubuntu_image_id)

        for flavor in [m1_medium, m1_cpu_flavor, m1_large]:
            self.resize(os_conn, vm, flavor)
            network_checks.check_ping_from_vm(
                env, os_conn, vm, vm_keypair=keypair, vm_login='ubuntu')
