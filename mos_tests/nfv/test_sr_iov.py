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
from mos_tests.functions import common
from mos_tests.functions.common import wait
from mos_tests.nfv.base import page_2mb
from mos_tests.nfv.base import TestBaseNFV
from mos_tests.nfv.conftest import get_cpu_distribition_per_numa_node
from mos_tests.nfv.conftest import get_hp_distribution_per_numa_node

logger = logging.getLogger(__name__)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_vlan', 'has_2_or_more_computes')
class TestSRIOV(TestBaseNFV):

    @pytest.yield_fixture()
    def ports(self, os_conn, security_group, networks):
        """Create ports
        :return: like following:
        : {
        : u'33741159-7e75-4084-b530-3027757d9115':
        :     {'ovs_ports': [u'940340a4-0734-430f-b6b1-72c2167fd600',
        :                    u'31272cc4-39f1-48c9-bcb7-ff2a0b7c7679'],
        :      'vf_ports': {'direct':
        :                      [u'3f5aa3ef-88d3-4d4d-9653-4e2bcbf7c5bd',
        :                       u'4dcf9ec5-02e1-4db0-a26d-79bd050e5aee'],
        :                   'macvtap':
        :                      [u'07b993ac-21fe-4869-bf6a-0c9e977f3aa3',
        :                       u'11244e96-2e5a-4b06-8b83-0e0a572b0cc8']}},
        : u'd2565b31-2e73-4cc7-8fba-d0b8ca5818a7':
        :     {'ovs_ports': [u'61f748df-c9ea-431b-bd8c-fdfe74962351',
        :                  u'b101f700-cc57-42c6-99f4-b449450a8b8c'],
        :      'vf_ports': {'direct':
        :                      [u'dd15ca36-32b2-45dd-9879-455c12ae3138',
        :                       u'635ab81a-a6c3-441d-89ad-ca99e5bfbd7f'],
        :                   'macvtap':
        :                      [u'e5bbf7ab-5a31-4160-aae9-ee533fc9862d',
        :                       u'259042c1-c407-45b7-91fa-9f05fcf73e23']}}
        : }
        """
        nets = {}
        vnic_types = ['direct', 'macvtap']
        for net in networks:
            ovs_ports = []
            vf_ports = {}
            for i in range(2):
                ovs_port = os_conn.neutron.create_port(
                    {'port': {'network_id': net,
                              'name': 'ovs-port{}'.format(i),
                              'security_groups': [security_group.id]}})
                ovs_ports.append(ovs_port['port']['id'])

                for vnic_type in vnic_types:
                    vf_port = os_conn.neutron.create_port(
                        {'port': {'network_id': net,
                                  'name': 'sriov-port-{}-{}'.format(vnic_type,
                                                                    i),
                                  'binding:vnic_type': vnic_type,
                                  'device_owner': 'nova-compute',
                                  'security_groups': [security_group.id]}})
                    if vnic_type not in vf_ports.keys():
                        vf_ports[vnic_type] = []
                    vf_ports[vnic_type].append(vf_port['port']['id'])

            nets[net] = {'ovs_ports': ovs_ports, 'vf_ports': vf_ports}
        yield nets
        for ports in nets.values():
            for i in range(2):
                os_conn.neutron.delete_port(ports['ovs_ports'][i])
                for vnic_type in vnic_types:
                    os_conn.neutron.delete_port(
                        ports['vf_ports'][vnic_type][i])

    @pytest.yield_fixture()
    def vf_port(self, os_conn, security_group):
        router = os_conn.create_router(name="router01")['router']
        ext_net = os_conn.ext_network
        os_conn.router_gateway_add(router_id=router['id'],
                                   network_id=ext_net['id'])
        net = os_conn.add_net(router['id'])
        vf_port = os_conn.neutron.create_port(
            {'port': {'network_id': net, 'name': 'sriov-port',
                      'binding:vnic_type': 'direct',
                      'device_owner': 'nova-compute',
                      'security_groups': [security_group.id]}})
        vf_port_id = vf_port['port']['id']
        yield vf_port_id
        os_conn.neutron.delete_port(vf_port_id)
        os_conn.delete_router(router['id'])
        os_conn.delete_network(net)

    @staticmethod
    def add_interface_to_vm(os_conn, env, vm, keypair):
        """Add and activate eth1 interface for vm when we use 2 ips"""
        cmd = (r'echo -e "auto eth1\niface eth1 inet dhcp" | '
               r'sudo dd of={file} && '
               r'sudo ifup eth1 ;').format(
                   file='/etc/network/interfaces.d/eth1.cfg')
        vm.get()
        vm_ips = [ip['addr'] for n, ips in vm.addresses.items()
                  for ip in ips]
        for vm_ip in vm_ips:
            try:
                with os_conn.ssh_to_instance(
                        env, vm, vm_keypair=keypair, username='ubuntu',
                        password='ubuntu', vm_ip=vm_ip) as remote:
                    remote.check_call(cmd)
            except Exception:
                logger.info(("Ip {0} is not active for {1}. "
                             "Try next ip...").format(vm_ip, vm.name))
                continue
            logger.info("Ip {0} is active for {1}.".format(vm_ip, vm.name))
            break
        else:
            raise Exception("No active ips for {}.".format(vm.name))

    @pytest.mark.testrail_id('838341')
    def test_connectivity_on_vf_ports(
            self, os_conn, env, ubuntu_image_id, keypair, ports, sriov_hosts):
        """This test checks vms connectivity for vms launched on vf ports
            Steps:
            1. Create net1 with subnet, net2 with subnet and router1 with
            interfaces to both nets
            2. Create vf ports on net1 and net2
            3. Launch instances vm1 and vm2 on compute-1 with vf ports in net1,
            m1.small flavor and ubuntu image
            4. Launch instance vm3 and vm4 on compute-2 with vf port in net2,
            m1.small flavor and ubuntu image
            5. Add a floating ip to the vm1
            6. Check vms connectivity
        """
        networks = ports.keys()
        flavor = os_conn.nova.flavors.find(name='m1.small')
        vms = []
        vm_distribution = [
            (sriov_hosts[0], ports[networks[0]]['vf_ports']['direct'][0]),
            (sriov_hosts[0], ports[networks[0]]['vf_ports']['direct'][1]),
            (sriov_hosts[1], ports[networks[1]]['vf_ports']['direct'][0]),
            (sriov_hosts[1], ports[networks[1]]['vf_ports']['direct'][1])]
        for i, (host, vf_port) in enumerate(vm_distribution, 1):

            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                key_name=keypair.name, flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}], wait_for_avaliable=False)
            vms.append(vm)

        floating_ip = os_conn.nova.floating_ips.create()
        vms[0].add_floating_ip(floating_ip)
        os_conn.wait_servers_ssh_ready(vms)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)

    @pytest.mark.testrail_id('838343')
    def test_connectivity_on_vf_or_ovs_ports(
            self, os_conn, env, ubuntu_image_id, keypair, ports, sriov_hosts):
        """This test checks vms connectivity for vms launched on vf ports
        or on ovs ports
            Steps:
            1. Create net1 with subnet, net2 with subnet
            and router1 with interfaces to both nets
            2. Create vf port on net1
            3. Create ovs ports on net1 and net2
            4. Launch instances vm1 on compute-1 with vf port(net1),
            m1.small flavor and ubuntu image
            5. Launch instances vm2 on compute-2(without sr-iov) with ovs
            port(net1),
            m1.small flavor and ubuntu image
            6. Launch instance vm3 on compute-3(without sr-iov) with ovs
            port(net2),
            m1.small flavor and ubuntu image
            7. Add a floating ip to the vm1
            8. Check vms connectivity
        """
        computes_list = os_conn.env.get_nodes_by_role('compute')
        hosts = [compute.data['fqdn'] for compute in computes_list if
                 compute not in sriov_hosts]
        networks = ports.keys()
        flavor = os_conn.nova.flavors.find(name='m1.small')
        vms = []
        vm_distribution = [
            (sriov_hosts[0], ports[networks[0]]['vf_ports']['direct'][0]),
            (hosts[0], ports[networks[0]]['ovs_ports'][0]),
            (hosts[1], ports[networks[1]]['ovs_ports'][0])]
        for i, (host, port) in enumerate(vm_distribution, 1):
            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                key_name=keypair.name, flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': port}], wait_for_avaliable=False)
            vms.append(vm)

        floating_ip = os_conn.nova.floating_ips.create()
        vms[0].add_floating_ip(floating_ip)
        os_conn.wait_servers_ssh_ready(vms)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)

    @pytest.mark.testrail_id('838344')
    def test_connectivity_on_vf_and_ovs_ports(
            self, os_conn, env, ubuntu_image_id, keypair, ports, sriov_hosts):
        """This test checks vms connectivity for vm launched on vf and ovs
        ports and vms launched on vf ports
            Steps:
            1. Create net1 with subnet, net2 with subnet and router1 with
            interfaces to both nets
            2. Create vf ports on net1 and net2
            3. Create ovs ports on net1
            4. Launch instance vm1 on compute-1 with vf and ovs ports in net1,
            m1.small flavor and ubuntu image
            5. Launch instance vm2 on compute-1 with vf port in net1, m1.small
            flavor and ubuntu image
            6. Launch instance vm3 on compute-1 with vf port in net2, m1.small
            flavor and ubuntu image
            7. Launch instance vm4 on compute-2 with vf port in net2, m1.small
            flavor and ubuntu image
            8. Check vms connectivity
        """
        networks = ports.keys()
        flavor = os_conn.nova.flavors.find(name='m1.small')
        vm_1 = os_conn.create_server(
            name='vm1', image_id=ubuntu_image_id, key_name=keypair.name,
            flavor=flavor.id,
            availability_zone='nova:{}'.format(sriov_hosts[0]),
            nics=[{'port-id': ports[networks[0]]['vf_ports']['direct'][0]},
                  {'port-id': ports[networks[1]]['ovs_ports'][0]}],
            wait_for_avaliable=False)
        self.add_interface_to_vm(os_conn, env, vm_1, keypair)
        vms = [vm_1]

        vm_distribution = [
            (sriov_hosts[0], ports[networks[0]]['vf_ports']['direct'][1]),
            (sriov_hosts[0], ports[networks[1]]['vf_ports']['direct'][0]),
            (sriov_hosts[1], ports[networks[1]]['vf_ports']['direct'][1])]
        for i, (host, vf_port) in enumerate(vm_distribution, 2):
            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                key_name=keypair.name, flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}], wait_for_avaliable=False)
            vms.append(vm)

        os_conn.wait_servers_ssh_ready(vms)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)

    @pytest.mark.check_env_('is_dvr')
    @pytest.mark.testrail_id('838345')
    def test_connectivity_on_vf_port_EW_for_non_DVR_router(
            self, os_conn, env, ubuntu_image_id, keypair, ports, sriov_hosts):
        """This test checks vms connectivity for vms launched on vf ports in
        DVR East-West case for non DVR router
            Steps:
            1. Enable DVR
            2. Create net1 with subnet, net2 with subnet and non dvr router1
            with interfaces to both nets
            3. Create vf ports on net1 and net2
            4. Launch instance vm1 on compute-1 with vf port in net1, m1.small
            flavor and ubuntu image
            5. Launch instance vm2 on compute-2 with vf port in net2, m1.small
            flavor and ubuntu image
            6. Check vms connectivity
        """
        networks = ports.keys()
        flavor = os_conn.nova.flavors.find(name='m1.small')
        vms = []
        vm_distribution = [
            (sriov_hosts[0], ports[networks[0]]['vf_ports']['direct'][0]),
            (sriov_hosts[1], ports[networks[1]]['vf_ports']['direct'][0])]
        for i, (host, vf_port) in enumerate(vm_distribution, 1):
            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                key_name=keypair.name, flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}],
                wait_for_avaliable=False)
            vms.append(vm)

        os_conn.wait_servers_ssh_ready(vms)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)

    @pytest.mark.check_env_('is_dvr')
    @pytest.mark.testrail_id('838346')
    def test_connectivity_on_vf_port_NS_with_floating_non_DVR_router(
            self, os_conn, env, ubuntu_image_id, keypair, vf_port,
            sriov_hosts):
        """This test checks vms connectivity for vm launched on vf port in
        DVR North-South case with floating ip for non DVR router
            Steps:
            1. Enable DVR
            2. Create net1 with subnet in non dvr router1
            3. Create vf port on net1
            4. Launch instance vm1 on compute-1 with vf port in net1, m1.small
            flavor and ubuntu image
            5. Add a floating ip to the vm1
            6. Check vms connectivity
        """
        flavor = os_conn.nova.flavors.find(name='m1.small')

        vm = os_conn.create_server(
            name='vm1', image_id=ubuntu_image_id,
            key_name=keypair.name, flavor=flavor.id,
            availability_zone='nova:{}'.format(sriov_hosts[0]),
            nics=[{'port-id': vf_port}])
        floating_ip = os_conn.nova.floating_ips.create()
        vm.add_floating_ip(floating_ip)

        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, [vm])

    @pytest.mark.check_env_('is_dvr', 'has_2_or_more_controllers')
    @pytest.mark.testrail_id('838348')
    def test_connectivity_on_vf_port_EW_non_DVR_router_after_reschedulling(
            self, os_conn, env, ubuntu_image_id, keypair, ports, sriov_hosts):
        """This test checks vms connectivity for vms launched on vf ports in
        DVR East-West case for non DVR router after manual reschedulling router
            Steps:
            1. Enable DVR
            2. Create net1 with subnet, net2 with subnet and non dvr router1
            with interfaces to both nets
            3. Create vf ports on net1 and net2
            4. Launch instance vm1 on compute-1 with vf port in net1, m1.small
            flavor and ubuntu image
            5. Launch instance vm2 on compute-2 with vf port in net2, m1.small
            flavor and ubuntu image
            6. Check vms connectivity
        """
        networks = ports.keys()
        flavor = os_conn.nova.flavors.find(name='m1.small')
        vms = []
        vm_distribution = [
            (sriov_hosts[0], ports[networks[0]]['vf_ports']['direct'][0]),
            (sriov_hosts[1], ports[networks[1]]['vf_ports']['direct'][0])]
        for i, (host, vf_port) in enumerate(vm_distribution, 1):
            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                key_name=keypair.name, flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}],
                wait_for_avaliable=False)
            vms.append(vm)

        floating_ip = os_conn.nova.floating_ips.create()
        vms[0].add_floating_ip(floating_ip)

        os_conn.wait_servers_ssh_ready(vms)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)
        router_id = os_conn.neutron.list_routers(
            name='router01')['routers'][0]['id']
        computes_list = [compute.data['fqdn'] for compute in
                         os_conn.env.get_nodes_by_role('compute')]
        agent = os_conn.neutron.list_l3_agent_hosting_routers(
            router_id)['agents'][0]
        old_host = agent['host']
        new_l3_agent = [x for x in os_conn.list_l3_agents() if
                        x['host'] != old_host and x['host']
                        not in computes_list][0]
        os_conn.neutron.remove_router_from_l3_agent(router_id=router_id,
                                                    l3_agent=agent['id'])
        os_conn.add_router_to_l3_agent(l3_agent_id=new_l3_agent['id'],
                                       router_id=router_id)
        common.wait(
            lambda: os_conn.neutron.list_l3_agent_hosting_routers(
                router_id)['agents'][0]['alive'],
            timeout_seconds=600,
            waiting_for='router is rescheduled')
        assert old_host != os_conn.neutron.list_l3_agent_hosting_routers(
            router_id)['agents'][0]['host']

        os_conn.wait_servers_ssh_ready(vms)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)

    @pytest.mark.check_env_('is_ceph_enabled')
    @pytest.mark.testrail_id('838350')
    def test_connectivity_on_vf_port_after_evacuation(
            self, os_conn, env, devops_env, ubuntu_image_id, keypair, vf_port,
            sriov_hosts):
        """This test checks vm connectivity for vm launched on vf port after
        evacuation
            Steps:
            1. Enable ceph on all computes
            2. Create network net1 with subnet,
            3. Create router, set gateway and add interface for the network
            4. Create vf port on net1
            5. Launch instance vm1 on compute-1 with vf port in net1, m1.small
            flavor and ubuntu image
            6. Check vm connectivity
            7. Kill compute-1
            8. Evacuate vm1 from compute-1
            9. Check vm connectivity
        """
        flavor = os_conn.nova.flavors.find(name='m1.small')

        vm = os_conn.create_server(
            name='vm1', image_id=ubuntu_image_id,
            key_name=keypair.name, flavor=flavor.id,
            availability_zone='nova:{}'.format(sriov_hosts[0]),
            nics=[{'port-id': vf_port}])

        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, [vm])
        old_hypervisor = [hpr for hpr in os_conn.nova.hypervisors.list() if
                          hpr.hypervisor_hostname == sriov_hosts[0]][0]
        assert old_hypervisor.vcpus_used == flavor.vcpus
        assert old_hypervisor.local_gb_used == flavor.disk

        with self.change_compute_state_to_down(os_conn, devops_env,
                                               sriov_hosts[0]):
            vm_new = self.evacuate(os_conn, devops_env, vm,
                                   host=sriov_hosts[1])
            os_conn.wait_servers_ssh_ready([vm_new])
            self.check_vm_connectivity_ubuntu(env, os_conn, keypair, [vm_new])

        os_conn.wait_hypervisor_be_free(old_hypervisor)
        old_hypervisor.get()
        assert old_hypervisor.vcpus_used == 0
        assert old_hypervisor.local_gb_used == 0

    @pytest.mark.testrail_id('842972')
    def test_connectivity_on_vf_port_after_migration(
            self, os_conn, env, ubuntu_image_id, keypair, vf_port,
            sriov_hosts):
        """This test checks vm connectivity for vm launched on vf port after
        migration
        Bug https://bugs.launchpad.net/fuel/+bug/1564352 will be fixed in 10.0
            Steps:
            1. Create network net1 with subnet,
            2. Create router, set gateway and add interface for the network
            3. Create vf port on net1
            4. Launch instance vm1 on compute-1 with vf port in net1, m1.small
            flavor and ubuntu image
            5. Check vm connectivity
            6. Migrate vm1 from compute-1
            7. Check vm connectivity
        """
        flavor = os_conn.nova.flavors.find(name='m1.small')
        vm = os_conn.create_server(
            name='vm1', image_id=ubuntu_image_id,
            key_name=keypair.name, flavor=flavor.id,
            availability_zone='nova:{}'.format(sriov_hosts[0]),
            nics=[{'port-id': vf_port}])

        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, [vm])
        old_hypervisor = [hpr for hpr in os_conn.nova.hypervisors.list() if
                          hpr.hypervisor_hostname == sriov_hosts[0]][0]
        assert old_hypervisor.vcpus_used == flavor.vcpus
        assert old_hypervisor.local_gb_used == flavor.disk
        vm_new = self.migrate(os_conn, vm)

        os_conn.wait_hypervisor_be_free(old_hypervisor)
        old_hypervisor.get()
        assert old_hypervisor.vcpus_used == 0
        assert old_hypervisor.local_gb_used == 0
        assert sriov_hosts[0] != getattr(vm_new, "OS-EXT-SRV-ATTR:host")
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, [vm_new])

    @pytest.mark.testrail_id('857354')
    def test_connectivity_on_ports_with_vnic_macvtap(
            self, os_conn, env, ubuntu_image_id, keypair, ports, sriov_hosts):
        """Check connectivity between VMs launched on ports
        with vnic-type macvtap.
        Steps:
        1. Create net1 with subnet, net2 with subnet and router1 with
        interfaces to both nets;
        2. Create vf ports=macvtap on net1 and net2;
        3. Launch instances vm1 and vm2 on compute-1 with vf ports=macvtap
        in net1, m1.small flavor and ubuntu image;
        4. Launch instance vm3 and vm4 on compute-2 with vf ports=macvtap
        in net2, m1.small flavor and ubuntu image;
        5. Add a floating ip to the vm1;
        6. Check vms connectivity;
        7. Create vf ports=direct on net2;
        8. Launch instance vm5 on compute-1 with vf ports=direct
        in net2, m1.small flavor and ubuntu image;
        9. Launch instance vm7 on compute-2 with vf ports=direct
        in net2, m1.small flavor and ubuntu image;
        10. Check vms connectivity;
        """
        nets_id = ports.keys()
        flavor = os_conn.nova.flavors.find(name='m1.small')

        # create 4 VMs on 2 diff computes and 2 diff networks with
        # port 'binding:vnic_type' = 'macvtap'
        vm_distribution = [
            (sriov_hosts[0], ports[nets_id[0]]['vf_ports']['macvtap'][0]),
            (sriov_hosts[0], ports[nets_id[0]]['vf_ports']['macvtap'][1]),
            (sriov_hosts[1], ports[nets_id[1]]['vf_ports']['macvtap'][0]),
            (sriov_hosts[1], ports[nets_id[1]]['vf_ports']['macvtap'][1])]
        vms_macvtap = []
        for i, (host, vf_port) in enumerate(vm_distribution, 1):
            vm = os_conn.create_server(
                name='vm_macvtap_{}'.format(i),
                image_id=ubuntu_image_id,
                key_name=keypair.id,
                flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}],
                wait_for_active=False,
                wait_for_avaliable=False)
            vms_macvtap.append(vm)
        os_conn.wait_servers_active(vms_macvtap)

        floating_ip = os_conn.nova.floating_ips.create()
        vms_macvtap[0].add_floating_ip(floating_ip.ip)

        os_conn.wait_servers_ssh_ready(vms_macvtap)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms_macvtap)

        # create 2 VMs on 2 diff computes and 2 diff networks with
        # port 'binding:vnic_type' = 'direct'
        vm_distribution = [
            (sriov_hosts[0], ports[nets_id[1]]['vf_ports']['direct'][0]),
            (sriov_hosts[1], ports[nets_id[1]]['vf_ports']['direct'][1])]
        vms_direct = []
        for i, (host, vf_port) in enumerate(vm_distribution, 1):
            vm = os_conn.create_server(
                name='vm_direct_{}'.format(i),
                image_id=ubuntu_image_id,
                key_name=keypair.id,
                flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}],
                wait_for_active=False,
                wait_for_avaliable=False)
            vms_direct.append(vm)
        os_conn.wait_servers_active(vms_direct)

        vms_to_ping = [vms_macvtap[0]] + vms_direct
        os_conn.wait_servers_ssh_ready(vms_to_ping)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms_to_ping)

    @pytest.mark.testrail_id('857355', port_type='macvtap')
    @pytest.mark.testrail_id('838342', port_type='direct')
    @pytest.mark.parametrize('port_type', ['macvtap', 'direct'])
    def test_connectivity_on_ports_with_vnic_vf_and_ovs(
            self, os_conn, env, ubuntu_image_id, keypair, ports,
            sriov_hosts, port_type):
        """Check connectivity between VMs launched on ports
        with vnic-type macvtap and ovs.

        Steps:
        1. Create net1 with subnet, net2 with subnet and router1 with
        interfaces to both nets;
        2. Create vf ports=macvtap/direct and ovs on net1 and net2;
        3. Launch instances vm1 and vm2 on compute-1 with
        vf ports=macvtap/direct and ovs in net1, m1.small flavor and
        ubuntu image;
        4. Launch instance vm3 and vm4 on compute-2 with
        vf ports=macvtap/direct and ovs in net2, m1.small flavor and
        ubuntu image;
        5. Add a floating ip to vms;
        6. Check vms connectivity;
        """
        nets_id = ports.keys()
        flavor = os_conn.nova.flavors.find(name='m1.small')

        # create 4 VMs on 2 diff computes and 2 diff networks with
        # port 'binding:vnic_type' = 'macvtap'/'direct' and ovs ports
        vm_distribution = [
            (sriov_hosts[0], ports[nets_id[0]]['vf_ports'][port_type][0],
                ports[nets_id[1]]['ovs_ports'][0]),
            (sriov_hosts[0], ports[nets_id[0]]['vf_ports'][port_type][1],
                ports[nets_id[1]]['ovs_ports'][1]),
            (sriov_hosts[1], ports[nets_id[1]]['vf_ports'][port_type][0],
                ports[nets_id[0]]['ovs_ports'][0]),
            (sriov_hosts[1], ports[nets_id[1]]['vf_ports'][port_type][1],
                ports[nets_id[0]]['ovs_ports'][1])]

        vms = []
        for i, (host, vf_port, ovs_port) in enumerate(vm_distribution, 1):
            vm = os_conn.create_server(
                name='vm_{0}_ovs{1}'.format(port_type, i),
                image_id=ubuntu_image_id,
                key_name=keypair.name,
                flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}, {'port-id': ovs_port}],
                wait_for_avaliable=False)
            self.add_interface_to_vm(os_conn, env, vm, keypair)
            vms.append(vm)

        os_conn.wait_servers_ssh_ready(vms)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)

    @pytest.mark.testrail_id('857356')
    def test_connectivity_on_port_with_macvtap_after_migration(
            self, os_conn, env, ubuntu_image_id, keypair, ports, sriov_hosts):
        """This test checks migration for VM launched on port with vnic-type
        macvtap
            Steps:
            1. Create net1 with subnet, net2 with subnet and router1 with
            interfaces to both nets
            2. Create ports with vnic-type macvtap on net1 and net2
            3. Launch instance vm1 on compute-1 with the port in net1, m1.small
            flavor and ubuntu image
            4. Launch instance vm2 on compute-1 with the port in net2, m1.small
            flavor and ubuntu image
            5. Check vm connectivity
            6. Migrate vm1 from compute-1
            7. Check vm connectivity
        """
        networks = ports.keys()
        flavor = os_conn.nova.flavors.find(name='m1.small')
        vms = []
        vm_distribution = [
            (sriov_hosts[0], ports[networks[0]]['vf_ports']['macvtap'][0]),
            (sriov_hosts[0], ports[networks[1]]['vf_ports']['macvtap'][0])]
        for i, (host, port) in enumerate(vm_distribution, 1):
            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                key_name=keypair.name, flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': port}], wait_for_avaliable=False)
            vms.append(vm)
        os_conn.wait_servers_ssh_ready(vms)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)
        old_hypervisor = [hpr for hpr in os_conn.nova.hypervisors.list() if
                          hpr.hypervisor_hostname == sriov_hosts[0]][0]
        assert old_hypervisor.vcpus_used == 2 * flavor.vcpus
        assert old_hypervisor.local_gb_used == 2 * flavor.disk
        vm_new = self.migrate(os_conn, vms[0])

        wait(lambda: old_hypervisor.get() or old_hypervisor.running_vms == 1,
             timeout_seconds=2 * 60,
             waiting_for='hypervisor {0} to have 1 vm'.format(
                 old_hypervisor.hypervisor_hostname))

        old_hypervisor.get()
        assert old_hypervisor.vcpus_used == flavor.vcpus
        assert old_hypervisor.local_gb_used == flavor.disk
        assert sriov_hosts[0] != getattr(vm_new, "OS-EXT-SRV-ATTR:host")
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)


class TestNegativeSRIOV(TestBaseNFV):

    created_flvs = []
    flavors_to_create = [
        {'name': 'm1.small.hpgs',
         'params': {'ram': 2048, 'vcpu': 2, 'disk': 5},
         'keys': {'hw:mem_page_size': 2048}},

        {'name': 'm1.small.performance',
         'params': {'ram': 2048, 'vcpu': 2, 'disk': 5},
         'keys': {'hw:cpu_policy': 'dedicated',
                  'aggregate_instance_extra_specs:pinned': 'true',
                  'hw:numa_nodes': 1}}]

    @pytest.yield_fixture()
    def vf_ports(self, os_conn, networks, security_group):
        ports = []
        for i in range(2):
            vf_port = os_conn.neutron.create_port(
                {'port': {'network_id': networks[0],
                          'name': 'sriov-port{0}'.format(i),
                          'binding:vnic_type': 'macvtap',
                          'device_owner': 'nova-compute',
                          'security_groups': [security_group.id]}})
            ports.append(vf_port['port']['id'])
        yield ports
        for port in ports:
            os_conn.neutron.delete_port(port)

    @pytest.fixture
    def mixed_hosts(self, aggregate, sriov_hosts, computes_with_hp_2mb):
        hosts = set(aggregate.hosts) & set(sriov_hosts) & set(
            computes_with_hp_2mb)
        if len(hosts) < 1:
            pytest.skip("No hosts with all features")
        return list(hosts)

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

    @pytest.mark.testrail_id('857357')
    def test_negative_lack_of_resources_on_pci_device(
            self, os_conn, env, ubuntu_image_id, keypair, mixed_hosts,
            vf_ports, flavors, networks, cleanup):
        """This test checks error state for vm when resources are not enough
            on pci device.

            Steps:
            1. Create network net1 with subnet
            2. Create router, set gateway and add interface for the network
            3. Create flavor for 2Mb huge pages
            4. Create flavor for cpu pinning with hw:numa_nodes=1
            5. Boot vm with the 1st flavor with vf_port on numa without pci
            device (usually it's numa1)
            6. Check that vms are in error state since no pci device found
            7. Redo for the 2nd flavor
        """
        host = mixed_hosts[0]
        cpus = get_cpu_distribition_per_numa_node(env)[host]
        hps = get_hp_distribution_per_numa_node(env)[host]

        # Calculate number of vcpus/huge pages for each numa in order to occupy
        #  all of them. Usually pci device is on numa1 => next step
        # (i.e. remove vm from numa0) allows to get numa with huge pages and
        # cpu pinning, but without sr-iov
        vms = {}

        # we need to order cpus so that numa with more cpus booted at first
        sorted_cpus = sorted(cpus.items(), key=lambda x: len(x[1]),
                             reverse=True)
        for numa, cpu_list in sorted_cpus:
            free_2mb = hps[numa][page_2mb]['free']
            flv = os_conn.nova.flavors.create(name='flavor_{}'.format(numa),
                                              ram=free_2mb * 2, disk=5,
                                              vcpus=len(cpu_list))
            self.created_flvs.append(flv)
            flv.set_keys({'hw:cpu_policy': 'dedicated',
                          'aggregate_instance_extra_specs:pinned': 'true',
                          'hw:numa_nodes': 1,
                          'hw:mem_page_size': page_2mb})

            vm = os_conn.create_server(
                name='vm_to_{0}'.format(numa), image_id=ubuntu_image_id,
                key_name=keypair.name, nics=[{'net-id': networks[0]}],
                availability_zone='nova:{}'.format(host), flavor=flv.id,
                wait_for_avaliable=False)
            nodeset = self.get_nodesets_for_vm(os_conn, vm)[0]
            assert numa == "numa{0}".format(nodeset), (
                "Nodeset used for {0} should be {1}, but it's {2}. "
                "It's critical for this test since pci device is on numa1 only"
                .format(vm, numa, "numa{0}".format(nodeset)))
            vms[numa] = vm

        # Remove vm from numa0
        vms['numa0'].delete()
        os_conn.wait_servers_deleted([vms['numa0']])

        # Boot vms with pci device
        for i, flavor in enumerate(flavors):
            with pytest.raises(InstanceError) as e:
                os_conn.create_server(
                    name='vm', image_id=ubuntu_image_id,
                    key_name=keypair.name, flavor=flavor.id,
                    availability_zone='nova:{}'.format(host),
                    nics=[{'port-id': vf_ports[i]}])
            expected_message = ("Insufficient compute resources: "
                                "Requested instance NUMA topology together "
                                "with requested PCI devices cannot fit the "
                                "given host NUMA topology")
            logger.info("Instance status is error:\n{0}".format(str(e.value)))
            assert expected_message in str(e.value), "Unexpected reason"
