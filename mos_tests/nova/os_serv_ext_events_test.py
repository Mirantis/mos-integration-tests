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

from mos_tests.neutron.python_tests.base import TestBase


@pytest.mark.undestructive
@pytest.mark.check_env_('has_2_or_more_computes')
class TestNovaOSServerExternalEvents(TestBase):
    """Tests OS-server-external-events"""

    @pytest.mark.testrail_id('842538')
    @pytest.mark.parametrize('instances', [{'count': 1}], indirect=True)
    def test_dispatch_external_event(self, instances):
        """Dispatch an external event
        Actions:
        1. Create instance with new net and subnet, boot it.
        2. Check in nova-api log that the external event "network-vif-plugged"
        have been created for this instance and got "status": "completed".
        """
        nova_log = '/var/log/nova/nova-api.log'
        vm_id = instances[0].id
        cmd = ('grep "server_external_events'
               '.*status.*completed'
               '.*name.*network-vif-plugged'
               '.*server_uuid.*{0}" {1}').format(vm_id, nova_log)
        result = []
        controllers = self.env.get_nodes_by_role('controller')
        for controller in controllers:
            with controller.ssh() as remote:
                out = remote.execute(cmd, verbose=False)
                if out.is_ok:
                    result.append(out['stdout'])
        # check that grep has found pattern
        assert len(result) > 0
