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

import pytest

from devops.helpers.helpers import wait

from mos_tests import settings
from tools.settings import logger


class NotFound(Exception):
    message = "Not Found."


@pytest.mark.usefixtures("check_ha_env", "check_several_computes", "setup")
class TestL3Agent(object):

    def get_node_with_dhcp(self, net_id):
        nodes = self.os_conn.get_node_with_dhcp_for_network(net_id)
        if not nodes:
            raise NotFound("Nodes with dhcp for network with id:{}"
                           " not found.".format(net_id))

        return self.env.find_node_by_fqdn(nodes[0])

    def run_on_vm(self, vm, vm_keypair, command, vm_login="cirros"):
        command = command.replace('"', r'\"')
        net_name = [x for x in vm.addresses if len(vm.addresses[x]) > 0][0]
        vm_ip = vm.addresses[net_name][0]['addr']
        net_id = self.os_conn.neutron.list_networks(
            name=net_name)['networks'][0]['id']
        dhcp_namespace = "qdhcp-{0}".format(net_id)
        devops_node = self.get_node_with_dhcp(net_id)
        _ip = devops_node.data['ip']
        with self.env.get_ssh_to_node(_ip) as remote:
            res = remote.execute(
                'ip netns list | grep -q {0}'.format(dhcp_namespace)
            )
            if res['exit_code'] != 0:
                raise Exception("Network namespace '{0}' doesn't exist on "
                                "remote slave!".format(dhcp_namespace))
            key_path = '/tmp/instancekey_rsa'
            res = remote.execute(
                'echo "{0}" > {1} ''&& chmod 400 {1}'.format(
                    vm_keypair.private_key, key_path))
            cmd = (
                ". openrc; ip netns exec {ns} ssh -i {key_path}"
                " -o 'StrictHostKeyChecking no'"
                " {vm_login}@{vm_ip} \"{command}\""
            ).format(
                ns=dhcp_namespace,
                key_path=key_path,
                vm_login=vm_login,
                vm_ip=vm_ip,
                command=command)
            err_msg = ("SSH command:\n{command}\nwas not completed with "
                       "exit code 0 after 3 attempts with 1 minute timeout.")
            results = []

            def run(cmd):
                results.append(remote.execute(cmd))
                return results[-1]

            wait(lambda: run(cmd)['exit_code'] == 0,
                 interval=60, timeout=3 * 60,
                 timeout_msg=err_msg.format(command=cmd))
            return results[-1]

    def check_ping_from_vm(self, vm, vm_keypair, ip_to_ping=None):
        if ip_to_ping is None:
            ip_to_ping = settings.PUBLIC_TEST_IP
        cmd = "ping -c1 {ip}".format(ip=ip_to_ping)
        res = self.run_on_vm(vm, vm_keypair, cmd)
        assert (0 == res['exit_code'],
                     'Instance has no connectivity, exit code {0},'
                     'stdout {1}, stderr {2}'.format(res['exit_code'],
                                                     res['stdout'],
                                                     res['stderr'])
        )

    def check_vm_connectivity(self):
        """Check that all vms can ping each other and public ip"""
        servers = self.os_conn.get_servers()
        for server1 in servers:
            for server2 in servers:
                if server1 == server2:
                    continue
                for ip in (
                    self.os_conn.get_nova_instance_ips(server2).values() +
                    [settings.PUBLIC_TEST_IP]
                ):
                    self.check_ping_from_vm(server1, self.instance_keypair, ip)

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
            remote.execute(
                "pcs resource ban p_neutron-l3-agent {0}".format(node_with_l3))

        logger.info("Ban L3 agent on node {0}".format(node_with_l3))

        # wait for l3 agent died
        if wait_for_die:
            wait(
                lambda: self.os_conn.get_l3_for_router(
                    router['id'])['agents'][0]['alive'] is False,
                timeout=60 * 3, timeout_msg="L3 agent is alive"
            )

        # Wait to migrate l3 agent on new controller
        if wait_for_migrate:
            err_msg = "l3 agent wasn't banned, it is still {0}"
            wait(lambda: not node_with_l3 == self.os_conn.get_l3_agent_hosts(
                 router['id'])[0], timeout=60 * 3,
                 timeout_msg=err_msg.format(node_with_l3))
        return node_with_l3

    def clear_l3_agent(self, _ip, router_name, node):
        """Clear L3 agent ban and wait until router moved to this node

        Clear previously banned L3 agent on node wait until ruter moved to this
        node

        :param _ip: ip of server to to execute clear command
        :param router_name: name of router to wait until it move to node
        :param node: name of node to clear
        """
        with self.env.get_ssh_to_node(_ip) as remote:
            remote.execute(
                "pcs resource clear p_neutron-l3-agent {0}".format(node))

        logger.info("Clear L3 agent on node {0}".format(node))

    def prepare_openstack(self, fuel, env, os_conn):
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
        self.fuel = fuel
        self.env = env
        self.os_conn = os_conn

        exist_networks = self.os_conn.list_networks()['networks']
        ext_network = [x for x in exist_networks
                       if x.get('router:external')][0]
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.hosts = self.zone.hosts.keys()[:2]
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')

        # create router
        router = self.os_conn.create_router(name="router01")
        self.os_conn.router_gateway_add(router_id=router['router']['id'],
                                        network_id=ext_network['id'])

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
        self.check_vm_connectivity()

    @pytest.mark.parametrize('ban_count', [1, 2], ids=['single', 'twice'])
    def test_ban_one_l3_agent(self, fuel, env, os_conn, ban_count):
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
                (e.g. pcs resource ban p_neutron-l3-agent
                node-3.test.domain.local)
            10. wait some time (about 20-30) while pcs resource and
                neutron agent-list will show that it is dead
            11. Check that router1 was rescheduled
            12. Boot vm3 in network1
            13. ping 8.8.8.8, vm1 (both ip), vm2 (fixed ip) and vm3 (fixed ip)
                from each other

        Duration 30m

        """
        self.prepare_openstack(fuel, env, os_conn)
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
        self.check_vm_connectivity()
