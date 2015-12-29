#    Copyright 2015 Mirantis, Inc.
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

from collections import defaultdict
import logging
import time

import pytest
from waiting import wait

from mos_tests.environment.devops_client import DevopsClient
from mos_tests.neutron.python_tests import base


logger = logging.getLogger(__name__)


@pytest.mark.check_env_('is_dvr')
@pytest.mark.usefixtures("setup")
class TestDVRBase(base.TestBase):
    """DVR specific test base class"""

    @pytest.fixture
    def variables(self, init):
        """Init Openstack variables"""
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        exist_networks = self.os_conn.list_networks()['networks']
        self.ext_network = [x for x in exist_networks
                            if x.get('router:external')][0]
        self.hosts = self.zone.hosts.keys()

    def reset_computes(self, hostnames, env_name):

        def get_hypervisors():
            return [x for x in self.os_conn.nova.hypervisors.list()
                    if x.hypervisor_hostname in hostnames]

        node_states = defaultdict(list)

        def is_nodes_started():
            for hypervisor in get_hypervisors():
                state = hypervisor.state
                prev_states = node_states[hypervisor.hypervisor_hostname]
                if len(prev_states) == 0 or state != prev_states[-1]:
                    prev_states.append(state)

            return all(x[-2:] == ['down', 'up'] for x in node_states.values())

        logger.info('Resetting computes {}'.format(hostnames))
        for hostname in hostnames:
            node = self.env.find_node_by_fqdn(hostname)
            devops_node = DevopsClient.get_node_by_mac(env_name=env_name,
                                                       mac=node.data['mac'])
            devops_node.reset()

        wait(is_nodes_started, timeout_seconds=10 * 60)

    def find_snat_controller(self, excluded=()):
        """Find controller with SNAT service.

        :param excluded: excluded nodes fqdns
        :returns: controller node with SNAT
        """
        all_controllers = self.env.get_nodes_by_role('controller')
        controller_with_snat = None
        for controller in all_controllers:
            if controller.data['fqdn'] in excluded:
                continue
            with controller.ssh() as remote:
                cmd = 'ip net | grep snat'
                res = remote.execute(cmd)
                if res['exit_code'] == 0:
                    controller_with_snat = controller
                    break
        return controller_with_snat


@pytest.mark.check_env_('has_1_or_more_computes')
class TestDVR(TestDVRBase):
    """DVR specific test cases"""

    def _prepare_openstack_env(self, distributed_router=True,
                               assign_floating_ip=True):
        """Prepare OpenStack for scenarios run


        Steps:
            1. Revert snapshot with neutron cluster
            2. Create network net01, subnet net01_subnet
            3. Create router with gateway to external net and
               interface with net01
            4. Launch instance
            5. Associate floating IP if needed
        """
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        net, subnet = self.create_internal_network_with_subnet(1)
        router = self.os_conn.create_router(name='router01',
                                            distributed=distributed_router)
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])

        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])

        self.server = self.os_conn.create_server(
            name='server01',
            availability_zone=self.zone.zoneName,
            key_name=self.instance_keypair.name,
            nics=[{'net-id': net['network']['id']}],
            security_groups=[self.security_group.id])

        if assign_floating_ip:
            self.os_conn.assign_floating_ip(self.server)

    @pytest.mark.parametrize('floating_ip', (True, False),
                             ids=('with floating', 'without floating'))
    @pytest.mark.parametrize('dvr_router', (True, False),
                             ids=('distributed router', 'centralized_router'))
    def test_north_south_connectivity(self, floating_ip, dvr_router):
        """Check North-South connectivity

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with external network and
                router type `dvr_router`
            3. Add interfaces to the router01 with net01__subnet
            4. Boot vm_1 in the net01
            5. Add floating ip if case of `floating_ip` arg is True
            6. Go to the vm_1
            7. Ping 8.8.8.8
        """
        self._prepare_openstack_env(distributed_router=dvr_router,
                                    assign_floating_ip=floating_ip)

        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair)

    def test_connectivity_after_reset_compute(self, env_name):
        """Check North-South connectivity with floatingIP after reset compute

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with external network and
                router type Distributed
            3. Add interfaces to the router01 with net01__subnet
            4. Boot vm_1 in the net01
            5. Associate floating IP
            6. Go to the vm_1 with ssh and floating IP
            7. Reset compute where vm resides and wait when it's starting
            8. Go to the vm_1 with ssh and floating IP
            9. Ping 8.8.8.8
        """
        self._prepare_openstack_env()

        with self.os_conn.ssh_to_instance(self.env, self.server,
                                          self.instance_keypair) as remote:
            remote.check_call('uname -a')

        # reset compute
        compute_hostname = getattr(self.server, 'OS-EXT-SRV-ATTR:host')
        self.reset_computes([compute_hostname], env_name)

        time.sleep(60)

        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair)

    def test_shutdown_snat_controller(self, env_name):
        """Shutdown controller with SNAT-namespace and check it reschedules.

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with external network and
                router type Distributed
            3. Add interfaces to the router01 with net01__subnet
            4. Boot vm_1 in the net01
            5. Go to the vm_1 and ping 8.8.8.8
            6. Find controller with SNAT-namespace
               and kill this controller with virsh:
               ``ip net | grep snat`` on all controllers
               ``virsh destroy <controller_with_snat>``
            7. Check SNAT moved to another
            8. Go to the vm_1 and ping 8.8.8.8

        Duration 10m

        """
        self._prepare_openstack_env()
        self.check_ping_from_cirros(self.server)
        # Get controller with SNAT and destroy it
        controller_with_snat = self.find_snat_controller()
        logger.info('Destroying controller with SNAT: {}'.format(
            controller_with_snat.data['fqdn']))
        devops_node = DevopsClient.get_node_by_mac(
            env_name=env_name, mac=controller_with_snat.data['mac'])
        self.env.destroy_nodes([devops_node])
        # Wait for SNAT reschedule
        wait_msg = "Waiting for snat is rescheduled"
        new_controller_with_snat = wait(
            lambda: self.find_snat_controller(
                excluded=[controller_with_snat.data['fqdn']]),
            timeout_seconds=60 * 3,
            sleep_seconds=(1, 60, 5),
            waiting_for=wait_msg)
        # Check external ping and proper SNAT rescheduling
        self.check_ping_from_cirros(self.server)
        assert (
            controller_with_snat.data['fqdn'] !=
            new_controller_with_snat.data['fqdn'])


def shut_down_br_ex_on_controllers(self):
        """Shut down br-ex for all controllers"""
        controllers = self.env.get_nodes_by_role('controller')
        for node in controllers:
            with node.ssh() as remote:
                res = remote.execute('ip link set br-ex down')
                assert 0 == res['exit_code'], \
                    ('Shut-downing br-ex is not successful, exit code {0},'
                     'stdout {1}, stderr {2}'.format(res['exit_code'],
                                                     res['stdout'],
                                                     res['stderr']))

    def test_north_south_floating_ip_shut_down_br_ex_on_controllers(
            self, prepare_openstack):
        """Check North-South connectivity with floatingIP after shut-downing
         br-ex on all controllers

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with external network and
                router type Distributed
            3. Add interfaces to the router01 with net01__subnet
            4. Boot vm_1 in the net01
            5. Associate floating IP
            6. Go to the vm_1 with ssh and floating IP
            7. Shut down br-ex on all controllers
            8. Go to the vm_1 with ssh and floating IP
            9. Ping 8.8.8.8

        Duration 10m

        """
        ip = self.os_conn.assign_floating_ip(
            self.server, use_neutron=True)["floating_ip_address"]

        self.check_ping_from_vm_with_ip(ip, vm_keypair=self.instance_keypair,
                                        ping_count=10, vm_login='cirros')

        self.shut_down_br_ex_on_controllers()

        self.check_ping_from_vm_with_ip(ip, vm_keypair=self.instance_keypair,
                                        ping_count=10, vm_login='cirros')

    def test_north_south_floating_ip_ban_clear_l3_agent_on_compute(
            self, prepare_openstack):
        """Check North-South connectivity with floatingIP after ban and
        clear l3-agent on compute

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with external network and
                router type Distributed
            3. Add interfaces to the router01 with net01__subnet
            4. Boot vm_1 in the net01
            5. Associate floating IP
            6. Go to the vm_1 with ssh and floating IP
            7. Ping 8.8.8.8
            8. Ban l3-agent on the compute with vm_1: service l3-agent stop
            9. Wait 15 seconds
            10. Clear this l3-agent: service l3-agent stop
            11. Go to vm_1 with ssh and floating IP
            12. Ping 8.8.8.8

        Duration 10m

        """
        ip = self.os_conn.assign_floating_ip(
            self.server, use_neutron=True)["floating_ip_address"]

        self.check_ping_from_vm_with_ip(ip, vm_keypair=self.instance_keypair,
                                        ping_count=10, vm_login='cirros')

        compute = self.env.find_node_by_fqdn(self.hosts[0])
        with compute.ssh() as remote:
            remote.check_call('service neutron-l3-agent stop')

        time.sleep(15)

        # Clear l3 agent
        with compute.ssh() as remote:
            remote.check_call('service neutron-l3-agent start')

        self.check_ping_from_vm_with_ip(ip, vm_keypair=self.instance_keypair,
                                        ping_count=10, vm_login='cirros')

@pytest.mark.check_env_('has_2_or_more_computes')
class TestDVRWestEastConnectivity(TestDVRBase):
    """Test DVR west-east routing"""

    @pytest.fixture
    def prepare_openstack(self, variables):
        """
        Prepare OpenStack for some scenarios run

        Steps:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed
                and with gateway to external network
            4. Add interfaces to the router01_02
                with net01_subnet and net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on different compute
            7. Add rules for ping
        """
        # Create router
        router = self.os_conn.create_router(name="router01", distributed=True)
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])
        # Create network and instance
        self.compute_nodes = self.hosts[:2]
        for i, compute_node in enumerate(self.compute_nodes, 1):
            net, subnet = self.create_internal_network_with_subnet(suffix=i)
            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(self.zone.zoneName,
                                                 compute_node),
                key_name=self.instance_keypair.name,
                nics=[{'net-id': net['network']['id']}],
                security_groups=[self.security_group.id])

        self.server1 = self.os_conn.nova.servers.find(name="server01")
        self.server1_ip = self.os_conn.get_nova_instance_ips(
            self.server1).values()[0]
        self.server2 = self.os_conn.nova.servers.find(name="server02")
        self.server2_ip = self.os_conn.get_nova_instance_ips(
            self.server2).values()[0]

    def test_routing(self, prepare_openstack):
        """Check connectivity to East-West-Routing

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed
                and with gateway to external network
            4. Add interfaces to the router01_02
                with net01_subnet and net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on different compute
            7. Add rules for ping
            8. Go to the vm_1
            9. Ping vm_2
        """
        self.check_ping_from_vm(vm=self.server1,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server2_ip)

    def test_routing_after_ban_and_clear_l3_agent(self, prepare_openstack):
        """Check West-East-Routing connectivity with floatingIP after ban
            and clear l3-agent on compute

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed and
                with gateway to external network
            4. Add interfaces to the router01_02 with net01_subnet
                and net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on different compute
            7. Ban l3-agent on the compute with vm_1: service l3-agent stop
            8. Wait 15 seconds
            9. Clear this l3-agent: service l3-agent stop
            10. Go to vm_1
            11. Ping vm_2 with internal IP
        """
        # Ban l3 agent
        compute1 = self.env.find_node_by_fqdn(self.compute_nodes[0])
        with compute1.ssh() as remote:
            remote.check_call('service neutron-l3-agent stop')

        time.sleep(15)

        # Clear l3 agent
        with compute1.ssh() as remote:
            remote.check_call('service neutron-l3-agent start')

        self.check_ping_from_vm(vm=self.server1,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server2_ip)

    def test_routing_after_reset_computes(self, prepare_openstack, env_name):
        """Check East-West connectivity after reset compute nodes

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed and
                with gateway to external network
            4. Add interfaces to the router01_02 with net01_subnet
                and net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on different compute
            7. Go to vm_1 and ping vm_2
            8. Reset computers on which vm_1 and vm_2 are
            9. Wait some time while computers are resetting
            10. Go to vm_2 and ping vm_1
        """
        self.check_ping_from_vm(vm=self.server1,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server2_ip)

        self.reset_computes(self.compute_nodes, env_name)

        time.sleep(60)
        # Check ping after reset
        self.check_ping_from_vm(vm=self.server2,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server1_ip)

    @pytest.mark.check_env_('is_ha')
    def test_east_west_connectivity_after_destroy_controller(
            self, prepare_openstack, env_name):
        """Check East-West connectivity after destroy controller

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed and
            with gateway to external network
            4. Add interfaces to the router01_02 with net01_subnet and
                net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02
            7. Check that VMs are on the different computes (otherwise migrate
                one of them to another compute: nova migrate <your_vm>)
            8. Go to the vm_1
            9. Ping vm_2
            10. Destroy one controller
            11. Go to the vm_2 with internal ip from namespace on compute
            12. Ping vm_1 with internal IP

        Duration 10m

        """
        self.check_ping_from_vm(vm=self.server1,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server2_ip)

        # destroy controller
        controller = self.env.get_nodes_by_role('controller')[0]
        devops_node = DevopsClient.get_node_by_mac(env_name=env_name,
                                                   mac=controller.data['mac'])
        self.env.destroy_nodes([devops_node])

        self.check_ping_from_vm(vm=self.server2,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server1_ip)

    def test_east_west_connectivity_instances_on_the_same_host(
            self, variables):
        """Check East-West connectivity with instances on the same host

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed and
                with gateway to external network
            4. Add interfaces to the router01_02 with net01_subnet
                and net02_subnet
            5. Boot vm_1 in the net01 (with
                --availability-zone nova:node-i.domain.tld
                parameter for command nova boot)
            6. Boot vm_2 in the net02 on the same node-compute
            7. Check that VMs are on the same computes
                (otherwise migrate one of them to another compute:
                nova migrate <your_vm>)
            8. Go to the vm_1
            9. Ping vm_2

        Duration 10m

        """
        # Create router
        router = self.os_conn.create_router(name="router01", distributed=True)
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])
        # Create network and instance
        compute_name = self.hosts[0]

        for i in xrange(1, 3):
            net, subnet = self.create_internal_network_with_subnet(suffix=i)
            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(self.zone.zoneName,
                                                 compute_name),
                key_name=self.instance_keypair.name,
                nics=[{'net-id': net['network']['id']}],
                security_groups=[self.security_group.id])

        server1 = self.os_conn.nova.servers.find(name="server01")

        server2_ip = self.os_conn.get_nova_instance_ips(
            self.os_conn.nova.servers.find(name="server02")).values()[0]

        self.check_ping_from_vm(vm=server1,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=server2_ip)


@pytest.mark.check_env_('has_2_or_more_computes')
class TestDVREastWestConnectivity(TestDVRBase):
    """Test DVR east-west connectivity"""

    @pytest.fixture
    def prepare_openstack(self, variables):
        # Create router
        router = self.os_conn.create_router(name="router01")
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])
        # Create network and instance
        self.compute_nodes = self.zone.hosts.keys()[:2]
        for i, compute_node in enumerate(self.compute_nodes, 1):
            net, subnet = self.create_internal_network_with_subnet(suffix=i)
            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(self.zone.zoneName,
                                                 compute_node),
                key_name=self.instance_keypair.name,
                nics=[{'net-id': net['network']['id']}],
                security_groups=[self.security_group.id])

        self.server1 = self.os_conn.nova.servers.find(name="server01")
        self.server1_ip = self.os_conn.get_nova_instance_ips(
            self.server1).values()[0]
        self.server2 = self.os_conn.nova.servers.find(name="server02")
        self.server2_ip = self.os_conn.get_nova_instance_ips(
            self.server2).values()[0]

    def test_routing_east_west(self, prepare_openstack):
        """Check connectivity to East-West-Routing

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create centralized router01_02 with gateway to external network
            4. Add interfaces to the router01_02
                with net01_subnet and net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on different compute
            7. Add rules for ping
            8. Go to the vm_1
            9. Ping vm_2
        """
        self.check_ping_from_vm(vm=self.server1,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server2_ip)
