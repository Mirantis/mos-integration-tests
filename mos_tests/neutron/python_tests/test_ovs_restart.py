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
    """Common fuctions for ovs tests"""

    def setup_rules_for_default_sec_group(self):
        """Add necessary rules to default security group."""
        default_sec_group = [
            group for group in self.os_conn.nova.security_groups.list()
            if group.name == "default"][0]

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



@pytest.mark.check_env_('is_vlan')
class TestPortTags(TestBase):
    """Chect that port tags arent't change after ovs-agent restart"""

    def get_ports_tags_data(self, lines):
        """Returns dict with ports as keys and tags as values"""
        port_tags = {}
        last_offset = 0
        port = None
        for line in lines[1:]:
            line = line.rstrip()
            key, val = line.split(None, 1)
            offset = len(line) - len(line.lstrip())
            if port is None:
                if key.lower() == 'port':
                    port = val.strip('"')
                    last_offset = offset
                    continue
            elif offset <= last_offset:
                port = None
            elif key.lower() == 'tag:':
                port_tags[port] = val
                port = None
        return port_tags

    def test_port_tags_immutable(self):
        """Check that ports tags don't change their values after
            ovs-agents restart

        Scenario:
            1. Collect ovs-vsctl tags before test
            2. Disable ovs-agents on all controllers,
                restart service 'neutron-plugin-openvswitch-agent'
                on all computes, and enable them back
            3. Check that all ovs-agents are in alive state
            4. Collect ovs-vsctl tags after test
            5. Check that values of the tag parameter for every port
                remain the same
        """

        def get_ovs_port_tags(nodes):
            ovs_cfg = {}
            for node in nodes:
                with node.ssh() as remote:
                    result = remote.execute('ovs-vsctl show')
                    assert result['exit_code'] == 0
                    ports_tags = self.get_ports_tags_data(result['stdout'])
                    ovs_cfg[node.data['fqdn']] = ports_tags
            return ovs_cfg

        nodes = self.env.get_all_nodes()

        # Collect ovs-vsctl data before test
        ovs_before_port_tags = get_ovs_port_tags(nodes)

        # ban and clear ovs-agents on controllers
        controller = self.env.get_nodes_by_role('controller')[0]
        with controller.ssh() as remote:
            cmd = "pcs resource disable p_neutron-plugin-openvswitch-agent"
            assert remote.execute(cmd)['exit_code'] == 0
            cmd = "pcs resource enable p_neutron-plugin-openvswitch-agent"
            assert remote.execute(cmd)['exit_code'] == 0

        # restart ovs-agents on computes
        for node in self.env.get_nodes_by_role('compute'):
            with node.ssh() as remote:
                cmd = 'service neutron-plugin-openvswitch-agent restart'
                assert remote.execute(cmd)['exit_code'] == 0

        # wait for 30 seconds
        time.sleep(30)

        # Collect ovs-vsctl data after test
        ovs_after_port_tags = get_ovs_port_tags(nodes)

        # Compare
        assert ovs_after_port_tags == ovs_before_port_tags


@pytest.mark.check_env_("has_1_or_more_computes")
@pytest.mark.usefixtures("setup")
class TestOVSRestartTwoVmsOnSingleCompute(OvsBase):
    """Check restarts of openvswitch-agents."""

    @pytest.fixture(autouse=True)
    def _prepare_openstack(self, init):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Update default security group
            2. Create networks net01: net01__subnet, 192.168.1.0/24
            3. Launch vm1 and vm2 in net01 network on a single compute compute
            4. Go to vm1 console and send pings to vm2
        """
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        host = zone.hosts.keys()[0]

        self.setup_rules_for_default_sec_group()

        # create 1 network and 2 instances
        net, subnet = self.create_internal_network_with_subnet()

        self.os_conn.create_server(
            name='server01',
            availability_zone='{}:{}'.format(zone.zoneName, host),
            key_name=self.instance_keypair.name,
            nics=[{'net-id': net['network']['id']}],
            max_count=2)

        # check pings
        self.server1 = self.os_conn.nova.servers.find(name="server01-1")
        self.server2_ip = self.os_conn.get_nova_instance_ips(
            self.os_conn.nova.servers.find(name="server01-2")
        ).values()[0]

        self.check_ping_from_vm(self.server1, self.instance_keypair,
                                self.server2_ip, timeout=2 * 60)

        # make a list of all ovs agent ids
        self.ovs_agent_ids = [agt['id'] for agt in
                              self.os_conn.neutron.list_agents(
                                  binary='neutron-openvswitch-agent')[
                                  'agents']]

    def test_ovs_restart_pcs_vms_on_single_compute_in_single_network(self):
        """Check connectivity for instances scheduled on a single compute in
         a single private network

        Steps:
            1. Update default security group
            2. Create networks net01: net01__subnet, 192.168.1.0/24
            3. Launch vm1 and vm2 in net01 network on a single compute compute
            4. Go to vm1 console and send pings to vm2
            5. Disable ovs-agents on all controllers, restart service
            neutron-plugin-openvswitch-agent on all computes, and enable
            them back. To do this, launch the script against master node.
            6. Wait 30 seconds, send pings from vm1 to vm2 and check that
            it is successful.

        Duration 10m

        """
        # Check that all ovs agents are alive
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

        # sleep is used to check that system will be stable for some time
        # after restarting service
        time.sleep(30)

        self.check_ping_from_vm(self.server1, self.instance_keypair,
                                self.server2_ip, timeout=2 * 60)

        # check all agents are alive
        assert all([agt['alive'] for agt in
                    self.os_conn.neutron.list_agents()['agents']])
