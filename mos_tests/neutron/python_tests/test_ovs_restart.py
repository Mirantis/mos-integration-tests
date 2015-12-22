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
import os
import re
import time
import pytest

from mos_tests.neutron.python_tests.base import TestBase


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


@pytest.mark.check_env_("has_2_or_more_computes")
@pytest.mark.usefixtures("setup")
class TestOVSRestartWithIperfTraffic(OvsBase):
    """Restart ovs-agents with iperf traffic background"""

    def create_image(self, path, name):
        full_path = os.path.join(path, name)
        with open(full_path, 'rb') as image_file:
            image = self.os_conn.glance.images \
                .create(name="image_ubuntu",
                        disk_format='qcow2',
                        data=image_file,
                        container_format='bare')
        return image

    def get_lost_percentage(self, output):
        lost_datagrams_rate_pattern = re.compile('\d+/\d+ \((\d+)%\)')
        server_report_flag = False
        for line in output:
            if server_report_flag:
                result = lost_datagrams_rate_pattern.search(line)
                if result:
                    return result.group(1)
            elif line.endswith("Server Report:\n"):
                server_report_flag = True
        return None

    @pytest.fixture(autouse=True)
    def _prepare_openstack(self, init):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Update default security group
            2. Upload the image with pre-installed iperf
            3. Create router01, create networks net01: net01__subnet,
            192.168.1.0/24, net02: net02__subnet, 192.168.2.0/24 and
            attach them to router01.
            4. Create keypair
            5. Launch vm1 in net01 network and vm2 in net02 network
            on different computes
            6. Go to vm1 console and send pings to vm2
        """

        self.setup_rules_for_default_sec_group()
        vm_image = self.create_image('/home/aallakhverdieva/images/',
                                     'ubuntu-iperf.qcow2')

        self.instance_keypair = self.os_conn.create_key(
            key_name='instancekey')
        zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        hosts = zone.hosts.keys()[:2]

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
                image_id=vm_image.id,
                flavor=2,
                key_name=self.instance_keypair.name,
                nics=[{'net-id': net['network']['id']}])

        # check pings
        self.server1 = self.os_conn.nova.servers.find(name="server01")
        self.server2 = self.os_conn.nova.servers.find(name="server02")
        self.server2_ip = self.os_conn.get_nova_instance_ips(
            self.os_conn.nova.servers.find(name="server02")).values()[0]
        self.check_ping_from_vm(self.server1, self.instance_keypair,
                                self.server2_ip, vm_login='ubuntu',
                                timeout=4 * 60)

        # make a list of all ovs agent ids
        self.ovs_agent_ids = [agt['id'] for agt in
                              self.os_conn.neutron.list_agents(
                                  binary='neutron-ovs-agent')['agents']]

    def test_ovs_restart_with_iperf_traffic(self):
        # Launch iperf server on server2
        server_cmd = 'iperf -u -s -p 5002 </dev/null > ~/iperf.log 2>&1 &'
        res_srv = self.run_on_vm(self.server2, self.instance_keypair,
                                 server_cmd, vm_login='ubuntu')
        err_msg = 'Failed to start the iperf server on vm result: {}'.format(
            res_srv)
        assert not res_srv['exit_code'], err_msg

        # Launch iperf client on server1
        client_cmd = 'iperf --port 5002 -u --client {0} --len 64 --bandwidth 1M --time 60 -i 10' \
            .format(self.os_conn.get_nova_instance_ips(self.server2)['fixed'])
        res = self.run_on_vm(self.server1, self.instance_keypair, client_cmd,
                             vm_login='ubuntu')
        err_msg = 'Failed to start the iperf client on vm result: {}'.format(
            res)
        assert not res['exit_code'], err_msg

        # Check iperf traffic before restart
        lost = self.get_lost_percentage(res['stdout'])
        err_msg = "Packet losses more than 1%. Actual value is {0}%".format(
            lost)
        assert not int(lost), err_msg

        # Check that all ovs agents are alive
        self.os_conn.wait_agents_alive(self.ovs_agent_ids)

        # Disable ovs agent on a controller
        self.disable_ovs_agents_on_controller()

        # Then check that all ovs went down
        self.os_conn.wait_agents_down(self.ovs_agent_ids)

        # Restart ovs agent service on all computes
        self.restart_ovs_agents_on_computes()

        # Enable ovs agent on a controller
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
