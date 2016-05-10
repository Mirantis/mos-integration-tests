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
from mos_tests.neutron.python_tests.base import TestBase


@pytest.yield_fixture
def one_inst(request, os_conn, security_group, keypair, network):
    """Create one instances on one compute node with new network.
    If required - create instance on ERROR state on fake node
    """
    param = getattr(request, 'param', {'fail_ok': False})
    zone = os_conn.nova.availability_zones.find(zoneName="nova")
    if param['fail_ok']:
        compute_host = 'node-999.test.domain.local'  # fake node
    else:
        compute_host = zone.hosts.keys()[0]
    instance = os_conn.create_server(
        name='server_00',
        availability_zone='{}:{}'.format(zone.zoneName, compute_host),
        key_name=keypair.name,
        nics=[{'net-id': network['network']['id']}],
        security_groups=[security_group.id],
        wait_for_active=False,
        wait_for_avaliable=False)
    if param['fail_ok'] is False:
        common.wait(lambda: os_conn.is_server_active(instance),
                    timeout_seconds=2 * 60,
                    waiting_for='instances to became to ACTIVE status')
        common.wait(lambda: os_conn.is_server_ssh_ready(instance),
                    timeout_seconds=2 * 60,
                    waiting_for='instances to be SSH available')
    else:  # if creation should fail
        common.wait(
            lambda: os_conn.nova.servers.get(instance).status == 'ERROR',
            timeout_seconds=2 * 60,
            waiting_for='instances to became to ERROR status')
    yield instance.id, network['network']['id']
    # clean Up
    try:                         # if instance was deleted in test
        instance.force_delete()
    except Exception as e:
        assert e.code == 404     # Instance not found
    common.wait(lambda: os_conn.is_server_deleted(instance),
                timeout_seconds=60,
                waiting_for='instances to be deleted')


@pytest.mark.undestructive
class TestNovaOSServerExternalEvents(TestBase):
    """Tests OS-server-external-events"""

    nova_log = '/var/log/nova/nova-api.log'

    @pytest.mark.testrail_id('842538')
    def test_dispatch_external_event(self, one_inst):
        """Dispatch an external event
        Actions:
        1. Create instance with new net and subnet, boot it.
        2. Check in nova-api log that the external event "network-vif-plugged"
        have been created for this instance and got "status": "completed".
        """
        vm_id, _ = one_inst
        cmd = ('grep "server_external_events'
               '.*status.*completed'
               '.*name.*network-vif-plugged'
               '.*server_uuid.*{0}" {1}').format(vm_id, self.nova_log)
        result = []
        controllers = self.env.get_nodes_by_role('controller')
        for controller in controllers:
            with controller.ssh() as remote:
                out = remote.execute(cmd, verbose=False)
                if out.is_ok:
                    result.append(out['stdout'])
        # check that grep has found pattern
        assert len(result) >= 1, ('Grep did not found pattern for plugging '
                                  'network-vif-plugged in completed status'
                                  'in nova-api.log')

    @pytest.mark.testrail_id('842539')
    def test_dispatch_external_event_inst_not_found(self, one_inst):
        """Dispatch an external event
        Actions:
        1. Create instance with new net and subnet, boot it.
        2. Delete created instance;
        3. Check in nova-api log that the external event 'network-vif-deleted'
        has been created for this instance;
        4. Check in nova-api log that the 'Dropping event' message appears for
        previously-deleted instance.
        """
        vm_id, _ = one_inst
        # Delete instance
        common.delete_instance(self.os_conn.nova, vm_id)

        grep_del = ('grep "server_external_events'
                    '.*name.*network-vif-deleted'
                    '.*server_uuid.*{0}" {1}').format(vm_id, self.nova_log)
        grep_drop = ('grep "server_external_events'
                     '.*Dropping event network-vif-deleted'
                     '.*instance {0}" {1}').format(vm_id, self.nova_log)
        # run grep on all controllers
        result = []
        controllers = self.env.get_nodes_by_role('controller')
        for controller in controllers:
            with controller.ssh() as remote:
                out_del = remote.execute(grep_del, verbose=False)
                out_drop = remote.execute(grep_drop, verbose=False)
                if out_del.is_ok and out_drop.is_ok:
                    result.extend((out_del['stdout'], out_drop['stdout']))

        # check that grep has found 2 patterns in nova-api log
        assert len(result) >= 2, ('Grep did not found pattern for deletion '
                                  'and/or for dropping network-vif-deleted in '
                                  'nova-api.log')

    @pytest.mark.testrail_id('842540')
    @pytest.mark.parametrize('one_inst', [{'fail_ok': True}], indirect=True)
    def test_dispatch_external_event_inst_not_assigned_to_host(
            self, one_inst):
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
        vm_id, net_id = one_inst
        # try to assign IP to VM in Error state
        try:
            self.os_conn.nova.servers.add_fixed_ip(vm_id, net_id)
        except Exception as e:
            # BUG: https://bugs.launchpad.net/nova/+bug/1533260
            assert ('Unexpected API Error' not in e.message and
                    e.code != 500 and
                    'while instance is in' in e.message and
                    e.code == 409)
        else:
            raise Exception('Addition of fixed IP should not be possible for'
                            'instance in ERROR state')
