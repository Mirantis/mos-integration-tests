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

from mos_tests.neutron.python_tests.base import TestBase


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
    def background_ping(self, vm, vm_keypair, ip_to_ping):
        """Start ping from `vm` to `ip_to_ping` before enter and stop it after

        Return dict with ping stat
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
                if ping_info.group_len >= 50:
                    break
            stdin.write(chr(signal.SIGINT))
            stdin.flush()
            chan.close()

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

        def new_active_agent(prev_node):
            agents = self.os_conn.get_l3_for_router(router['router']['id'])
            new_agents = [x for x in agents['agents']
                          if x['ha_state'] == 'active'
                          and x['host'] != prev_node and x['alive'] is True]
            if len(new_agents) == 1:
                return new_agents[0]

        for _ in range(ban_count):

            # Ban l3 agent
            with self.background_ping(vm=server1,
                                      vm_keypair=self.instance_keypair,
                                      ip_to_ping=server2_ip
            ) as ping_result:
                with self.env.get_ssh_to_node(controller_ip) as remote:
                    logger.info("Ban L3 agent on node {0}".format(node_to_ban))
                    remote.execute(
                        "pcs resource ban p_neutron-l3-agent {0}".format(
                            node_to_ban))
                    waiting_for = "router rescheduled from {}".format(
                            node_to_ban)
                    node_to_ban = wait(lambda: new_active_agent(node_to_ban),
                                       timeout_seconds=60,
                                       waiting_for=waiting_for)

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
            remote.check_call('pcs resource disable p_neutron-l3-agent')
            self.os_conn.wait_agents_down(agent_ids)
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

        agents = self.os_conn.get_l3_for_router(router['router']['id'])
        hostname = [x['host'] for x in agents['agents']
                    if x['ha_state'] == 'active' and x['alive'] is True][0]
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
