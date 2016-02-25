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

from functools import partial
import tempfile
import uuid

import pytest
from six.moves import configparser
from tempest.lib.cli import base

from mos_tests.functions import common
from mos_tests.functions import os_cli


@pytest.fixture
def suffix():
    return str(uuid.uuid4())


@pytest.yield_fixture
def short_lifetime_keystone(env):
    """Change keystone token lifetime to 30s"""

    def set_lifetime(node):
        with node.ssh() as remote:
            remote.check_call('service apache2 stop')
            remote.check_call('mv /etc/keystone/keystone.conf '
                              '/etc/keystone/keystone.conf.orig')
            with remote.open('/etc/keystone/keystone.conf.orig') as f:
                parser = configparser.RawConfigParser()
                parser.readfp(f)
                parser.set('token', 'expiration', 30)
                with remote.open('/etc/keystone/keystone.conf', 'w') as new_f:
                    parser.write(new_f)
            remote.check_call('service apache2 start')

    def reset_lifetime(node):
        with node.ssh() as remote:
            remote.check_call('service apache2 stop')
            remote.check_call('mv /etc/keystone/keystone.conf.orig '
                              '/etc/keystone/keystone.conf')
            remote.check_call('service apache2 start')

    def wait_keystone_alive():
        common.wait(lambda: common.get_os_conn(env), timeout_seconds=60 * 3,
                    waiting_for='keystone available',
                    expected_exceptions=Exception)

    controllers = env.get_nodes_by_role('controller')
    for controller in controllers:
        set_lifetime(controller)
    wait_keystone_alive()
    yield
    for controller in controllers:
        reset_lifetime(controller)
    wait_keystone_alive()


@pytest.fixture
def cli(os_conn):
    return base.CLIClient(username=os_conn.username,
                          password=os_conn.password,
                          tenant_name=os_conn.tenant,
                          uri=os_conn.keystone.auth_url,
                          cli_dir='.tox/glance/bin',
                          insecure=os_conn.insecure,
                          prefix='env PYTHONIOENCODING=UTF-8')


@pytest.fixture
def glance(request, os_conn, cli):
    flags = '--os-cacert {0.path_to_cert} --os-image-api-version {1}'.format(
        os_conn, request.param)
    return partial(cli.glance, flags=flags)


@pytest.yield_fixture
def image_file(request):
    size = getattr(request, 'param', 100)  # Size in MB
    with tempfile.NamedTemporaryFile(delete=True) as f:
        f.seek(size * (1024 ** 2))
        f.write(' ')
        f.flush()
        yield f.name


@pytest.yield_fixture
def controller_remote(env):
    with env.get_nodes_by_role('controller')[0].ssh() as remote:
        yield remote


@pytest.fixture
def openstack_client(controller_remote):
    return os_cli.OpenStack(controller_remote)


@pytest.fixture(params=['1', '2'], ids=['api v1', 'api v2'])
def glance_remote(request, controller_remote):
    # TODO(gdyuldin) Replace with glance fixture after
    # https://review.openstack.org/284355 will be merged
    flags = '--os-image-api-version {0.param}'.format(request)
    return partial(os_cli.Glance(controller_remote), flags=flags,
                   prefix='env PYTHONIOENCODING=UTF-8')


@pytest.yield_fixture
def project(openstack_client, suffix):
    project_name = "project_{}".format(suffix[:6])
    project = openstack_client.project_create(project_name)
    yield project
    openstack_client.project_delete(project['id'])


@pytest.yield_fixture
def user(openstack_client, suffix, project):
    name = "user_{}".format(suffix[:6])
    password = "password"
    user = openstack_client.user_create(name=name, password=password,
                                project=project['id'])
    yield user
    openstack_client.user_delete(user['id'])
