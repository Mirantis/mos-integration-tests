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

import pytest

from mos_tests.functions.common import wait
from mos_tests.neutron.python_tests import base
from mos_tests.neutron.python_tests.functions import ban_dhcp_agent


logger = logging.getLogger(__name__)


@pytest.mark.check_env_('is_ha', 'has_2_or_more_computes')
@pytest.mark.usefixtures("setup")
class TestBaseDHCPAgent(base.TestBase):
    """Base DHCP agents tests."""

    def create_cirros_instance_with_ssh(self, name='server01',
                                        net_name='net04', **kwargs):
        """Boot instance from cirros image with access by ssh.

        :param name: instance name
        :param net_name: network name
        :param kwargs: some other params to create instance
        :returns: created instance
        """
        security_group = self.os_conn.create_sec_group_for_ssh()

        network = [net.id for net in self.os_conn.nova.networks.list()
                   if net.label == net_name]

        kwargs.update({'nics': [{'net-id': network[0]}],
                       'security_groups': [security_group.name]})

        instance = self.os_conn.create_server(
            name=name, **kwargs)
        return instance

    def ban_dhcp_agent(self, node_to_ban, host, network_name=None,
                       wait_for_die=True, wait_for_rescheduling=True):
        """Ban DHCP agent and wait until agents rescheduling.

        Ban dhcp agent on same node as network placed and wait until agents
        rescheduling.

        :param node_to_ban: dhcp-agent host to ban
        :param host: host or ip of controller onto execute ban command
        :param network_name: name of network to determine node with dhcp agents
        :param wait_for_die: wait until dhcp-agent die
        :param wait_for_rescheduling: wait new dhcp-agent starts
        :returns: str, name of banned node
        """
        return ban_dhcp_agent(self.os_conn, self.env, node_to_ban, host,
                              network_name, wait_for_die,
                              wait_for_rescheduling)

    def clear_dhcp_agent(self, node_to_clear, host, network_name=None,
                         wait_for_rescheduling=True):
        """Clear DHCP agent after ban and wait until agents rescheduling.

        :param node_to_clear: dhcp-agent host to clear
        :param host: host or ip of controller onto execute ban command
        :param network_name: name of network to determine node with dhcp agents
        :param wait_for_rescheduling: wait until dhcp-agent reschedule
        :returns: str, name of cleared node
        """
        list_dhcp_agents = lambda: self.os_conn.list_all_neutron_agents(
            agent_type='dhcp', filter_attr='host')
        if network_name:
            network = self.os_conn.neutron.list_networks(
                name=network_name)['networks'][0]
            list_dhcp_agents = (
                lambda: self.os_conn.get_node_with_dhcp_for_network(
                    network['id']))

        # clear dhcp agent on provided node
        with self.env.get_ssh_to_node(host) as remote:
            remote.check_call(
                "pcs resource clear neutron-dhcp-agent {0}".format(
                    node_to_clear))

        # Wait to reschedule dhcp agent
        if wait_for_rescheduling:
            wait(
                lambda: (node_to_clear in list_dhcp_agents()),
                timeout_seconds=60 * 3,
                sleep_seconds=(1, 60, 5),
                waiting_for="DHCP agent {0} to reschedule".format(
                    node_to_clear))
        return node_to_clear

    def kill_dnsmasq(self, host):
        """Kill dnsmasq on host.

        :param host: host onto kill dnsmasq
        """
        with self.env.get_ssh_to_node(host) as remote:
            remote.execute("killall dnsmasq")

        logger.info("Kill dnsmasq on node {0}".format(host))

    def run_on_cirros_through_host(self, vm, cmd):
        """Run command on Cirros VM, connected through some host.

        :param vm: instance with cirros
        :param cmd: command to execute
        :returns: dict, result of command with code, stdout, stderr.
        """
        vm = self.os_conn.get_instance_detail(vm)
        srv_host = self.env.find_node_by_fqdn(
            self.os_conn.get_srv_hypervisor_name(vm)).data['ip']

        _floating_ip = self.os_conn.get_nova_instance_ips(vm)['floating']

        with self.env.get_ssh_to_node(srv_host) as remote:
            res = self.os_conn.execute_through_host(
                remote, _floating_ip, cmd)
        return res

    def check_dhcp_on_cirros_instance(self, vm):
        """Check dhcp client on Cirros instance.

        :param vm: instance with cirros
        """
        cmd = 'sudo -i cirros-dhcpc up eth0'
        res = self.run_on_cirros(vm, cmd)
        err_msg = (
            'DHCP client can\'t get ip, '
            'exit code {exit_code}, '
            'stdout {stdout}, stderr {stderr}'.format(**res))
        assert 0 == res['exit_code'], err_msg

    def _prepare_openstack_state(self):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create network net01, subnet net01_subnet
            2. Create router with gateway to external net and
               interface with net01
            3. Launch instance and associate floating IP
            4. Check ping from instance google DNS
            5. Check run dhcp-client in instance's console:
               sudo cirros-dhcpc up eth0
        """
        # create network with subnet and router
        int_net, sub_net = self.create_internal_network_with_subnet()
        self.net_id = int_net['network']['id']
        self.net_name = int_net['network']['name']
        router = self.create_router_between_nets(self.os_conn.ext_network,
                                                 sub_net)
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')

        # create instance and assign floating ip to it
        self.instance = self.create_cirros_instance_with_ssh(
            net_name=int_net['network']['name'],
            key_name=self.instance_keypair.name,
            router=router)

        self.os_conn.assign_floating_ip(self.instance)

        # check ping from instance and dhcp client on instance
        self.check_vm_is_available(self.instance, **self.cirros_creds)
        self.check_ping_from_cirros(vm=self.instance)
        self.check_dhcp_on_cirros_instance(vm=self.instance)


class TestBanDHCPAgent(TestBaseDHCPAgent):
    """Check DHCP agents rescheduling."""

    @pytest.fixture(autouse=True)
    def prepare_openstack_state(self, init):
        self._prepare_openstack_state()

    @pytest.mark.testrail_id('542615', params={'ban_count': 1})
    @pytest.mark.testrail_id('542616', params={'ban_count': 2})
    @pytest.mark.parametrize('ban_count', [1, 2])
    def test_ban_some_dhcp_agents(self, ban_count):
        """Check dhcp-agent rescheduling after dhcp-agent dies.

        :param ban_count: count of banned dhcp-agents

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
               pcs resource ban neutron-dhcp-agent <node>
            8. Run dhcp-client in instance's console: sudo cirros-dhcpc up eth0
            9. Check that this network is on other dhcp-agent and
               other health dhcp-agent:
               neutron dhcp-agent-list-hosting-net <network_name>

        Duration 15m

        """
        # Fixture init from method self._prepare_openstack_state
        # Get dhcp agents and ban some of it
        agents_hosts = self.os_conn.get_node_with_dhcp_for_network(self.net_id)
        controller_host = self.env.find_node_by_fqdn(
            agents_hosts[0]).data['ip']

        for identifier in range(ban_count):
            host_to_ban = agents_hosts[identifier]
            self.ban_dhcp_agent(node_to_ban=host_to_ban,
                                host=controller_host,
                                network_name=self.net_name,
                                wait_for_rescheduling=(not identifier))

        # check dhcp client on instance
        self.check_dhcp_on_cirros_instance(vm=self.instance)

        # check dhcp agent nodes after rescheduling
        new_agents_hosts = self.os_conn.get_node_with_dhcp_for_network(
            self.net_id)
        err_msg = ('Rescheduling failed, agents list after and '
                   'before scheduling are same: '
                   'old agents hosts - {0}, '
                   'new agents hosts - {1}'.format(agents_hosts,
                                                   new_agents_hosts))
        assert sorted(agents_hosts) != sorted(new_agents_hosts), err_msg

    @pytest.mark.testrail_id('542617')
    def test_ban_all_dhcp_agents_and_restart_one(self):
        """Check dhcp-agent state after ban all agents and restart one of them.

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network net01, subnet net01_subnet
            3. Create router with gateway to external net and
               interface with net01
            4. Launch instance and associate floating IP
            5. Run dhcp-client in instance's console: sudo cirros-dhcpc up eth0
            6. Look on what DHCP-agents chosen network is:
               neutron dhcp-agent-list-hosting-net <network_name>
            7. Ban both DHCP-agent on what chosen network is:
               pcs resource ban neutron-dhcp-agent <node1>
               pcs resource ban neutron-dhcp-agent <node2>
            8. Check that network is on other DHCP-agent(s)
            9. Ban other DHCP-agent(s)
            10. Clear last banned DHCP-agent
            11. Run dhcp-client in instance's console:
                sudo cirros-dhcpc up eth0
            12. Check that this network is on cleared dhcp-agent:
                neutron dhcp-agent-list-hosting-net <network_name>
            13. Check that all networks is on cleared dhcp-agent:
                neutron net-list-on-dhcp-agent <id_clr_agnt> | grep net | wc -l

        Duration 15m

        """
        # Fixture init from method self._prepare_openstack_state
        # Get dhcp agents and ban all of it
        agents = self.os_conn.get_node_with_dhcp_for_network(
            self.net_id, filter_attr=None)

        # collect all networks on dhcp agents
        agents_ids = [agent['id'] for agent in agents]
        agents_networks = [net['id'] for agent_id in agents_ids for net in
                           self.os_conn.get_networks_on_dhcp_agent(agent_id)]
        # ban first part of agents
        agents_hosts = [agent['host'] for agent in agents]
        controller_host = self.env.find_node_by_fqdn(
            agents_hosts[0]).data['ip']

        for index, host_to_ban in enumerate(agents_hosts):
            self.ban_dhcp_agent(node_to_ban=host_to_ban,
                                host=controller_host,
                                network_name=self.net_name,
                                wait_for_rescheduling=(not index))

        # ban rescheduled dhcp agents
        new_agents_hosts = self.os_conn.get_node_with_dhcp_for_network(
            self.net_id)
        last_banned = None
        for host_to_ban in new_agents_hosts:
            last_banned = self.ban_dhcp_agent(node_to_ban=host_to_ban,
                                              host=controller_host,
                                              network_name=self.net_name,
                                              wait_for_rescheduling=False)
        # check that it was other rescheduled agent after ban presented agents
        assert (
            last_banned is not None), (
            "First step DHCP agent rescheduling failed")
        # clear last banned
        cleared_agent = self.clear_dhcp_agent(node_to_clear=last_banned,
                                              host=controller_host,
                                              network_name=self.net_name)
        # check dhcp client on instance after agent clearing and rescheduling
        self.check_dhcp_on_cirros_instance(vm=self.instance)

        # check dhcp agent behaviour after clearing
        actual_agents = self.os_conn.get_node_with_dhcp_for_network(
            self.net_id)
        err_msg = ('We have to much dhcp-agent alive:'
                   'last banned - {0}, '
                   'last cleared - {1},'
                   'current actual - {2}'.format(last_banned,
                                                 cleared_agent,
                                                 actual_agents))
        # check that network of instance on last cleared agent
        assert len(actual_agents) == 1, err_msg
        assert actual_agents[0] == cleared_agent, err_msg

        # check that all networks are on last cleared agent
        cleared_agent_id = self.os_conn.get_node_with_dhcp_for_network_by_host(
            self.net_id, cleared_agent)[0]['id']
        nets_on_dhcp_agent = [net['id'] for net in
                              self.os_conn.get_networks_on_dhcp_agent(
                                  cleared_agent_id)]
        err_msg = (
            'There is not all networks on cleared agent: '
            'all existing networks - {0}, '
            'networks on cleared agent - {1}'.format(agents_networks,
                                                     nets_on_dhcp_agent))
        assert set(agents_networks) == set(nets_on_dhcp_agent), err_msg

    @pytest.mark.testrail_id('542618')
    def test_multiple_ban_dhcp_agents_and_restart_first(self, ban_count=18):
        """Check dhcp-agent state after ban all agents and restart one of them.

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network net01, subnet net01_subnet
            3. Create router with gateway to external net and
               interface with net01
            4. Launch instance and associate floating IP
            5. Run dhcp-client in instance's console:
               ``sudo cirros-dhcpc up eth0``
            6. Look on what DHCP-agents chosen network is:
               ``neutron dhcp-agent-list-hosting-net <network_name>``
            7. Clear all DHCP-agents on all controllers:
               ``pcs resource clear neutron-dhcp-agent node-1``
               ``pcs resource clear neutron-dhcp-agent node-2``
               ``pcs resource clear neutron-dhcp-agent node-3``
            8. Ban DHCP-agent on what chosen network is NOT and wait it dies:
               from primary controller:
               ``pcs resource ban neutron-dhcp-agent node-3``
               from node-3:
               ``killall dnsmasq``
            9. Kill other DHCP-agents on which instance's net is
               without waiting from primary controller:
               ``pcs resource ban neutron-dhcp-agent node-1``
               ``pcs resource ban neutron-dhcp-agent node-2``
               from node-1 and node-2:
               ``killall dnsmasq``
            10. Unban(clear) first banned DHCP-agent and wait it get up:
                ``pcs resource clear neutron-dhcp-agent node-3``
            11. Repeat 7-11 steps for 18 times
            12. Run dhcp-client in instance's console:
                ``sudo cirros-dhcpc up eth0``
            13. Check that this network is on cleared dhcp-agent:
                ``neutron dhcp-agent-list-hosting-net <network_name>``
            14. Check that all networks is on cleared dhcp-agent:
                ``neutron net-list-on-dhcp-agent <id_clr_agnt>|grep net|wc -l``

        Duration 30m

        """
        def _killing_cycle(
                controller, agent_first, agent_second, agent_free):
            # clear all agents and wait that they up
            self.clear_dhcp_agent(node_to_clear=agent_first['agent']['host'],
                                  host=controller)
            self.clear_dhcp_agent(node_to_clear=agent_second['agent']['host'],
                                  host=controller)
            self.clear_dhcp_agent(node_to_clear=agent_free['agent']['host'],
                                  host=controller)
            # ban agent without current network
            self.ban_dhcp_agent(node_to_ban=agent_free['agent']['host'],
                                host=controller, wait_for_die=False,
                                wait_for_rescheduling=False)
            self.kill_dnsmasq(agent_free['node'].data['ip'])
            self.ban_dhcp_agent(node_to_ban=agent_free['agent']['host'],
                                host=controller,
                                wait_for_rescheduling=False)
            # ban agent with current network without awaiting
            for curr_agent in (agent_first, agent_second):
                self.ban_dhcp_agent(node_to_ban=curr_agent['agent']['host'],
                                    host=controller, wait_for_die=False,
                                    wait_for_rescheduling=False)
                self.kill_dnsmasq(curr_agent['node'].data['ip'])
            # clear free dhcp agent
            self.clear_dhcp_agent(node_to_clear=agent_free['agent']['host'],
                                  host=controller)
        # Fixture init from method self._prepare_openstack_state
        # Get all dhcp agents
        all_agents = self.os_conn.list_all_neutron_agents(agent_type='dhcp')
        agents_mapping = {
            agent['host']:
                {'agent': agent,
                 'node': self.env.find_node_by_fqdn(agent['host'])}
            for agent in all_agents}
        curr_agents = self.os_conn.get_node_with_dhcp_for_network(
            net_id=self.net_id)
        # determine free of current network dhcp agent
        all_agents_hosts = agents_mapping.keys()
        free_agent = (set(all_agents_hosts) - set(curr_agents)).pop()

        # collect all networks on dhcp agents
        agents_ids = [agent['id'] for agent in all_agents]
        agents_networks = [net['id'] for agent_id in agents_ids for net in
                           self.os_conn.get_networks_on_dhcp_agent(agent_id)]
        # determine primary controller
        leader_node_ip = self.env.leader_controller.data['ip']
        for i in range(ban_count):
            logger.info('Ban iteration #{}'.format(i + 1))
            _killing_cycle(leader_node_ip,
                           agents_mapping[curr_agents[0]],
                           agents_mapping[curr_agents[1]],
                           agents_mapping[free_agent])

        # check dhcp client on instance after dhcp agents killing cycle
        self.check_dhcp_on_cirros_instance(vm=self.instance)

        # check dhcp agent behaviour after clearing
        actual_agents = self.os_conn.get_node_with_dhcp_for_network(
            self.net_id)
        err_msg = ('We have to much dhcp-agent alive: '
                   'current actual - {0}'.format(actual_agents))
        # check that network of instance on last cleared agent
        assert len(actual_agents) == 1, err_msg
        assert actual_agents[0] == free_agent, err_msg

        # check that all networks are on free agent
        free_agent_id = agents_mapping[free_agent]['agent']['id']
        nets_on_free_dhcp_agent = [
            net['id'] for net in self.os_conn.get_networks_on_dhcp_agent(
                free_agent_id)]
        err_msg = (
            'There is not all networks on free agent: '
            'all existing networks - {0}, '
            'networks on free agent - {1}'.format(agents_networks,
                                                  nets_on_free_dhcp_agent))
        assert set(agents_networks) == set(nets_on_free_dhcp_agent), err_msg

    @pytest.mark.testrail_id('542620')
    def test_ban_dhcp_agent_many_times(self, ban_count=40):
        """Check dhcp-agent state after ban all agents and restart one of them.

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network net01, subnet net01_subnet
            3. Create router with gateway to external net and
               interface with net01
            4. Launch instance and associate floating IP
            5. Run dhcp-client in instance's console:
               ``sudo cirros-dhcpc up eth0``
            6. Look on what DHCP-agents chosen network is:
               ``neutron dhcp-agent-list-hosting-net <network_name>``
            7. Ban DHCP-agent on what chosen network is NOT and wait it dies:
               ``pcs resource ban neutron-dhcp-agent node-3``
            8. Ban one of DHCP-agents on which instance's net is:
               ``pcs resource ban neutron-dhcp-agent node-1``
            9. Unban (clear) last banned DHCP-agent and wait it get up:
                ``pcs resource clear neutron-dhcp-agent node-1``
            10. Repeat 8-10 steps for 40 times
            11. Run dhcp-client in instance's console:
                ``sudo cirros-dhcpc up eth0``
            12. Check that instance networks is on two dhcp-agents:
                ``neutron dhcp-agent-list-hosting-net <network_name>``

        Duration 30m

        """
        # Fixture init from method self._prepare_openstack_state
        # Get all dhcp agents

        all_agents = self.os_conn.list_all_neutron_agents(agent_type='dhcp',
                                                          filter_attr='host')
        curr_agents = self.os_conn.get_node_with_dhcp_for_network(
            net_id=self.net_id)

        # determine primary controller
        leader_node_ip = self.env.leader_controller.data['ip']

        # determine free of current network dhcp agent and ban it
        free_agent = (set(all_agents) - set(curr_agents)).pop()

        self.ban_dhcp_agent(node_to_ban=free_agent,
                            host=leader_node_ip, wait_for_die=True,
                            wait_for_rescheduling=False)

        for i in range(ban_count):
            logger.info('Ban iteration #{}'.format(i + 1))
            # ban agent was on current network
            self.ban_dhcp_agent(node_to_ban=curr_agents[0],
                                host=leader_node_ip, wait_for_die=True,
                                wait_for_rescheduling=False)

            # clear free dhcp agent and wait for reschedule it
            self.clear_dhcp_agent(node_to_clear=curr_agents[0],
                                  host=leader_node_ip)

        # check dhcp client on instance after dhcp agents killing cycle
        self.check_dhcp_on_cirros_instance(vm=self.instance)

        # check dhcp agent behaviour after clearing
        actual_agents = self.os_conn.get_node_with_dhcp_for_network(
            self.net_id)
        err_msg = ('We have not enough dhcp-agent alive: '
                   'current actual - {}'.format(actual_agents))
        # check instance network is on same count of dhcp-agents as on start
        assert len(actual_agents) == len(curr_agents), err_msg

    @pytest.mark.testrail_id('542622')
    def test_reschedule_dhcp_agents(self):
        """Check dhcp-agent manual rescheduling.

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Create network net01, subnet net01_subnet
            3. Create router with gateway to external net and
               interface with net01
            4. Launch instance and associate floating IP
            5. Check ports on net
            6. Run dhcp-client in instance's console: sudo cirros-dhcpc up eth0
            7. Look on what DHCP-agents chosen network is:
               neutron dhcp-agent-list-hosting-net <network_name>
            8. Remove network from one of dhcp-agents:
               neutron dhcp-agent-network-remove <agent_id> <network>
            9. Check removing:
               neutron dhcp-agent-list-hosting-net <network_name>
            10. Set network to other dhcp-agent:
                neutron dhcp-agent-network-add <agent_id> <network>
            11. Run dhcp-client in instance's console:
                sudo cirros-dhcpc up eth0
            12. Check that ports on net wasn't affected


        Duration 10m

        """
        # Fixture init from method self._prepare_openstack_state
        # Get all dhcp agents and ports on network
        ports_ids = [
            port['id'] for port in self.os_conn.list_ports_for_network(
                network_id=self.net_id, device_owner='network:dhcp')]
        all_agents = self.os_conn.list_all_neutron_agents(agent_type='dhcp')
        agents_mapping = {agent['host']: agent for agent in all_agents}
        curr_agents = self.os_conn.get_node_with_dhcp_for_network(
            net_id=self.net_id)
        # determine free of current network dhcp agent
        all_agents_hosts = agents_mapping.keys()
        free_agent = (set(all_agents_hosts) - set(curr_agents)).pop()

        # remove net from one of dhcp-agents
        id_agent_to_remove = agents_mapping[curr_agents[0]]['id']
        logger.info(
            'Removing network from dhcp agent: {}'.format(
                agents_mapping[curr_agents[0]]['host']))
        self.os_conn.remove_network_from_dhcp_agent(id_agent_to_remove,
                                                    self.net_id)

        # check that network removed
        err_msg = 'Manual remove net: {0} from agent: {0} failed.'.format(
            self.net_id, id_agent_to_remove
        )
        new_agents = self.os_conn.get_node_with_dhcp_for_network(
            net_id=self.net_id)
        assert curr_agents[0] not in new_agents, err_msg

        # add network to other dhcp-agent
        id_agent_to_add = agents_mapping[free_agent]['id']
        logger.info(
            'Adding network to dhcp agent: {}'.format(
                agents_mapping[free_agent]['host']))
        self.os_conn.add_network_to_dhcp_agent(id_agent_to_add, self.net_id)

        # check that network is on third agent
        err_msg = 'Manual add net: {0} to agent: {0} failed.'.format(
            self.net_id, free_agent
        )
        new_agents = self.os_conn.get_node_with_dhcp_for_network(
            net_id=self.net_id)
        assert free_agent in new_agents, err_msg

        # check dhcp client on instance
        self.check_dhcp_on_cirros_instance(vm=self.instance)

        # check, that ports was not affected
        new_ports_ids = [
            port['id'] for port in self.os_conn.list_ports_for_network(
                network_id=self.net_id, device_owner='network:dhcp')]
        err_msg = ('Rescheduling failed, ports list after and '
                   'before rescheduling are not same: '
                   'old ports - {0}, '
                   'new ports - {1}'.format(ports_ids,
                                            new_ports_ids))
        assert sorted(ports_ids) == sorted(new_ports_ids), err_msg


class TestBanDHCPAgentWithSettings(TestBaseDHCPAgent):
    """Test with preparation of neutron service."""
    @staticmethod
    def _apply_new_neutron_param_value(remote, value, param=None, path=None):
        """Change some parameter in neutron config to new value
        and restart the service.
        Changing dhcp_agents_per_network by default.

        :param remote: ssh connection to controller
        :param value: new value for param
        :param param: parameter to change in config file
        :param path: path to config file
        :returns: result of command execution
        """
        param = param or 'dhcp_agents_per_network'
        path = path or '/etc/neutron/neutron.conf'
        param_change_value = (
            r"sed -i 's/^\({param} *= *\).*/\1{value}/' {path}".format(
                param=param, value=value, path=path)
        )
        restart_service = "service neutron-server restart"
        res = remote.check_call(
            '{} && {}'.format(param_change_value, restart_service))
        logger.info(
            'Applied new neutron config value {} for param {}'.format(value,
                                                                      param))
        return res

    def _prepare_neutron_server_and_env(self, net_count):
        """Prepares neutron service network count on dhcp agent
            and prepares env.

        :param net_count: how many networks musth dhcp agent handle
        """
        def _check_neutron_restart():
            try:
                self.os_conn.list_networks()['networks']
            except Exception as e:
                logger.debug(e)
                return False
            return True

        all_controllers = self.env.get_nodes_by_role('controller')
        for controller in all_controllers:
            with controller.ssh() as remote:
                res = self._apply_new_neutron_param_value(remote, net_count)
                error_msg = (
                    'Neutron service restart with new value failed, '
                    'exit code {exit_code},'
                    'stdout {stdout}, stderr {stderr}').format(**res)
                assert 0 == res['exit_code'], error_msg

        wait(
            lambda: _check_neutron_restart(),
            timeout_seconds=60 * 3,
            sleep_seconds=(1, 60, 5),
            waiting_for='neutron to be up')

        self._prepare_openstack_state()

    @pytest.mark.testrail_id('542623', params={'net_on_dhcp_count': 1})
    @pytest.mark.testrail_id('542624', params={'net_on_dhcp_count': 3})
    @pytest.mark.parametrize('net_on_dhcp_count', [1, 3])
    def test_rescheduling_with_one_or_three_dhcp_agents(self,
                                                        net_on_dhcp_count):
        """Check dhcp-agent rescheduling with
           net on dhcp-agent count not equal two.

        :param net_on_dhcp_count: count of dhcp-agents for network

        Scenario:
            1. Revert snapshot with neutron cluster
            2. Apply new config for neutron on all controllers:
               set dhcp_agents_per_network property to 1 and restart service
            3. Create network net01, subnet net01_subnet
            4. Create router with gateway to external net and
               interface with net01
            5. Launch instance and associate floating IP
            6. Run dhcp-client in instance's console: sudo cirros-dhcpc up eth0
            7. Look on what DHCP-agents chosen network is:
               ``neutron dhcp-agent-list-hosting-net <network_name>``
            8. Ban DHCP-agent on which instance's net is:
               ``pcs resource ban neutron-dhcp-agent node-x``
            9. Run dhcp-client in instance's console:
               ``sudo cirros-dhcpc up eth0``
            10. Repeat previous 3 steps two times.
            11. Check that all networks is on last dhcp-agent:
                ``neutron net-list-on-dhcp-agent <id_clr_agnt>``
            12. Ban last DHCP-agent on which instance's net is:
                ``pcs resource ban neutron-dhcp-agent node-3``
            13. Clear first banned DHCP-agent
                ``pcs resource clear neutron-dhcp-agent node-1``
            14. Check that all networks is on cleared dhcp-agent:
                ``neutron net-list-on-dhcp-agent <id_clr_agnt>|grep net|wc -l``
            15. Run dhcp-client in instance's console:
                ``sudo cirros-dhcpc up eth0``

        Duration 15m

        """
        self._prepare_neutron_server_and_env(net_on_dhcp_count)
        # Collect all networks on dhcp-agents
        all_agents = self.os_conn.list_all_neutron_agents(agent_type='dhcp')
        agents_mapping = {agent['host']: agent for agent in all_agents}
        agents_networks = [net['id'] for agent in all_agents
                           for net in self.os_conn.get_networks_on_dhcp_agent(
                               agent['id'])]
        # Ban first two agents
        leader_node_ip = self.env.leader_controller.data['ip']
        banned_agents = []
        for ban_counter in range(2):
            curr_agents = self.os_conn.get_node_with_dhcp_for_network(
                net_id=self.net_id)
            assert len(curr_agents) <= len(all_agents) - ban_counter
            self.ban_dhcp_agent(curr_agents[0], leader_node_ip, self.net_name,
                                wait_for_rescheduling=(net_on_dhcp_count == 1))
            banned_agents.append(curr_agents[0])
            self.check_dhcp_on_cirros_instance(vm=self.instance)

        # check that all networks are on free agent
        last_agent = (set(agents_mapping.keys()) - set(banned_agents)).pop()
        last_agent_id = agents_mapping[last_agent]['id']
        nets_on_last_dhcp_agent = [
            net['id'] for net in self.os_conn.get_networks_on_dhcp_agent(
                last_agent_id)]
        err_msg = (
            'There is not all networks on last agent: '
            'all existing networks - {0}, '
            'networks on free agent - {1}'.format(agents_networks,
                                                  nets_on_last_dhcp_agent))
        assert set(agents_networks) == set(nets_on_last_dhcp_agent), err_msg

        # Ban last agent and unban first agent
        self.ban_dhcp_agent(last_agent, leader_node_ip, self.net_name,
                            wait_for_rescheduling=False)
        cleared_agent = self.clear_dhcp_agent(
            banned_agents[0], leader_node_ip, self.net_name)
        cleared_agent_id = agents_mapping[cleared_agent]['id']
        nets_on_cleared_dhcp_agent = [
            net['id'] for net in self.os_conn.get_networks_on_dhcp_agent(
                cleared_agent_id)]
        err_msg = (
            'There is not all networks on last agent: '
            'all existing networks - {0}, '
            'networks on free agent - {1}'.format(agents_networks,
                                                  nets_on_cleared_dhcp_agent))
        assert set(agents_networks) == set(nets_on_cleared_dhcp_agent), err_msg

        self.check_dhcp_on_cirros_instance(vm=self.instance)
