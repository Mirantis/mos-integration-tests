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


import logging

import pytest
from tempest_lib.cli import output_parser as parser

from mos_tests.environment.devops_client import DevopsClient
from mos_tests.neutron.python_tests.base import TestBase
from mos_tests import settings


logger = logging.getLogger(__name__)


@pytest.mark.check_env_('is_ha')
class TestGlanceHA(TestBase):

    @pytest.mark.parametrize('glance', [2], indirect=['glance'])
    def test_shutdown_primary_controller(
            self, glance, image_file, suffix, timeout=60):
        """Check creating image after shutdown primary controller

        Steps:
            1. Shutdown primary controller
            2. Create image from `image_file`
            3. Check that image is present in list and image status is `active`
            4. Delete created image
            5. Check that image deleted
        """
        # Find a primary controller
        primary_controller = self.env.primary_controller
        mac = primary_controller.data['mac']
        primary_node = DevopsClient.get_node_by_mac(
            env_name=self.env_name, mac=mac)

        # Shutdown primary controller
        self.env.warm_shutdown_nodes([primary_node])

        name = 'Test_{}'.format(suffix[:6])
        cmd = ('image-create --name {name} --container-format bare '
               '--disk-format qcow2 --file {file}'.format(
                    name=name, file=image_file))
        image = parser.details(glance(cmd))
        logger.info('Image starts to upload')

        image_list = parser.listing(glance('image-list'))
        assert image['id'] in [x['ID'] for x in image_list]

        image_data = parser.details(glance('image-show {id}'.format(**image)))
        assert image_data['status'] == 'active'
        logger.info('Image is active')

        glance('image-delete {id}'.format(**image))

        images = parser.listing(glance('image-list'))
        assert image['id'] not in [x['ID'] for x in images]

    @pytest.mark.parametrize('glance', [1], indirect=['glance'])
    def test_shutdown_active_controller_during_upload(
            self, glance, image_file, suffix, timeout=60):
        """Check that image is created successfully if during creating image
        to perform shutdown of active controller

        Steps:
            1. Create image using URL Link
            2. Shutdown active controller during creation of image
            3. Check that image is present in list and image status is `active`
            4. Delete created image
            5. Check that image deleted
        """

        # Find a primary controller
        primary_controller = self.env.primary_controller
        mac = primary_controller.data['mac']
        self.primary_node = DevopsClient.get_node_by_mac(
            env_name=self.env_name, mac=mac)

        name = 'Test_{}'.format(suffix[:6])
        image_url = settings.GLANCE_IMAGE_URL
        cmd = ('image-create --name {name} --container-format bare '
               '--disk-format qcow2 --location {image_url}'.format(
                    name=name, image_url=image_url))
        image = parser.details(glance(cmd))
        logger.info('Image starts to upload')

        # Shutdown primary controller
        self.env.warm_shutdown_nodes([self.primary_node])

        image_list = parser.listing(glance('image-list'))
        assert image['id'] in [x['ID'] for x in image_list]

        image_data = parser.details(glance('image-show {id}'.format(**image)))
        assert image_data['status'] == 'active'
        logger.info('Image is active')

        glance('image-delete {id}'.format(**image))

        images = parser.listing(glance('image-list'))
        assert image['id'] not in [x['ID'] for x in images]
