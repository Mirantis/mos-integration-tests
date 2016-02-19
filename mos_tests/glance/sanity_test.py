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
from tempest_lib.cli import output_parser as parser


@pytest.mark.parametrize('glance', [1], indirect=['glance'])
def test_update_raw_data_in_image(glance, image_file):
    """Checks updating raw data in Glance image"""
    name = "Test_{0}".format(str(uuid.uuid4())[:6])
    cmd = ("image-create --name {name} --container-format bare --disk-format "
           "qcow2".format(name=name))
    image = parser.details(glance(cmd))
    image_data = parser.details(glance('image-show {id}'.format(**image)))
    assert image_data['status'] == 'queued'

    image_list = parser.listing(glance('image-list'))
    assert image['id'] in [x['ID'] for x in image_list]

    glance('image-update --file {file} --progress {id}'.format(
        file=image_file, **image))
    image_data = parser.details(glance('image-show {id}'.format(**image)))
    assert image_data['status'] == 'active'

    glance('image-delete {id}'.format(**image))
    image_list = parser.listing(glance('image-list'))
    assert image['id'] not in [x['ID'] for x in image_list]
