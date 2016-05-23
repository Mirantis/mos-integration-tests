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


import pytest
import requests

from glanceclient.exc import Forbidden

from six.moves import configparser

from mos_tests.glance.conftest import wait_for_glance_alive
from mos_tests.neutron.python_tests.base import TestBase
from mos_tests import settings


@pytest.fixture
def change_glance_credentials(env, openstack_client, os_conn):
    """Change user and password for Glance"""

    config_api = '/etc/glance/glance-api.conf'
    config_swift = '/etc/glance/glance-swift.conf'

    def change_credentials(node):
        with node.ssh() as remote:
            with remote.open(config_api) as f:
                parser = configparser.RawConfigParser()
                parser.readfp(f)
            parser.set('keystone_authtoken', 'admin_user', 'glance-1')
            parser.set('keystone_authtoken', 'admin_password', 'test')
            with remote.open(config_api, 'w') as f:
                parser.write(f)

            with remote.open(config_swift) as f:
                parser = configparser.RawConfigParser()
                parser.readfp(f)
            parser.set('ref1', 'user', 'services:glance-1')
            parser.set('ref1', 'key', 'test')
            with remote.open(config_swift, 'w') as f:
                parser.write(f)

            remote.check_call('service glance-api restart')

    controllers = env.get_nodes_by_role('controller')
    openstack_client.user_set_new_name('glance', 'glance-1')
    openstack_client.user_set_new_password('glance-1', 'test')
    for controller in controllers:
        change_credentials(controller)
    wait_for_glance_alive(os_conn)


class TestGlanceSecurity(TestBase):

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('836638')
    @pytest.mark.usefixtures('enable_multiple_locations_glance')
    @pytest.mark.parametrize('glance', [2], indirect=['glance'])
    def test_remove_last_image_location(self, glance, suffix):
        """Checks that deleting of last image location is not possible

        Scenario:
            1. Create new image, check that image status is queued
            2. Add two locations for the image, check that image status is
            active, locations are correct
            3. Delete the first image location, check that image status is
            active, correct location is deleted
            4. Try to delete the second image location, check that last
            location is not deleted - 403 error message is observed, image
            status is active
            5. Delete image, check that image deleted
        """
        name = "Test_{0}".format(suffix[:6])
        url_1 = settings.GLANCE_IMAGE_URL
        url_2 = ('http://download.cirros-cloud.net/0.3.1/'
                 'cirros-0.3.1-x86_64-disk.img')
        metadata = {}

        image = self.os_conn.glance.images.create(name=name,
                                                  disk_format='qcow2',
                                                  container_format='bare')
        assert len(image.locations) == 0
        assert image.status == 'queued'

        self.os_conn.glance.images.add_location(image.id, url_1, metadata)
        self.os_conn.glance.images.add_location(image.id, url_2, metadata)

        image = self.os_conn.glance.images.get(image.id)
        assert len(image.locations) == 2
        image_locations = [x['url'] for x in image.locations]
        assert url_1 in image_locations
        assert url_2 in image_locations
        assert image.status == 'active'

        self.os_conn.glance.images.delete_locations(image.id, set([url_1]))
        image = self.os_conn.glance.images.get(image.id)
        assert len(image.locations) == 1
        assert image.locations[0]['url'] == url_2
        assert image.status == 'active'

        with pytest.raises(Forbidden):
            self.os_conn.glance.images.delete_locations(image.id, set([url_2]))

        image = self.os_conn.glance.images.get(image.id)
        assert len(image.locations) == 1
        assert image.status == 'active'

        self.os_conn.glance.images.delete(image.id)
        images_id = [i.id for i in self.os_conn.glance.images.list()]
        assert image.id not in images_id

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('836636')
    @pytest.mark.check_env_('not is_ceph_enabled')
    @pytest.mark.parametrize('glance', [2], indirect=['glance'])
    def test_image_direct_url_false(self, glance, suffix):
        """Check absence of 'direct_url' property for glance image by default
        for Swift storage

        Scenario:
            1. Create image from `image_file`
            2. Check that image status is `active`
            3. Check that image doesn't have property 'direct_url'
            4. Delete image
            5. Check that image deleted
        """
        name = "Test_{0}".format(suffix[:6])
        image = self.os_conn.glance.images.create(name=name,
                                                  disk_format='qcow2',
                                                  container_format='bare')
        self.os_conn.glance.images.upload(image.id, 'image content')

        image = self.os_conn.glance.images.get(image.id)
        assert image.status == 'active'
        assert 'direct_url' not in image.keys()

        self.os_conn.glance.images.delete(image.id)
        images_id = [i.id for i in self.os_conn.glance.images.list()]
        assert image.id not in images_id

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('843822')
    @pytest.mark.check_env_('not is_ceph_enabled')
    @pytest.mark.usefixtures('enable_image_direct_url_glance')
    @pytest.mark.parametrize('glance', [2], indirect=['glance'])
    def test_image_direct_url_true(self, glance, suffix):
        """Check that value of 'direct_url' property doesn't contain glance
        credentials (tenant:user:password) in case of show_image_direct_url =
        True for Swift storage

        Scenario:
            1. Set show_image_direct_url = True in glance-api.conf on all
            controllers and restart glance-api service on all controllers
            2. Create image from `image_file`
            3. Check that image status is `active`
            4. Check that value of image property 'direct_url' has format
            'swift+config://ref1/glance/image_id'
            5. Delete image
            6. Check that image deleted
        """
        name = "Test_{0}".format(suffix[:6])
        image = self.os_conn.glance.images.create(name=name,
                                                  disk_format='qcow2',
                                                  container_format='bare')
        self.os_conn.glance.images.upload(image.id, 'image content')

        image = self.os_conn.glance.images.get(image.id)
        assert image.status == 'active'
        expected_direct_url_value = ('swift+config://ref1/glance/{image_id}'
                                     .format(image_id=image.id))
        assert image.direct_url == expected_direct_url_value

        self.os_conn.glance.images.delete(image.id)
        images_id = [i.id for i in self.os_conn.glance.images.list()]
        assert image.id not in images_id

    @pytest.mark.testrail_id('836637')
    @pytest.mark.check_env_('not is_ceph_enabled')
    @pytest.mark.parametrize('glance_remote', [2], indirect=['glance_remote'])
    def test_download_image_if_change_credentials(self, glance_remote, suffix,
                                                  image_file_remote,
                                                  env, openstack_client,
                                                  request):
        """Check that if create image and then change glance username and
        password, it will be possible to download this image successfully

        Scenario:
            1. Create image from `image_file`
            2. Check that image status is `active`
            3. Change glance credentials into keystone, glance-api.conf,
            glance-swift.conf and restart glance-api service on all controllers
            4. Check that downloading of image executed without errors
            5. Delete image
            6. Check that image deleted
            7. Restore glance credentials
        """
        name = "Test_{0}".format(suffix[:6])
        cmd = ('image-create --name {name} --container-format bare '
               '--disk-format qcow2 --file {source} --progress'.format(
                   name=name,
                   source=image_file_remote))

        image = glance_remote(cmd).details()
        assert image['status'] == 'active'

        request.getfuncargvalue('change_glance_credentials')

        glance_remote('image-download {id} >> /dev/null'.format(**image))

        glance_remote('image-delete {id}'.format(**image))

        image_list = glance_remote('image-list').listing()
        assert image['id'] not in [x['ID'] for x in image_list]

    @pytest.mark.testrail_id('856613')
    @pytest.mark.parametrize('glance', [2], indirect=['glance'])
    def test_image_status_after_curl_request(self, glance, suffix):
        """Checks image status after curl PUT request

        Scenario:
            1. Execute 'keystone token-get' in controller and get Token ID
            2. Create image from file
            3. Check that image exists and has `active` status
            4. Send curl PUT request:
            curl -X PUT http://192.168.0.2:9292/v1/images/<image_id>
            -H 'X-Auth-Token: <token>' -H 'x-image-meta-status: queued'
            5. Check image status is not changed
        """
        token = self.os_conn.session.get_token()
        endpoint = self.os_conn.session.get_endpoint(service_type='image')

        name = "Test_{0}".format(suffix[:6])
        image = self.os_conn.glance.images.create(name=name,
                                                  disk_format='qcow2',
                                                  container_format='bare')
        self.os_conn.glance.images.upload(image.id, "image_content")

        image_status = self.os_conn.glance.images.get(image.id)['status']
        err_msg = ('Glance image status after creation is [{0}].'
                   'Expected is [active]').format(image_status)
        assert image_status == 'active', err_msg

        request_headers = {'x-image-meta-status': 'queued',
                           'X-Auth-Token': token}
        url = '{endpoint}/images/{image_id}'.format(endpoint=endpoint,
                                                    image_id=image.id)
        response = requests.put(url, headers=request_headers)
        response.raise_for_status()

        image_status = self.os_conn.glance.images.get(image.id)['status']
        err_msg = ('Glance image status is changed to [{0}].'
                   'Expected is [active]').format(image_status)
        assert image_status == 'active', err_msg
