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


@pytest.mark.testrail_id('1295474')
@pytest.mark.check_env_('is_ha')
def test_restart_all_services(env, os_conn):
    """Test keystone works after restart all keystone services

    Scenario:
        1. Create new user 'testuser'
        2. Check 'testuser' present in user list
        3. Restart apache2 services on all computes
        4. Create new user 'testuser2'
        5. Check 'testuser' present in user list
        6. Check 'testuser2' present in user list
        7. Boot vm
        8. Check vm reach ACTIVE status
    """
    user = os_conn.keystone.users.create('testuser', password='testuser')

    assert user in os_conn.keystone.users.list()

    # Restart keystone servvices
    for node in env.get_nodes_by_role('controller'):
        with node.ssh() as remote:
            remote.check_call('service apache2 restart')

    user2 = os_conn.keystone.users.create('testuser2', password='testuser')

    userlist = os_conn.keystone.users.list()
    assert user in userlist
    assert user2 in userlist

    internal_net = os_conn.int_networks[0]
    instance_keypair = os_conn.create_key(key_name='instancekey')
    security_group = os_conn.create_sec_group_for_ssh()

    vm = os_conn.create_server(name='vm',
                               availability_zone='nova',
                               key_name=instance_keypair.name,
                               nics=[{'net-id': internal_net['id']}],
                               security_groups=[security_group.id],
                               wait_for_avaliable=False)

    assert os_conn.server_status_is(vm, 'ACTIVE')
