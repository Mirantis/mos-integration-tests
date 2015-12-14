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

from tools.settings import logger
from mos_tests.neutron.python_tests import base


@pytest.mark.usefixtures("check_ha_env", "check_several_computes", "setup")
class TestDHCPAgent(base.TestBase):
    """Check DHCP agents rescheduling."""

    def create_internal_network_with_subnet(self, suffix=1):
        """Create network with subnet

        :param suffix: desired integer suffix to names of network, subnet
        :returns network and subnet tuple
        """
        network = self.os_conn.create_network(name='net%02d' % suffix)
        subnet = self.os_conn.create_subnet(
            network_id=network['network']['id'],
            name='net%02d__subnet' % suffix,
            cidr="192.168.%d.0/24" % suffix)
        return network, subnet

    def create_router_between_nets(self, ext_net, subnet, suffix=1):
        """Create router between external network and sub network.

        :param ext_net: external network to set gateway
        :param subnet: subnet which for provide route to external network
        :param suffix: desired integer suffix to names of router

        :returns created router
        """
        router = self.os_conn.create_router(name='router%02d' % suffix)
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=ext_net['id'])

        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])
        return router

    def ban_dhcp_agent(self, host, network_name, wait_for_migrate=True):
        """Ban DHCP agent and wait until agents rescheduling.

        Ban dhcp agent on same node as network placed and wait until agents
        rescheduling

        :param host: host or ip of controller onto execute ban command
        :param network_name: name of network to determine node with dhcp agents
        :param wait_for_migrate:
            wait until dhcp-agent migrate to new controller
        :returns: name of banned node
        """
        network = self.os_conn.neutron.list_networks(
            name=network_name)['networks'][0]
        node_with_dhcp = self.os_conn.get_node_with_dhcp_for_network(
            network['id'])[0]

        # ban dhcp agent on this node
        with self.env.get_ssh_to_remote(host) as remote:
            remote.execute(
                "pcs resource ban p_neutron-dhcp-agent {0}".format(
                    node_with_dhcp))

        logger.info("Ban DHCP agent on node {0}".format(node_with_dhcp))

        # Wait to migrate dhcp agent on new controller
        if wait_for_migrate:
            err_msg = "DHCP agent wasn't banned, it is still on {0}"
            wait(
                lambda: (
                    node_with_dhcp not in
                    self.os_conn.get_node_with_dhcp_for_network(
                        network['id'])),
                timeout=60 * 3,
                timeout_msg=err_msg.format(node_with_dhcp))
        return node_with_dhcp

    def _check_dhcp_on_instance(self, vm):
            vm = self.os_conn.get_instance_detail(vm)
            srv_host = self.env.find_node_by_fqdn(
                self.os_conn.get_srv_hypervisor_name(vm))['ip']

            _floating_ip = self.os_conn.get_nova_instance_ips(vm)['floating']

            cmd = 'sudo -i cirros-dhcpc up eth0'

            with self.env.get_ssh_to_remote(srv_host) as remote:
                res = self.os_conn.execute_through_host(
                    remote, _floating_ip, cmd)

            assert 0 == res['exit_code'], \
                'DHCP client can\'t get ip, exit code {0}, stdout {1}, ' \
                'stderr {2}'.format(
                    res['exit_code'], res['stdout'], res['stderr'])

    def check_ban_dhcp_agent(self, ban_count=1):
        """Check DHCP agent migration after ban.

        :param ban_count: count of banned dhcp-agents
        """

        # init variables
        exist_networks = self.os_conn.list_networks()['networks']
        ext_net = [net for net in exist_networks
                   if net.get('router:external')][0]

        # create network with subnet and router
        int_net, sub_net = self.create_internal_network_with_subnet()
        router = self.create_router_between_nets(ext_net, sub_net)

        # create instance and assign floating ip to it
        instance = self.os_conn.create_server_for_migration(
            label=int_net['network']['name'],
            router=router)

        self.os_conn.assign_floating_ip(instance)

        # check dhcp client on instance
        self._check_dhcp_on_instance(vm=instance)

        # get dhcp agents and ban some of it
        net_id = int_net['network']['id']
        agents_hosts = self.os_conn.get_node_with_dhcp_for_network(net_id)
        controller_host = self.env.find_node_by_fqdn(
            agents_hosts[0])['ip']

        for _ in range(ban_count):
            self.ban_dhcp_agent(host=controller_host, network_name='net01')

        # check dhcp client on instance
        self._check_dhcp_on_instance(vm=instance)

        # check dhcp agent nodes after rescheduling
        new_agents_hosts = self.os_conn.get_node_with_dhcp_for_network(net_id)
        err_msg = ('Rescheduling failed, agents list after and '
                   'before scheduling are same: '
                   'old agents hosts - {0}, '
                   'new agents hosts - {1}'.format(agents_hosts,
                                                   new_agents_hosts))
        assert sorted(agents_hosts) != sorted(new_agents_hosts), err_msg

    @pytest.mark.parametrize('ban_count', [1, 2])
    def test_ban_one_dhcp_agent_vlan(self, ban_count):
        """Check dhcp-agent rescheduling after dhcp-agent dies on vlan.

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network net01, subnet net01_subnet
            3. Create router with gateway to external net and
               interface with net01
            4. Launch instance and associate floating IP
            5. Run dhcp-client in instance's console: sudo cirros-dhcpc up eth0
            6. Look on what DHCP-agents chosen network is:
               neutron dhcp-agent-list-hosting-net <network_name>
            7. Ban one DHCP-agent on what chosen network is:
               pcs resource ban p_neutron-dhcp-agent <node>
            8. Run dhcp-client in instance's console: sudo cirros-dhcpc up eth0
            9. Check that this network is on other dhcp-agent and
               other health dhcp-agent:
               neutron dhcp-agent-list-hosting-net <network_name>

        Duration 30m

        """
        import pydevd
        pydevd.settrace('172.16.68.146', port=20001,
                        stdoutToServer=True, stderrToServer=True)
        self.check_ban_dhcp_agent(ban_count=ban_count)
