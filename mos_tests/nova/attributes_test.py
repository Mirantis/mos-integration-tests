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

pytestmark = pytest.mark.undestructive


@pytest.yield_fixture
def instance(os_conn, security_group, keypair, network):
    zone = os_conn.nova.availability_zones.find(zoneName="nova")
    compute_host = zone.hosts.keys()[0]
    instance = os_conn.create_server(
        name='server01',
        availability_zone='{}:{}'.format(zone.zoneName, compute_host),
        key_name=keypair.name,
        nics=[{'net-id': network['network']['id']}],
        security_groups=[security_group.id],
        wait_for_active=False,
        wait_for_avaliable=False)
    yield instance
    instance.delete()
    common.wait(lambda: os_conn.is_server_deleted(instance.id),
                timeout_seconds=60,
                waiting_for='instances to be deleted')


@pytest.mark.testrail_id('842541')
def test_server_address_during_boot(instance, os_conn):
    """Check that server addresses are hidden during boot

    Scenario:
        1. Create net01, net01__subnet
        2. Boot an instance vm1 in net01
        3. Check that the network field isn't visible when the instance is
            in BUILD status
        4. Wait while an instance goes to an ACTIVE status
        5. Check that now the network field is visible
    """
    common.wait(lambda: os_conn.server_status_is(instance, 'BUILD'),
                timeout_seconds=60,
                waiting_for='instance to became to BUILD status')
    instance = os_conn.nova.servers.get(instance.id)
    assert len(instance.addresses) == 0
    common.wait(lambda: os_conn.is_server_active(instance),
                timeout_seconds=60,
                waiting_for='instance to became to ACTIVE status')
    instance = os_conn.nova.servers.get(instance.id)
    assert len(instance.addresses) > 0


srv_usg_attrs = ('OS-SRV-USG:launched_at', 'OS-SRV-USG:terminated_at')
ext_sts_attrs = ('OS-EXT-AZ:availability_zone', 'OS-EXT-STS:power_state',
                 'OS-EXT-STS:task_state', 'OS-EXT-STS:vm_state')


@pytest.mark.testrail_id('842544', attrs=srv_usg_attrs)
@pytest.mark.testrail_id('842543', attrs=ext_sts_attrs)
@pytest.mark.parametrize('attrs', [srv_usg_attrs, ext_sts_attrs])
def test_os_instance_attributes(request, error_instance, os_conn, attrs):
    """Check instance extended attributes

    Scenario:
        1. Create net and subnet
        2. Boot instance on net
        3. Check that attributes `attrs` are visible in instance attributes
        4. Wait instance to reach ACTIVE status
        5. Check that attributes `attrs` are visible in instance attributes
        6. Boot instance in ERROR status
        7. Check that attributes `attrs` are visible in instance attributes
    """
    instance = request.getfuncargvalue('instance')
    common.wait(lambda: os_conn.server_status_is(instance, 'BUILD'),
                timeout_seconds=60,
                waiting_for='instance to became to BUILD status')
    instance = os_conn.nova.servers.get(instance.id)

    for attr in attrs:
        assert hasattr(instance, attr)

    common.wait(lambda: os_conn.is_server_active(instance),
                timeout_seconds=60,
                waiting_for='instance to became to ACTIVE status')
    instance = os_conn.nova.servers.get(instance.id)

    for attr in attrs:
        assert hasattr(instance, attr)

    error_instance = os_conn.nova.servers.get(error_instance.id)
    for attr in attrs:
        assert hasattr(error_instance, attr)


@pytest.mark.testrail_id('842542')
def test_image_size_attributes(instance, os_conn):
    """Check the OS-EXT-IMG-SIZE:size extended attribute

    Scenario:
        1. Create net and subnet
        2. Check that TestVM image has an OS-EXT-IMG-SIZE:size attribute
        3. Boot instance with TestVM image on net
        4. Wait for instance to reach ACTIVE status
        5. Create new image as snapshot of instance
        6. Check that the created snapshot has an
            OS-EXT-IMG-SIZE:size attribute
    """
    attr = 'OS-EXT-IMG-SIZE:size'
    test_vm_image = os_conn.nova.images.find(name='TestVM')
    assert hasattr(test_vm_image, attr)

    common.wait(lambda: os_conn.is_server_active(instance),
                timeout_seconds=60,
                waiting_for='instance to became to ACTIVE status')

    instance = os_conn.nova.servers.get(instance.id)
    snapshot_id = instance.create_image('snap1')
    snapshot = os_conn.nova.images.get(snapshot_id)

    assert hasattr(snapshot, attr)
