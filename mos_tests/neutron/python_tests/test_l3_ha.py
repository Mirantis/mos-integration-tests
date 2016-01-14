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
from collections import namedtuple
from contextlib import contextmanager
import logging
import re
import signal

import pytest
from waiting import wait

from mos_tests.environment.devops_client import DevopsClient
from mos_tests.neutron.python_tests.base import TestBase
from mos_tests import settings


logger = logging.getLogger(__name__)


def get_ping_seq(line):
    """Return ping seq"""
    seq = re.search(r'seq=(\d+) ', line)
    if seq is None:
        return None
    return int(seq.group(1))


def ping_groups(stdout):
    """Generate ping info for each line of stdout

    Format:
        * `sended` - count of sended packets
        * `received` - count of received packets
        * `group_len` - len of last continuous group of success pings
    """
    PingInfo = namedtuple('PingInfo', ['sended', 'received', 'group_len'])
    prev_seq = -1
    group_start = 0
    received = 0
    for line in stdout:
        logger.debug('Ping result: {}'.format(line.strip()))
        seq = get_ping_seq(line)
        if seq is None:
            continue
        received += 1
        if seq != prev_seq + 1:
            logger.debug('ping interrupted')
            group_start = seq
        pi = PingInfo(sended=seq, received=received,
                      group_len=seq - group_start)
        yield pi
        prev_seq = seq


@pytest.mark.check_env_('is_l3_ha', 'has_2_or_more_computes')
class TestL3HA(TestBase):
    """Tests for L3 HA"""

    @contextmanager
    def background_ping(self, vm, vm_keypair, ip_to_ping, good_pings=50):
        """Start ping from `vm` to `ip_to_ping` before enter and stop it after

        Return dict with ping stat

        :param vm: instance to ping from
        :param vm_keypair: keypair to connect to `vm`
        :param ip_to_ping: ip address to ping from `vm`
        :param good_pings: count of continuous pings to determine that connect
            is restored
        """

        result = {}

        logger.info('Start ping on {0}'.format(ip_to_ping))
        with self.os_conn.ssh_to_instance(self.env, vm,
                                          vm_keypair) as remote:
            command = 'ping {0}'.format(ip_to_ping)
            chan, stdin, stdout, stderr = remote.execute_async(command)

            # Wait for 10 not interrupted packets
            groups = ping_groups(stdout)
            for ping_info in groups:
                if ping_info.group_len >= 10:
                    break

            yield result

            logger.info('Wait for ping restored')
            for ping_info in groups:
                result['received'] = ping_info.received
                result['sended'] = ping_info.sended
                if ping_info.group_len >= good_pings:
                    break
            stdin.write(chr(signal.SIGINT))
            stdin.flush()
            chan.close()

    def get_active_l3_agents_for_router(self, router_id):
        agents = self.os_conn.get_l3_for_router(router_id)
        return [x for x in agents['agents']
                if x['ha_state'] == 'active' and x['alive'] is True]

    def wait_router_rescheduled(self, router_id, from_node,
                                timeout_seconds=2 * 60):
        """Wait until active l3 agent moved from prev_node
        Returns new active l3 agent for router
        """

        def new_active_agent():
            agents = self.get_active_l3_agents_for_router(router_id)
            new_agents = [x for x in agents if x['host'] != from_node]
            if len(new_agents) == 1:
                return new_agents[0]

        return wait(new_active_agent, timeout_seconds=timeout_seconds,
                    waiting_for="router rescheduled from {}".format(
                            from_node))

    def wait_router_migrate(self, router_id, new_node, timeout_seconds=60):
        """Wait for router migrate to l3 agent hosted on `new node`"""
        return wait(
            lambda: self.get_active_l3_agents_for_router(
                router_id)[0]['host'] == new_node,
            timeout_seconds=timeout_seconds,
            waiting_for="router migrate to l3 agent hosted on {}".format(
                new_node)
        )

    @pytest.fixture
    def variables(self, init):
        """Init Openstack variables"""
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')

    @pytest.fixture
    def router(self, variables):
        """Make router and connnect it to external network"""
        router = self.os_conn.create_router(name="router01")
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])
        return router

    @pytest.fixture
    def prepare_openstack(self, router):
        computes = self.zone.hosts.keys()[:2]
        # create 2 networks and 2 instances
        for i, hostname in enumerate(computes, 1):
            net, subnet = self.create_internal_network_with_subnet(suffix=i)
            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(self.zone.zoneName, hostname),
                key_name=self.instance_keypair.name,
                nics=[{'net-id': net['network']['id']}],
                security_groups=[self.security_group.id])

        # add floating ip to second server
        server2 = self.os_conn.nova.servers.find(name="server02")
        self.os_conn.assign_floating_ip(server2)

    @pytest.mark.parametrize('ban_count', [1, 2], ids=['once', 'twice'])
    def test_ban_l3_agent_with_active_ha_state(self, router, prepare_openstack,
                                               ban_count):
        """Ban l3-agent with ACTIVE ha_state for router

        Scenario:
            1. Create network1, network2
            2. Create router1 and connect it with network1, network2 and
                external net
            3. Boot vm1 in network1
            4. Boot vm2 in network2 and associate floating ip
            5. Add rules for ping
            6. Check what one agent has ACTIVE ha_state
                and other has STANDBY state
            7. Start ping vm2 from vm1 by floating ip
            8. Ban agent on what router scheduled with ACTIVE state
            9. Wait until router rescheduled
            10. Stop ping
            11. Check that ping lost no more than 10 packets
            12. Repeat steps 7-10 `ban_count` times
        """
        # collect l3 agents and group it by hs_state
        agents = defaultdict(list)
        agent_list = self.os_conn.get_l3_for_router(router['router']['id'])
        for agent in agent_list['agents']:
            agents[agent['ha_state']].append(agent)

        # check agents state
        assert len(agents['active']) == 1
        assert len(agents['standby']) == 2

        server1 = self.os_conn.nova.servers.find(name="server01")
        server2 = self.os_conn.nova.servers.find(name="server02")
        server2_ip = self.os_conn.get_nova_instance_ips(server2)['floating']
        controller_ip = self.env.get_nodes_by_role('controller')[0].data['ip']

        node_to_ban = agents['active'][0]['host']

        for _ in range(ban_count):

            # Ban l3 agent
            with self.background_ping(vm=server1,
                                      vm_keypair=self.instance_keypair,
                                      ip_to_ping=server2_ip) as ping_result:
                with self.env.get_ssh_to_node(controller_ip) as remote:
                    logger.info("Ban L3 agent on node {0}".format(node_to_ban))
                    remote.check_call(
                        "pcs resource ban p_neutron-l3-agent {0}".format(
                            node_to_ban))
                    new_agent = self.wait_router_rescheduled(
                        router_id=router['router']['id'],
                        from_node=node_to_ban)
                    node_to_ban = new_agent['host']

            assert ping_result['sended'] - ping_result['received'] < 10

    def test_ban_all_l3_agents_and_clear_them(self, router, prepare_openstack):
        """Disable all l3 agents and enable them

        Scenario:
            1. Create network1, network2
            2. Create router1 and connect it with network1, network2 and
                external net
            3. Boot vm1 in network1
            4. Boot vm2 in network2 and associate floating ip
            5. Add rules for ping
            6. Disable all p_neutron-l3-agent
            7. Wait until all agents died
            8. Enable all p_neutron-l3-agent
            9. Wait until all agents alive
            10. Check ping vm2 from vm1 by floating ip
        """
        server1 = self.os_conn.nova.servers.find(name="server01")
        server2 = self.os_conn.nova.servers.find(name="server02")
        server2_ip = self.os_conn.get_nova_instance_ips(server2)['floating']

        agents = self.os_conn.get_l3_for_router(router['router']['id'])
        agent_ids = [x['id'] for x in agents['agents']]
        controller = self.env.get_nodes_by_role('controller')[0]
        with controller.ssh() as remote:
            logger.info('disable all l3 agents')
            remote.check_call('pcs resource disable p_neutron-l3-agent')
            self.os_conn.wait_agents_down(agent_ids)
            logger.info('enable all l3 agents')
            remote.check_call('pcs resource enable p_neutron-l3-agent')
            self.os_conn.wait_agents_alive(agent_ids)

        self.check_ping_from_vm(vm=server1, vm_keypair=self.instance_keypair,
                                ip_to_ping=server2_ip)

    def test_delete_ns_for_active_router(self, router, prepare_openstack):
        """Delete namespace for router on node with ACTIVE ha_state

        Scenario:
            1. Create network1, network2
            2. Create router1 and connect it with network1, network2 and
                external net
            3. Boot vm1 in network1
            4. Boot vm2 in network2 and associate floating ip
            5. Add rules for ping
            6. Find node with active ha_state for router
            7. Start ping vm2 from vm1 by floating ip
            8. Delete namespace for router on node with ACTIVE ha_state
            9. Stop ping
            10. Check that ping lost no more than 10 packets
        """

        server1 = self.os_conn.nova.servers.find(name="server01")
        server2 = self.os_conn.nova.servers.find(name="server02")
        server2_ip = self.os_conn.get_nova_instance_ips(server2)['floating']

        agents = self.get_active_l3_agents_for_router(router['router']['id'])
        hostname = agents[0]['host']
        node_ip = self.env.find_node_by_fqdn(hostname).data['ip']

        # Delete namespace
        with self.background_ping(vm=server1, vm_keypair=self.instance_keypair,
                                  ip_to_ping=server2_ip) as ping_result:
            with self.env.get_ssh_to_node(node_ip) as remote:
                logger.info(("Delete namespace for router `router01` "
                             "on {0}").format(node_ip))
                remote.check_call(
                    "ip netns delete qrouter-{0}".format(
                        router['router']['id']))

        assert ping_result['sended'] - ping_result['received'] < 10

    def test_destroy_primary_controller(self, router, prepare_openstack,
                                        env_name):
        """Destroy primary controller (l3 agent on it should be
            with ACTIVE ha_state)

        Scenario:
            1. Create network1, network2
            2. Create router1 and connect it with network1, network2 and
                external net
            3. Boot vm1 in network1
            4. Boot vm2 in network2 and associate floating ip
            5. Add rules for ping
            6. Find node with active ha_state for router
            7. If node from step 6 isn't primary controller,
                reschedule router1 to primary by banning all another
                and then clear them
            8. Start ping vm2 from vm1 by floating ip
            9. Destroy primary controller
            10. Stop ping
            11. Check that ping lost no more than 10 packets
        """
        router_id = router['router']['id']
        agents = self.get_active_l3_agents_for_router(router_id)
        l3_agent_controller = self.env.find_node_by_fqdn(agents[0]['host'])
        primary_controller = self.env.primary_controller
        other_controllers = [x for x
                             in self.env.get_nodes_by_role('controller')
                             if x != primary_controller]

        # Rescedule active l3 agent to primary if needed
        if primary_controller != l3_agent_controller:
            with primary_controller.ssh() as remote:
                for node in other_controllers:
                    remote.check_call(
                        'pcs resource ban p_neutron-l3-agent {}'.format(
                            node.data['fqdn']))
                self.wait_router_migrate(router_id,
                                         primary_controller.data['fqdn'])
                for node in other_controllers:
                    remote.check_call(
                        'pcs resource clear p_neutron-l3-agent {}'.format(
                            node.data['fqdn']))

        server1 = self.os_conn.nova.servers.find(name="server01")
        server2 = self.os_conn.nova.servers.find(name="server02")
        server2_ip = self.os_conn.get_nova_instance_ips(server2)['floating']

        logger.info("Destroy primary controller {}".format(
            primary_controller.data['fqdn']))
        devops_node = DevopsClient.get_node_by_mac(
            env_name=env_name, mac=primary_controller.data['mac'])
        devops_node.destroy()

        self.wait_router_rescheduled(router_id=router['router']['id'],
                                     from_node=primary_controller.data['fqdn'],
                                     timeout_seconds=5 * 60)

        self.check_ping_from_vm(vm=server1, vm_keypair=self.instance_keypair,
                                ip_to_ping=server2_ip)

    def test_ban_l3_agent_for_many_routers(self, variables):
        """Ban agent for many routers

        Scenario:
            1. Create 19 nets, subnets, routers.
            2. Create network20, network21
            3. Create router20_21 and connect it with network20, network21
            4. Boot vm1 in network20
            5. Boot vm2 in network21
            6. Add rules for ping
            7. Start ping beetween vms
            8. Ban active agent for router between vms
            9. Check lost pings not more 10 packets
        """
        # Update quota
        tenant = self.os_conn.neutron.get_quotas_tenant()
        tenant_id = tenant['tenant']['tenant_id']
        self.os_conn.neutron.update_quota(
            tenant_id,
            {
                'quota': {
                    'network': 30,
                    'router': 30,
                    'subnet': 30,
                    'port': 90
                }
            })
        # Create 19 nets, subnets, routers
        for i in range(1, 20):
            net, subnet = self.create_internal_network_with_subnet(suffix=i)
            router = self.os_conn.create_router(name="router01")
            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])

        # Create 2 networks, subnets, vms, add router between subnets
        router20_21 = self.os_conn.create_router(name="router01")
        for i in range(20, 22):
            net, subnet = self.create_internal_network_with_subnet(suffix=i)
            self.os_conn.router_interface_add(
                router_id=router20_21['router']['id'],
                subnet_id=subnet['subnet']['id'])
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone=self.zone.zoneName,
                key_name=self.instance_keypair.name,
                nics=[{'net-id': net['network']['id']}],
                security_groups=[self.security_group.id])

        server20 = self.os_conn.nova.servers.find(name='server20')
        server21 = self.os_conn.nova.servers.find(name='server21')
        server21_ip = self.os_conn.get_nova_instance_ips(server21)['fixed']

        agent = self.get_active_l3_agents_for_router(
            router20_21['router']['id'])[0]
        node_to_ban = agent['host']

        # Ban l3 agent
        with self.background_ping(vm=server20,
                                  vm_keypair=self.instance_keypair,
                                  ip_to_ping=server21_ip) as ping_result:
            with self.env.leader_controller.ssh() as remote:
                logger.info("Ban L3 agent on node {0}".format(node_to_ban))
                remote.check_call(
                    "pcs resource ban p_neutron-l3-agent {0}".format(
                        node_to_ban))
                new_agent = self.wait_router_rescheduled(
                    router_id=router['router']['id'],
                    from_node=node_to_ban)
                node_to_ban = new_agent['host']

        assert ping_result['sended'] - ping_result['received'] < 10

    def test_ban_active_l3_agent_with_external_connectivity(self, router,
                                                            prepare_openstack):
        """Ban l3-agent with ACTIVE ha_state for router and check external ping

         Steps:
            1. Create network net01, subnet net01_subnet
            2. Create router with gateway to external net and
               interface with net01
            3. Launch instance and associate floating IP
            4. Check ping from instance to google DNS
            5. Ban active l3 agent
            6. Wait until router rescheduled
            7. Stop ping
            8. Check that ping lost less than 40 packets
        """
        instance = self.os_conn.nova.servers.find(name="server02")
        controller_ip = self.env.get_nodes_by_role('controller')[0].data['ip']

        active_agents = self.get_active_l3_agents_for_router(
            router['router']['id'])
        node_to_ban = active_agents[0]['host']

        # Ban l3 agent
        with self.background_ping(
                vm=instance,
                vm_keypair=self.instance_keypair,
                ip_to_ping=settings.PUBLIC_TEST_IP) as ping_result:
            with self.env.get_ssh_to_node(controller_ip) as remote:
                logger.info("Ban L3 agent on node {0}".format(node_to_ban))
                remote.check_call(
                    "pcs resource ban p_neutron-l3-agent {0}".format(
                        node_to_ban))
                self.wait_router_rescheduled(
                    router_id=router['router']['id'],
                    from_node=node_to_ban)

        assert (ping_result['sended'] - ping_result['received']) < 40

    def test_move_router_iface_to_down_state(self, router, prepare_openstack):
        """Move router ha-interface down and check ping.

         Steps:
            1. Create network net01, subnet net01_subnet
            2. Create router with gateway to external net and
               interface with net01
            3. Launch instance and associate floating IP
            4. Check ping from instance to google DNS
            5. Find node with active agent for router
            6. Move router interface to down state on founded controller:
               ip netns exec qrouter-<router_id> ip link set dev ha-<id> down
            7. Wait until router rescheduled
            8. Stop ping
            9. Check that ping lost less than 10 packets
        """
        instance = self.os_conn.nova.servers.find(name="server01")
        router_id = router['router']['id']

        active_agents = self.get_active_l3_agents_for_router(router_id)
        active_hostname = active_agents[0]['host']
        active_node = self.env.find_node_by_fqdn(active_hostname)

        ports_list_for_router = self.os_conn.neutron.list_ports(
            device_owner='network:router_ha_interface',
            device_id=router_id)['ports']
        active_l3_ha_port_for_router_id = [
            port for port in ports_list_for_router
            if port['binding:host_id'] == active_hostname][0]['id']
        active_ha_iface_id = 'ha-{}'.format(
            active_l3_ha_port_for_router_id[:11])

        # Ban l3 agent
        with self.background_ping(
                vm=instance,
                vm_keypair=self.instance_keypair,
                ip_to_ping=settings.PUBLIC_TEST_IP) as ping_result:
            with active_node.ssh() as remote:
                logger.info("Move down ha-port on router")
                remote.check_call(
                    "ip netns exec qrouter-{router_id} "
                    "ip link set dev {iface_id} down".format(
                        router_id=router_id, iface_id=active_ha_iface_id))
                self.wait_router_rescheduled(
                    router_id=router['router']['id'],
                    from_node=active_hostname)

        assert (ping_result['sended'] - ping_result['received']) < 10
