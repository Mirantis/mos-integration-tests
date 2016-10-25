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

from datetime import datetime
import logging
import re
import time
import yaml

from keystoneclient.auth.identity.v2 import Password as KeystonePassword
from neutronclient.common.exceptions import NeutronClientException
import neutronclient.v2_0.client as neutronclient
import pytest

from mos_tests.environment.devops_client import DevopsClient
from mos_tests.environment.ssh import SSHClient
from mos_tests.functions.common import gen_random_resource_name
from mos_tests.functions.common import wait
from mos_tests.neutron.python_tests import base


logger = logging.getLogger(__name__)


@pytest.mark.check_env_('is_dvr')
class TestDVRBase(base.TestBase):
    """DVR specific test base class"""

    @pytest.fixture
    def variables(self, init):
        """Init Openstack variables"""
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        self.hosts = self.zone.hosts.keys()

    def reset_computes(self, hostnames, env_name):

        logger.info('Resetting computes {}'.format(hostnames))
        for hostname in hostnames:
            node = self.env.find_node_by_fqdn(hostname)
            devops_node = DevopsClient.get_node_by_mac(env_name=env_name,
                                                       mac=node.data['mac'])
            devops_node.reset()

        def get_agents_on_hosts():
            agents = self.os_conn.neutron.list_agents()['agents']
            hosts_agents = [x for x in agents if x['host'] in hostnames]
            for agent in hosts_agents:
                agent['updated'] = datetime.strptime(
                    agent['heartbeat_timestamp'], "%Y-%m-%d %H:%M:%S")
            return hosts_agents

        last_updated = max(x['updated'] for x in get_agents_on_hosts())

        def is_neutron_agents_alive():
            computes_agents = get_agents_on_hosts()
            fresh_checked = [x for x in computes_agents
                             if x['updated'] > last_updated]
            alive = [x for x in fresh_checked if x['alive']]
            for agent in fresh_checked:
                state = ['is NOT', 'is'][int(agent['alive'])]
                logger.debug('{agent_type} on {host} {state} alive'.format(
                             state=state, **agent))
            return len(computes_agents) == len(alive)

        def is_nova_hypervisors_alive():
            hypervisors = [x for x in self.os_conn.nova.hypervisors.list()
                           if x.hypervisor_hostname in hostnames]
            for hypervisor in hypervisors:
                logger.debug('hypervisor on {0.hypervisor_hostname} is '
                             '{0.state}'.format(hypervisor))
            return all(x.state == 'up' for x in hypervisors)

        wait(is_neutron_agents_alive, timeout_seconds=10 * 60,
             sleep_seconds=10,
             waiting_for="nodes {0} neutron agents are up".format(hostnames))

        # Restart autodisabled nova-compute services
        for hostname in hostnames:
            hypervisor = self.os_conn.nova.hypervisors.find(
                hypervisor_hostname=hostname)
            if hypervisor.status == 'disabled':
                node = self.env.find_node_by_fqdn(hostname)
                with node.ssh() as remote:
                    remote.check_call('service nova-compute restart')

        wait(is_nova_hypervisors_alive, timeout_seconds=10 * 60,
             sleep_seconds=10,
             waiting_for="hypervisors on {0} are alive".format(hostnames))

    def find_snat_controller(self, router_id, excluded=()):
        """Find controller with SNAT service.

        :param router_id: router id to find SNAT for it
        :param excluded: excluded nodes fqdns
        :returns: controller node with SNAT
        """
        all_controllers = self.env.get_nodes_by_role('controller')
        for controller in all_controllers:
            if controller.data['fqdn'] in excluded:
                continue
            with controller.ssh() as remote:
                cmd = 'ip net | grep snat-{}'.format(router_id)
                res = remote.execute(cmd)
                if res['exit_code'] == 0:
                    return controller

    def shut_down_br_ex_on_controllers(self):
        """Shut down br-ex for all controllers"""
        controllers = self.env.get_nodes_by_role('controller')
        for node in controllers:
            with node.ssh() as remote:
                remote.check_call('ip link set br-ex down')


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
        self.router_id = router['router']['id']
        self.os_conn.router_gateway_add(
            router_id=self.router_id,
            network_id=self.os_conn.ext_network['id'])

        self.os_conn.router_interface_add(
            router_id=self.router_id,
            subnet_id=subnet['subnet']['id'])

        self.server = self.os_conn.create_server(
            name='server01',
            availability_zone=self.zone.zoneName,
            key_name=self.instance_keypair.name,
            nics=[{'net-id': net['network']['id']}],
            security_groups=[self.security_group.id])

        if assign_floating_ip:
            self.floating_ip = self.os_conn.assign_floating_ip(
                self.server, use_neutron=True)

    @pytest.mark.testrail_id(
        '542746', params={'floating_ip': True, 'dvr_router': True})
    @pytest.mark.testrail_id(
        '542748', params={'floating_ip': False, 'dvr_router': True})
    @pytest.mark.testrail_id(
        '542750', params={'floating_ip': False, 'dvr_router': False})
    @pytest.mark.testrail_id(
        '542752', params={'floating_ip': True, 'dvr_router': False})
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

    @pytest.mark.testrail_id('542764')
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

        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair)

    @pytest.mark.testrail_id('638477')
    def test_connectivity_after_reset_primary_controller_with_snat(self,
            env_name):
        """Check North-South connectivity without floating after resetting
            primary controller with snat

        Scenario:
            1. Create net1, subnet1
            2. Create DVR router router1, set gateway and add interface to net1
            3. Boot vm in net1
            4. Check that ping 8.8.8.8 available from vm
            5. Find node with snat for router1:
                ip net | grep snat-<id_router> on each controller
            6. If node with snat isn't the primary controller
                (pcs cluster status), manually recshedule router:
                neutron l3-agent-router-remove agent_id_where_is_snat router1
                neutron l3-agent-network-add on_primary_agent_id router1
                and wait some time while snat is rescheduling
            7. Reset primary controller
            8. Wait some time while snat is rescheduling
            9. Check that snat have moved to another controller
            10. Check that ping 8.8.8.8 available from vm
        """
        self._prepare_openstack_env(assign_floating_ip=False)

        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair)

        leader_controller = self.env.leader_controller

        # Check l3 agent with SNAT placed on leader_controller
        controller_with_snat = self.find_snat_controller(self.router_id)
        if controller_with_snat != leader_controller:
            logger.info('Moving router to leader {}'.format(leader_controller))
            l3_agents = self.os_conn.list_l3_agents()
            snat_agent = [x for x in l3_agents
                          if x['host'] == controller_with_snat.data['fqdn']][0]
            new_l3_agent = [x for x in l3_agents
                            if x['host'] == leader_controller.data['fqdn']][0]
            self.os_conn.remove_router_from_l3_agent(router_id=self.router_id,
                l3_agent_id=snat_agent['id'])
            self.os_conn.add_router_to_l3_agent(router_id=self.router_id,
                l3_agent_id=new_l3_agent['id'])

        devops_node = DevopsClient.get_node_by_mac(
            env_name=env_name, mac=leader_controller.data['mac'])
        devops_node.reset()

        new_controller_with_snat = wait(
            lambda: self.find_snat_controller(
                self.router_id,
                excluded=[leader_controller.data['fqdn']]),
            timeout_seconds=60 * 3,
            sleep_seconds=(1, 60, 5),
            waiting_for="snat is rescheduled")

        assert (
            leader_controller.data['fqdn'] !=
            new_controller_with_snat.data['fqdn'])

        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair,
                                timeout=5 * 60)

    @pytest.mark.testrail_id('542778')
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
        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair)
        # Get controller with SNAT and destroy it
        controller_with_snat = self.find_snat_controller(self.router_id)
        logger.info('Destroying controller with SNAT: {}'.format(
            controller_with_snat.data['fqdn']))
        devops_node = DevopsClient.get_node_by_mac(
            env_name=env_name, mac=controller_with_snat.data['mac'])
        self.env.destroy_nodes([devops_node])
        # Wait for SNAT reschedule
        new_controller_with_snat = wait(
            lambda: self.find_snat_controller(
                self.router_id,
                excluded=[controller_with_snat.data['fqdn']]),
            timeout_seconds=60 * 3,
            sleep_seconds=(1, 60, 5),
            waiting_for="snat is rescheduled")
        # Check external ping and proper SNAT rescheduling
        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair)
        assert (
            controller_with_snat.data['fqdn'] !=
            new_controller_with_snat.data['fqdn'])

    @pytest.mark.testrail_id('542762')
    def test_north_south_floating_ip_shut_down_br_ex_on_controllers(self):
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
        self._prepare_openstack_env()

        ip = self.floating_ip['floating_ip_address']
        self.check_ping_from_vm_with_ip(ip, vm_keypair=self.instance_keypair,
                                        ip_to_ping='8.8.8.8',
                                        ping_count=10, vm_login='cirros')

        self.shut_down_br_ex_on_controllers()

        self.check_ping_from_vm_with_ip(ip, vm_keypair=self.instance_keypair,
                                        ip_to_ping='8.8.8.8',
                                        ping_count=10, vm_login='cirros')

    @pytest.mark.testrail_id('674297')
    def test_connectivity_after_ban_l3_agent_many_times(self, count=40):
        """Check North-South connectivity without floating after ban l3 agent
            many times

        Scenario:
            1. Create net1, subnet1
            2. Create DVR router router1, set gateway and add interface to net1
            3. Boot vm in net1
            4. Check that ping 8.8.8.8 available from vm
            5. Find node with snat for router1:
                ip net | grep snat-<id_router> on each controller
            6. Ban other l3-agents
            7. Ban l3-agent on for node with snat:
                pcs resource ban p_neutron-l3-agent <controller>
            8. Wait 10 seconds
            9. Clear l3-agent on for node with snat:
                pcs resource clear p_neutron-l3-agent <controller>
            10. Repeat steps 7-9 `count` times
            11. Check that ping 8.8.8.8 available from vm
        """
        self._prepare_openstack_env(assign_floating_ip=False)

        controller = self.find_snat_controller(self.router_id)
        controllers = self.env.get_nodes_by_role('controller')

        # Ban all l3 agents
        with controller.ssh() as remote:
            logger.info('Ban all l3 agents, except placed on {}'.format(
                controller))
            for agent in self.os_conn.list_l3_agents():
                if agent['host'] not in [x.data['fqdn'] for x in controllers]:
                    continue
                if agent['host'] == controller.data['fqdn']:
                    continue
                remote.check_call(
                    'pcs resource ban p_neutron-l3-agent {host}'.format(
                        **agent))

        cmd = 'pcs resource {{action}} p_neutron-l3-agent {fqdn}'.format(
                **controller.data)
        with controller.ssh() as remote:
            for i in range(1, 41):
                logger.info('Ban/clear l3 agent on {node} - {i}'.format(
                    node=controller, i=i))
                remote.check_call(cmd.format(action='ban'))
                time.sleep(10)
                remote.check_call(cmd.format(action='clear'))
                time.sleep(10)

        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair)

    @pytest.mark.testrail_id('542774')
    def test_north_south_floating_ip_ban_clear_l3_agent_on_compute(self):
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
        self._prepare_openstack_env()

        ip = self.floating_ip['floating_ip_address']

        self.check_ping_from_vm_with_ip(ip, vm_keypair=self.instance_keypair,
                                        ip_to_ping='8.8.8.8',
                                        ping_count=10, vm_login='cirros')

        compute_hostname = getattr(self.server, 'OS-EXT-SRV-ATTR:host')
        compute = self.env.find_node_by_fqdn(compute_hostname)
        with compute.ssh() as remote:
            remote.check_call('service neutron-l3-agent stop')

        time.sleep(15)

        # Clear l3 agent
        with compute.ssh() as remote:
            remote.check_call('service neutron-l3-agent start')

        self.check_ping_from_vm_with_ip(ip, vm_keypair=self.instance_keypair,
                                        ip_to_ping='8.8.8.8',
                                        ping_count=10, vm_login='cirros')

    @pytest.mark.testrail_id('638467', params={'count': 1})
    @pytest.mark.testrail_id('638469', params={'count': 2})
    @pytest.mark.parametrize('count', [1, 2])
    def test_ban_l3_agent_on_snat_node(self, count):
        """Check North-South connectivity without floating after ban l3 agent
            on node with snat
        Scenario:
            1. Create net1, subnet1
            2. Create DVR router router1, set gateway and add interface to net1
            3. Boot vm in net1
            4. Check that ping 8.8.8.8 available from vm
            5. Find node with snat for router1:
                ip net | grep snat-<id_router> on each controller
            6. Ban agent on node from previous step:
                pcs resource ban p_neutron-l3-agent node-x.domain.tld
            7. Wait some time while snat is rescheduling
            8. Check that snat have moved to another controller
            9. Repest steps 5-8 `count` times
            10. Check that ping 8.8.8.8 available from vm
        """

        self._prepare_openstack_env(assign_floating_ip=False)

        controller_with_snat = self.find_snat_controller(self.router_id)

        for _ in range(count):

            with controller_with_snat.ssh() as remote:
                remote.check_call(
                    'pcs resource ban p_neutron-l3-agent {fqdn}'.format(
                        **controller_with_snat.data))

            # Wait for SNAT reschedule
            new_controller_with_snat = wait(
                lambda: self.find_snat_controller(
                    self.router_id,
                    excluded=[controller_with_snat.data['fqdn']]),
                timeout_seconds=60 * 3,
                sleep_seconds=20,
                waiting_for="snat is rescheduled")
            assert controller_with_snat != new_controller_with_snat
            controller_with_snat = new_controller_with_snat

        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair)

    @pytest.mark.testrail_id('638473', params={'node_to_clear_key': 'first'})
    @pytest.mark.testrail_id('638471', params={'node_to_clear_key': 'last'})
    @pytest.mark.parametrize('node_to_clear_key', ['first', 'last'])
    def test_ban_and_clear_l3_agent_on_snat_node(self, node_to_clear_key):
        """Check North-South connectivity without floating after ban all
            l3 agent on nodes with snat and then clear one

        Scenario:
            1. Create net1, subnet1
            2. Create DVR router router1, set gateway and add interface to net1
            3. Boot vm in net1
            4. Check that ping 8.8.8.8 available from vm
            5. Find node with snat for router1:
                ip net | grep snat-<id_router> on each controller
            6. Ban agent on node from previous step:
                pcs resource ban p_neutron-l3-agent node-x.domain.tld
            7. Wait some time while snat is rescheduling
            8. Check that snat have moved to another controller
            9. Find node with snat for router1:
                ip net | grep snat-<id_router> on each controller
            10. Ban agent on node from previous step:
                pcs resource ban p_neutron-l3-agent node-x.domain.tld
            11. Wait some time while snat is rescheduling
            12. Check that snat have moved to another controller
            13. Find node with snat for router1:
                ip net | grep snat-<id_router> on each controller
            14. Ban agent on node from previous step:
                pcs resource ban p_neutron-l3-agent node-x.domain.tld
            15. Wait some time while agent is alive
            16. Clear one agent (last or first):
                pcs resource clear p_neutron-l3-agent node-<node_id>
            17. Wait while agent isn't alive
            18. Check that snat have moved to another controller
            19. Check that ping 8.8.8.8 available from vm
        """
        self._prepare_openstack_env(assign_floating_ip=False)

        controller_with_snat = self.find_snat_controller(self.router_id)

        banned_nodes = {'first': controller_with_snat}

        for i in range(3):
            logging.info('Banning step {i}: {node}'.format(
                i=i, node=controller_with_snat))
            with controller_with_snat.ssh() as remote:
                remote.check_call(
                    'pcs resource ban p_neutron-l3-agent {fqdn}'.format(
                        **controller_with_snat.data))

            if i < 2:
                # Wait for SNAT reschedule
                new_controller_with_snat = wait(
                    lambda: self.find_snat_controller(
                        self.router_id,
                        excluded=[controller_with_snat.data['fqdn']]),
                    timeout_seconds=60 * 3,
                    sleep_seconds=10,
                    waiting_for="snat is rescheduled")
                assert controller_with_snat != new_controller_with_snat
                controller_with_snat = new_controller_with_snat
            elif node_to_clear_key == 'last':
                # Wait for SNAT on last controller will die
                wait(lambda: self.find_snat_controller(self.router_id) is None,
                     timeout_seconds=60 * 3, sleep_seconds=10,
                     waiting_for="snat on {} to die".format(
                         controller_with_snat))

        banned_nodes['last'] = controller_with_snat

        node_to_clear = banned_nodes[node_to_clear_key]

        with node_to_clear.ssh() as remote:
            remote.check_call(
                'pcs resource clear p_neutron-l3-agent {fqdn}'.format(
                    **node_to_clear.data))

        # Wait for SNAT back to node
        wait(lambda: self.find_snat_controller(
                self.router_id) == node_to_clear,
             timeout_seconds=60 * 3, sleep_seconds=20,
             waiting_for="snat go back to {}".format(node_to_clear))

        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair,
                                timeout=5 * 60)


@pytest.mark.check_env_('has_2_or_more_computes')
class TestDVRWestEastConnectivity(TestDVRBase):
    """Test DVR west-east routing"""

    @pytest.fixture
    def prepare_openstack(self, variables):
        """Prepare OpenStack for some scenarios run

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

    @pytest.mark.testrail_id('542744')
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

    @pytest.mark.testrail_id('542776')
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

    @pytest.mark.testrail_id('542766')
    def test_routing_after_reset_computes(self, env_name, prepare_openstack):
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

        # Check ping after reset
        self.check_ping_from_vm(vm=self.server2,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server1_ip)

    @pytest.mark.testrail_id('542768')
    @pytest.mark.check_env_('is_ha')
    def test_east_west_connectivity_after_destroy_controller(self, env_name,
            prepare_openstack):
        """Check East-West connectivity after destroy controller

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed and
                with gateway to external network
            4. Add interfaces to the router01_02 with net01_subnet and
                net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on another compute
            7. Go to the vm_1
            8. Ping vm_2
            9. Destroy one controller
            10. Go to the vm_2 with internal ip from namespace on compute
            11. Ping vm_1 with internal IP

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

    @pytest.mark.testrail_id('542756')
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
        compute_name = self.zone.hosts.keys()[0]

        for i in range(1, 3):
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

    @pytest.mark.testrail_id('542754')
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


@pytest.mark.check_env_('has_1_or_more_computes')
class TestDVRTypeChange(TestDVRBase):

    def check_exception_on_router_update_to_centralize(self, router_id):
        # Change admin_state_up to False
        # and then try to set distributed to False
        self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'admin_state_up': False}})

        # distributed parameter can't be changed from True to False
        # exception is expected here
        # in case if no exception is generated the py.test will fail
        with pytest.raises(NeutronClientException) as e:
            self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'distributed': False}})

        # allowed_msg is for doulbe check
        # There is no separate exception for each case
        # So just check that generated exception contains the expected message
        # Otherwise the test is failed
        allowed_msg = 'Migration from distributed router'
        allowed_msg = allowed_msg + ' to centralized is not supported'
        err_msg = 'Failed to update the router, exception: {}'.format(e)
        assert allowed_msg in str(e.value), err_msg

    @pytest.mark.testrail_id('542770')
    def test_distributed_router_is_not_updated_to_centralized(self, init):
        """Check that it is not poissible to update distributed
        router to centralized.

        Scenario:
            1. Create router with enabled dvr feature
            2. Check that distributed attribute is set to True
            3. Set admin_state_up of the router to False
            4. Try to change the distributed attribute to False
                The value should not be changed and exception occured
        """

        # Create router with default value of distributed
        # In case of dvr feature distributed default value should be True
        router = {'name': 'router01'}
        router_id = self.os_conn.neutron.create_router(
                        {'router': router})['router']['id']
        logger.info('router {} was created'.format(router_id))

        # Check that router is distributed by default
        router = self.os_conn.neutron.show_router(router_id)['router']
        err_msg = (
            "distributed parameter for the router {0} is {1}. "
            "But it's expected value is True").format(
            router['name'], router['distributed'])
        assert router['distributed'], err_msg

        self.check_exception_on_router_update_to_centralize(router['id'])

    @pytest.fixture
    def legacy_router(self, variables):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create centralized router1 and connect it with external net
        """

        router = self.os_conn.create_router(
                     name="router01", distributed=False)['router']
        self.os_conn.router_gateway_add(
            router_id=router['id'],
            network_id=self.os_conn.ext_network['id'])
        logger.info('router {} was created'.format(router['id']))
        return router

    @pytest.fixture
    def dvr_router(self, variables):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create distributed router1 and connect it with external net
        """

        router = self.os_conn.create_router(
                     name="router01", distributed=True)['router']
        self.os_conn.router_gateway_add(
            router_id=router['id'],
            network_id=self.os_conn.ext_network['id'])
        logger.info('router {name}({id}) was created'.format(**router))
        return router

    def create_net_and_vm(self, router_id):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create network1 and connect it with router01
            2. Boot vm1 in network1 and associate floatidvrng ip
            3. Add rules for ping
            4. ping 8.8.8.8 from vm1
        """
        # create one network and one instacne in it
        net_id = self.os_conn.add_net(router_id)
        srv = self.os_conn.add_server(net_id,
                                      self.instance_keypair.name,
                                      self.hosts[0],
                                      self.security_group.id)

        # add floating ip to first server
        self.os_conn.assign_floating_ip(srv)

        # check pings
        self.check_vm_connectivity()

        # find the compute where the vm is run
        computes = self.env.get_nodes_by_role('compute')
        compute_nodes = [node for node in computes
                         if node.data['fqdn'] == self.hosts[0]]

        assert compute_nodes, "Can't find the compute node with the vm"

        return compute_nodes[0]

    @pytest.mark.testrail_id('542772')
    def test_centralized_update_to_distributed(self, legacy_router, variables):
        """Create centralized router and update it to distributed.

        Steps:
            1. Check that the router is not distributed by default
            2. Try to change the distributed parameter
                It shouldn't be possible without
                setting admin_state_up to False
            3. Change admin_state_up to False and than set distributed to True
            4. Change admin_state_up to True to enable the router
            5. Check that the router namespace is available on the compute
            6. Ping 8.8.8.8 from vm1
            7. And finally as a bonus check that it is not poissible
                to change the router type from distributed to centralized
        """
        router_id = legacy_router['id']
        compute_node = self.create_net_and_vm(router_id)

        # Check that router is not distributed by default
        router = self.os_conn.neutron.show_router(router_id)['router']
        err_msg = (
            "distributed parameter for the router {0} is {1}. "
            "But it's expected value is False").format(
            router['name'], router['distributed'])
        assert not router['distributed'], err_msg

        # Try to change the distributed parameter
        # That shouldn't be possible without setting admin_state_up to False
        # exception is expected here
        # in case if no exception is generated the py.test will fail
        with pytest.raises(NeutronClientException) as e:
            self.os_conn.neutron.update_router(router_id,
                                               {'router': {
                                                   'distributed': True}})

        # allowed_msg is for doulbe check
        # There is no separate exception for each case
        # So just check that generated exception contains the expected message
        # Otherwise the test is failed
        allowed_msg = 'admin_state_up to False prior to upgrade'
        err_msg = 'Failed to update the router, exception: {}'.format(e)
        assert allowed_msg in str(e.value), err_msg

        # Change admin_state_up to False and than set distributed to True
        self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'admin_state_up': False}})

        self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'distributed': True}})

        # Change admin_state_up to True to enable the router
        self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'admin_state_up': True}})

        # Check that distributed is really changed to True
        router = self.os_conn.neutron.show_router(router_id)['router']
        err_msg = (
            "distributed parameter for the router {0} is {1}. "
            "But it's expected value is True").format(
            router['name'], router['distributed'])
        assert router['distributed'], err_msg

        # Check that the router namespace is available on the compute now
        with compute_node.ssh() as remote:
            cmd = "ip netns | grep [q]router-{}".format(router_id)
            wait_msg = (
                'router: {} namespace is available on compute: {}'.format(
                    router_id, compute_node.data['fqdn']))
            wait(
                lambda: remote.execute(cmd)['exit_code'] == 0,
                timeout_seconds=15,
                sleep_seconds=5,
                waiting_for=wait_msg)

        # check pings
        self.check_vm_connectivity()

        # And finally check that after all it is not poissible
        # to change the router type from distributed to centralized

        self.check_exception_on_router_update_to_centralize(router['id'])

    def get_snat_controller(self, host_name, router_id):
        snat_controller = None
        controllers = self.env.get_nodes_by_role('controller')
        for node in controllers:
            if node.data['fqdn'] == host_name:
                with self.env.get_ssh_to_node(node.data['ip']) as remote:
                    cmd = 'ip netns | grep [s]nat-{}'.format(router_id)
                    result = remote.execute(cmd)
                    if result['exit_code'] == 0:
                        snat_controller = node
                        break
        return snat_controller

    @pytest.mark.testrail_id('542780')
    @pytest.mark.check_env_('is_ha')
    def test_reschedule_router_from_snat_controller(self, dvr_router):
        """Reschedule router from snat controller.

        Steps:
            1.  Find controller with SNAT-namespace:
                `ip net | grep snat` on all controller
            2.  Reschedule router to another controller
            3.  Check that SNAT-namespace moved to another controller
            4.  Go to the vm_1 with ssh and floating IP and Ping 8.8.8.8
        """
        router_id = dvr_router['id']
        self.create_net_and_vm(router_id)

        # Find the current controller with snat namespace
        snat_controller = self.find_snat_controller(router_id)

        logger.info('Old SNAT on {fqdn}'.format(**snat_controller.data))

        # Find all another controllers fqdn
        other_controllers_fqdn = [x.data['fqdn'] for x in
                                  self.env.get_nodes_by_role('controller')
                                  if x != snat_controller]

        l3_agents = self.os_conn.get_l3_for_router(router_id)['agents']

        # Get current l3 agent with snat
        current_l3_agt = [x for x in l3_agents
                          if x['host'] == snat_controller.data['fqdn']][0]

        # Get router's l3 agents ids
        l3_agent_ids = [x['id'] for x in l3_agents]

        # Search l3 agent on another controller, and hot hosted router
        for l3_agent in self.os_conn.list_l3_agents():
            if l3_agent['host'] in other_controllers_fqdn:
                break
        else:
            raise Exception("Can't find new l3 agent to reschedule router")

        logger.info('Choosed new l3_agent {id}({host})'.format(**l3_agent))

        # Reschedule the router to new l3 agent
        self.os_conn.force_l3_reschedule(
            router_id, new_l3_agt_id=l3_agent['id'],
            current_l3_agt_id=current_l3_agt['id'])

        def get_new_snat_controller():
            new_controller = self.find_snat_controller(router_id)
            if new_controller is None:
                return
            if new_controller != snat_controller:
                return new_controller

        wait(get_new_snat_controller, timeout_seconds=30, sleep_seconds=5,
             waiting_for='reschedule l3_agent with snat')

        # Check pings
        self.check_vm_connectivity()

    @pytest.mark.testrail_id('542758')
    def test_create_dvr_by_no_admin_user(self, openstack_client):
        """Create distributed router with member user

        Steps:
            1.  Create new user for admin tenant with member role
            2.  Login with this user in the CLI
            3.  Create router with parameter Distributed = True
            4.  Check that creation isn't available
            5.  Create router with parameter Distributed = False
            6.  Check that creation isn't available
            7.  Create router without this parameter
            8.  Log in as admin user
            9.  Check that parameter Distributed is true
        """
        username = 'test_dvr'
        userpass = 'test_dvr'
        tenant = 'admin'

        openstack_client.user_create(username, userpass, project=tenant)

        auth = KeystonePassword(username=username,
                                password=userpass,
                                auth_url=self.os_conn.session.auth.auth_url,
                                tenant_name=tenant)

        neutron = neutronclient.Client(auth=auth, session=self.os_conn.session)

        # Try to create router with explicit distributed True value
        # by user with member role but in admin tenant
        # That shouldn't be possible, exception is expected here
        # in case if no exception is generated the py.test will fail
        with pytest.raises(NeutronClientException) as e:
            router = {'name': 'router01', 'distributed': True}
            router_id = neutron.create_router(
                {'router': router})['router']['id']
        # allowed_msg is for double check
        # There is no separate exception for each case
        # So just check that generated exception contains the expected message
        # Otherwise the test is failed
        allowed_msg = 'disallowed by policy'
        err_msg = 'Failed to create the router, exception: {}'.format(e)
        assert allowed_msg in str(e.value), err_msg

        # Try to create router with explicit distributed False value
        # by user with member role but in admin tenant
        # exception is expected here
        with pytest.raises(NeutronClientException) as e:
            router = {'name': 'router01', 'distributed': False}
            router_id = neutron.create_router(
                {'router': router})['router']['id']
        allowed_msg = 'disallowed by policy'
        err_msg = 'Failed to create the router, exception: {}'.format(e)
        assert allowed_msg in str(e.value), err_msg

        # Try to create router with default distributed value
        # by user with memeber role but in admin tenant
        router = {'name': 'router01'}
        router_id = neutron.create_router(
            {'router': router})['router']['id']

        # Check that the created router has distributed value set to True
        # Check is done by admin user
        router = self.os_conn.neutron.show_router(router_id)['router']
        err_msg = (
            "distributed parameter for the router {0} is {1}. "
            "But it's expected value is True").format(
            router['name'], router['distributed'])
        assert router['distributed'], err_msg

        self.check_exception_on_router_update_to_centralize(router['id'])


class TestDVRRegression(TestDVRBase):
    @pytest.fixture
    def prepare_neutron_logs(self):
        """Mark logs to know which logs are generated during the test"""
        self.controllers = self.env.get_nodes_by_role('controller')
        self.logs_path = "/var/log/neutron/server.log"
        self.logs_start_marker = gen_random_resource_name(
            prefix='neutron')

        for controller in self.controllers:
            with controller.ssh() as remote:
                res = remote.check_call(
                    "echo {0} >> {1}".format(self.logs_start_marker,
                                             self.logs_path))['exit_code']
                assert res == 0

    @pytest.yield_fixture
    def set_debug_logging_for_neutron_l3_agent(self, os_conn):
        """Set debug logging for neutron l3 agent"""
        def enable_debug_logging(node):
            with node.ssh() as remote:
                remote.check_call('mv /etc/neutron/l3_agent.ini '
                                  '/etc/neutron/l3_agent.ini.orig')
                remote.check_call("cat /etc/neutron/l3_agent.ini.orig | sed "
                                  "'s/debug = False/debug = True/g' > "
                                  "/etc/neutron/l3_agent.ini")
                remote.check_call('service neutron-l3-agent restart')

        def disable_debug_logging(node):
            with node.ssh() as remote:
                remote.execute('mv /etc/neutron/l3_agent.ini.orig '
                               '/etc/neutron/l3_agent.ini')
                remote.execute('service neutron-l3-agent restart')

        l3_agent_ids = [agt['id'] for agt in os_conn.neutron.list_agents(
                        binary='neutron-l3-agent')['agents']]

        settings = self.env.get_settings_data()
        if settings['editable']['common']['debug']['value'] is False:
            nodes = self.env.get_all_nodes()
            for node in nodes:
                enable_debug_logging(node)
            os_conn.wait_agents_alive(l3_agent_ids)
            yield
            for node in nodes:
                disable_debug_logging(node)
            os_conn.wait_agents_alive(l3_agent_ids)
        else:
            yield

    def get_updated_floating_rules(self, compute, router, ip1, ip2, count):
        router_namespace = "qrouter-{0}".format(router['router']['id'])
        cmd = 'ip netns exec {0} ip rule s'.format(router_namespace)

        def get_floating_rules():
            with compute.ssh() as remote:
                out = remote.check_call(cmd).stdout_string.split('\n')
                all_rules = [i.split(':\t') for i in out]
                floating_rules = [i for i in all_rules for ip in [ip1, ip2]
                                  if ip in i[1]]
                return floating_rules

        wait(lambda: len(get_floating_rules()) == count,
             timeout_seconds=15,
             waiting_for='floatings rules will be updated on compute node')

        return get_floating_rules()

    @pytest.mark.testrail_id('843828')
    @pytest.mark.usefixtures('prepare_neutron_logs')
    def test_add_router_interface_with_port_id(self):
        """Add router interface with port_id parameter

        Steps:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with router type Distributed
            3. Create port
            4. Add interfaces to the router01 with created port
            5. Check that the error with message 'Could not retrieve
                gateway port for subnet' didn't appear in logs
        """
        net, _ = self.create_internal_network_with_subnet(1)
        router = self.os_conn.create_router(name='router01', distributed=True)
        port = self.os_conn.create_port(net['network']['id'])
        self.os_conn.router_interface_add(router_id=router['router']['id'],
                                          port_id=port['port']['id'])
        logger.debug("Wait some time before collecting neutron logs.")
        time.sleep(30)

        log_msg = "Could not retrieve gateway port for subnet"
        err_msg = ("ERROR with '{}' message was found in {}.".format(
            log_msg, self.logs_path))

        logger.debug("Verify that the error log is absent in {}".format(
            self.logs_path))
        for controller in self.controllers:
            with controller.ssh() as remote:
                with remote.open(self.logs_path) as f:
                    # check only generated during the test logs
                    lines = iter(f)
                    for line in lines:
                        if self.logs_start_marker in line:
                            break
                    for line in lines:
                        assert log_msg not in line, err_msg

    @pytest.mark.testrail_id('844801')
    def test_check_router_namespace_on_compute_node(self):
        """Check router namespace on compute node with vm and after deleting vm

        Steps:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with router type Distributed
            3. Add interfaces to the router01
            4. Set router gateway to external net
            5. Boot VM in created net01
            6. On compute node (where vm is hosted) check that router namespace
            is present
            7. Delete VM
            8. On compute node (where vm is hosted) check that router namespace
            is deleted
        """
        security_group = self.os_conn.create_sec_group_for_ssh()
        net, subnet = self.create_internal_network_with_subnet(1)
        router = self.os_conn.create_router(name='router01', distributed=True)

        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])

        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])

        server = self.os_conn.create_server(
            name='server01',
            nics=[{'net-id': net['network']['id']}],
            security_groups=[security_group.id])

        compute_hostname = getattr(server, 'OS-EXT-SRV-ATTR:host')
        node = self.env.find_node_by_fqdn(compute_hostname)
        router_namespace = "qrouter-{0}".format(router['router']['id'])
        cmd = 'ip net | grep {0}'.format(router_namespace)

        logger.debug('Verify that router namespace is present on compute node')
        with node.ssh() as remote:
            remote.check_call(cmd)

        self.os_conn.delete_servers()

        with node.ssh() as remote:
            wait(lambda: not remote.execute(cmd).is_ok,
                 timeout_seconds=60,
                 waiting_for='router namespace to be deleted on compute node')

    @pytest.mark.testrail_id('851673')
    @pytest.mark.check_env_('has_2_or_more_computes')
    @pytest.mark.usefixtures('set_debug_logging_for_neutron_l3_agent')
    def test_check_router_update_notification_for_l3_agents(self):
        """Check that router update notification is sent only in log of l3
        agent on appropriate compute node when boot a vm and assign/delete
        floating ip to/from this vm
        Steps:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with router type Distributed
            3. Add interfaces to the router01
            4. Set router gateway to external net
            5. Clear l3 agent's log on all nodes
            6. Boot VM in created net01
            7. Assign floating IP to that VM
            8. Delete floating IP from that VM
            9. Check l3 agent's log to make sure that notification 'Got routers
            updated notification' was sent to only one l3 agent on compute node
            where instance is hosted - in total 3 notifications for steps 6-8
        """
        security_group = self.os_conn.create_sec_group_for_ssh()
        net, subnet = self.create_internal_network_with_subnet(1)
        router = self.os_conn.create_router(name='router01', distributed=True)

        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])

        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])

        l3_agent_log = '/var/log/neutron/neutron-l3-agent.log'
        nodes = self.env.get_all_nodes()
        for node in nodes:
            with node.ssh() as remote:
                remote.execute('truncate -s 0 {0}'.format(l3_agent_log))

        server = self.os_conn.create_server(
            name='server01',
            nics=[{'net-id': net['network']['id']}],
            security_groups=[security_group.id])

        floating_ip = self.os_conn.assign_floating_ip(server, use_neutron=True)
        self.os_conn.delete_floating_ip(floating_ip, use_neutron=True)

        logger.debug('Verify the specified l3 agent received 3 notifications')
        log_msg = 'Got routers updated notification'
        cmd = 'grep -c "{0}" {1}'.format(log_msg, l3_agent_log)
        compute_hostname = getattr(server, 'OS-EXT-SRV-ATTR:host')
        compute_node = self.env.find_node_by_fqdn(compute_hostname)
        with compute_node.ssh() as remote:
            assert remote.check_call(cmd).stdout_string == '3'

        logger.debug('Verify the other l3 agents did not receive notification')
        err_msg = 'l3 agent has received unneeded notification'
        nodes.remove(compute_node)
        for node in nodes:
            with node.ssh() as remote:
                assert not remote.execute(cmd).is_ok, err_msg

    @pytest.mark.testrail_id('857407')
    @pytest.mark.usefixtures('variables')
    def test_instance_connectivity_after_l3_agent_restart(self):
        """Check instances don't lose connectivity after restart l3 agent

        Steps:
            1. Update quotas for creation enough networks.
            2. Create 10 nets, 10 routers, create 10 vms on 1 compute.
            3. Choose 1 vm and ping 8.8.8.8 from it.
            4. Restart l3 agent on compute with vms 60 times.
            5. Ping 8.8.8.8 is available.
        """
        self.set_neutron_quota(network=50, router=50, subnet=50, port=150)
        compute_node = self.env.get_nodes_by_role('compute')[0]
        flavor = self.os_conn.nova.flavors.find(name='m1.micro')
        servers = []
        for x in range(10):
            router = self.os_conn.create_router(name='router{}'.format(x),
                                                distributed=True)
            self.os_conn.router_gateway_add(
                router_id=router['router']['id'],
                network_id=self.os_conn.ext_network['id'])

            net_id = self.os_conn.add_net(router['router']['id'])

            srv = self.os_conn.create_server(
                name='instanceNo{}'.format(x),
                flavor=flavor,
                key_name=self.instance_keypair.name,
                security_groups=[self.security_group.id],
                availability_zone='{}:{}'.format(self.zone.zoneName,
                                                 compute_node.data['fqdn']),
                nics=[{'net-id': net_id}],
                wait_for_active=False,
                wait_for_avaliable=False)

            servers.append(srv)

        self.os_conn.wait_servers_active(servers)
        self.os_conn.wait_servers_ssh_ready(servers)

        srv = servers[0]
        self.check_ping_from_vm(srv, ip_to_ping="8.8.8.8")

        with compute_node.ssh() as remote:
            for _ in range(60):
                remote.check_call("service neutron-l3-agent restart")
                self.check_ping_from_vm(srv, ip_to_ping="8.8.8.8")

    @pytest.mark.testrail_id('1681396')
    def test_floating_ip_rules_after_l3_agent_restart(self):
        """Check that floating ip rules priority association works correctly
        after restarting of l3 agent.
        Steps:
            1. Create net01, subnet net01__subnet for it
            2. Create router01, connect to external network
            3. Boot VM1, associate floating ip to it
            4. Restart l3 agent on appropriate compute node
            5. Boot VM2, associate floating ip to it
            6. Check uniqueness of floatings rules priorities
            7. Disassociate the floating ip
            8. Check that correct floating's rule was deleted after step 7
        [Bug] - https://bugs.launchpad.net/mos/+bug/1577985
        """
        security_group = self.os_conn.create_sec_group_for_ssh()
        net, subnet = self.create_internal_network_with_subnet(1)
        router = self.os_conn.create_router(name='router01', distributed=True)

        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])

        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])

        server1 = self.os_conn.create_server(
            name='server01',
            nics=[{'net-id': net['network']['id']}],
            security_groups=[security_group.id])

        self.os_conn.assign_floating_ip(server1, use_neutron=True)

        compute_hostname = getattr(server1, 'OS-EXT-SRV-ATTR:host')
        compute = self.env.find_node_by_fqdn(compute_hostname)
        l3_agents = self.os_conn.list_l3_agents()
        vm_l3_agents = [x['id'] for x in l3_agents
                        if x['host'] == compute_hostname]

        with compute.ssh() as remote:
            logger.info('disable l3 agent')
            remote.check_call('service neutron-l3-agent stop')
            self.os_conn.wait_agents_down(vm_l3_agents)
            logger.info('enable l3 agent')
            remote.check_call('service neutron-l3-agent start')
            self.os_conn.wait_agents_alive(vm_l3_agents)

        server2 = self.os_conn.create_server(
            name='server02',
            availability_zone='nova:{}'.format(compute_hostname),
            nics=[{'net-id': net['network']['id']}],
            security_groups=[security_group.id])

        fip = self.os_conn.assign_floating_ip(server2, use_neutron=True)

        fixed_ip1 = server1.networks['net01'][0]
        fixed_ip2 = server2.networks['net01'][0]

        logger.debug("Verify there is no duplicated floating ip's priorities")
        rules = self.get_updated_floating_rules(compute, router,
                                                fixed_ip1, fixed_ip2, 2)
        err_msg = "Floating's rules have the same priorities"
        assert not rules[0][0] == rules[1][0], err_msg

        self.os_conn.disassociate_floating_ip(server2, fip, use_neutron=True)

        logger.debug("Verify correct floating ip's rule was deleted")
        rules = self.get_updated_floating_rules(compute, router,
                                                fixed_ip1, fixed_ip2, 1)
        err_msg = "Incorrect floating ip rule was deleted"
        assert fixed_ip1 in rules[0][1], err_msg

    @pytest.mark.testrail_id('1696115')
    @pytest.mark.check_env_('has_2_or_more_computes')
    def test_check_floating_ip_after_live_migration(self):
        """Check that floating ip works correctly after live migration.
        Steps:
            1. Create net01, subnet net01__subnet for it
            2. Create router01, connect to external network
            3. Boot VM, associate floating ip to it
            4. Note floating ip's route from compute1
            5. Initiate live migration for VM
            6. Check that floating ip's route disappeared from compute1
            7. Check that floating ip's route appears on compute2
            8. Ssh to admin node and run arping to check that only one mac
            address is answered to ARP queries

        [Bug] - https://bugs.launchpad.net/mos/+bug/1620863
        """
        security_group = self.os_conn.create_sec_group_for_ssh()
        net, subnet = self.create_internal_network_with_subnet(1)
        router = self.os_conn.create_router(name='router01', distributed=True)

        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])

        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])

        server1 = self.os_conn.create_server(
            name='server01',
            nics=[{'net-id': net['network']['id']}],
            security_groups=[security_group.id])

        fip = self.os_conn.assign_floating_ip(server1, use_neutron=True)
        fip_ip = fip.get('floating_ip_address')

        compute_hostname1 = getattr(server1, 'OS-EXT-SRV-ATTR:host')
        compute1 = self.env.find_node_by_fqdn(compute_hostname1)

        with compute1.ssh() as remote:
            logger.info('Getting floating ip namespace from compute1')
            cmd = 'ip netns list | grep fip'
            wait(lambda: remote.execute(cmd).is_ok,
                 timeout_seconds=10,
                 waiting_for='floating ip namespace appears on compute1')
            fip_namespace = remote.check_call(cmd).stdout_string

            logger.info('Getting floating ip route from compute1')
            cmd = 'ip netns exec {0} ip route | grep {1}'.format(fip_namespace,
                                                                 fip_ip)
            wait(lambda: remote.execute(cmd).is_ok,
                 timeout_seconds=15,
                 waiting_for='floating ip route appears on compute1')
            fip_route = remote.check_call(cmd).stdout_string

        self.os_conn.live_migration(server1, fip_ip)

        compute_hostname2 = getattr(server1, 'OS-EXT-SRV-ATTR:host')
        compute2 = self.env.find_node_by_fqdn(compute_hostname2)

        with compute1.ssh() as remote:
            logger.info('Verify absence of floating ip route on compute1')
            err_msg = 'Floating ip namespace route is still exist on compute1'
            assert not remote.execute(cmd).is_ok, err_msg

        with compute2.ssh() as remote:
            logger.info('Verify presence of floating ip route on compute2')
            err_msg = 'Floating ip route is absent on compute2'
            assert remote.check_call(cmd).stdout_string == fip_route, err_msg

        logger.info('Verify how many addresses are answered to ARP queries')
        with SSHClient(host=self.fuel.admin_ip,
                       username=self.fuel.ssh_login,
                       password=self.fuel.ssh_password,
                       private_keys=self.fuel.admin_keys) as remote:
            mac = self.env.primary_controller.data['mac']
            cmd = 'fuel node --node-id {0} --network --download'.format(mac)
            interfaces = remote.check_call(cmd).stdout_string.split('\n')[1]
            with remote.open(interfaces) as f:
                data = yaml.load(f)
            device = [data[i]['name'] for i in range(len(data))
                      if data[i]['assigned_networks'][0]['name'] == 'public']
            cmd = 'arping -I {0} -c 5 {1} | grep ms'.format(device[0], fip_ip)
            reply_list = remote.check_call(cmd).stdout_string.split('\n')
            mac_list = []
            for reply in reply_list:
                mac_list.append(re.findall('\[(.+?)\]', reply)[0])
            err_msg = 'More than one mac address is answered on ARP queries'
            assert len(set(mac_list)) == 1, err_msg

    @pytest.mark.testrail_id('1696122')
    def test_check_correctness_of_ip_address_in_ping_replies(self):
        """Check that ping replies were received from floating ip address if
        VMs are on the same network.
        Steps:
            1. Create net01, subnet net01__subnet for it
            2. Create router01, connect to external network
            3. Boot VM1, don't associate floating ip to it
            4. Boot VM2 (the same compute node should be hosting), associate
            floating ip to it
            5. Ssh to VM1 and ping to VM2's floating ip
            6. Check that ping replies were received from VM2's floating ip
            (not from fixed ip)
        [Bug] - https://bugs.launchpad.net/mos/+bug/1630242
        """
        security_group = self.os_conn.create_sec_group_for_ssh()
        net, subnet = self.create_internal_network_with_subnet(1)
        router = self.os_conn.create_router(name='router01', distributed=True)
        key = self.os_conn.nova.keypairs.create('key_1696122')

        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])

        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])

        vm1 = self.os_conn.create_server(
            name='vm01',
            nics=[{'net-id': net['network']['id']}],
            security_groups=[security_group.id],
            key_name=key.name)

        compute_hostname = getattr(vm1, 'OS-EXT-SRV-ATTR:host')

        vm2 = self.os_conn.create_server(
            name='vm02',
            availability_zone='nova:{}'.format(compute_hostname),
            nics=[{'net-id': net['network']['id']}],
            security_groups=[security_group.id])

        fip = self.os_conn.assign_floating_ip(vm2, use_neutron=True)
        vm2_fip_ip = fip.get('floating_ip_address')

        logger.info("From VM1 ping to VM2's floating ip and verify that "
                    "ping reply was received from VM2's floating ip")
        result = self.check_ping_from_vm_helper(vm1, key, vm2_fip_ip, 15,
                                                'cirros', 'cubswin:)')
        ping_reply = result.stdout_string.split('\n')[1]
        reply_ip = re.findall('\d{1,3}.\d{1,3}.\d{1,3}.\d{1,3}', ping_reply)
        err_msg = "Ping reply was received from another ip address"
        assert reply_ip == vm2_fip_ip, err_msg

    @pytest.mark.testrail_id('2276953')
    def test_check_snat_for_routers_when_ban_l3_agent(self):
        """Checks that SNAT rescheduling on first router doesn't affect
        SNAT of the second one when ban l3-agent.

        Steps:
            1. Create router01, router02 with router type Distributed
            2. Add interfaces to the router01, router02
            3. Set router gateway to external net
            4. Create 2 networks with subnets
            5. Boot VMs in created net01, net02
            6. Check VMs connectivity
            7. Find controller with SNAT-namespace for both routers.
            If they are the same, reschedule
            8. Ban l3-agent on node with SNAT for the first router
            9. Check that SNAT for the second router didn't reschedule to
            another node
        """
        zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        security_group = self.os_conn.create_sec_group_for_ssh()
        instance_keypair = self.os_conn.create_key(key_name='instancekey')
        router_ids = []
        for x in range(2):
            net, subnet = self.create_internal_network_with_subnet(x)
            router = self.os_conn.create_router(name='router0{}'.format(x),
                                                distributed=True)
            router_ids.append(router['router']['id'])

            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])

            self.os_conn.router_gateway_add(
                router_id=router['router']['id'],
                network_id=self.os_conn.ext_network['id'])

            server = self.os_conn.create_server(
                name='server0{}'.format(x),
                availability_zone=zone.zoneName,
                key_name=instance_keypair.name,
                nics=[{'net-id': net['network']['id']}],
                security_groups=[security_group.id])

            floating_ip = self.os_conn.assign_floating_ip(server,
                                                          use_neutron=True)
            ip = floating_ip['floating_ip_address']
            self.check_ping_from_vm_with_ip(ip, vm_keypair=instance_keypair,
                                            ip_to_ping='8.8.8.8',
                                            ping_count=10, vm_login='cirros')
        # Check l3 agent with SNAT for both routers
        r01_snat_controller = self.find_snat_controller(router_ids[0])
        r02_snat_controller = self.find_snat_controller(router_ids[1])
        controllers = self.env.get_nodes_by_role('controller')
        if r01_snat_controller == r02_snat_controller:
            logger.info('Moving router01 SNAT to another controller')
            l3_agents = self.os_conn.list_l3_agents()
            snat_agent = [x for x in l3_agents
                          if x['host'] == r01_snat_controller.data['fqdn']][0]
            l3_agents_on_controller = [x for x in l3_agents
                                       for controller in controllers
                                       if x['host'] == controller.data['fqdn']]
            new_l3_agent = [x for x in l3_agents_on_controller
                            if x['host'] !=
                            r01_snat_controller.data['fqdn']][0]
            self.os_conn.remove_router_from_l3_agent(router_id=router_ids[0],
                l3_agent_id=snat_agent['id'])
            self.os_conn.add_router_to_l3_agent(router_id=router_ids[0],
                l3_agent_id=new_l3_agent['id'])

            r01_snat_controller_new = wait(
                lambda: self.find_snat_controller(
                    router_ids[0],
                    excluded=[r01_snat_controller.data['fqdn']]),
                timeout_seconds=60 * 3,
                sleep_seconds=(1, 60, 5),
                waiting_for="snat is rescheduled")

            assert (r01_snat_controller.data['fqdn'] !=
                    r01_snat_controller_new.data['fqdn'])
            r01_snat_controller = r01_snat_controller_new

        with r01_snat_controller.ssh() as remote:
            remote.check_call(
                'pcs resource ban p_neutron-l3-agent {fqdn}'.format(
                    **r01_snat_controller.data))

        # Wait for SNAT reschedule
        r01_snat_controller_resched = wait(
            lambda: self.find_snat_controller(
                router_ids[0],
                excluded=[r01_snat_controller.data['fqdn']]),
            timeout_seconds=60 * 3,
            sleep_seconds=20,
            waiting_for="snat is rescheduled")
        assert r01_snat_controller_resched != r01_snat_controller
        r02_snat_controller_new = self.find_snat_controller(router_ids[1])
        assert r02_snat_controller_new == r02_snat_controller
