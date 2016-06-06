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

from mos_tests.functions import common
from mos_tests.nfv.base import TestBaseNFV


logger = logging.getLogger(__name__)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_vlan', 'has_2_or_more_computes')
class TestSRIOV(TestBaseNFV):

    @pytest.yield_fixture()
    def ports(self, os_conn, security_group, networks):
        nets = {}
        for net in networks:
            ovs_ports = []
            vf_ports = []
            for i in range(2):
                ovs_port = os_conn.neutron.create_port(
                    {'port': {'network_id': net,
                              'name': 'ovs-port{}'.format(i),
                              'security_groups': [security_group.id]}})

                vf_port = os_conn.neutron.create_port(
                    {'port': {'network_id': net,
                              'name': 'sriov-port{}'.format(i),
                              'binding:vnic_type': 'direct',
                              'device_owner': 'nova-compute',
                              'security_groups': [security_group.id]}})
                ovs_ports.append(ovs_port['port']['id'])
                vf_ports.append(vf_port['port']['id'])
            nets[net] = {'ovs_ports': ovs_ports, 'vf_ports': vf_ports}
        yield nets
        for ports in nets.values():
            for i in range(2):
                os_conn.neutron.delete_port(ports['ovs_ports'][i])
                os_conn.neutron.delete_port(ports['vf_ports'][i])

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
        vm_distribution = [(sriov_hosts[0], ports[networks[0]]['vf_ports'][0]),
                           (sriov_hosts[0], ports[networks[0]]['vf_ports'][1]),
                           (sriov_hosts[1], ports[networks[1]]['vf_ports'][0]),
                           (sriov_hosts[1], ports[networks[1]]['vf_ports'][1])]
        for i, (host, vf_port) in enumerate(vm_distribution, 1):

            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                key_name=keypair.name, flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}], wait_for_avaliable=False)
            vms.append(vm)

        floating_ip = os_conn.nova.floating_ips.create()
        vms[0].add_floating_ip(floating_ip)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)

    @pytest.mark.testrail_id('838342')
    def test_connectivity_on_vf_and_ovs_ports_one_time(
            self, os_conn, env, ubuntu_image_id, keypair, ports, sriov_hosts):
        """This test checks vms connectivity for vms launched on vf ports
        and on ovs ports one time
            Steps:
            1. Create net1 with subnet, net2 with subnet
            and router1 with interfaces to both nets
            2. Create vf ports on net1 and net2
            3. Create ovs ports on net1 and net2
            4. Launch instances vm1 and vm2 on compute-1 on vf and ovs ports in
            net1 with m1.small flavor and ubuntu image
            5. Launch instance vm3 and vm4 on compute-2 on vf and ovs ports in
            net2 with m1.small flavor and ubuntu image
            6. Add a floating ip to the vm1
            7. Check vms connectivity
        """
        networks = ports.keys()
        flavor = os_conn.nova.flavors.find(name='m1.small')
        ips = []
        vms = []
        vm_distribution = [(sriov_hosts[0], ports[networks[0]]['vf_ports'][0],
                            ports[networks[0]]['ovs_ports'][0]),
                           (sriov_hosts[0], ports[networks[0]]['vf_ports'][1],
                            ports[networks[0]]['ovs_ports'][1]),
                           (sriov_hosts[1], ports[networks[1]]['vf_ports'][0],
                            ports[networks[1]]['ovs_ports'][0]),
                           (sriov_hosts[1], ports[networks[1]]['vf_ports'][1],
                            ports[networks[1]]['ovs_ports'][1])]
        for i, (host, vf_port, ovs_port) in enumerate(vm_distribution, 1):

            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                key_name=keypair.name, flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}, {'port-id': ovs_port}],
                wait_for_avaliable=False)
            vms.append(vm)
            ip_vf = self.get_port_ips(os_conn, vf_port)[0]
            ips.append(ip_vf)
        floating_ip = os_conn.nova.floating_ips.create()
        vms[0].add_floating_ip(floating_ip)
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms,
                                          inactive_ips=ips)

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
        vm_distribution = [(sriov_hosts[0], ports[networks[0]]['vf_ports'][0]),
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
            nics=[{'port-id': ports[networks[0]]['vf_ports'][0]},
                  {'port-id': ports[networks[0]]['ovs_ports'][0]}],
            wait_for_avaliable=False)
        vms = [vm_1]
        vm_distribution = [(sriov_hosts[0], ports[networks[0]]['vf_ports'][1]),
                           (sriov_hosts[0], ports[networks[1]]['vf_ports'][0]),
                           (sriov_hosts[1], ports[networks[1]]['vf_ports'][1])]
        for i, (host, vf_port) in enumerate(vm_distribution, 2):
            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                key_name=keypair.name, flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}], wait_for_avaliable=False)
            vms.append(vm)
        ip_vf_1 = self.get_port_ips(
            os_conn, ports[networks[0]]['vf_ports'][0])[0]
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms,
                                          inactive_ips=[ip_vf_1])

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
        vm_distribution = [(sriov_hosts[0], ports[networks[0]]['vf_ports'][0]),
                           (sriov_hosts[1], ports[networks[1]]['vf_ports'][0])]
        for i, (host, vf_port) in enumerate(vm_distribution, 1):
            vm = os_conn.create_server(
                name='vm{}'.format(i), image_id=ubuntu_image_id,
                key_name=keypair.name, flavor=flavor.id,
                availability_zone='nova:{}'.format(host),
                nics=[{'port-id': vf_port}],
                wait_for_avaliable=False)
            vms.append(vm)
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
            nics=[{'port-id': vf_port}], wait_for_avaliable=False)
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
        vm_distribution = [(sriov_hosts[0], ports[networks[0]]['vf_ports'][0]),
                           (sriov_hosts[1], ports[networks[1]]['vf_ports'][0])]
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
        self.check_vm_connectivity_ubuntu(env, os_conn, keypair, vms)
