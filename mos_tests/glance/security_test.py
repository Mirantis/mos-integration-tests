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


import logging

import pytest

from glanceclient.exc import Forbidden

from mos_tests.neutron.python_tests.base import TestBase
from mos_tests import settings


logger = logging.getLogger(__name__)


@pytest.mark.testrail_id('836638')
@pytest.mark.usefixtures('enable_multiple_locations_glance')
@pytest.mark.parametrize('glance', [2], indirect=['glance'])
class TestGlanceSecurity(TestBase):
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
        url_2 = 'http://download.cirros-cloud.net/0.3.1/' \
                'cirros-0.3.1-x86_64-disk.img'
        metadata = {}

        image = self.os_conn.glance.images.create(name=name,
                                                  disk_format='qcow2',
                                                  container_format='bare')
        image_id = image.id
        image_info = [i for i in self.os_conn.glance.images.list()
                      if i.id == image_id][0]
        assert len(image_info.locations) == 0
        assert image_info.status == 'queued'

        self.os_conn.glance.images.add_location(image_id, url_1, metadata)
        self.os_conn.glance.images.add_location(image_id, url_2, metadata)

        image_info = [i for i in self.os_conn.glance.images.list()
                      if i.id == image_id][0]
        assert len(image_info.locations) == 2
        image_locations = [image_info.locations[i]['url'] for i in range(2)]
        assert url_1, url_2 in image_locations
        assert image_info.status == 'active'

        self.os_conn.glance.images.delete_locations(image_id, set([url_1]))
        image_info = [i for i in self.os_conn.glance.images.list()
                      if i.id == image_id][0]
        assert len(image_info.locations) == 1
        assert image_info.locations[0]['url'] == url_2
        assert image_info.status == 'active'

        try:
            self.os_conn.glance.images.delete_locations(image_id, set([url_2]))
        except Forbidden as e:
            logger.info(e)

        image_info = [i for i in self.os_conn.glance.images.list()
                      if i.id == image_id][0]
        assert len(image_info.locations) == 1
        assert image_info.status == 'active'

        self.os_conn.glance.images.delete(image_id)
        images_id = [i.id for i in self.os_conn.glance.images.list()]
        assert image_id not in images_id
