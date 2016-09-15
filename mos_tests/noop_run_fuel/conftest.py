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

from contextlib2 import ExitStack
import pytest

from keystoneclient.v3 import Client as KeystoneClientV3
from mos_tests.functions.service import patch_conf


logger = logging.getLogger(__name__)


@pytest.yield_fixture
def admin_remote(fuel):
    with fuel.ssh_admin() as remote:
        yield remote


@pytest.yield_fixture
def rename_role(os_conn):
    """Rename the role 'SwiftOperator'"""
    role_name_old = "SwiftOperator"
    role_name_new = role_name_old + "-new"
    logger.info("Rename role {0} -> {1}".format(role_name_old, role_name_new))
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    role = keystone_v3.roles.find(name=role_name_old)
    keystone_v3.roles.update(role=role, name=role_name_new)
    yield
    keystone_v3.roles.update(role=role, name=role_name_old)


@pytest.yield_fixture
def disable_user(os_conn):
    """Disable/enable the user 'glare'"""
    user_name = "glare"
    logger.info("Disable user {0}".format(user_name))
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    user = keystone_v3.users.find(name=user_name)
    keystone_v3.users.update(user=user, enabled=False)
    yield
    keystone_v3.users.update(user=user, enabled=True)


@pytest.fixture
def delete_project(os_conn):
    """Delete/create the project 'services'"""
    project_name = "services"
    logger.info("Delete project {0}".format(project_name))
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    project = keystone_v3.projects.find(name=project_name)
    keystone_v3.projects.delete(project=project)


def config_patch(env, config_path, config, role=None):
    role = role or 'controller'
    node = env.get_nodes_by_role(role)[0]

    with ExitStack() as stack:
        remote = node.ssh()
        logger.info('Patch {0} on {1}'.format(config_path, node.data['fqdn']))
        stack.enter_context(patch_conf(remote,
                                       path=config_path,
                                       new_values=config))
        yield node


def change_config_factory(config_path, config, role=None):

    @pytest.yield_fixture
    def change_config(env, role=role):
        for step in config_patch(env, config_path, config, role=role):
            yield step, config

    return change_config

nova_conf_on_ctrl = change_config_factory(
    config_path="/etc/nova/nova.conf",
    config=[('DEFAULT', 'debug', False)])

nova_conf_on_cmpt = change_config_factory(
    config_path="/etc/nova/nova.conf",
    config=[('oslo_messaging_rabbit', 'amqp_durable_queues', '')],
    role='compute')

cinder_conf = change_config_factory(
    config_path="/etc/cinder/cinder.conf",
    config=[('DEFAULT', 'log_dir', '/'),
            ('keystone_authtoken', 'admin_user', 'admin')])

keystone_conf = change_config_factory(
    config_path="/etc/keystone/keystone.conf",
    config=[('DEFAULT', 'admin_token', ''),
            ('oslo_messaging_rabbit', 'rabbit_userid', 'cinder')])

heat_conf = change_config_factory(
    config_path="/etc/heat/heat.conf",
    config=[('DEFAULT', 'debug', False)])

glance_api_conf = change_config_factory(
    config_path="/etc/glance/glance-api.conf",
    config=[('DEFAULT', 'show_image_direct_url', 'wrong_value')])

neutron_conf = change_config_factory(
    config_path="/etc/neutron/neutron.conf",
    config=[('DEFAULT', 'auth_strategy', 'nova')])


@pytest.yield_fixture
def puppet_file_new_mod(env):
    controller = env.get_nodes_by_role('controller')[0]
    puppet_file = "/etc/logrotate.d/apache2"
    new_mod = '0777'
    with controller.ssh() as remote:
        cmd = 'stat -c "%a" {0}'.format(puppet_file)
        mod = remote.check_call(cmd)['stdout'][0].strip()
        remote.check_call('chmod {0} {1}'.format(new_mod, puppet_file))

    yield {'node': controller, 'new_mod': new_mod}

    with controller.ssh() as remote:
        remote.check_call('chmod {0} {1}'.format(mod, puppet_file))


@pytest.yield_fixture
def puppet_file_new_owner(env):
    controller = env.get_nodes_by_role('controller')[0]
    puppet_file = "/etc/logrotate.d/apache2"
    new_owner = 'test_user'
    with controller.ssh() as remote:
        cmd = 'stat -c "%U" {0}'.format(puppet_file)
        owner = remote.check_call(cmd)['stdout'][0].strip()
        remote.check_call('useradd -g root {0}'.format(new_owner))
        remote.check_call('chown {0}:root {1}'.format(new_owner, puppet_file))

    yield {'node': controller, 'new_owner': new_owner}

    with controller.ssh() as remote:
        remote.check_call('chown {0}:root {1}'.format(owner, puppet_file))
        remote.check_call('userdel {0}'.format(new_owner))


@pytest.fixture
def without_router(os_conn):
    router = os_conn.neutron.list_routers(name='router04')['routers'][0]
    os_conn.delete_router(router['id'])
