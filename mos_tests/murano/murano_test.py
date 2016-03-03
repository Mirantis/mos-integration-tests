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
from random import randint

import pytest

from tempest_lib import exceptions

pytestmark = pytest.mark.undestructive


def rand_num(a=1, b=1000):
    return randint(a, b)


def user_env(user, password, project):
    """Add this env before you command if you need to perform actions
    under another user
    """
    env = ('env OS_TENANT_NAME="{2}" OS_PROJECT_NAME="{2}" '
           'OS_USERNAME="{0}" OS_PASSWORD="{1}" ').format(
            user, password, project)
    return env


def execute_on_all_controllers(env, cmd, fail_ok=False):
    controllers = env.get_nodes_by_role('controller')
    all_output = []
    for controller in controllers:
        with controller.ssh() as remote:
            result = remote.execute(cmd)
            if not fail_ok and not result.is_ok:
                raise exceptions.CommandFailed(result['exit_code'],
                                               cmd,
                                               result.stdout_string,
                                               result.stderr_string)
            all_output.append(result)
    return all_output


def wa_for_1543135(env):
    # WA for "Wrong OS_AUTH_URL makes keystone operations fail"
    # https://bugs.launchpad.net/mos/+bug/1543135
    # Changes OS_AUTH_URL from ":5000/" --> ":5000/v2.0" in /root/openrc
    cmd = unicode(r"sed -i 's#:5000/\x27#:5000/v2.0\x27#g' /root/openrc")
    execute_on_all_controllers(env, cmd)


@pytest.mark.testrail_id('543127')
@pytest.mark.testrail_id('543125')
def test_user_with_permissions_can_share_pkg(
        env, openstack_client, cli_to_controller, restore_murano_policy):
    """Tests modifying Murano pkg as 'service' project user.
    QA-1572 [Murano Features] User with all permissions can set
        'shared' package to 'unshared'.
    QA-1570 [Murano Features] Sharing Murano App with all permissions.
    Actions:
    1. Create new role 'can_publicize_packages';
    2. Create new user inside 'services' project;
    3. Assign new role to the new user;
    4. On all controllers add new role to /etc/murano/policy.json:
        from:
        "publicize_package": "rule:admin_api",
        to:
        "publicize_package": "rule:admin_api or role:can_publicize_packages",
    5. As a new user import Murano pkg;
    6. As a new user update imported pkg with Public=TRUE;
    7. Check that pkg became public.
    8. As a new user update imported pkg with Public=FALSE;
    9. Check that pkg is not public.

    !!! At the moment of writing this test-case, MOS has several bugs:
    !!!    https://bugs.launchpad.net/mos/+bug/1551575
    !!!    https://bugs.launchpad.net/mos/+bug/1543135
    """
    pkg_for_import = 'io.murano.apps.docker.Interfaces'
    murano_policy_file = '/etc/murano/policy.json'
    role_name = 'can_publicize_packages'
    new_user = {'name': '_test_user_{0}'.format(rand_num()),
                'password': 'password',
                'project': 'services'}
    new_user_env = user_env(new_user['name'], new_user['password'],
                            new_user['project'])

    # Create role
    role = openstack_client('role create {0} -f json'.format(role_name))
    role = openstack_client.details(role)

    # Save original file
    cmd = "yes n | cp -i /etc/murano/policy.json /etc/murano/policy.json_orig"
    execute_on_all_controllers(env, cmd)

    # Modify file /etc/murano/policy.json
    # "publicize_package": "rule:admin_api",      ---->
    # "publicize_package": "rule:admin_api or role:can_publicize_packages",
    cmd = 'echo -n $(cat {0})'.format(murano_policy_file)
    murano_policy = cli_to_controller(cmd)
    murano_policy = json.loads(murano_policy)
    murano_policy['publicize_package'] = "rule:admin_api or role:{0}".\
        format(role_name)
    # Write updated policy to file
    execute_on_all_controllers(
        env,
        "echo '{0}' > {1}".format(
            json.dumps(murano_policy, indent=4),
            murano_policy_file))

    # Create new user inside 'services' prj
    test_user = openstack_client.user_create(**new_user)

    # Assign role to user
    assign_role = openstack_client(
        'role add {0} --user {1} --project {2} -f json'.format(
            role_name, test_user['name'], test_user['project_id']))
    assign_role = openstack_client.details(assign_role)

    # As a new user import new murano pkg
    cmd = ('murano --murano-repo-url=http://storage.apps.openstack.org '
           'package-import {0} --exists-action s'.format(pkg_for_import))
    murano_pkg = cli_to_controller(new_user_env + cmd)
    murano_pkg = cli_to_controller.details_table(murano_pkg)
    murano_pkg = [x for x in murano_pkg if x['FQN'] == pkg_for_import][0]

    # As new user update pkg with public=TRUE
    pkg_id = murano_pkg['ID']
    cmd = 'murano package-update {0} --is-public true'.format(pkg_id)
    cli_to_controller(new_user_env + cmd)
    # Check that Murano pkg has public=TRUE
    cmd = 'murano package-list'
    murano_pkg_upd = cli_to_controller(cmd)
    murano_pkg_upd = cli_to_controller.details_table(murano_pkg_upd)
    is_public = [x['Is Public'] for x in murano_pkg_upd
                 if x['FQN'] == pkg_for_import]
    assert 'true' == str(is_public).lower()

    # As new user update pkg with public=FALSE
    cmd = 'murano package-update {0} --is-public false'.format(pkg_id)
    cli_to_controller(new_user_env + cmd)
    # Check that Murano pkg has public=FALSE
    cmd = 'murano package-list'
    murano_pkg_upd = cli_to_controller(cmd)
    murano_pkg_upd = cli_to_controller.details_table(murano_pkg_upd)
    is_public = [x['Is Public'] for x in murano_pkg_upd
                 if x['FQN'] == pkg_for_import]
    assert '' == str(is_public).lower()

    # CleanUp
    openstack_client.user_delete(new_user['name'])
    openstack_client('role delete {0}'.format(role_name))
    cli_to_controller('murano package-delete {0}'.format(pkg_id))
