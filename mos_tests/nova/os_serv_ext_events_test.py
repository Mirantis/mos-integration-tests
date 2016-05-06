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

from mos_tests.functions import common as common_functions
from mos_tests.neutron.python_tests.base import TestBase


@pytest.mark.undestructive
@pytest.mark.check_env_('has_2_or_more_computes')
class TestNovaOSServerExternalEvents(TestBase):
    """Tests OS-server-external-events"""

    nova_log = '/var/log/nova/nova-api.log'

    @pytest.mark.testrail_id('842538')
    @pytest.mark.parametrize('instances', [{'count': 1}], indirect=True)
    def test_dispatch_external_event(self, instances):
        """Dispatch an external event
        Actions:
        1. Create instance with new net and subnet, boot it.
        2. Check in nova-api log that the external event "network-vif-plugged"
        have been created for this instance and got "status": "completed".
        """
        vm_id = instances[0].id
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
        assert len(result) > 0

    @pytest.mark.testrail_id('842539')
    @pytest.mark.parametrize('instances', [{'count': 1}], indirect=True)
    def test_dispatch_external_event_inst_not_found(self, instances):
        """Dispatch an external event
        Actions:
        1. Create instance with new net and subnet, boot it.
        2. Delete created instance;
        3. Check in nova-api log that the external event 'network-vif-deleted'
        has been created for this instance;
        4. Check in nova-api log that the 'Dropping event' message appears for
        previously-deleted instance.
        """
        vm_id = instances[0].id
        # Delete instance
        common_functions.delete_instance(self.os_conn.nova, vm_id)

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
