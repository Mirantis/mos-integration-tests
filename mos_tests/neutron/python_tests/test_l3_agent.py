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

import logging

from neutronclient.common.exceptions import NeutronClientException
import pytest

from mos_tests.environment.devops_client import DevopsClient
from mos_tests.functions.common import wait
from mos_tests.functions import network_checks
from mos_tests.neutron.python_tests.base import TestBase


logger = logging.getLogger(__name__)


@pytest.mark.check_env_(
    'is_ha '
    'and has_2_or_more_computes '
    'and not(is_dvr or is_l3_ha)')
@pytest.mark.usefixtures("setup")
class TestL3Agent(TestBase):

    @pytest.fixture(autouse=True)
    def prepare_openstack(self, init):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create network1, network2
            2. Create router1 and connect it with network1, network2 and
                external net
            3. Boot vm1 in network1 and associate floating ip
            4. Boot vm2 in network2
            5. Add rules for ping
            6. Ping 8.8.8.8, vm1 (both ip) and vm2 (fixed ip) from each other
        """
        # init variables
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.hosts = self.zone.hosts.keys()[:2]
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')

        # create router
        router = self.os_conn.create_router(name="router01")
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])

        # create 2 networks and 2 instances
        for i, hostname in enumerate(self.hosts, 1):
            network = self.os_conn.create_network(name='net%02d' % i)
            subnet = self.os_conn.create_subnet(
                network_id=network['network']['id'],
                name='net%02d__subnet' % i,
                cidr="192.168.%d.0/24" % i)
            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(self.zone.zoneName, hostname),
                key_name=self.instance_keypair.name,
                nics=[{'net-id': network['network']['id']}],
                security_groups=[self.security_group.id])

        # add floating ip to first server
        server1 = self.os_conn.nova.servers.find(name="server01")
        self.os_conn.assign_floating_ip(server1)

        # check pings
        network_checks.check_vm_connectivity(self.env, self.os_conn)

    def ban_l3_agent(self, _ip, router_name, wait_for_migrate=True,
                     wait_for_die=True):
        """Ban L3 agent and wait until router rescheduling

        Ban L3 agent on same node as router placed and wait until router
        rescheduling

        :param _ip: ip of server to to execute ban command
        :param router_name: name of router to determine node with L3 agent
        :param wait_for_migrate: wait until router migrate to new controller
        :param wait_for_die: wait for l3 agent died
        :returns: str -- name of banned node
        """
        router = self.os_conn.neutron.list_routers(
            name=router_name)['routers'][0]
        node_with_l3 = self.os_conn.get_l3_agent_hosts(router['id'])[0]

        # ban l3 agent on this node
        with self.env.get_ssh_to_node(_ip) as remote:
            remote.check_call(
                "pcs resource ban neutron-l3-agent {0}".format(node_with_l3))

        logger.info("Ban L3 agent on node {0}".format(node_with_l3))

        # wait for l3 agent died
        if wait_for_die:
            wait(
                lambda: self.os_conn.get_l3_for_router(
                    router['id'])['agents'][0]['alive'] is False,
                timeout_seconds=60 * 3, waiting_for="L3 agent is die",
                sleep_seconds=(1, 60)
            )

        # Wait to migrate l3 agent on new controller
        if wait_for_migrate:
            waiting_for = "l3 agent migrate from {0}"
            wait(lambda: not node_with_l3 == self.os_conn.get_l3_agent_hosts(
                 router['id'])[0], timeout_seconds=60 * 3,
                 waiting_for=waiting_for.format(node_with_l3),
                 sleep_seconds=(1, 60))
        return node_with_l3

    def clear_l3_agent(self, _ip, router_name, node, wait_for_alive=False):
        """Clear L3 agent ban and wait until router moved to this node

        Clear previously banned L3 agent on node wait until router moved
        to this node

        :param _ip: ip of server to to execute clear command
        :param router_name: name of router to wait until it move to node
        :param node: name of node to clear
        :param wait_for_alive:
        """
        router = self.os_conn.neutron.list_routers(
            name=router_name)['routers'][0]
        with self.env.get_ssh_to_node(_ip) as remote:
            remote.check_call(
                "pcs resource clear neutron-l3-agent {0}".format(node))

        logger.info("Clear L3 agent on node {0}".format(node))

        # wait for l3 agent alive
        if wait_for_alive:
            wait(
                lambda: self.os_conn.get_l3_for_router(
                    router['id'])['agents'][0]['alive'] is True,
                timeout_seconds=60 * 3, waiting_for="L3 agent is alive",
                sleep_seconds=(1, 60)
            )

    def drop_rabbit_port(self, router_name):
        """Drop rabbit port and wait until router rescheduling

        Drop rabbit port on same node as router placed and wait until router
        rescheduling

        :param router_name: name of router to determine node with L3 agent
        """
        router = self.os_conn.neutron.list_routers(
            name=router_name)['routers'][0]
        node_with_l3 = self.os_conn.get_l3_agent_hosts(router['id'])[0]

        devops_node = self.env.find_node_by_fqdn(node_with_l3)
        ip = devops_node.data['ip']

        # ban l3 agent on this node
        with self.env.get_ssh_to_node(ip) as remote:
            remote.execute(
                "iptables -I OUTPUT 1 -p tcp --dport 5673 -j DROP")

        logger.info("Drop rabbit port on node {}".format(node_with_l3))

        # wait for l3 agent died
        wait(
            lambda: self.os_conn.get_l3_for_router(
                router['id'])['agents'][0]['alive'] is False,
            timeout_seconds=60 * 3, waiting_for="L3 agent is died",
            sleep_seconds=(1, 60)
        )

        # Wait to migrate l3 agent on new controller
        waiting_for = "l3 agent migrated from {0}"
        wait(lambda: not node_with_l3 == self.os_conn.get_l3_agent_hosts(
             router['id'])[0], timeout_seconds=60 * 3,
             waiting_for=waiting_for.format(node_with_l3),
             sleep_seconds=(1, 60))

    @pytest.mark.testrail_id('542603', params={'ban_count': 1})
    @pytest.mark.testrail_id('542604', params={'ban_count': 2})
    @pytest.mark.parametrize('ban_count', [1, 2], ids=['once', 'twice'])
    def test_ban_one_l3_agent(self, ban_count):
        """Check l3-agent rescheduling after l3-agent dies on vlan

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network1, network2
            3. Create router1 and connect it with network1, network2 and
               external net
            4. Boot vm1 in network1 and associate floating ip
            5. Boot vm2 in network2
            6. Add rules for ping
            7. ping 8.8.8.8, vm1 (both ip) and vm2 (fixed ip) from each other
            8. get node with l3 agent on what is router1
            9. ban this l3 agent on the node with pcs
                (e.g. pcs resource ban neutron-l3-agent
                node-3.test.domain.local)
            10. wait some time (about 20-30) while pcs resource and
                neutron agent-list will show that it is dead
            11. Check that router1 was rescheduled
            12. Boot vm3 in network1
            13. ping 8.8.8.8, vm1 (both ip), vm2 (fixed ip) and vm3 (fixed ip)
                from each other

        Duration 10m

        """
        net_id = self.os_conn.neutron.list_networks(
            name="net01")['networks'][0]['id']
        devops_node = self.get_node_with_dhcp(net_id)
        ip = devops_node.data['ip']

        # ban l3 agent
        for _ in range(ban_count):
            self.ban_l3_agent(_ip=ip, router_name="router01")

        # create another server on net01
        net01 = self.os_conn.nova.networks.find(label="net01")
        self.os_conn.create_server(
            name='server03',
            availability_zone='{}:{}'.format(self.zone.zoneName,
                                             self.hosts[0]),
            key_name=self.instance_keypair.name,
            nics=[{'net-id': net01.id}],
            security_groups=[self.security_group.id])

        # check pings
        network_checks.check_vm_connectivity(self.env, self.os_conn)

    @pytest.mark.testrail_id('542605')
    def test_ban_l3_agents_and_clear_last(self):
        """Ban all l3-agents, clear last of them and check health of l3-agent

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network1, network2
            3. Create router1 and connect it with network1, network2 and
               external net
            4. Boot vm1 in network1 and associate floating ip
            5. Boot vm2 in network2
            6. Add rules for ping
            7. ping 8.8.8.8, vm1 (both ip) and vm2 (fixed ip) from each other
            8. Ban l3-agent on what router1 is
            9. Wait for route rescheduling
            10. Repeat steps 7-8 twice
            11. Clear last L3 agent
            12. Check that router moved to the health l3-agent
            13. Boot one more VM (VM3) in network1
            14. Boot vm3 in network1
            15. ping 8.8.8.8, vm1 (both ip), vm2 (fixed ip) and vm3 (fixed ip)
                from each other

        Duration 10m

        """
        net_id = self.os_conn.neutron.list_networks(
            name="net01")['networks'][0]['id']
        devops_node = self.get_node_with_dhcp(net_id)
        ip = devops_node.data['ip']

        # ban l3 agents
        for _ in range(2):
            self.ban_l3_agent(router_name="router01", _ip=ip)
        last_banned_node = self.ban_l3_agent(router_name="router01",
                                             _ip=ip,
                                             wait_for_migrate=False)

        # clear last banned l3 agent
        self.clear_l3_agent(_ip=ip,
                            router_name="router01",
                            node=last_banned_node,
                            wait_for_alive=True)

        # create another server on net01
        net01 = self.os_conn.nova.networks.find(label="net01")
        self.os_conn.create_server(
            name='server03',
            availability_zone='{}:{}'.format(self.zone.zoneName,
                                             self.hosts[0]),
            key_name=self.instance_keypair.name,
            nics=[{'net-id': net01.id}],
            security_groups=[self.security_group.id])

        # check pings
        network_checks.check_vm_connectivity(self.env, self.os_conn)

    @pytest.mark.testrail_id('542606')
    def test_ban_l3_agents_and_clear_first(self):
        """Ban all l3-agents, clear first of them and check health of l3-agent

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network1, network2
            3. Create router1 and connect it with network1, network2 and
               external net
            4. Boot vm1 in network1 and associate floating ip
            5. Boot vm2 in network2
            6. Add rules for ping
            7. ping 8.8.8.8, vm1 (both ip) and vm2 (fixed ip) from each other
            8. Ban l3-agent on what router1 is
            9. Wait for route rescheduling
            10. Repeat steps 7-8
            11. Ban l3-agent on what router1 is
            12. Clear first banned L3 agent
            13. Check that router moved to the health l3-agent
            14. Boot one more VM (VM3) in network1
            15. Boot vm3 in network1
            16. ping 8.8.8.8, vm1 (both ip), vm2 (fixed ip) and vm3 (fixed ip)
                from each other

        Duration 10m

        """
        net_id = self.os_conn.neutron.list_networks(
            name="net01")['networks'][0]['id']
        devops_node = self.get_node_with_dhcp(net_id)
        ip = devops_node.data['ip']

        # ban l3 agents
        first_banned_node = self.ban_l3_agent(router_name="router01", _ip=ip)
        self.ban_l3_agent(router_name="router01", _ip=ip)
        self.ban_l3_agent(router_name="router01",
                          _ip=ip,
                          wait_for_migrate=False,
                          wait_for_die=False)

        # clear first banned l3 agent
        self.clear_l3_agent(_ip=ip,
                            router_name="router01",
                            node=first_banned_node,
                            wait_for_alive=True)

        # wait for router migrate to cleared node
        router = self.os_conn.neutron.list_routers(
            name='router01')['routers'][0]
        waiting_for = "l3 agent wasn't migrate to {0}"
        wait(lambda: first_banned_node == self.os_conn.get_l3_agent_hosts(
             router['id'])[0], timeout_seconds=60 * 3,
             waiting_for=waiting_for.format(first_banned_node),
             sleep_seconds=(1, 60))

        # create another server on net01
        net01 = self.os_conn.nova.networks.find(label="net01")
        self.os_conn.create_server(
            name='server03',
            availability_zone='{}:{}'.format(self.zone.zoneName,
                                             self.hosts[0]),
            key_name=self.instance_keypair.name,
            nics=[{'net-id': net01.id}],
            security_groups=[self.security_group.id])

        # check pings
        network_checks.check_vm_connectivity(self.env, self.os_conn)

    @pytest.mark.testrail_id('542607')
    def test_l3_agent_after_drop_rabbit_port(self):
        """Drop rabbit port and check l3-agent work

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network1, network2
            3. Create router1 and connect it with network1, network2 and
               external net
            4. Boot vm1 in network1 and associate floating ip
            5. Boot vm2 in network2
            6. Add rules for ping
            7. ping 8.8.8.8, vm1 (both ip) and vm2 (fixed ip) from each other
            8. with iptables in CLI drop rabbit's port #5673 on what router1 is
            9. Wait for route rescheduling
            10. Check that router moved to the health l3-agent
            11. Boot one more VM (VM3) in network1
            12. Boot vm3 in network1
            13. ping 8.8.8.8, vm1 (both ip), vm2 (fixed ip) and vm3 (fixed ip)
                from each other

        Duration 10m

        """
        # drop rabbit port
        self.drop_rabbit_port(router_name="router01")

        # check pings
        network_checks.check_vm_connectivity(self.env, self.os_conn)

    @pytest.mark.testrail_id('542608')
    def test_ban_l3_agents_many_times(self):
        """Ban l3-agent many times and check health of l3-agent

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network1, network2
            3. Create router1 and connect it with network1, network2 and
               external net
            4. Boot vm1 in network1 and associate floating ip
            5. Boot vm2 in network2
            6. Add rules for ping
            7. ping 8.8.8.8, vm1 (both ip) and vm2 (fixed ip) from each other
            8. Ban l3-agent on what router1 is
            9. Wait for route rescheduling
            10. Repeat steps 7-8
            11. Ban l3-agent on what router1 is
            12. Wait for L3 agent dies
            13. Clear last banned L3 agent
            14. Wait for L3 agent alive
            15. Repeat steps 11-14 40 times
            16. Boot one more VM (VM3) in network1
            17. Boot vm3 in network1
            18. ping 8.8.8.8, vm1 (both ip), vm2 (fixed ip) and vm3 (fixed ip)
                from each other vm

        Duration 30m

        """
        net_id = self.os_conn.neutron.list_networks(
            name="net01")['networks'][0]['id']
        devops_node = self.get_node_with_dhcp(net_id)
        ip = devops_node.data['ip']

        # ban 2 l3 agents
        for _ in range(2):
            self.ban_l3_agent(router_name="router01", _ip=ip)

        for _ in range(40):
            # ban l3 agent
            last_banned_node = self.ban_l3_agent(router_name="router01",
                                                 _ip=ip,
                                                 wait_for_migrate=False,
                                                 wait_for_die=True)
            # clear last banned l3 agent
            self.clear_l3_agent(_ip=ip,
                                router_name="router01",
                                node=last_banned_node,
                                wait_for_alive=True)

        # check pings
        network_checks.check_vm_connectivity(self.env, self.os_conn)

    @pytest.mark.need_devops
    @pytest.mark.testrail_id('542609')
    def test_shutdown_not_primary_controller(self, env_name):
        """Shut down non-primary controller and check l3-agent work

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network1, network2
            3. Create router1 and connect it with network1, network2 and
               external net
            4. Boot vm1 in network1 and associate floating ip
            5. Boot vm2 in network2
            6. Add rules for ping
            7. ping 8.8.8.8, vm1 (both ip) and vm2 (fixed ip) from each other
            8. Check on what agents is router1
            9. If agent on primary controller move it to any other controller
            10. Destroy non primary controller
            11. Wait for L3 agent dies
            12. Check that all routers reschedule from non primary controller
            13. Boot one more VM (VM3) in network1
            14. Boot vm3 in network1
            15. ping 8.8.8.8, vm1 (both ip), vm2 (fixed ip) and vm3 (fixed ip)
                from each other vm

        Duration 10m

        """
        router = self.os_conn.neutron.list_routers(
            name='router01')['routers'][0]
        l3_agent = self.os_conn.get_l3_for_router(router['id'])['agents'][0]
        leader_node = self.env.leader_controller

        # Move router to slave l3 agent, if needed
        if leader_node.data['fqdn'] == l3_agent['host']:
            l3_agents = self.os_conn.list_l3_agents()
            leader_l3_agent = [x for x in l3_agents
                               if x['host'] == leader_node.data['fqdn']][0]
            self.os_conn.neutron.remove_router_from_l3_agent(
                leader_l3_agent['id'],
                router_id=router['id'])
            slave_l3_agents = [x for x in l3_agents if x != leader_l3_agent]
            l3_agent = slave_l3_agents[0]
            self.os_conn.neutron.add_router_to_l3_agent(
                l3_agent['id'],
                body={'router_id': router['id']})

        # Destroy node with l3 agent
        node = self.env.find_node_by_fqdn(l3_agent['host'])
        devops_node = DevopsClient.get_node_by_mac(env_name=env_name,
                                                   mac=node.data['mac'])
        if devops_node is not None:
            devops_node.destroy()
        else:
            raise Exception("Can't find devops controller node to destroy it")

        # Wait for l3 agent die
        wait(
            lambda: self.os_conn.get_l3_for_router(
                router['id'])['agents'][0]['alive'] is False,
            expected_exceptions=NeutronClientException,
            timeout_seconds=60 * 5, sleep_seconds=(1, 60, 5),
            waiting_for="L3 agent is died")

        # Wait for migrating all routers from died L3 agent
        wait(
            lambda: len(self.os_conn.neutron.list_routers_on_l3_agent(
                l3_agent['id'])['routers']) == 0,
            timeout_seconds=60 * 5, sleep_seconds=(1, 60, 5),
            waiting_for="migrating all routers from died L3 agent"
        )

        # create another server on net01
        net01 = self.os_conn.nova.networks.find(label="net01")
        self.os_conn.create_server(
            name='server03',
            availability_zone='{}:{}'.format(self.zone.zoneName,
                                             self.hosts[0]),
            key_name=self.instance_keypair.name,
            nics=[{'net-id': net01.id}],
            security_groups=[self.security_group.id])

        # check pings
        network_checks.check_vm_connectivity(self.env, self.os_conn)
