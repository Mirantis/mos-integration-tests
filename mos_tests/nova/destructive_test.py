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

import time

import pytest

from mos_tests.functions import common
from mos_tests.functions import network_checks


@pytest.mark.testrail_id('842496')
@pytest.mark.check_env_('is_ceph_enabled', 'has_2_or_more_computes')
def test_evacuate(devops_env, env, os_conn, instances, keypair):
    """Evacuate instances from failed compute node

    Scenario:
        1. Create net01, net01__subnet:
            neutron net-create net01
            neutron subnet-create net01 192.168.1.0/24 --enable-dhcp \
            --name net01__subnet
        2. Boot instances vm1 and vm2 in net01 on a single compute node:
        3. Destroy a compute node where instances are scheduled
        4. Evacuate instances vm1 and vm2:
            nova evacuate vm1 && nova evacuate vm2
        5. Check that they are rescheduled onto another compute node and
            are in ACTIVE state:
        6. Check that pings between vm1 and vm2 are successful
    """
    compute_host = getattr(instances[0], 'OS-EXT-SRV-ATTR:hypervisor_hostname')
    compute_node = env.find_node_by_fqdn(compute_host)
    devops_node = devops_env.get_node_by_fuel_node(compute_node)
    devops_node.destroy()

    def is_hypervisor_down():
        hypervisor = os_conn.nova.hypervisors.find(
            hypervisor_hostname=compute_host)
        return hypervisor.state == 'down'

    common.wait(
        is_hypervisor_down,
        timeout_seconds=5 * 60,
        waiting_for='hypervisor {0} to be in down state'.format(compute_host))

    alive_host = os_conn.nova.hypervisors.find(state='up').hypervisor_hostname

    # wait some time before evacuate
    time.sleep(30)

    for instance in instances:
        os_conn.nova.servers.evacuate(instance, host=alive_host)

    def is_instances_migrate():
        for instance in os_conn.nova.servers.list():
            if instance not in instances:
                continue
            if not os_conn.is_server_active(instance):
                return False
            if getattr(instance,
                       'OS-EXT-SRV-ATTR:hypervisor_hostname') == compute_host:
                return False
        return True

    common.wait(is_instances_migrate,
                timeout_seconds=5 * 60,
                waiting_for='instances to migrate to another compute')

    for vm1, vm2 in zip(instances, instances[::-1]):
        vm2_ip = os_conn.get_nova_instance_ips(vm2)['fixed']
        network_checks.check_ping_from_vm(env,
                                          os_conn,
                                          vm1,
                                          vm_keypair=keypair,
                                          ip_to_ping=vm2_ip)
