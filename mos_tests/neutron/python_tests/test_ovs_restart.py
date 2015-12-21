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

from contextlib import contextmanager
from multiprocessing import Process
import re
import time

import pytest

from mos_tests import settings
from mos_tests.neutron.python_tests.base import TestBase


@pytest.mark.usefixtures("setup")
class TestOVSRestart(TestBase):
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

        # create router
        router = self.os_conn.create_router(name="router01")

        self.setup_rules_for_default_sec_group()

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
        assert controller is not None, 'No controllers have been found.'

        with self.env.get_ssh_to_node(controller.data['ip']) as remote:
            result = remote.execute(
                '. openrc && pcs resource disable '
                'p_neutron-plugin-openvswitch-agent --wait')
            assert result['exit_code'] == 0

    def restart_ovs_agents_on_computes(self):
        """Restart openvswitch-agents on all computes."""
        computes = self.env.get_nodes_by_role('compute')
        assert len(computes) > 0, 'No computes have been found.'

        for node in computes:
            with self.env.get_ssh_to_node(node.data['ip']) as remote:
                result = remote.execute(
                    'service neutron-plugin-openvswitch-agent restart')
                assert result['exit_code'] == 0

    def enable_ovs_agents_on_controllers(self):
        """Disable openvswitch-agents on all controllers."""
        controllers = self.env.get_nodes_by_role('controller')
        assert len(controllers) > 0, 'No controllers have been found.'

        for node in controllers:
            with self.env.get_ssh_to_node(node.data['ip']) as remote:
                result = remote.execute(
                    '. openrc && pcs resource enable '
                    'p_neutron-plugin-openvswitch-agent --wait')
                assert result['exit_code'] == 0

    @contextmanager
    def start_ping_from_vm(self, vm, vm_keypair, log_filename,
                           vm_login, ip_to_ping=None):
        """Start ping second vm from the first before enter and stop it after.
        Log will be copied to /tmp/ovs_restart_ping.log path."""
        def check_ping_from_vm(vm, vm_keypair, ip_to_ping):
            if ip_to_ping is None:
                ip_to_ping = settings.PUBLIC_TEST_IP

            cmd = 'ping {0} > /tmp/ovs_restart_ping.log &'.format(ip_to_ping)

            res = self.run_on_vm(vm, vm_keypair, cmd, vm_login="cirros",
                                 timeout=3 * 60)
            assert res['exit_code'] == 0, \
                'Can\'t connect to vm .'.format(vm.name)

        process = Process(target=check_ping_from_vm,
                          args=(vm, vm_keypair, ip_to_ping))

        try:
            process.start()
            yield
        finally:
            cmd = 'killall -sigint ping'
            res = self.run_on_vm(vm, vm_keypair, cmd, vm_login=vm_login,
                                 timeout=3 * 60)
            assert res['exit_code'] == 0, \
                'Can\'t kill ping process with pid {}.'.format(res)

            cmd = 'cat {}'.format(log_filename)
            res = self.run_on_vm(vm, vm_keypair, cmd, vm_login=vm_login,
                                 timeout=3 * 60)
            assert res['exit_code'] == 0, \
                'Can\'t get log file {} ' \
                'on vm {}.'.format(log_filename, vm.name)

            with open(log_filename, 'w') as log_file:
                log_file.writelines(res['stdout'])

            process.join(0)

    @staticmethod
    def parse_ping_info_from_file(filename):
        with open(filename) as f:
            logs = f.readlines()

        ping_template = r'(\d+) packets transmitted, (\d+) packets received'
        for line in logs:
            packets_data = re.search(ping_template, line)
            if packets_data:
                sent_count, recieved_count = packets_data.groups()
                break
        else:
            pytest.fail(
                'File with pings don\'t contains info '
                'about transmitted and received packets.')

        return sent_count, recieved_count

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
            them back. To do this, launch the script against master node
            6. Check that pings between vm1 and vm2 are not interrupted or
            not more than 2 packets are lost

        Duration 10m

        """
        logfile = "/tmp/ovs_restart_ping.log"

        with self.start_ping_from_vm(
                vm=self.server1,
                vm_keypair=self.instance_keypair,
                log_filename=logfile,
                vm_login="cirros",
                ip_to_ping=self.server2_ip):
            self.disable_ovs_agents_on_controller()
            self.restart_ovs_agents_on_computes()
            self.enable_ovs_agents_on_controllers()

            # sleep is used to check that system will be stable for some time
            # after restarting service
            time.sleep(30)

        sent_count, recieved_count = self.parse_ping_info_from_file(logfile)

        assert int(sent_count) - int(recieved_count) <= 2, \
            ('More than 2 packets have been lost: {} packets transmitted, '
             '{} received').format(sent_count, recieved_count)
