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
from tempest_lib.cli import base


@pytest.fixture
def cli(os_conn):
    return base.CLIClient(username=os_conn.username,
                          password=os_conn.password,
                          tenant_name=os_conn.tenant,
                          uri=os_conn.keystone.auth_url,
                          cli_dir='.tox/glance/bin',
                          insecure=os_conn.insecure)


@pytest.fixture(params=['1', '2'], ids=['api v1', 'api v2'])
def glance(request, os_conn, cli):
    flags = '--os-cacert {0.path_to_cert} --os-image-api-version {1}'.format(
        os_conn, request.param)
    return partial(cli.glance, flags=flags)


@pytest.yield_fixture
def image_file():
    with tempfile.NamedTemporaryFile(delete=True) as f:
        f.seek(10 * (1024 ** 2))  # 10 MB
        f.write(' ')
        yield f.name
