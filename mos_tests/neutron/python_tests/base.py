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

import paramiko
from paramiko import ssh_exception
import pytest
import six
from waiting import wait

from mos_tests import settings


logger = logging.getLogger(__name__)


class NotFound(Exception):
    message = "Not Found."


class TestBase(object):
    """Class contains common methods for neutron tests"""

    @pytest.fixture(autouse=True)
    def init(self, fuel, env, os_conn):
        self.fuel = fuel
        self.env = env
        self.os_conn = os_conn
        self.cirros_creds = {'username': 'cirros',
                             'password': 'cubswin:)'}

    def get_node_with_dhcp(self, net_id):
        nodes = self.os_conn.get_node_with_dhcp_for_network(net_id)
        if not nodes:
            raise NotFound("Nodes with dhcp for network with id:{}"
                           " not found.".format(net_id))

        return self.env.find_node_by_fqdn(nodes[0])

    def create_internal_network_with_subnet(self, suffix=1, cidr=None):
        """Create network with subnet.

        :param suffix: desired integer suffix to names of network, subnet
        :param cidr: desired cidr of subnet
        :returns: tuple, network and subnet
        """
        if cidr is None:
            cidr = '192.168.%d.0/24' % suffix

        network = self.os_conn.create_network(name='net%02d' % suffix)
        subnet = self.os_conn.create_subnet(
            network_id=network['network']['id'],
            name='net%02d__subnet' % suffix,
            cidr=cidr)
        return network, subnet

    def create_router_between_nets(self, ext_net, subnet, suffix=1):
        """Create router between external network and sub network.

        :param ext_net: external network to set gateway
        :param subnet: subnet which for provide route to external network
        :param suffix: desired integer suffix to names of router

        :returns: created router
        """
        router = self.os_conn.create_router(name='router%02d' % suffix)
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=ext_net['id'])

        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])
        return router

    def run_on_vm(self, vm, vm_keypair=None, command='uname',
                  vm_login="cirros", timeout=3 * 60, vm_password='cubswin:)'):
        """Execute command on vm and return dict with results

        :param vm: server to execute command on
        :param vm_keypair: keypair used dduring vm creating
        :param command: command to execute
        :param vm_login: username to login to vm via ssh
        :param vm_password: password to login to vm via ssh
        :param timeout: type - int or None
            - if None - execute command and return results
            - if int - wait `timeout` seconds until command exit_code will be 0
        :returns: Dictionary with `exit_code`, `stdout`, `stderr` keys.
            `Stdout` and `stderr` are list of strings
        """
        results = []

        def execute():
            with self.os_conn.ssh_to_instance(self.env, vm, vm_keypair,
                                              username=vm_login,
                                              password=vm_password) as remote:
                result = remote.execute(command)
                results.append(result)
                return result

        logger.info('Executing `{cmd}` on {vm_name}'.format(
            cmd=command,
            vm_name=vm.name))

        if timeout is None:
            execute()
        else:
            err_msg = "SSH command:\n{command}\n completed with exit code 0."
            wait(lambda: execute()['exit_code'] == 0,
                 sleep_seconds=(1, 60, 5), timeout_seconds=timeout,
                 expected_exceptions=(Exception,),
                 waiting_for=err_msg.format(command=command))
        return results[-1]

    def check_ping_from_vm(self, vm, vm_keypair=None, ip_to_ping=None,
                           timeout=3 * 60, vm_login='cirros',
                           vm_password='cubswin:)'):
        logger.info('Expecting that ping from VM should pass')
        # Get ping results
        result = self.check_ping_from_vm_helper(
            vm, vm_keypair, ip_to_ping,
            timeout, vm_login, vm_password)

        error_msg = (
            'Instance has NO connection, but it should have.\n'
            'EXIT CODE: "{exit_code}"\n'
            'STDOUT: "{stdout}"\n'
            'STDERR {stderr}').format(**result)

        # As ping should pass we expect '0' in exit_code
        assert 0 == result['exit_code'], error_msg

    def check_no_ping_from_vm(self, vm, vm_keypair=None, ip_to_ping=None,
                              timeout=None, vm_login='cirros',
                              vm_password='cubswin:)'):
        logger.info('Expecting that ping from VM should fail')
        # Get ping results
        result = self.check_ping_from_vm_helper(
            vm, vm_keypair, ip_to_ping,
            timeout, vm_login, vm_password)

        error_msg = (
            'Instance has a connection, but it should NOT have.\n'
            'EXIT CODE: "{exit_code}"\n'
            'STDOUT: "{stdout}"\n'
            'STDERR {stderr}').format(**result)

        # As ping should fail we expect NOT '0' in exit_code
        assert 0 != result['exit_code'], error_msg

    def check_ping_from_vm_helper(self, vm, vm_keypair, ip_to_ping,
                                  timeout, vm_login, vm_password):
        """ Returns dictionary with results of ping execution:
        exit_code, stdout, stderr """
        if ip_to_ping is None:
            ip_to_ping = [settings.PUBLIC_TEST_IP]
        if isinstance(ip_to_ping, six.string_types):
            ip_to_ping = [ip_to_ping]
        cmd_list = ["ping -c1 {0}".format(x) for x in ip_to_ping]
        cmd = ' && '.join(cmd_list)
        res = self.run_on_vm(vm, vm_keypair, cmd, timeout=timeout,
                             vm_login=vm_login, vm_password=vm_password)
        return res

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

    def check_vm_is_available(self, vm,
                              username=None, password=None, pkeys=None):
        """Check that instance is available for connect from controller.

        :param vm: instance to ping from it compute node
        :param username: username to login to instance
        :param password: password to connect to instance
        :param pkeys: private keys to connect to instance
        """
        vm = self.os_conn.get_instance_detail(vm)
        srv_host = self.env.find_node_by_fqdn(
            self.os_conn.get_srv_hypervisor_name(vm)).data['ip']

        vm_ip = self.os_conn.get_nova_instance_ips(vm)['floating']

        with self.env.get_ssh_to_node(srv_host) as remote:
            cmd = "ping -c1 {0}".format(vm_ip)

            waiting_for_msg = (
                'Waiting for instance with ip {0} has '
                'connectivity from node with ip {1}.').format(vm_ip, srv_host)

            wait(lambda: remote.execute(cmd)['exit_code'] == 0,
                 sleep_seconds=10, timeout_seconds=3 * 10,
                 waiting_for=waiting_for_msg)
        return self.check_vm_is_accessible_with_ssh(
            vm_ip, username=username, password=password, pkeys=pkeys)

    def check_vm_is_accessible_with_ssh(self, vm_ip, username=None,
                                        password=None, pkeys=None):
        """Check that instance is accessible with ssh via floating_ip.

        :param vm_ip: floating_ip of instance
        :param username: username to login to instance
        :param password: password to connect to instance
        :param pkeys: private keys to connect to instance
        """
        error_msg = 'Instance with ip {0} is not accessible with ssh.'\
            .format(vm_ip)

        def is_accessible():
            try:
                with self.env.get_ssh_to_vm(
                        vm_ip, username, password, pkeys) as vm_remote:
                    vm_remote.execute("date")
                    return True
            except ssh_exception.SSHException:
                return False
            except ssh_exception.NoValidConnectionsError:
                return False

        wait(is_accessible,
             sleep_seconds=10, timeout_seconds=60,
             waiting_for=error_msg)

    @staticmethod
    def convert_private_key_for_vm(private_keys):
        return [paramiko.RSAKey.from_private_key(six.StringIO(str(pkey)))
                for pkey in private_keys]

    def run_udhcpc_on_vm(self, vm):
        command = 'sudo -i cirros-dhcpc up eth0'
        result = self.run_on_vm(vm,
                                self.instance_keypair,
                                command)
        err_msg = 'Failed to start the udhcpc on vm std_err: {}'.format(
            result['stderr'])
        assert not result['exit_code'], err_msg
