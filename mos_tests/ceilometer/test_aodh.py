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

from mos_tests.functions import os_cli

pytestmark = pytest.mark.undestructive


@pytest.mark.incremental
class TestAlarms(object):
    """Test CRUD operations with alarms with *aodh* CLI client"""

    old_name = 'alarm1'
    new_name = 'new_alarm2'
    alarm_id = None

    @classmethod
    @pytest.yield_fixture(scope='class', autouse=True)
    def cleanup(cls, env):
        yield
        if cls.alarm_id is None:
            return
        controller = env.get_nodes_by_role('controller')[0]
        with controller.ssh() as remote:
            aodh = os_cli.Aodh(remote)
            aodh('alarm delete {0.alarm_id}'.format(cls), fail_ok=True)

    @pytest.fixture(autouse=True)
    def aodh_client(self, controller_remote):
        self.aodh = os_cli.Aodh(controller_remote)

    @pytest.mark.testrail_id('843885')
    def test_create(self):
        alarm = self.aodh('alarm create --name {0.old_name} -m cpu '
                          '-t threshold --threshold 1'.format(self)).details()
        self.__class__.alarm_id = alarm['alarm_id']

    @pytest.mark.testrail_id('843887')
    def test_list(self):
        alarms = self.aodh('alarm list -t threshold').listing()
        assert any([x['alarm_id'] == self.alarm_id for x in alarms])

    @pytest.mark.testrail_id('843902')
    def test_show(self):
        alarm = self.aodh('alarm show {0.alarm_id}'.format(self)).details()
        assert alarm['name'] == self.old_name

    @pytest.mark.testrail_id('843903')
    def test_update(self):
        self.aodh('alarm update {0.alarm_id} --name {0.new_name}'.format(
            self)).details()

    @pytest.mark.testrail_id('843904')
    def test_history_show(self):
        self.aodh('alarm-history show {0.alarm_id} '.format(self))

    @pytest.mark.testrail_id('843886')
    def test_delete(self):
        self.aodh('alarm delete {0.alarm_id}'.format(self))
