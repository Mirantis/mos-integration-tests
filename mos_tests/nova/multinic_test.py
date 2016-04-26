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
