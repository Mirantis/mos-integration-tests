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
from tempest.lib.cli import output_parser as parser

from mos_tests.conftest import ubuntu_image_id as ubuntu_image_id_base
from mos_tests.neutron.python_tests.base import TestBase
from mos_tests import settings


logger = logging.getLogger(__name__)


@pytest.fixture
def ubuntu_image_id(os_conn):
    return next(ubuntu_image_id_base(os_conn))


@pytest.mark.check_env_('is_ha')
class TestGlanceHA(TestBase):

    @pytest.mark.testrail_id('836632')
    @pytest.mark.parametrize('glance', [2], indirect=['glance'])
    def test_shutdown_primary_controller(
            self, glance, image_file, suffix, devops_env, timeout=60):
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
        primary_node = devops_env.get_node_by_fuel_node(primary_controller)

        # Shutdown primary controller
        self.env.warm_shutdown_nodes([primary_node])

        name = 'Test_{}'.format(suffix[:6])
        cmd = ('image-create --name {name} --container-format bare '
               '--disk-format qcow2 --file {file}'.format(name=name,
                                                          file=image_file))
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

    @pytest.mark.testrail_id('836633')
    @pytest.mark.parametrize('glance', [1], indirect=['glance'])
    def test_shutdown_active_controller_during_upload(
            self, glance, image_file, suffix, devops_env, timeout=60):
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
        primary_node = devops_env.get_node_by_fuel_node(primary_controller)

        name = 'Test_{}'.format(suffix[:6])
        image_url = settings.GLANCE_IMAGE_URL
        cmd = ('image-create --name {name} --container-format bare '
               '--disk-format qcow2 --location {image_url}'
               .format(name=name, image_url=image_url))
        image = parser.details(glance(cmd))
        logger.info('Image starts to upload')

        # Shutdown primary controller
        self.env.warm_shutdown_nodes([primary_node])

        image_list = parser.listing(glance('image-list'))
        assert image['id'] in [x['ID'] for x in image_list]

        image_data = parser.details(glance('image-show {id}'.format(**image)))
        assert image_data['status'] == 'active'
        logger.info('Image is active')

        glance('image-delete {id}'.format(**image))

        images = parser.listing(glance('image-list'))
        assert image['id'] not in [x['ID'] for x in images]

    @pytest.mark.testrail_id('1295472')
    def test_restart_all_services(self, env, os_conn, ubuntu_image_id):
        """Check GLance work after restarting all Glance services

        Scenario:
            1. Boot vm "vm1" with ubuntu image
            2. Check "vm1" vm is SSH available
            3. Upload new image "image1" to Glance
            4. Download "image1" image and check it's content
            5. Restart all glance services on all controllers
            6. Check that "image1" image in glance list
            7. Download "image1" image and check it's content
            8. Upload new image "image2" to Glance
            9. Download "image2" image and check it's content
            10. Boot vm "vm2" with ubuntu image
            11. Check "vm2" vm is SSH available
        """
        internal_net = os_conn.int_networks[0]
        instance_keypair = os_conn.create_key(key_name='instancekey')
        security_group = self.os_conn.create_sec_group_for_ssh()
        flavor = os_conn.nova.flavors.find(name='m1.small')

        # Boot vm1 from ubuntu
        os_conn.create_server(name='vm1',
                              image_id=ubuntu_image_id,
                              flavor=flavor,
                              availability_zone='nova',
                              key_name=instance_keypair.name,
                              nics=[{'net-id': internal_net['id']}],
                              security_groups=[security_group.id])

        # Create image1
        image1_content = 'image1_content'
        image1 = os_conn.glance.images.create(name='image1',
                                              disk_format='qcow2',
                                              container_format='bare')
        os_conn.glance.images.upload(image1.id, image1_content)

        # Check image1 content
        data = os_conn.glance.images.data(image1.id)
        assert ''.join(data) == image1_content

        # Restart glance services
        glance_services_cmd = ("service --status-all 2>&1 | grep '+' | "
                               "grep glance | awk '{ print $4 }'")
        for node in env.get_nodes_by_role('controller'):
            with node.ssh() as remote:
                output = remote.check_call(glance_services_cmd).stdout_string
                for service in output.splitlines():
                    remote.check_call('service {0} restart'.format(service))

        # Check image1 in list
        images_ids = [x.id for x in os_conn.glance.images.list()]
        assert image1.id in images_ids

        # Check image1 content
        data = os_conn.glance.images.data(image1.id)
        assert ''.join(data) == image1_content

        # Create image2
        image2_content = image1_content.upper()
        image2 = os_conn.glance.images.create(name='image2',
                                              disk_format='qcow2',
                                              container_format='bare')

        os_conn.glance.images.upload(image2.id, image2_content)

        # Check image1 content
        data = os_conn.glance.images.data(image2.id)
        assert ''.join(data) == image2_content

        # Boot vm1 from ubuntu
        os_conn.create_server(name='vm2',
                              image_id=ubuntu_image_id,
                              flavor=flavor,
                              availability_zone='nova',
                              key_name=instance_keypair.name,
                              nics=[{'net-id': internal_net['id']}],
                              security_groups=[security_group.id])
