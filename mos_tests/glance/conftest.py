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

import pytest
from six.moves import configparser
from tempest.lib.cli import base

from mos_tests.functions import common
from mos_tests.functions import os_cli


def wait_for_glance_alive(os_conn):
    common.wait(lambda: len(list(os_conn.glance.images.list())) > 0,
                timeout_seconds=60,
                expected_exceptions=Exception,
                waiting_for='glance to be alive')


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
            remote.check_call('for i in {1..15};'
                              'do if [ "$(service apache2 start)" ];'
                              'then break;fi;done')

    def wait_keystone_alive():
        session = env.os_conn.session
        common.wait(lambda: session.get(session.auth.auth_url).ok,
                    timeout_seconds=60 * 3,
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
                          uri=os_conn.session.auth.auth_url,
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
def image_file_remote(request, controller_remote, suffix):
    size = getattr(request, 'param', 100)  # Size in MB
    filename = '/tmp/{}'.format(suffix[:6])
    with controller_remote.open(filename, 'w') as f:
        f.seek(size * (1024 ** 2))
        f.write(' ')
        f.flush()
    yield filename
    controller_remote.execute('rm -f {}'.format(filename))


@pytest.fixture
def openstack_client(controller_remote):
    return os_cli.OpenStack(controller_remote)


@pytest.fixture(params=['1', '2'], ids=['api v1', 'api v2'])
def glance_remote(request, controller_remote):
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


@pytest.yield_fixture
def enable_multiple_locations_glance(env):
    """Change show_multiple_locations to true"""

    def set_show_multiple_locations(node):
        with node.ssh() as remote:
            remote.check_call('mv /etc/glance/glance-api.conf '
                              '/etc/glance/glance-api.conf.orig')
            remote.check_call("cat /etc/glance/glance-api.conf.orig | sed "
                              "'s/#show_multiple_locations = false/"
                              "show_multiple_locations = true/g' > "
                              "/etc/glance/glance-api.conf")
            remote.check_call('service glance-api restart')

    def reset_show_multiple_locations(node):
        with node.ssh() as remote:
            remote.check_call('mv /etc/glance/glance-api.conf.orig '
                              '/etc/glance/glance-api.conf')
            remote.check_call('service glance-api restart')

    controllers = env.get_nodes_by_role('controller')
    for controller in controllers:
        set_show_multiple_locations(controller)
    wait_for_glance_alive(env.os_conn)
    yield
    for controller in controllers:
        reset_show_multiple_locations(controller)
    wait_for_glance_alive(env.os_conn)


@pytest.yield_fixture
def enable_image_direct_url_glance(env):
    """Change show_image_direct_url to True"""

    def set_show_image_direct_url(node):
        with node.ssh() as remote:
            remote.check_call('mv /etc/glance/glance-api.conf '
                              '/etc/glance/glance-api.conf.orig')
            remote.check_call("cat /etc/glance/glance-api.conf.orig | sed "
                              "'s/show_image_direct_url = False/"
                              "show_image_direct_url = True/g' > "
                              "/etc/glance/glance-api.conf")
            remote.check_call('service glance-api restart')

    def reset_show_image_direct_url(node):
        with node.ssh() as remote:
            remote.check_call('mv /etc/glance/glance-api.conf.orig '
                              '/etc/glance/glance-api.conf')
            remote.check_call('service glance-api restart')

    controllers = env.get_nodes_by_role('controller')
    for controller in controllers:
        set_show_image_direct_url(controller)
    wait_for_glance_alive(env.os_conn)
    yield
    for controller in controllers:
        reset_show_image_direct_url(controller)
    wait_for_glance_alive(env.os_conn)
