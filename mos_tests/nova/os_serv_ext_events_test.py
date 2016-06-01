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

from novaclient import exceptions as nova_exceptions
import pytest

from mos_tests.functions import common
from mos_tests.neutron.python_tests.base import TestBase


def create_instance(os_conn, compute_host, keypair, network, security_group):
    return os_conn.create_server(name='server_00',
                                 availability_zone='nova:{}'.format(
                                     compute_host),
                                 key_name=keypair.name,
                                 nics=[{'net-id': network['network']['id']}],
                                 security_groups=[security_group.id],
                                 wait_for_active=False,
                                 wait_for_avaliable=False)


def delete_instance(os_conn, instance):
    try:
        instance.force_delete()
    except Exception as e:
        assert e.code == 404
    os_conn.wait_servers_deleted([instance])


@pytest.fixture
def instance(request, os_conn, security_group, keypair, network):
    zone = os_conn.nova.availability_zones.find(zoneName="nova")
    compute_host = zone.hosts.keys()[0]

    instance = create_instance(os_conn=os_conn,
                               compute_host=compute_host,
                               keypair=keypair,
                               network=network,
                               security_group=security_group)

    request.addfinalizer(lambda: delete_instance(os_conn, instance))

    os_conn.wait_servers_active([instance])
    os_conn.wait_servers_ssh_ready([instance])

    return instance


@pytest.fixture
def error_instance(request, os_conn, security_group, keypair, network):
    compute_host = 'node-999.test.domain.local'  # fake node

    instance = create_instance(os_conn=os_conn,
                               compute_host=compute_host,
                               keypair=keypair,
                               network=network,
                               security_group=security_group)

    request.addfinalizer(lambda: delete_instance(os_conn, instance))

    common.wait(
        lambda: os_conn.nova.servers.get(instance).status == 'ERROR',
        timeout_seconds=2 * 60,
        waiting_for='instances to became to ERROR status')

    return instance


@pytest.mark.undestructive
class TestNovaOSServerExternalEvents(TestBase):
    """Tests OS-server-external-events"""

    nova_log = '/var/log/nova/nova-api.log'

    @pytest.mark.testrail_id('842538')
    def test_dispatch_external_event(self, instance):
        """Dispatch an external event
        Actions:
        1. Create instance with new net and subnet, boot it.
        2. Check in nova-api log that the external event "network-vif-plugged"
        have been created for this instance and got "status": "completed".
        """
        cmd = ('grep "server_external_events'
               '.*status.*completed'
               '.*name.*network-vif-plugged'
               '.*server_uuid.*{0}" {1}').format(instance.id, self.nova_log)
        controllers = self.env.get_nodes_by_role('controller')
        for controller in controllers:
            with controller.ssh() as remote:
                out = remote.execute(cmd, verbose=False)
                if out.is_ok:
                    break
        else:
            pytest.fail('Grep did not found pattern for plugging '
                        'network-vif-plugged in completed status'
                        'in nova-api.log')

    @pytest.mark.testrail_id('842539')
    def test_dispatch_external_event_inst_not_found(self, instance):
        """Dispatch an external event
        Actions:
        1. Create instance with new net and subnet, boot it.
        2. Delete created instance;
        3. Check in nova-api log that the external event 'network-vif-deleted'
        has been created for this instance;
        4. Check in nova-api log that the 'Dropping event' message appears for
        previously-deleted instance.
        """
        # Delete instance
        common.delete_instance(self.os_conn.nova, instance.id)

        grep_del = ('grep "server_external_events'
                    '.*name.*network-vif-deleted'
                    '.*server_uuid.*{0}" '
                    '{1}').format(instance.id, self.nova_log)
        grep_drop = ('grep "server_external_events'
                     '.*Dropping event network-vif-deleted'
                     '.*instance {0}" {1}').format(instance.id, self.nova_log)
        # run grep on all controllers
        del_founded = False
        drop_founded = False
        controllers = self.env.get_nodes_by_role('controller')
        for controller in controllers:
            with controller.ssh() as remote:
                out_del = remote.execute(grep_del, verbose=False)
                out_drop = remote.execute(grep_drop, verbose=False)
                if out_del.is_ok:
                    del_founded = True
                if out_drop.is_ok:
                    drop_founded = True

        # check that grep has found 2 patterns in nova-api log
        assert del_founded is True and drop_founded is True, (
            'Grep did not found pattern for deletion '
            'and/or for dropping network-vif-deleted in '
            'nova-api.log')

    @pytest.mark.testrail_id('842540')
    def test_dispatch_external_event_inst_not_assigned_to_host(
            self, error_instance, network):
        """Dispatch an external event for an instance not assigned to a host
        Actions:
        1. Create instance with new net and subnet on not existing compute.
        2. Check that instance in Error state;
        3. Try to assign fixed IP to instance;
        4. Check that error does not contain 'Unexpected API Error'.
        It should have more clear description.
        Like:
        ("Cannot '%(action)s' while instance is in %(attr)s %(state)s")

        BUG: https://bugs.launchpad.net/nova/+bug/1533260
        """
        # try to assign IP to VM in Error state
        with pytest.raises(Exception) as e:
            self.os_conn.nova.servers.add_fixed_ip(error_instance.id,
                                                   network['network']['id'])
        assert e.type == nova_exceptions.ResourceInErrorState
