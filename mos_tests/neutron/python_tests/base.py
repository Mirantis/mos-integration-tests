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

import six
import pytest
import logging

from devops.helpers.helpers import wait

from mos_tests import settings

logger = logging.getLogger(__name__)


class NotFound(Exception):
    message = "Not Found."


class TestBase(object):

    @pytest.fixture(autouse=True)
    def init(self, fuel, env, os_conn):
        self.fuel = fuel
        self.env = env
        self.os_conn = os_conn

    def get_node_with_dhcp(self, net_id):
        nodes = self.os_conn.get_node_with_dhcp_for_network(net_id)
        if not nodes:
            raise NotFound("Nodes with dhcp for network with id:{}"
                           " not found.".format(net_id))

        return self.env.find_node_by_fqdn(nodes[0])

    def run_on_vm(self, vm, vm_keypair, command, vm_login="cirros",
                  timeout=3 * 60):
        command = command.replace('"', r'\"')
        net_name = [x for x in vm.addresses if len(vm.addresses[x]) > 0][0]
        vm_ip = vm.addresses[net_name][0]['addr']
        net_id = self.os_conn.neutron.list_networks(
            name=net_name)['networks'][0]['id']
        dhcp_namespace = "qdhcp-{0}".format(net_id)
        devops_node = self.get_node_with_dhcp(net_id)
        _ip = devops_node.data['ip']
        logger.info('Connect to {ip}'.format(ip=_ip))
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

            logger.info('Executing {cmd} on {vm_name}'.format(
                cmd=cmd,
                vm_name=vm.name))
            wait(lambda: run(cmd)['exit_code'] == 0,
                 interval=60, timeout=timeout,
                 timeout_msg=err_msg.format(command=cmd))
            return results[-1]

    def check_ping_from_vm(self, vm, vm_keypair, ip_to_ping=None,
                           timeout=3 * 60):
        if ip_to_ping is None:
            ip_to_ping = [settings.PUBLIC_TEST_IP]
        if isinstance(ip_to_ping, six.string_types):
            ip_to_ping = [ip_to_ping]
        cmd_list = ["ping -c1 {0}".format(x) for x in ip_to_ping]
        cmd = ' && '.join(cmd_list)
        res = self.run_on_vm(vm, vm_keypair, cmd, timeout=timeout)
        error_msg = (
            'Instance has no connectivity, exit code {exit_code},'
            'stdout {stdout}, stderr {stderr}'
        ).format(**res)
        assert 0 == res['exit_code'], error_msg

    def check_vm_connectivity(self, timeout=3 * 60):
        """Check that all vms can ping each other and public ip"""
        servers = self.os_conn.get_servers()
        for server1 in servers:
            ips_to_ping = [settings.PUBLIC_TEST_IP]
            for server2 in servers:
                if server1 == server2:
                    continue
                ips_to_ping += self.os_conn.get_nova_instance_ips(
                    server2).values()
            self.check_ping_from_vm(server1, self.instance_keypair,
                                    ips_to_ping, timeout=timeout)
