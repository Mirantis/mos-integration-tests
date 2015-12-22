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


@pytest.mark.check_env_("has_1_or_more_computes")
class OvsBase(TestBase):
    """ Common fuctions for ovs tests"""

    def setup_rules_for_default_sec_group(self):
        """Add necessary rules to default security group."""
        default_sec_group = [
            group for group in self.os_conn.nova.security_groups.list()
            if group.name == "default"][0]

        self.os_conn.nova.security_group_rules.create(
            default_sec_group.id,
            ip_protocol='tcp',
            from_port=22,
            to_port=22,
            cidr='0.0.0.0/0')
        self.os_conn.nova.security_group_rules.create(
            default_sec_group.id,
            ip_protocol='icmp',
            from_port=-1,
            to_port=-1,
            cidr='0.0.0.0/0')
        self.os_conn.nova.security_group_rules.create(
            default_sec_group.id,
            ip_protocol='tcp',
            from_port=1,
            to_port=65535,
            cidr='0.0.0.0/0')
        self.os_conn.nova.security_group_rules.create(
            default_sec_group.id,
            ip_protocol='udp',
            from_port=1,
            to_port=65535,
            cidr='0.0.0.0/0')

    def disable_ovs_agents_on_controller(self):
        """Disable openvswitch-agents on all controllers."""
        controller = self.env.get_nodes_by_role('controller')[0]

        with controller.ssh() as remote:
            result = remote.execute(
                '. openrc && pcs resource disable '
                'p_neutron-plugin-openvswitch-agent --wait')
            assert result['exit_code'] == 0

    def restart_ovs_agents_on_computes(self):
        """Restart openvswitch-agents on all computes."""
        computes = self.env.get_nodes_by_role('compute')

        for node in computes:
            with node.ssh() as remote:
                result = remote.execute(
                    'service neutron-plugin-openvswitch-agent restart')
                assert result['exit_code'] == 0

    def enable_ovs_agents_on_controllers(self):
        """Enable openvswitch-agents on all controllers."""
        controller = self.env.get_nodes_by_role('controller')[0]

        with controller.ssh() as remote:
            result = remote.execute(
                '. openrc && pcs resource enable '
                'p_neutron-plugin-openvswitch-agent --wait')
            assert result['exit_code'] == 0


@pytest.mark.check_env_("has_2_or_more_computes")
@pytest.mark.usefixtures("setup")
class TestOVSRestartTwoVms(OvsBase):
    """Check restarts of openvswitch-agents."""

    @pytest.fixture(autouse=True)
    def _prepare_openstack(self, init):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Update default security group
            2. Create router01, create networks net01: net01__subnet,
            192.168.1.0/24, net02: net02__subnet, 192.168.2.0/24 and
            attach them to router01.
            3. Launch vm1 in net01 network and vm2 in net02 network
            on different computes
            4. Go to vm1 console and send pings to vm2
        """
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        hosts = zone.hosts.keys()[:2]

        self.setup_rules_for_default_sec_group()

        # create router
        router = self.os_conn.create_router(name="router01")

        # create 2 networks and 2 instances
        for i, hostname in enumerate(hosts, 1):
            net, subnet = self.create_internal_network_with_subnet(suffix=i)
            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(zone.zoneName, hostname),
                key_name=self.instance_keypair.name,
                nics=[{'net-id': net['network']['id']}])

        # check pings
        self.server1 = self.os_conn.nova.servers.find(name="server01")
        self.server2_ip = self.os_conn.get_nova_instance_ips(
            self.os_conn.nova.servers.find(name="server02")
        ).values()[0]

        self.check_ping_from_vm(self.server1, self.instance_keypair,
                                self.server2_ip, timeout=2 * 60)

    def test_ovs_restart_pcs_disable_enable(self):
        """Restart openvswitch-agents with pcs disable/enable on controllers

        Steps:
            1. Update default security group
            2. Create router01, create networks net01: net01__subnet,
            192.168.1.0/24, net02: net02__subnet, 192.168.2.0/24 and
            attach them to router01.
            3. Launch vm1 in net01 network and vm2 in net02 network
            on different computes
            4. Go to vm1 console and send pings to vm2
            5. Disable ovs-agents on all controllers, restart service
            neutron-plugin-openvswitch-agent on all computes, and enable
            them back. To do this, launch the script against master node.
            6. Wait 30 seconds, send pings from vm1 to vm2 and check that
            it is successful.

        Duration 10m

        """
        self.disable_ovs_agents_on_controller()
        self.restart_ovs_agents_on_computes()
        self.enable_ovs_agents_on_controllers()

        # sleep is used to check that system will be stable for some time
        # after restarting service
        time.sleep(30)

        self.check_ping_from_vm(self.server1, self.instance_keypair,
                                self.server2_ip, timeout=2 * 60)


@pytest.mark.check_env_('is_ha', 'has_2_or_more_computes')
@pytest.mark.usefixtures("setup")
class TestOVSRestartsOneNetwork(OvsBase):

    @pytest.fixture(autouse=True)
    def _prepare_openstack(self, init):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create network1
            2. Create router1 and connect it with network1 and external net
            3. Boot vm1 in network1 and associate floating ip
            4. Boot vm2 in network2
            5. Add rules for ping
            6. ping 8.8.8.8 from vm2
            7. ping vm1 from vm2 and vm1 from vm2
        """

        # init variables
        exist_networks = self.os_conn.list_networks()['networks']
        ext_network = [x for x in exist_networks
                       if x.get('router:external')][0]
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.hosts = self.zone.hosts.keys()[:2]
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        self.setup_rules_for_default_sec_group()

        # create router
        self.router = self.os_conn.create_router(name="router01")['router']
        self.os_conn.router_gateway_add(router_id=self.router['id'],
                                        network_id=ext_network['id'])
        logger.info('router {} was created'.format(self.router['id']))

        # create one network by amount of the compute hosts
        self.net_id = self.os_conn.add_net(self.router['id'])

        # create two instaced in that network
        # each instance is on the own compute
        for i, hostname in enumerate(self.hosts, 1):
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(self.zone.zoneName, hostname),
                key_name=self.instance_keypair.name,
                nics=[{'net-id': self.net_id}])

        # check pings
        self.check_vm_connectivity()

        # make a list of all ovs agent ids
        self.ovs_agent_ids = [agt['id'] for agt in
                              self.os_conn.neutron.list_agents(
                                    binary='neutron-ovs-agent')['agents']]

    def test_restart_openvswitch_agent_under_bat(self):
        """[Networking: OVS graceful restart] Create automated test
           Restart openvswitch-agents with broadcast traffic background

        TestRail ids are C270643 C270644 C273800 C273801 C273802
        Steps:
            1. Go to vm1's console and run arping
               to initiate broadcast traffic:
                    sudo arping -I eth0 <vm2_fixed_ip>
            2. Disable ovs-agents on all controllers
            3. Restart service 'neutron-plugin-openvswitch-agent'
               on all computes
            4. Enable ovs-agents back.
            5. Check that pings between vm1 and vm2 aren't interrupted
               or not more than 2 packets are lost
        """
        # Run arping in background on server01 towards server02
        srv_list = self.os_conn.nova.servers.list()
        srv1 = srv_list.pop()
        srv2 = srv_list.pop()
        vm_ip = self.os_conn.get_nova_instance_ips(
            self.os_conn.nova.servers.find(name=srv2.name))['fixed']

        arping_cmd = 'sudo arping -I eth0 {}'.format(vm_ip)
        cmd = ' '.join((arping_cmd, '< /dev/null > ~/arp.log 2>&1 &'))
        result = self.run_on_vm(srv1,
                                self.instance_keypair,
                                cmd)
        err_msg = 'Failed to start the arping on vm result: {}'.format(
                                                                result)
        assert not result['exit_code'], err_msg

        # Then check that all ovs agents are alive
        self.os_conn.wait_agents_alive(self.ovs_agent_ids)

        # Disable ovs agent on all controllers
        self.disable_ovs_agents_on_controller()

        # Then check that all ovs went down
        self.os_conn.wait_agents_down(self.ovs_agent_ids)

        # Restart ovs agent service on all computes
        self.restart_ovs_agents_on_computes()

        # Enable ovs agent on all controllers
        self.enable_ovs_agents_on_controllers()

        # Then check that all ovs agents are alive
        self.os_conn.wait_agents_alive(self.ovs_agent_ids)

        # Check that arping is still executing
        cmd = 'ps'
        result = self.run_on_vm(srv1,
                                self.instance_keypair,
                                cmd)
        arping_is_run = False
        for line in result['stdout']:
            if arping_cmd in line:
                arping_is_run = True
                break
        err_msg = 'arping was not found in stdout: {}'.format(result['stdout'])
        assert arping_is_run, err_msg

        # Read log of arpping execution for future possible debug
        cmd = 'cat ~/arp.log'
        result = self.run_on_vm(srv1,
                                self.instance_keypair,
                                cmd)
        logger.debug(result)

        # Check connectivity
        self.check_vm_connectivity()
