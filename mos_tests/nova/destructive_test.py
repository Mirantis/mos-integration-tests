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

from mos_tests.functions import common
from mos_tests.functions import network_checks


@pytest.fixture
def instances(os_conn, security_group, keypair, network):
    instances = []
    zone = os_conn.nova.availability_zones.find(zoneName="nova")
    compute_host = zone.hosts.keys()[0]
    for i in range(2):
        instance = os_conn.create_server(
            name='server%02d' % i,
            availability_zone='{}:{}'.format(zone.zoneName, compute_host),
            key_name=keypair.name,
            nics=[{'net-id': network['network']['id']}],
            security_groups=[security_group.id],
            wait_for_active=False,
            wait_for_avaliable=False)
        instances.append(instance)
    common.wait(lambda: all(os_conn.is_server_active(x) for x in instances),
                timeout_seconds=2 * 60,
                waiting_for='instances to became to active status')
    common.wait(lambda: all(os_conn.is_server_ssh_ready(x) for x in instances),
                timeout_seconds=2 * 60,
                waiting_for='instances to be ready for ssh')
    return instances


@pytest.mark.testrail_id('842496')
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
    devops_node = devops_env.get_node_by_mac(compute_node.data['mac'])
    devops_node.destroy()

    def is_hypervisor_down():
        hypervisor = os_conn.nova.hypervisors.find(
            hypervisor_hostname=compute_host)
        return hypervisor.state == 'down'

    common.wait(
        is_hypervisor_down,
        timeout_seconds=5 * 60,
        waiting_for='hypervisor {0} to be in down state'.format(compute_host))

    for instance in instances:
        os_conn.nova.servers.evacuate(instance)

    def is_instances_migrate():
        for instance in os_conn.nova.servers.list():
            if instance not in instances:
                continue
            if instance.status == 'ERROR':
                raise Exception('Instance {0.name} is in ERROR status\n'
                                '{0.fault[message]}\n'
                                '{0.fault[details]}'.format(instance))
            if not os_conn.server_status_is(instance, 'ACTIVE'):
                return False
            if getattr(instance,
                       'OS-EXT-SRV-ATTR:hypervisor_hostname') == compute_host:
                return False
        return True

    common.wait(is_instances_migrate,
                timeout_seconds=5 * 60,
                waiting_for='instances to migrate to another compute')

    network_checks.check_vm_connectivity(env, os_conn, vm_keypair=keypair)
