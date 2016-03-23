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

import uuid

import pytest
from tempest.lib.cli import output_parser as parser

pytestmark = pytest.mark.undestructive


@pytest.mark.testrail_id('542896', params={'glance': 1})
@pytest.mark.testrail_id('542924', params={'glance': 2})
@pytest.mark.parametrize('glance', [1, 2], indirect=['glance'])
def test_upload_image_wo_disk_format_and_container_format(image_file, glance):
    """Checks that disk-format and container-format are required"""
    name = 'Test_{0}'.format(str(uuid.uuid4())[:6])
    cmd = 'image-create --name {name} --file {path} --progress'.format(
        name=name,
        path=image_file)
    out = glance(cmd, fail_ok=True, merge_stderr=True)
    assert 'error: Must provide' in out
    assert '--container-format' in out
    assert '--disk-format' in out
    assert 'when using --file' in out
    images = parser.listing(glance('image-list'))
    assert name not in [x['Name'] for x in images]


@pytest.mark.testrail_id('542895', params={'glance_remote': 1})
@pytest.mark.testrail_id('542923', params={'glance_remote': 2})
@pytest.mark.parametrize('glance_remote', [1, 2], indirect=['glance_remote'])
def test_remove_deleted_image(glance_remote):
    """Checks error message on delete already deleted image"""
    image = parser.details(glance_remote('image-create'))
    glance_remote('image-delete {id}'.format(**image))

    out = glance_remote('image-delete {id}'.format(**image),
                        fail_ok=True,
                        merge_stderr=True)
    assert "No image with an ID of '{id}' exists".format(**image) in out


@pytest.mark.testrail_id('542897', params={'glance_remote': 1})
@pytest.mark.testrail_id('542925', params={'glance_remote': 2})
@pytest.mark.parametrize(
    'glance_remote, message',
    ((1, 'Image {id} is not active (HTTP 404)'),
     (2, 'Image {id} has no data.'), ),
    indirect=['glance_remote'])
def test_download_zero_size_image(glance_remote, message):
    image = parser.details(glance_remote('image-create'))

    for command in ('image-download {id}', 'image-download {id} --progress'):
        out = glance_remote(
            command.format(**image),
            fail_ok=True,
            merge_stderr=True)
        assert message.format(**image) in out

    glance_remote('image-delete {id}'.format(**image))

    images = parser.listing(glance_remote('image-list'))
    assert image['id'] not in [x['ID'] for x in images]
