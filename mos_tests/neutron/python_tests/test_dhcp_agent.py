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
import time

import pytest

from mos_tests.neutron.python_tests.base import TestBase

logger = logging.getLogger(__name__)


@pytest.mark.check_env_('is_ha', 'has_2_or_more_computes')
@pytest.mark.usefixtures("setup")
class TestDHCPAgent(TestBase):

    @pytest.fixture(autouse=True)
    def prepare_openstack(self, setup):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create router01 with external gateway
        """
        # init variables
        exist_networks = self.os_conn.list_networks()['networks']
        ext_network = [x for x in exist_networks
                       if x.get('router:external')][0]
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.hosts = self.zone.hosts.keys()[:2]
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.networks = []

        # create router
        self.router = self.os_conn.create_router(name="router01")['router']
        self.os_conn.router_gateway_add(router_id=self.router['id'],
                                        network_id=ext_network['id'])
        logger.info('router {} was created'.format(self.router['id']))

        self.dhcp_agent_ids = [agt['id'] for agt in
                               self.os_conn.neutron.list_agents(
                                   binary='neutron-dhcp-agent')['agents']]

    def isclose(self, a, b, rel_tol=1e-9, abs_tol=0.0):
        return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

    @pytest.mark.testrail_id('542614')
    def test_to_check_dhcp_agents_work(self):
        """[Neutron VLAN and VXLAN] Check dhcp-agents work

        Steps:
            1. Update quotas for creation a lot of networks:
                neutron quota-update --network 1000 --subnet 1000
                                     --router 1000 --port 1000:
            2. Create 50 networks, subnets, launch and terminate instance
            3. Get the table with all agents:
                neutron agent-list
            4. Checl networks on each dhcp-agent:
                neutron net-list-on-dhcp-agent <id_agent_from_the_table>
                Check that there are nets on all of agent
            5. Check networks quantity on each dhcp-agent:
                neutron net-list-on-dhcp-agent <id_agent_from_the_table>
              Check that quantity on agents are nearly equal
        """

        tenant = self.os_conn.neutron.get_quotas_tenant()
        tenant_id = tenant['tenant']['tenant_id']
        self.os_conn.neutron.update_quota(tenant_id, {'quota':
                                                      {'network': 50,
                                                       'router': 50,
                                                       'subnet': 50,
                                                       'port': 150}})
        # According to the test requirements 50 networks should be created
        # However during implementation found that only about 34 nets
        # can be created for one tenant. Need to clarify that situation.
        for x in range(29):
            net_id = self.os_conn.add_net(self.router['id'])
            self.networks.append(net_id)
            logger.info('Total networks created at the moment {}'.format(
                        len(self.networks)))
            srv = self.os_conn.create_server(
                name='instanseNo{}'.format(x),
                key_name=self.instance_keypair.name,
                security_groups=[self.security_group.name],
                nics=[{'net-id': net_id}],
                wait_for_avaliable=False)
            logger.info('Delete the server {}'.format(srv.name))
            self.os_conn.nova.servers.delete(srv)

        # Count networks for each dhcp agent
        # Each agent should contain networks
        # And amount of networks for each agent should be nearly equal
        networks_amount_on_each_agt = []
        for agt_id in self.dhcp_agent_ids:
            amount = len(self.os_conn.neutron.list_networks_on_dhcp_agent(
                         agt_id)['networks'])
            err_msg = "The dhcp agent {} has no networks!".format(agt_id)
            assert amount, err_msg
            networks_amount_on_each_agt.append(amount)
            logger.info('the dhcp agent {0} has {1} networks'.
                        format(agt_id, amount))
        max_value = max(networks_amount_on_each_agt)
        networks_amount_on_each_agt.remove(max_value)
        err_msg = "Amounts of networks for each agent are not nearly equal."
        for value in networks_amount_on_each_agt:
            assert self.isclose(value, max_value, abs_tol=3), err_msg

    @pytest.mark.testrail_id('542619')
    def test_drop_rabbit_port_check_dhcp_agent(self):
        """[Neutron VLAN and VXLAN] Drop rabbit port and check dhcp-agent

        Steps:
            2. Create network net01, subnet net01_subnet, add it to router01
            3. Launch instance
            4. Log on by root: sudo -i
            5. Run dhcpclient in console
                udhcpc
            6. Look on what dhcp-agents is the chosen network in CLI:
                neutron dhcp-agent-list-hosting-net network_name
            7. With iptables in CLI drop rabbit's port #5673 on the node,
               where is dhcp-agent chosen network:
               iptables -A OUTPUT -p tcp --dport 5673 -j DROP
            8. Check that dhcp-agent isn't alive:
                neutron agent-list
            9. Run dhcp-client (command udhcpc) in instance's console
            10. In CLI that the network is on the 2 health DHCP-agents:
                neutron dhcp-agent-list-hosting-net <network_name>
            11. Rehabilitate rabbit's port:
                iptables -D OUTPUT -p tcp --dport 5673 -j DROP
            12. Check that all neutron servers are alive:
                neutron agent-list
        """

        net_id = self.os_conn.add_net(self.router['id'])
        srv = self.os_conn.add_server(net_id,
                                      self.instance_keypair.name,
                                      self.hosts[0],
                                      self.security_group.id)

        # Run udhcpc on the found instance
        self.run_udhcpc_on_vm(srv)

        # Get current DHCP agent for the net_id
        network_agt = self.os_conn.neutron.list_dhcp_agent_hosting_networks(
                          net_id)['agents']
        err_msg = 'No dhcp agents were found for network {}'.format(
                     net_id)
        assert len(network_agt), err_msg

        # Find controller ip where network resides
        controller_ip = self.env.get_node_ip_by_host_name(
            network_agt[0]['host'])
        # If ip is empty than no controller was found
        err_msg = 'No controller with hostname {} was found'.format(
                network_agt[0]['host'])
        assert controller_ip, err_msg

        # Disable rabbit's port
        with self.env.get_ssh_to_node(controller_ip) as remote:
            cmd = 'iptables -A OUTPUT -p tcp --dport 5673 -j DROP'
            result = remote.execute(cmd)
            assert not result['exit_code'], " failed {}".format(result)

        self.os_conn.wait_agents_down([network_agt[0]['id']])

        # Update current DHCP agent for the net_id
        network_agt = self.os_conn.neutron.list_dhcp_agent_hosting_networks(
                          net_id)['agents']
        err_msg = 'No dhcp agents were found for network {}'.format(
                     net_id)

        # Update controller ip where network resides
        controller_ip = self.env.get_node_ip_by_host_name(
            network_agt[0]['host'])
        # If ip is empty than no controller was found
        err_msg = 'No controller with hostname {} was found'.format(
                network_agt[0]['host'])
        assert controller_ip, err_msg

        # Run udhcpc once again
        self.run_udhcpc_on_vm(srv)

        # Rehabilitate the rabbit's port
        with self.env.get_ssh_to_node(controller_ip) as remote:
            cmd = 'iptables -D OUTPUT -p tcp --dport 5673 -j DROP'
            result = remote.execute(cmd)
            assert not result['exit_code'], " failed {}".format(result)

        self.os_conn.wait_agents_alive(self.dhcp_agent_ids)

    @pytest.mark.testrail_id('542621')
    def test_kill_active_dhcp_agt(self):
        """"[Neutron VLAN and VXLAN] Kill process and check dhcp-agents"

        Steps:
        logger.info('wait until the nodes get offline state')
            1. Create network net01, subnet net01_subnet, add it to router01
            2. Launch instance
            3. Log on instance by root:
                sudo -i
            4. Run dhcp-client in console:
                udhcp
            5. In CLI look on what DHCP-agents chosen network is:
                neutron dhcp-agent-list-hosting-net network_name
            6. Go to the node where this DHCP-agent is
            7. Find dhcp-agent process:
                ps aux | grep dhcp-agent
            8. Kill it:
                kill -9 <pid>
            9. Check that network is on the health dhcp-agents from some time
               (~30-60 seconds)
            10. Run
                    sudo udhcpc
                in vm-console
        """

        net_id = self.os_conn.add_net(self.router['id'])
        srv = self.os_conn.add_server(net_id,
                                      self.instance_keypair.name,
                                      self.hosts[0],
                                      self.security_group.id)

        # Run udhcpc on the found instance
        self.run_udhcpc_on_vm(srv)

        # Get current DHCP agent for the self.networks[0]
        network_agts = self.os_conn.neutron.list_dhcp_agent_hosting_networks(
                          net_id)['agents']

        err_msg = 'No dhcp agents were found for network {}'.format(
                     net_id)
        assert len(network_agts), err_msg

        # Find controller ip where network resides
        controller_ip = self.env.get_node_ip_by_host_name(
            network_agts[0]['host'])
        # If ip is empty than no controller was found
        err_msg = 'No controller with hostname {} was found'.format(
                network_agts[0]['host'])
        assert controller_ip, err_msg

        with self.env.get_ssh_to_node(controller_ip) as remote:
            cmd = "ps -aux | grep [n]eutron-dhcp-agent | awk '{print $2}'"
            result = remote.execute(cmd)
            pid = result['stdout'][0]
            logger.info('Got dhcp agent pid  {}'.format(pid))
            logger.info('Now going to kill it on the controller {}'.format(
                        controller_ip))
            result = remote.execute('kill -9 {}'.format(pid))
            assert not result['exit_code'], "kill failed {}".format(result)

        # Check that dhcp agents for the network are alive
        # And check that all these agents have networks
        # Check will run in loop for several times during about 60 seconds
        logger.info('Checking that dhcp agents alive and have networks')
        for x in range(10):
            self.os_conn.wait_agents_alive(self.dhcp_agent_ids)
            for agt in network_agts:
                nets = self.os_conn.neutron.list_networks_on_dhcp_agent(
                           agt['id'])['networks']
                err_msg = 'No networks on the dhcp agent {}'.format(
                        agt['id'])
                assert len(nets)
            time.sleep(6)

        # Run udhcp again
        self.run_udhcpc_on_vm(srv)
