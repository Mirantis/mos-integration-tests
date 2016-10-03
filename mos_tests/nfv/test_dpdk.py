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
import time

import pytest

from mos_tests.functions import common
from mos_tests.functions import network_checks
from mos_tests.nfv.base import page_2mb
from mos_tests.nfv.base import TestBaseNFV
from mos_tests.nfv.conftest import computes_configuration


@pytest.mark.check_env_('is_vlan', 'is_kvm')
@pytest.mark.undestructive
class TestDpdk(TestBaseNFV):

    flavors_to_create = [
        {'name': 'm1.small.hpgs',
         'params': {'ram': 512, 'vcpu': 1, 'disk': 1},
         'keys': {'hw:mem_page_size': 2048}}]

    def create_vms(self, os_conn, hosts, networks, flavor, keypair,
                   security_group, vms_param):
        """This method creates vms which are required for dpdk test cases.
        Expected format of vms_param is list of tuples (host, network, volume).
        """
        vms = []
        for i, (host, network, vol) in enumerate(vms_param):
            vm = os_conn.create_server(
                name='vm{}'.format(i), flavor=flavor.id,
                nics=[{'net-id': network}], key_name=keypair.name,
                availability_zone='nova:{}'.format(host),
                security_groups=[security_group.id],
                block_device_mapping=vol,
                wait_for_active=False, wait_for_avaliable=False)
            vms.append(vm)
        os_conn.wait_servers_active(vms)
        os_conn.wait_servers_ssh_ready(vms)
        return vms

    def restart_ovs_on_computes(self, env, os_conn):
        ovs_agent_ids, ovs_conroller_agents = self.get_ovs_agents(env, os_conn)
        os_conn.wait_agents_alive(ovs_agent_ids)
        common.disable_ovs_agents_on_controller(env)
        os_conn.wait_agents_down(ovs_conroller_agents)
        common.restart_ovs_agents_on_computes(env)
        common.enable_ovs_agents_on_controllers(env)
        os_conn.wait_agents_alive(ovs_agent_ids)
        # sleep to make sure that system will be stable after ovs restarting
        time.sleep(30)

    def restart_ovs_on_controllers(self, env, os_conn):
        ovs_agent_ids, ovs_conroller_agents = self.get_ovs_agents(env, os_conn)
        os_conn.wait_agents_alive(ovs_agent_ids)
        common.ban_ovs_agents_controllers(env)
        os_conn.wait_agents_down(ovs_conroller_agents)
        common.clear_ovs_agents_controllers(env)
        common.restart_ovs_agents_on_computes(env)
        os_conn.wait_agents_alive(ovs_agent_ids)
        # sleep to make sure that system will be stable after ovs restarting
        time.sleep(30)

    @pytest.mark.testrail_id('838331')
    def test_base_vms_connectivity(self, env, os_conn, computes_with_dpdk_hp,
                                   networks, keypair, flavors, security_group):
        """This test checks base connectivity between VMs with DPDK. Please
        note we're not able to count DPDK huge pages only, they're added to
        count of 2Mb huge pages.
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Create flavor for huge pages with 512Mb ram, 1 vcpu and 1Gb disk
            3. Launch vm1, vm2, vm3 on compute-1 and vm4 on compute-2, vm1 and
            vm2 in net1, vm3 and vm4 in net2
            4. Check vms connectivity
            5. Check instance page size
            6. Check that neutron port has binding:vif_type = vhostuser
            7. Check that count of 2Mb huge pages is expected for each host
        """
        hosts = computes_with_dpdk_hp
        initial_conf = computes_configuration(env)

        vms_param = [(hosts[0], networks[0], None),
                     (hosts[0], networks[0], None),
                     (hosts[0], networks[1], None),
                     (hosts[1], networks[1], None)]
        vms = self.create_vms(os_conn, hosts, networks, flavors[0], keypair,
                              security_group, vms_param)
        network_checks.check_vm_connectivity(env, os_conn, vm_keypair=keypair)

        for vm in vms:
            self.check_vif_type_for_vm(vm, os_conn)
            act_size = self.get_instance_page_size(os_conn, env)
            assert act_size == page_2mb, (
                "Unexpected package size. Should be {0} instead of {1}".format(
                    page_2mb, act_size))

        final_conf = computes_configuration(env)
        exp_hosts_usage = [(hosts[0], 3), (hosts[1], 1)]
        for (host, nr_2mb) in exp_hosts_usage:
            exp_free_2m = (initial_conf[host][page_2mb]['free'] -
                           nr_2mb * flavors[0].ram * 1024 / page_2mb)
            assert exp_free_2m == final_conf[host][page_2mb]['free']

    @pytest.mark.testrail_id('838335')
    def test_vms_connectivity_after_cold_migration(self, env, os_conn,
                                                   computes_with_dpdk_hp,
                                                   flavors, networks, keypair,
                                                   security_group):
        """This test checks connectivity between VMs with DPDK after cold
        migration. Please note we're not able to count DPDK huge pages only,
        they're added to count of 2Mb huge pages.
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Create flavor for huge pages with 512Mb ram, 1 vcpu and 1Gb disk
            3. Launch vm1, vm2 on compute-1, vm3 - on compute-2, vm1 in net1,
            vm2 and vm3 in net2
            4. Migrate vm1 and check that vm moved to other compute with
            huge pages
            5. Check instance page size
            6. Check that neutron port has binding:vif_type = vhostuser
            7. Check vms connectivity
        """
        hosts = computes_with_dpdk_hp
        vms_param = [(hosts[0], networks[0], None),
                     (hosts[0], networks[1], None),
                     (hosts[1], networks[1], None)]
        vms = self.create_vms(os_conn, hosts, networks, flavors[0], keypair,
                              security_group, vms_param=vms_param)
        network_checks.check_vm_connectivity(env, os_conn, vm_keypair=keypair)

        vm0_new = self.migrate(os_conn, vms[0])
        vm0_host = getattr(os_conn.nova.servers.get(vm0_new),
                           "OS-EXT-SRV-ATTR:host")
        assert vm0_host in hosts, ("Unexpected host {0},"
                                   "should be in {1}".format(vm0_host, hosts))
        assert vm0_host != hosts[0], ("New host is expected instead of {0}"
                                      "after cold migration".format(hosts[0]))

        network_checks.check_vm_connectivity(env, os_conn, vm_keypair=keypair)

    @pytest.mark.testrail_id('838337')
    def test_vms_connectivity_after_live_migration(self, env, os_conn,
                                                   computes_with_dpdk_hp,
                                                   flavors, networks, keypair,
                                                   security_group):
        """This test checks connectivity between VMs with DPDK after live
        migration. Please note we're not able to count DPDK huge pages only,
        they're added to count of 2Mb huge pages.
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Create flavor for huge pages with 512Mb ram, 1 vcpu and 1Gb disk
            3. Launch vm1, vm2 on compute-1, vm3 - on compute-2, vm1 in net1,
            vm2 and vm3 in net2
            4. Live migrate vm1 to compute2
            5. Check instance page size
            6. Check that neutron port has binding:vif_type = vhostuser
            7. Check that count of free 2Mb huge pages is expected one for
            each host
            8. Check vms connectivity
        """
        hosts = computes_with_dpdk_hp
        initial_conf = computes_configuration(env)
        vms_param = [(hosts[0], networks[0], None),
                     (hosts[0], networks[1], None),
                     (hosts[1], networks[1], None)]
        vms = self.create_vms(os_conn, hosts, networks, flavors[0], keypair,
                              security_group, vms_param=vms_param)
        self.live_migrate(os_conn, vms[0], hosts[1])
        network_checks.check_vm_connectivity(env, os_conn, vm_keypair=keypair)

        final_conf = computes_configuration(env)
        exp_hosts_usage = [(hosts[0], 1), (hosts[1], 2)]
        for (host, nr_2mb) in exp_hosts_usage:
            exp_free_2m = (initial_conf[host][page_2mb]['free'] -
                           nr_2mb * flavors[0].ram * 1024 / page_2mb)
            assert exp_free_2m == final_conf[host][page_2mb]['free']

    @pytest.mark.testrail_id('838336')
    def test_vms_connectivity_after_evacuation(self, env, os_conn, volume,
                                               computes_with_dpdk_hp, flavors,
                                               networks, keypair, devops_env,
                                               security_group):
        """This test checks connectivity between VMs with DPDK after
        evacuation. Please note we're not able to count DPDK huge pages only,
        they're added to count of 2Mb huge pages.
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Create flavor for huge pages with 512Mb ram, 1 vcpu and 1Gb disk
            3. Launch vm1 (from not empty volume), vm2 on compute-1,
            vm3 - on compute-2, vm1 in net1, vm2 and vm3 in net2
            4. Kill compute2 and evacuate vm3
            5. Check vms connectivity
            6. Start compute2
            7. Check instance page size
            8. Check that neutron port has binding:vif_type = vhostuser
            9. Check that count of free 2Mb huge pages is expected one for
            each host
        """
        hosts = computes_with_dpdk_hp
        initial_conf = computes_configuration(env)
        vms_param = [(hosts[0], networks[0], {'vda': volume.id}),
                     (hosts[0], networks[1], None),
                     (hosts[1], networks[1], None)]
        vms = self.create_vms(os_conn, hosts, networks, flavors[0], keypair,
                              security_group, vms_param=vms_param)
        network_checks.check_vm_connectivity(env, os_conn, vm_keypair=keypair)

        with self.change_compute_state_to_down(os_conn, devops_env, hosts[1]):
            vm_new = self.evacuate(os_conn, devops_env, vms[2])
            vm_new_host = getattr(os_conn.nova.servers.get(vm_new),
                                  "OS-EXT-SRV-ATTR:host")
            assert vm_new_host in hosts
            assert vm_new_host != hosts[1]
            os_conn.wait_servers_ssh_ready(vms)
            network_checks.check_vm_connectivity(env, os_conn,
                                                 vm_keypair=keypair)

        final_conf = computes_configuration(env)
        exp_hosts_usage = [(hosts[0], 3), (hosts[1], 0)]
        for (host, nr_2mb) in exp_hosts_usage:
            exp_free_2m = (initial_conf[host][page_2mb]['free'] -
                           nr_2mb * flavors[0].ram * 1024 / page_2mb)
            assert exp_free_2m == final_conf[host][page_2mb]['free']

    @pytest.mark.testrail_id('838332')
    def test_vms_connectivity_after_ovs_restart_on_computes(
            self, env, os_conn, computes_with_dpdk_hp, flavors, networks,
            keypair, security_group):
        """This test checks connectivity between VMs with DPDK after ovs
        restart on computes. Please note we're not able to count DPDK huge
        pages only, they're added to count of 2Mb huge pages.
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Create flavor for huge pages with 512Mb ram, 1 vcpu and 1Gb disk
            3. Launch vm1, vm2, vm3 on compute-1 and vm4 on compute-2, vm1 and
            vm2 in net1, vm3 and vm4 in net2
            4. Check that neutron port has binding:vif_type = vhostuser
            5. Check instance page size
            6. Restart ovs on computes
            7. Check vms connectivity after ovs restart
        """

        hosts = computes_with_dpdk_hp
        vms_param = [(hosts[0], networks[0], None),
                     (hosts[0], networks[0], None),
                     (hosts[0], networks[1], None),
                     (hosts[1], networks[1], None)]
        self.create_vms(os_conn, hosts, networks, flavors[0], keypair,
                        security_group, vms_param)

        network_checks.check_vm_connectivity(env, os_conn, vm_keypair=keypair)
        self.restart_ovs_on_computes(env, os_conn)
        network_checks.check_vm_connectivity(env, os_conn, vm_keypair=keypair)

    @pytest.mark.testrail_id('838333', restart_point='computes')
    @pytest.mark.testrail_id('838334', restart_point='controllers')
    @pytest.mark.parametrize('restart_point',
                             ['computes', 'controllers'],
                             ids=['computes', 'controllers'])
    def test_ssh_connection_after_ovs_restart(self, env, os_conn,
                                              computes_with_dpdk_hp, flavors,
                                              networks, security_group,
                                              keypair, restart_point):
        """This test checks ssh connection between VMs with DPDK after ovs
        restart on computes/controllers.
            Steps:
            1. Create net1 with subnet, net2 with subnet and  router1 with
            interfaces to both nets
            2. Create flavor for huge pages with 512Mb ram, 1 vcpu and 1Gb disk
            3. Launch vm1, vm2, vm3 on compute-1 and vm4 on compute-2, vm1 and
            vm2 in net1, vm3 and vm4 in net2
            4. Check that neutron port has binding:vif_type = vhostuser
            5. Check instance page size
            6. Open ssh connection to vm1 and vm4
            7. Restart ovs on computes/controllers
            8. Check that both ssh connections are still alive
            9. Check vms connectivity
        """
        hosts = computes_with_dpdk_hp
        vms_param = [(hosts[0], networks[0], None),
                     (hosts[0], networks[0], None),
                     (hosts[0], networks[1], None),
                     (hosts[1], networks[1], None)]
        vms = self.create_vms(os_conn, hosts, networks, flavors[0], keypair,
                              security_group, vms_param)

        vm1_remote = os_conn.ssh_to_instance(env, vms[0], keypair)
        vm4_remote = os_conn.ssh_to_instance(env, vms[3], keypair)

        with vm1_remote, vm4_remote:
            if restart_point == 'computes':
                self.restart_ovs_on_computes(env, os_conn)
            elif restart_point == 'controllers':
                self.restart_ovs_on_controllers(env, os_conn)
            vm1_remote.check_call("uname")
            vm4_remote.check_call("uname")
        network_checks.check_vm_connectivity(env, os_conn, vm_keypair=keypair)
