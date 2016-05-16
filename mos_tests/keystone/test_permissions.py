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


@pytest.mark.testrail_id('851868')
def test_keystone_permission_lose(os_conn):
    """Test to cover bugs #1386696, #1326668, #1430951

    Steps to reproduce:
    1. Admin login
    2. Create a new project
    3. Add admin member with admin role to this new project
    4. Remove the admin role for this project
    EX: Admin should have access to keystone in this session
    """

    tenant_name = 'test-admin-project'

    current_user = os_conn.keystone.users.find(username=os_conn.username)
    admin_role = os_conn.keystone.roles.find(name='admin')

    project = os_conn.keystone.tenants.create(tenant_name)

    os_conn.keystone.roles.add_user_role(current_user, admin_role.id, project)

    project.remove_user(current_user, admin_role.id)

    # when bug presented, admin can't get list of tenants or users
    for ten in os_conn.keystone.tenants.list():
        ten.list_users()

    os_conn.keystone.tenants.delete(project)
