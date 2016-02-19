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

import pytest
from tempest_lib.cli import output_parser as parser


def check_image_in_list(glance, image):
    __tracebackhide__ = True
    image_list = parser.listing(glance('image-list'))
    if image['id'] not in [x['ID'] for x in image_list]:
        pytest.fail('There is no image {id} in list'.format(**image))


def check_image_not_in_list(glance, image):
    __tracebackhide__ = True
    image_list = parser.listing(glance('image-list'))
    if image['id'] in [x['ID'] for x in image_list]:
        pytest.fail('There is image {id} in list'.format(**image))


def check_image_active(glance, image):
    __tracebackhide__ = True

    image_data = parser.details(glance('image-show {id}'.format(**image)))
    if image_data['status'] != 'active':
        pytest.fail('Image {id} status is {status} (not active)'.format(
            **image_data))


@pytest.mark.parametrize('glance', [1], indirect=['glance'])
def test_update_raw_data_in_image(glance, image_file, suffix):
    """Checks updating raw data in Glance image

    Scenario:
        1. Create image
        2. Check that image is present in list and image status is `quened`
        3. Update image with `image_file`
        4. Check that image status changes to `active`
        5. Delete image
        6. Check that image deleted
    """
    name = "Test_{0}".format(suffix[:6])
    cmd = ("image-create --name {name} --container-format bare --disk-format "
           "qcow2".format(name=name))
    image = parser.details(glance(cmd))
    image_data = parser.details(glance('image-show {id}'.format(**image)))
    assert image_data['status'] == 'queued'

    check_image_in_list(glance, image)

    glance('image-update --file {file} --progress {id}'.format(
        file=image_file, **image))
    check_image_active(glance, image)

    glance('image-delete {id}'.format(**image))

    check_image_not_in_list(glance, image)


def test_share_glance_image(glance, user, tenant, image_file, suffix):
    """Check sharing glance image to another tenant

    Scenario:
        1. Create image from `image_file`
        2. Check that image is present in list and image status is `active`
        3. Bind another tenant to image
        4. Check that binded tenant id is present in image member list
        5. Unbind tenant from image
        6. Check that tenant id is not present in image member list
        7. Delete image
        8. Check that image deleted
    """
    name = "Test_{0}".format(suffix[:6])
    cmd = ("image-create --name {name} --container-format bare --disk-format "
           "qcow2 --file {file} --progress".format(name=name, file=image_file))
    image = parser.details(glance(cmd))

    check_image_active(glance, image)

    check_image_in_list(glance, image)

    glance('member-create {id} {tenant_id}'.format(tenant_id=tenant['id'],
                                                   **image))

    member_list = parser.listing(glance('member-list --image-id {id}'.format(
        **image)))
    assert tenant['id'] in [x['Member ID'] for x in member_list]

    glance('member-delete {id} {tenant_id}'.format(tenant_id=tenant['id'],
                                                   **image))

    member_list = parser.listing(glance('member-list --image-id {id}'.format(
        **image)))
    assert tenant['id'] not in [x['Member ID'] for x in member_list]

    glance('image-delete {id}'.format(**image))

    check_image_not_in_list(glance, image)
