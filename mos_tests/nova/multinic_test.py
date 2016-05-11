#    Copyright 2016 Mirantis, Inc.
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

import pytest
import random

from mos_tests.functions import common
from mos_tests.functions import network_checks

pytestmark = pytest.mark.undestructive


@pytest.mark.testrail_id('842545')
def test_basic_operation_with_fixed_ips(env, os_conn, instances, keypair,
                                        network):
    """Basic operations with fixed IPs on an instance

    Scenario:
        1. Create net01, net01__subnet
        2. Boot instances vm1 and vm2 in net01
        3. Check that they ping each other by their fixed IPs
        4. Add a fixed IP to vm1
            nova add-fixed-ip vm1 $NET_ID
        5. Remove old fixed IP from vm1
            nova remove-fixed-ip vm1 <old_fixed_ip>
        6. Wait some time
        7. Check that vm2 can send pings to vm1 by its new fixed IP
    """
    for instance1, instance2 in zip(instances, instances[::-1]):
        ip = os_conn.get_nova_instance_ips(instance2)['fixed']
        network_checks.check_ping_from_vm(env,
                                          os_conn,
                                          instance1,
                                          vm_keypair=keypair,
                                          ip_to_ping=ip)

    instance1, instance2 = instances
    old_ip = os_conn.get_nova_instance_ips(instance1)['fixed']
    instance1.add_fixed_ip(network['network']['id'])

    instance1.remove_fixed_ip(old_ip)
    new_ip = os_conn.get_nova_instance_ips(instance1)['fixed']

    network_checks.check_ping_from_vm(env,
                                      os_conn,
                                      instance2,
                                      vm_keypair=keypair,
                                      ip_to_ping=new_ip)


@pytest.mark.testrail_id('842547')
@pytest.mark.parametrize('instances', [{'count': 1}], indirect=True)
def test_remove_incorrect_fixed_ip_from_instance(os_conn, instances, network):
    """Remove incorrect fixed IP from an instance
    Scenario:
    1. Create instance with net, subnet;
    2. Add new fixed IP to instance;
    3. Try to remove fake (not assigned) fixed IP from instance. Check that
    error raised;
    4. Remove real assigned fixed IP from instance.
    5. Check that instance is available with single left fixed IP.

    BUG: https://bugs.launchpad.net/nova/+bug/1534186
    """
    def check_num_of_fixed_ips(vmid, exp_ip_num):
        vm = os_conn.get_instance_detail(vmid)
        return exp_ip_num == len([x['addr'] for y in vm.addresses.values()
                                  for x in y
                                  if x['OS-EXT-IPS:type'] == 'fixed'])

    fake_ips = ['191.191.191.191', '192.192.192.192', '193.193.193.193']
    vm1 = instances[0]

    # add new fixed IP
    vm1.add_fixed_ip(network['network']['id'])
    # wait for IP to be assigned
    common.wait(lambda: check_num_of_fixed_ips(vm1.id, 2),
                timeout_seconds=30,
                waiting_for='new IP will be assigned to VM')
    # get list of fixed IPs
    vm1 = os_conn.get_instance_detail(vm1.id)
    fixed_ips = [x['addr'] for y in vm1.addresses.values()
                 for x in y
                 if x['OS-EXT-IPS:type'] == 'fixed']

    # Get fake IP and check that it is not in real IP list
    fake_ip = random.choice(fake_ips)
    while fake_ip in fixed_ips:
        fake_ip = random.choice(fake_ips)

    # Try to remove fake (not assigned) IP from VMs
    try:
        os_conn.nova.servers.remove_fixed_ip(vm1.id, fake_ip)
    except Exception:
        pass  # expected
    else:
        raise Exception(
            'Removing not assigned IP from VM should raise error. \n'
            'But it did not happen. That is why you see this exception. \n'
            'Check this bug: https://bugs.launchpad.net/nova/+bug/1534186')

    # Remove assigned fixed IP and update VM's info
    os_conn.nova.servers.remove_fixed_ip(vm1.id, fixed_ips[-1])
    # wait for IP to be assigned
    common.wait(lambda: check_num_of_fixed_ips(vm1.id, 1),
                timeout_seconds=30,
                waiting_for='new IP will be assigned to VM')

    # Check that removed IP not present in VM
    vm1 = os_conn.get_instance_detail(vm1.id)
    assert fixed_ips[-1] not in str(vm1.addresses.values())

    # check that VM is still available for connections
    assert os_conn.is_server_ssh_ready(vm1)
