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


@pytest.mark.undestructive
class TestNovaOSServerExternalEvents(object):
    """Tests OS-server-external-events"""

    nova_log = '/var/log/nova/nova-api.log'

    @pytest.mark.testrail_id('842538')
    @pytest.mark.parametrize('instances', [{'count': 1}], indirect=True)
    def test_dispatch_external_event(self, instances, env):
        """Dispatch an external event
        Actions:
        1. Create instance with new net and subnet, boot it.
        2. Check in nova-api log that the external event "network-vif-plugged"
        have been created for this instance and got "status": "completed".
        """
        instance = instances[0]
        cmd = ('grep "server_external_events'
               '.*status.*completed'
               '.*name.*network-vif-plugged'
               '.*server_uuid.*{0}" {1}').format(instance.id, self.nova_log)
        controllers = env.get_nodes_by_role('controller')
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
    @pytest.mark.parametrize('instances', [{'count': 1}], indirect=True)
    def test_dispatch_external_event_inst_not_found(self, instances, os_conn,
                                                    env):
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
        instance = instances[0]
        common.delete_instance(os_conn.nova, instance.id)

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
        controllers = env.get_nodes_by_role('controller')
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
            self, error_instance, network, os_conn):
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
            os_conn.nova.servers.add_fixed_ip(error_instance.id,
                                              network['network']['id'])
        assert e.type == nova_exceptions.ResourceInErrorState
