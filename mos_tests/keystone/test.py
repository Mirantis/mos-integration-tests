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


import logging

import pytest
from mos_tests.neutron.python_tests.base import TestBase

logger = logging.getLogger(__name__)


class TestKeystone(TestBase):

    @pytest.mark.testrail_id('844692')
    @pytest.mark.parametrize('glance_remote', [2], indirect=['glance_remote'])
    def test_keystone_bla(self):
        """Test to cover bug#1546197

        Steps to reproduce:

        1. Create new project and new user there
        2. Add new project like member in admin tenant
        3. Login under this user
        4. Execute 'keystone token-get' in controller
        5. Get TOKEN_ID
        6. Execute curl request: curl -H "X-Auth-Token:
        TOKEN_ID" http://192.168.0.2:5000/v2.0/tenants

        ER: curl should return correct result

        7. Delete new user from admin tenant
        8. Repeat curl request

        ER: curl should return 401-error
        """

        user = self.os_conn.keystone.users.create('testuser', 'testuser')

        role_id = ''
        endpoint = ''
        service_id = ''
        roles_list = self.os_conn.keystone.roles.list()
        end_point_list = self.os_conn.keystone.endpoints.list()

        services_list = self.os_conn.keystone.services.list()
        for srv in services_list:
            if srv.name == 'keystone':
                service_id = srv.id

        for role in roles_list:
            if role.name == '_member_':
                role_id = role.id

        tenant_id = self.os_conn.keystone.session.get_project_id()

        for endpnt in end_point_list:
            if endpnt.service_id == service_id:
                endpoint = endpnt.internalurl

        self.os_conn.keystone.roles.add_user_role(user.id, role_id, tenant_id)

        controller = self.env.get_nodes_by_role('controller')[0]

        with controller.ssh() as remote:
            remote.check_call(
                "cat openrc >> openrc2 && sed -i 's/export "
                "OS_USERNAME='admin'"
                "/export OS_USERNAME='testuser'/g' openrc2 && sed -i "
                "'s/export OS_PASSWORD='admin'/export "
                "OS_PASSWORD='testuser'/g' openrc2")

            result = remote.check_call(
                "source openrc2 && "
                "keystone token-get | awk '/ id/{print $4}'")
            token_id = result.stdout_string

            remote.check_call(
                'curl -H "X-Auth-Token: '
                '{}" {}/tenants'.format(token_id, endpoint))

        self.os_conn.keystone.users.delete(user.id)

        with controller.ssh() as remote:
            with pytest.raises(Exception):
                remote.check_call(
                    'curl -H "X-Auth-Token: {}" '
                    '{}/tenants'.format(token_id, endpoint))
