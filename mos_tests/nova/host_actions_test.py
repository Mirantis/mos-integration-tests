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
from mos_tests.functions import os_cli

pytestmark = pytest.mark.undestructive


@pytest.fixture
def nova_client(controller_remote):
    return os_cli.Nova(controller_remote)


@pytest.mark.check_env_('has_2_or_more_computes')
@pytest.mark.testrail_id('842499')
def test_live_evacuate_instances(instances, os_conn, env, keypair,
                                 nova_client):
    """Live evacuate all instances of the specified host to other available
    hosts without shared storage

    Scenario:
        1. Create net01, net01__subnet
        2. Boot instances vm1 and vm2 in net01 on compute node1
        3. Run the 'nova host-evacuate-live' command to live-migrate
            vm1 and vm2 instances from compute node1 to compute node2:
            nova host-evacuate-live --target-host node-2.domain.tld \
            --block-migrate node-1.domain.tld
        4. Check that all live-migrated instances are hosted on target host
            and are in ACTIVE status
        5. Check pings between vm1 and vm2
    """
    old_host = getattr(instances[0], 'OS-EXT-SRV-ATTR:host')
    new_host = [x.hypervisor_hostname
                for x in os_conn.nova.hypervisors.list()
                if x.hypervisor_hostname != old_host][0]

    nova_client(
        'host-evacuate-live',
        params='--target-host {new_host} --block-migrate {old_host}'.format(
            old_host=old_host,
            new_host=new_host))

    common.wait(lambda: all([os_conn.is_server_active(x) for x in instances]),
                timeout_seconds=2 * 60,
                waiting_for='instances became to ACTIVE status')

    for instance in instances:
        instance.get()
        assert getattr(instance, 'OS-EXT-SRV-ATTR:host') == new_host

    for instance1, instance2 in zip(instances, instances[::-1]):
        ip = os_conn.get_nova_instance_ips(instance2)['fixed']
        network_checks.check_ping_from_vm(env,
                                          os_conn,
                                          instance1,
                                          vm_keypair=keypair,
                                          ip_to_ping=ip)


@pytest.mark.check_env_('has_2_or_more_computes')
@pytest.mark.parametrize('instances',
                         [{'count': 3}],
                         ids=['3 vms'],
                         indirect=True)
@pytest.mark.testrail_id('842500')
def test_migrate_instances(instances, os_conn, env, keypair, nova_client):
    """Migrate all instances of the specified host to other available hosts

    Scenario:
        1. Create net01, net01__subnet
        2. Boot instances vm1, vm2 and vm3 in net01 on compute node1
        3. Run the 'nova host-servers-migrate <compute node1>' command
        4. Check that every instance is rescheduled to other computes
        5. Check that the status of every rescheduled instance is VERIFY_RESIZE
        6. Confirm resize for every instance:
            nova resize-confirm vm1 (vm2, vm3)
        7. Check that every migrated instance has an ACTIVE status now
        8. Send pings between vm1, vm2 and vm3 to check network connectivity
    """
    old_host = getattr(instances[0], 'OS-EXT-SRV-ATTR:host')
    nova_client('host-servers-migrate', params=old_host)

    common.wait(lambda: all([os_conn.server_status_is(x, 'VERIFY_RESIZE')
                             for x in instances]),
                timeout_seconds=2 * 60,
                waiting_for='instances became to VERIFY_RESIZE status')

    for instance in instances:
        instance.get()
        assert getattr(instance, 'OS-EXT-SRV-ATTR:host') != old_host

    for instance in instances:
        instance.confirm_resize()

    common.wait(lambda: all([os_conn.is_server_active(x) for x in instances]),
                timeout_seconds=2 * 60,
                waiting_for='instances became to ACTIVE status')

    for instance in instances:
        ips = [os_conn.get_nova_instance_ips(x)['fixed']
               for x in instances if x != instance]
        network_checks.check_ping_from_vm(env,
                                          os_conn,
                                          instance,
                                          vm_keypair=keypair,
                                          ip_to_ping=ips)


@pytest.mark.testrail_id('842497')
@pytest.mark.check_env_('has_2_or_more_computes')
def test_compute_resources_info(os_conn, env, keypair, nova_client, request):
    """Get info about resources' usage on compute nodes

    Scenario:
        1. Get list of compute nodes
        2. Get info about available resources on every compute node with
            'nova host-describe <node-n.domain.tld>'
        3. Create net01, net01__subnet
        4. Boot instances vm1 and vm2 in net01 on node-1
        5. Launch 'nova host-describe <node-1.domain.tld>' and check
            that used_now and used_max characteristics were changed and
            new line with tenant ID appeared for compute node1
        6. Launch 'nova host-describe <node-2.domain.tld>' and check
            that used_now and used_max characteristics weren't changed for
            compute node2
        7. Boot instances vm3 and vm4 in net01 on compute node2
        8. Launch 'nova host-describe <node-2.domain.tld>' and check
            that used_now and used_max characteristics were changed and
            new line with tenant ID appeared for the compute node2
    """
    compute_hosts = os_conn.nova.hosts.findall(service='compute')
    old_data = {}
    for host in compute_hosts:
        data = nova_client('host-describe', params=host.host_name).listing()
        old_data[host.host_name] = {x['PROJECT']: x for x in data}

    instances = request.getfuncargvalue('instances')
    host1 = getattr(instances[0], 'OS-EXT-SRV-ATTR:host')
    data = nova_client('host-describe', params=host1).listing()
    host1_data = {x['PROJECT']: x for x in data}

    # Check that host1 used_now and used_max values were changed
    for row in ('(used_now)', '(used_max)'):
        assert host1_data[row] != old_data[host1][row]

    # Check tenant_id in host1 data
    assert os_conn.session.get_project_id() in host1_data

    # Check other compute's datas doesn't changes
    for host in compute_hosts:
        if host.host_name == host1:
            continue
        host2 = host.host_name
        data = nova_client('host-describe', params=host.host_name).listing()
        host_data = {x['PROJECT']: x for x in data}
        assert host_data == old_data[host.host_name]

    network = request.getfuncargvalue('network')
    security_group = request.getfuncargvalue('security_group')

    # Boot 2 instances on host2
    for i in range(2, 4):
        instance = os_conn.create_server(
            name='server%02d' % i,
            availability_zone='nova:{}'.format(host2),
            key_name=keypair.name,
            nics=[{'net-id': network['network']['id']}],
            security_groups=[security_group.id],
            wait_for_active=False,
            wait_for_avaliable=False)
        instances.append(instance)

    common.wait(lambda: all(os_conn.is_server_active(x) for x in instances),
                timeout_seconds=2 * 60,
                waiting_for='instances to became to ACTIVE status')

    data = nova_client('host-describe', params=host2).listing()
    host2_data = {x['PROJECT']: x for x in data}

    # Check that host2 used_now and used_max values were changed
    for row in ('(used_now)', '(used_max)'):
        assert host2_data[row] != old_data[host2][row]

    # Check tenant_id in host2 data
    assert os_conn.session.get_project_id() in host2_data


@pytest.mark.testrail_id('842498')
@pytest.mark.check_env_('has_2_or_more_computes')
def test_put_metadata(instances, os_conn, env, keypair, nova_client, network,
                      security_group):
    """Put metadata on all instances scheduled on a single compute node

    Scenario:
        1. Create net01, net01__subnet
        2. Boot instances vm1 and vm2 in net01 on compute node1
        3. Boot instances vm3 and vm4 in net01 on compute node2
        4. Put metadata 'key=test' on all instances scheduled on compute node1:
            nova host-meta node-1.domain.tld set key=test
        5. Check the 'metadata' field of every instance's details scheduled on
            compute node1 is contains {"key": "test"}
        6. Check that 'metadata' field of every instance's details scheduled on
            compute node2 is empty
        7. Delete metadata for all instances scheduled on compute node1:
            nova host-meta node-1.domain.tld delete key=test
        8. Check that metadata field is empty now for every instance scheduled
            on a compute node1
    """
    host1 = getattr(instances[0], 'OS-EXT-SRV-ATTR:host')

    zone = os_conn.nova.availability_zones.find(zoneName="nova")
    host2 = [x for x in zone.hosts.keys() if x != host1][0]

    # Boot 2 instances on host2
    for i in range(2, 4):
        instance = os_conn.create_server(
            name='server%02d' % i,
            availability_zone='nova:{}'.format(host2),
            key_name=keypair.name,
            nics=[{'net-id': network['network']['id']}],
            security_groups=[security_group.id],
            wait_for_active=False,
            wait_for_avaliable=False)
        instances.append(instance)

    common.wait(lambda: all(os_conn.is_server_active(x) for x in instances),
                timeout_seconds=2 * 60,
                waiting_for='instances to became to ACTIVE status')

    nova_client('host-meta', params='{host} set key=test'.format(host=host1))

    for instance in instances[:2]:
        instance.get()
        assert instance.metadata == {'key': 'test'}

    for instance in instances[2:]:
        instance.get()
        assert instance.metadata == {}

    nova_client('host-meta',
                params='{host} delete key=test'.format(host=host1))

    for instance in instances[:2]:
        instance.get()
        assert instance.metadata == {}
