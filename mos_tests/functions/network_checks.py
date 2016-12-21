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
from multiprocessing.dummy import Pool
import warnings

import six
from waiting import TimeoutExpired

from mos_tests.functions import common
from mos_tests import settings


logger = logging.getLogger(__name__)


class MultipleAssertionErrors(AssertionError):
    def __init__(self, exceptions):
        self.exceptions = exceptions

    def __str__(self):
        msg = u'Multiple assertion errors raised:\n'
        msg += '\n'.join([str(x) for x in self.exceptions])
        return msg


def run_on_vm(env,
              os_conn,
              vm,
              vm_keypair=None,
              command='uname',
              vm_login="cirros",
              timeout=3 * 60,
              vm_password='cubswin:)',
              vm_ip=None):
    warnings.warn('This method is deprecated and will be removed in '
                  'future. Use `os_conn.run_on_vm` instead.',
                  DeprecationWarning)
    return os_conn.run_on_vm(env=env,
                             vm=vm,
                             vm_keypair=vm_keypair,
                             command=command,
                             vm_login=vm_login,
                             vm_password=vm_password,
                             timeout=timeout,
                             vm_ip=vm_ip)


def _ping_ip_list(remote, ips, ipv6):
    results = []
    for ip in ips:
        if ipv6:
            cmd = "ping6 -c1 {0}".format(ip)
        else:
            cmd = "ping -c1 {0}".format(ip)
        result = remote.execute(cmd, verbose=False)
        results.append(result)
    return results


def _wait_success_ping(remote, ip_list, timeout=None, ipv6=False):
    results = []
    timeout = timeout or 0

    def predicate():
        loop_result = _ping_ip_list(remote, ip_list, ipv6)
        results.append(loop_result)
        return all([x.is_ok for x in loop_result])

    try:
        common.wait(predicate,
                    timeout_seconds=timeout,
                    waiting_for='pings to be successful')
    except TimeoutExpired as e:
        logger.error(e)
    return results[-1]


def check_ping_from_vm(env,
                       os_conn,
                       vm,
                       vm_keypair=None,
                       ip_to_ping=None,
                       timeout=3 * 60,
                       vm_login='cirros',
                       vm_password='cubswin:)',
                       vm_ip=None,
                       ipv6=False):
    logger.info('Expecting that ping from VM should pass')
    # Get ping results

    if ip_to_ping is None:
        ip_to_ping = [settings.PUBLIC_TEST_IP]
    if isinstance(ip_to_ping, six.string_types):
        ip_to_ping = [ip_to_ping]

    with os_conn.ssh_to_instance(env,
                                 vm,
                                 vm_keypair=vm_keypair,
                                 username=vm_login,
                                 password=vm_password) as remote:
        result = _wait_success_ping(remote, ip_to_ping, timeout=timeout,
                                    ipv6=ipv6)

    error_msg = '\n'.join([repr(x) for x in result if not x.is_ok])

    error_msg = ('Connectivity error from {name}:\n{msg}').format(
        name=vm.name, msg=error_msg)

    # As ping should pass we expect '0' in exit_code
    assert all([x.is_ok for x in result]), error_msg


def check_vm_connectivity(env, os_conn, vm_keypair=None, timeout=4 * 60,
                          ipv6=False):
    """Check that all vms can ping each other and public ip"""
    ping_plan = {}
    exc = []

    def check(args):
        server, ips_to_ping = args
        try:
            check_ping_from_vm(env, os_conn, server, vm_keypair, ips_to_ping,
                               timeout=timeout, ipv6=ipv6)
        except AssertionError as e:
            return e

    servers = os_conn.get_servers()
    for server1 in servers:
        if not ipv6:
            ips_to_ping = [settings.PUBLIC_TEST_IP]
        else:
            ips_to_ping = []
        for server2 in servers:
            if server1 == server2:
                continue
            ips_to_ping += os_conn.get_nova_instance_ips(
                server2).values()
        ping_plan[server1] = ips_to_ping
    p = Pool(len(ping_plan))
    for result in p.imap_unordered(check, ping_plan.items()):
        if result is not None:
            exc.append(result)
    if len(exc) > 0:
        raise MultipleAssertionErrors(exc)
