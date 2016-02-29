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
from tempest_lib.cli import base

from mos_tests.functions import os_cli


@pytest.fixture
def suffix():
    return str(uuid.uuid4())


@pytest.fixture
def cli(os_conn):
    return base.CLIClient(username=os_conn.username,
                          password=os_conn.password,
                          tenant_name=os_conn.tenant,
                          uri=os_conn.keystone.auth_url,
                          cli_dir='.tox/glance/bin',
                          insecure=os_conn.insecure)


@pytest.fixture(params=['1', '2'], ids=['api_v1', 'api_v2'])
def glance(request, os_conn, cli):
    flags = '--os-cacert {0.path_to_cert} --os-image-api-version {1}'.format(
        os_conn, request.param)
    return partial(cli.glance, flags=flags)


@pytest.yield_fixture
def image_file(request):
    size = getattr(request, 'param', 100)
    with tempfile.NamedTemporaryFile(delete=True) as f:
        f.seek(size * (1024 ** 2))
        f.write(' ')
        f.flush()
        yield f.name


@pytest.yield_fixture
def openstack_client(env):
    with env.get_nodes_by_role('controller')[0].ssh() as remote:
        yield os_cli.OpenStack(remote)


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
