# -*- coding: utf-8 -*-
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

import hashlib
import tempfile

import pytest
from tempest.lib.cli import output_parser as parser

from mos_tests.functions.common import wait
from mos_tests import settings

pytestmark = pytest.mark.undestructive


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


def calc_md5(filename):
    with open(filename, 'r') as f:
        md5 = hashlib.md5()
        for chunk in iter(lambda: f.read(1024), ''):
            md5.update(chunk)
    return md5.hexdigest()


@pytest.mark.testrail_id('542892')
@pytest.mark.parametrize('glance_remote', [1], indirect=['glance_remote'])
def test_update_raw_data_in_image(glance_remote, image_file_remote, suffix):
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
    image = parser.details(glance_remote(cmd))
    image_data = glance_remote('image-show {id}'.format(**image)).details()
    assert image_data['status'] == 'queued'

    check_image_in_list(glance_remote, image)

    glance_remote('image-update --file {file} --progress {id}'.format(
        file=image_file_remote,
        **image))
    check_image_active(glance_remote, image)

    glance_remote('image-delete {id}'.format(**image))

    check_image_not_in_list(glance_remote, image)


@pytest.mark.testrail_id('542893', params={'glance': 1})
@pytest.mark.testrail_id('542913', params={'glance': 2})
@pytest.mark.parametrize('glance', [1, 2], indirect=['glance'])
def test_share_glance_image(glance, user, project, image_file, suffix):
    """Check sharing glance image to another project

    Scenario:
        1. Create image from `image_file`
        2. Check that image is present in list and image status is `active`
        3. Bind another project to image
        4. Check that binded project id is present in image member list
        5. Unbind project from image
        6. Check that project id is not present in image member list
        7. Delete image
        8. Check that image deleted
    """
    name = "Test_{0}".format(suffix[:6])
    cmd = ("image-create --name {name} --container-format bare --disk-format "
           "qcow2 --file {file} --progress".format(name=name,
                                                   file=image_file))
    image = parser.details(glance(cmd))

    check_image_active(glance, image)

    check_image_in_list(glance, image)

    glance('member-create {id} {project_id}'.format(project_id=project['id'],
                                                    **image))

    member_list = parser.listing(glance('member-list --image-id {id}'.format(
        **image)))
    assert project['id'] in [x['Member ID'] for x in member_list]

    glance('member-delete {id} {project_id}'.format(project_id=project['id'],
                                                    **image))

    member_list = parser.listing(glance('member-list --image-id {id}'.format(
        **image)))
    assert project['id'] not in [x['Member ID'] for x in member_list]

    glance('image-delete {id}'.format(**image))

    check_image_not_in_list(glance, image)


@pytest.mark.testrail_id('542882', params={'glance': 1})
@pytest.mark.testrail_id('542898', params={'glance': 2})
@pytest.mark.parametrize('glance', [1, 2], indirect=['glance'])
def test_image_create_delete_from_file(glance, image_file, suffix):
    """Checks image creation and deletion from file

    Scenario:
        1. Create image from file
        2. Check that image exists and has `active` status
        3. Delete image
        4. Check that image deleted
    """
    name = 'Test_{}'.format(suffix)
    cmd = ('image-create --name {name} --container-format bare '
           '--disk-format qcow2 --file {source} --progress'.format(
               name=name,
               source=image_file))

    image = parser.details(glance(cmd))

    check_image_active(glance, image)

    glance('image-delete {id}'.format(**image))

    check_image_not_in_list(glance, image)


@pytest.mark.testrail_id('542883',
                         params={'glance': 1,
                                 'option': '--copy-from'})
@pytest.mark.testrail_id('542884',
                         params={'glance': 1,
                                 'option': '--location'})
@pytest.mark.parametrize('glance', [1], indirect=['glance'])
@pytest.mark.parametrize('option', ('--location', '--copy-from'))
def test_image_create_delete_from_url(glance, suffix, option):
    """Check image creation and deletion from URL

    Scenario:
        1. Create image from URL
        2. Wait until image has active `status`
        3. Delete image
        4. Check that image deleted
    """
    name = 'Test_{}'.format(suffix)
    image_url = settings.GLANCE_IMAGE_URL
    cmd = ('image-create --name {name} --container-format bare '
           '--disk-format qcow2 {option} {image_url} --progress'.format(
               name=name,
               option=option,
               image_url=image_url))

    image = parser.details(glance(cmd))

    def is_image_active():
        image_data = parser.details(glance('image-show {id}'.format(**image)))
        return image_data['status'] == 'active'

    wait(is_image_active, timeout_seconds=60, waiting_for='image is active')

    glance('image-delete {id}'.format(**image))

    check_image_not_in_list(glance, image)


@pytest.mark.testrail_id('542890', params={'glance': 1})
@pytest.mark.testrail_id('542911', params={'glance': 2})
@pytest.mark.parametrize('glance', [1, 2], indirect=['glance'])
def test_image_file_equal(glance, image_file, suffix):
    """Check that after upload-download image file are not changed

    Scenario:
        1. Create image from file
        2. Download image to new file
        3. Compare file and new file
        4. Delete image
    """
    name = 'Test_{}'.format(suffix)
    cmd = ('image-create --name {name} --container-format bare '
           '--disk-format qcow2 --file {source} --progress'.format(
               name=name,
               source=image_file))

    image = parser.details(glance(cmd))

    with tempfile.NamedTemporaryFile() as new_file:
        new_file.write(glance('image-download {id}'.format(**image)))
        new_file.flush()
        original_md5 = calc_md5(image_file)
        new_md5 = calc_md5(new_file.name)

    assert original_md5 == new_md5, 'MD5 sums of images are different'

    glance('image-delete {id}'.format(**image))


@pytest.mark.testrail_id('542894', params={'glance_remote': 1})
@pytest.mark.testrail_id('542914', params={'glance_remote': 2})
@pytest.mark.parametrize('glance_remote', [1, 2], indirect=['glance_remote'])
def test_unicode_support(glance_remote, suffix):
    """Check support of unicode symbols in image name

    Scenario:
        1. Create image with name 試験画像
        2. Check that created image is in list and has status `queued`
        3. Delete image
        4. Check that image deleted
    """
    name = u"試験画像_{0}".format(suffix[:6])
    cmd = (u"image-create --name {name}".format(name=name))
    image = parser.details(glance_remote(cmd))

    check_image_in_list(glance_remote, image)

    image_data = glance_remote('image-show {id}'.format(**image)).details()
    assert image_data['status'] == 'queued'

    glance_remote('image-delete {id}'.format(**image))
    check_image_not_in_list(glance_remote, image)


@pytest.mark.testrail_id('775840', params={'glance': 1})
@pytest.mark.testrail_id('775842', params={'glance': 2})
@pytest.mark.usefixtures('short_lifetime_keystone')
@pytest.mark.parametrize('image_file', [5 * 1024], indirect=['image_file'])
@pytest.mark.parametrize('glance', [1, 2], indirect=['glance'])
def test_upload_image_with_token_expiration(glance, image_file, suffix):
    """Check that big image uploaded succcess if token expired during uploading

    Scenario:
        1. Create image from big file
        2. Check that created image is in list and has status `active`
        3. Delete image
        4. Check that image deleted
    """
    name = u"Test_{0}".format(suffix[:6])
    cmd = ('image-create --name {name} --container-format bare '
           '--disk-format qcow2 --file {source} --progress'.format(
               name=name,
               source=image_file))

    image = parser.details(glance(cmd))

    check_image_active(glance, image)

    glance('image-delete {id}'.format(**image))

    check_image_not_in_list(glance, image)


@pytest.mark.testrail_id('843369', params={'glance_remote': 2})
@pytest.mark.testrail_id('836601', params={'glance_remote': 1})
@pytest.mark.parametrize('glance_remote, key_name',
                         ((1, "Property 'key'"),
                          (2, 'key'), ),
                         indirect=['glance_remote'])
def test_update_properties_of_image(glance_remote, image_file_remote, suffix,
                                    key_name):
    """Check updating properties of glance image

    Scenario:
        1. Create image from `image_file`
        2. Check that image is present in list and image status is `active`
        3. Update image with property key=test
        4. Check that image has property 'key' = test
        5. Delete image
        6. Check that image deleted
    """
    name = "Test_{0}".format(suffix[:6])
    cmd = ("image-create --name {name} --container-format bare --disk-format "
           "qcow2 --file {file} --progress".format(name=name,
                                                   file=image_file_remote))
    image = parser.details(glance_remote(cmd))

    check_image_active(glance_remote, image)

    check_image_in_list(glance_remote, image)

    glance_remote('image-update {id} --property key=test'.format(**image))

    image_data = glance_remote('image-show {id}'.format(**image)).details()
    assert image_data[key_name] == 'test'

    glance_remote('image-delete {id}'.format(**image))

    check_image_not_in_list(glance_remote, image)


@pytest.yield_fixture
def images(os_conn):
    """Create images for filtering"""
    image_params = {
        "img1": {"name": "image-1", "container_format": "ami",
                 "disk_format": "qcow2"},
        "img2": {"name": "image-2", "container_format": "bare",
                 "disk_format": "qcow2"},
        "img2_1": {"name": "image-2", "container_format": None,
                   "disk_format": None},
        "img3": {"name": "image-3", "container_format": "ami",
                 "disk_format": None}
    }
    images = {}
    for key, params in image_params.items():
        image = os_conn.glance.images.create(**params)
        images[key] = image.id
    yield images
    for image_id in images.values():
        os_conn.glance.images.delete(image_id)


@pytest.mark.testrail_id('851874')
@pytest.mark.parametrize('glance_remote', [2], indirect=['glance_remote'])
def test_filtering(glance_remote, os_conn, images):
    """Check filtering of glance

    Scenario:
        1. Create 4 images with different properties
        2. Check that images in list
        3. Check that filtering works correctly
        4. Delete all images
        5. Check that all images was deleted
    """
    filters = {
        "--property-filter name=in:image-1": {images["img1"]},
        "--property-filter name=in:image-1,image-2": {images["img1"],
                                                      images["img2"],
                                                      images["img2_1"]},
        "--property-filter disk_format=in:qcow2": {images["img1"],
                                                   images["img2"]},
        "--property-filter container_format=in:ami": {images["img1"],
                                                      images["img3"]},
        "--property-filter id=in:{image1},{image3}".format(
            image1=images["img1"],
            image3=images["img3"]): {images["img1"],
                                     images["img3"]},
        "--property-filter name=in:image-1 "
        "--property-filter disk_format=in:bare": set()
    }

    for fltr, expected_ids in filters.items():
        image_list = glance_remote(
            'image-list {0}'.format(fltr)).listing()
        filtered_image_ids = {x['ID'] for x in image_list}
        assert filtered_image_ids & set(images.values()) == expected_ids
