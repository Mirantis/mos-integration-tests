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

import six

from mos_tests.functions.common import wait
from mos_tests import settings


logger = logging.getLogger(__name__)


def run_on_vm(env, os_conn, vm, vm_keypair=None, command='uname',
              vm_login="cirros", timeout=3 * 60, vm_password='cubswin:)'):
    """Execute command on vm and return dict with results

    :param vm: server to execute command on
    :param vm_keypair: keypair used during vm creating
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
        with os_conn.ssh_to_instance(env, vm, vm_keypair,
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
        err_msg = "SSH command: `{command}` completed with 0 exit code"
        wait(lambda: execute()['exit_code'] == 0,
             sleep_seconds=(1, 60, 5), timeout_seconds=timeout,
             expected_exceptions=(Exception,),
             waiting_for=err_msg.format(command=command))
    return results[-1]


def check_ping_from_vm(env, os_conn, vm, vm_keypair=None, ip_to_ping=None,
                       timeout=3 * 60, vm_login='cirros',
                       vm_password='cubswin:)'):
    logger.info('Expecting that ping from VM should pass')
    # Get ping results
    result = check_ping_from_vm_helper(
        env, os_conn, vm, vm_keypair, ip_to_ping, timeout, vm_login,
        vm_password)

    error_msg = (
        'Instance has NO connection, but it should have.\n'
        'EXIT CODE: "{exit_code}"\n'
        'STDOUT: "{stdout}"\n'
        'STDERR {stderr}').format(**result)

    # As ping should pass we expect '0' in exit_code
    assert 0 == result['exit_code'], error_msg


def check_ping_from_vm_helper(env, os_conn, vm, vm_keypair, ip_to_ping,
                              timeout, vm_login, vm_password):
    """Returns dictionary with results of ping execution:
        exit_code, stdout, stderr
    """
    if ip_to_ping is None:
        ip_to_ping = [settings.PUBLIC_TEST_IP]
    if isinstance(ip_to_ping, six.string_types):
        ip_to_ping = [ip_to_ping]
    cmd_list = ["ping -c1 {0}".format(x) for x in ip_to_ping]
    cmd = ' && '.join(cmd_list)
    res = run_on_vm(
        env, os_conn, vm, vm_keypair, cmd, timeout=timeout,
        vm_login=vm_login, vm_password=vm_password)
    return res


def check_vm_connectivity(env, os_conn, vm_keypair=None, timeout=4 * 60):
    """Check that all vms can ping each other and public ip"""
    servers = os_conn.get_servers()
    for server1 in servers:
        ips_to_ping = [settings.PUBLIC_TEST_IP]
        for server2 in servers:
            if server1 == server2:
                continue
            ips_to_ping += os_conn.get_nova_instance_ips(
                server2).values()
        check_ping_from_vm(env, os_conn, server1, vm_keypair, ips_to_ping,
                           timeout=timeout)
