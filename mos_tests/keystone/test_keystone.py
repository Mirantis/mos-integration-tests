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

import json

import pytest


@pytest.mark.testrail_id('844692')
def test_get_token_by_unauthorised_user(os_conn):
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

    user = os_conn.keystone.users.create('testuser', password='testuser')
    role = os_conn.keystone.roles.find(name='_member_')
    tenant_id = os_conn.keystone.session.get_project_id()
    os_conn.keystone.roles.add_user_role(user.id, role.id, tenant_id)

    controller = os_conn.env.get_nodes_by_role('controller')[0]
    with controller.ssh() as remote:
        token_id = remote.check_call("source openrc && "
                                     "export OS_USERNAME='testuser' && "
                                     "export OS_PASSWORD='testuser' && "
                                     "openstack token issue | awk '/ id / "
                                     "{print $4}'").stdout_string
        endpoint = os_conn.session.get_endpoint(service_type='identity',
                                                endpoint_type='internalUrl')
        check_call = remote.check_call(
            'curl -H "X-Auth-Token: {0}" '
            '{1}/tenants'.format(token_id, endpoint))
        assert 'error' not in check_call.stdout_string, 'Request has failed!'

        os_conn.keystone.roles.remove_user_role(user.id, role.id, tenant_id)

        std_out = remote.check_call('curl -H "X-Auth-Token: {0}" '
                                    '{1}/tenants'.format(token_id, endpoint))
        error_str = std_out['stdout'][0]
        error = json.loads(error_str)['error']
        assert error['code'] == 401

        os_conn.keystone.users.delete(user.id)
