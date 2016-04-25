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
        4. Waitwhile an instance goes to an ACTIVE status
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
