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
import os
import subprocess
import uuid

import pytest
from tempest_lib.cli import base
from tempest_lib.cli import output_parser as parser


pytestmark = pytest.mark.undestructive


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
def fake_image():
    image_name = "image_{}".format(str(uuid.uuid4())[:4])
    subprocess.check_call('fallocate -l 100MB {}'.format(image_name),
                          shell=True)
    yield image_name
    os.remove(image_name)


def test_upload_image_wo_disk_format_and_container_format(fake_image, glance):
    """Checks that disk-format and container-format are required"""
    name = 'Test_{0}'.format(str(uuid.uuid4())[:6])
    cmd = 'image-create --name {name} --file {path} --progress'.format(
        name=name, path=fake_image)
    out = glance(cmd, fail_ok=True, merge_stderr=True)
    assert 'error: Must provide' in out
    assert '--container-format' in out
    assert '--disk-format' in out
    assert 'when using --file' in out
    images = parser.listing(glance('image-list'))
    assert name not in [x['Name'] for x in images]


@pytest.mark.parametrize('glance, message', (
    (1, "No image with an ID of '{id}' exists"),
    (2, "No image found with ID {id} (HTTP 404)"),
), indirect=['glance'])
def test_remove_deleted_image(glance, message):
    """Checks error message on delete already deleted image"""
    image = parser.details(glance('image-create'))
    glance('image-delete {id}'.format(**image))
    out = glance('image-delete {id}'.format(**image), fail_ok=True,
                 merge_stderr=True)
    assert message.format(**image) in out
