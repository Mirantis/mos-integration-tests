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

import functools
import json

import pytest

from mos_tests.functions import os_cli

pytestmark = pytest.mark.undestructive


@pytest.fixture
def role_name():
    return "can_publicize_packages"


@pytest.yield_fixture
def patch_murano_policy(env, role_name):
    murano_policy_file = '/etc/murano/policy.json'
    controllers = env.get_nodes_by_role('controller')

    for controller in controllers:
        with controller.ssh() as remote:
            # Save original file
            remote.check_call(
                'cp {file} {file}_backup'.format(file=murano_policy_file))
            with remote.open(murano_policy_file, 'r') as f:
                data = json.load(f)
            data['publicize_package'] += " or role:{0}".format(role_name)
            with remote.open(murano_policy_file, 'w') as f:
                json.dump(data, f)

    yield
    for controller in controllers:
        with controller.ssh() as remote:
            remote.check_call(
                'mv {file}_backup {file}'.format(file=murano_policy_file))


@pytest.yield_fixture
def role(openstack_client, role_name):
    role = openstack_client.role_create(name=role_name)
    yield role
    openstack_client.role_delete(name=role_name)


@pytest.yield_fixture
def user_env(openstack_client, suffix, role):
    name = 'test_user_{0}'.format(suffix[:4])
    user = openstack_client.user_create(name=name, password='password',
                                        project='services')
    openstack_client.assign_role_to_user(role['name'], user['name'],
                                         user['project_id'])
    yield ('env OS_TENANT_NAME=services OS_PROJECT_NAME=services '
           'OS_USERNAME={name} OS_PASSWORD=password'.format(**user))
    openstack_client.user_delete(name=name)


@pytest.fixture
def murano_cli(controller_remote, user_env):
    return functools.partial(os_cli.Murano(controller_remote), prefix=user_env)


@pytest.yield_fixture
def package(murano_cli):
    fqn = 'io.murano.apps.docker.Interfaces'
    packages = murano_cli(
        'package-import',
        params='{0} --exists-action s'.format(fqn),
        flags='--murano-repo-url=http://storage.apps.openstack.org'
    ).listing()
    package = [x for x in packages if x['FQN'] == fqn][0]
    yield package
    murano_cli('package-delete', params=package['ID'])


@pytest.mark.testrail_id('543125')
def test_user_with_permissions_can_share_pkg(murano_cli, package,
                                             patch_murano_policy):
    """Tests modifying Murano pkg as 'service' project user.

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

    """
    murano_cli('package-update', params='{0} --is-public true'.format(
        package['ID']))

    pkg_data = murano_cli('package-show', params=package['ID']).details()

    assert pkg_data['is_public'] == 'True'

    murano_cli('package-update', params='{0} --is-public false'.format(
        package['ID']))

    pkg_data = murano_cli('package-show', params=package['ID']).details()

    assert pkg_data['is_public'] == 'False'
