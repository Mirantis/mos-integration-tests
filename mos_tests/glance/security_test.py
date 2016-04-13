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

from glanceclient.exc import Forbidden

from mos_tests.neutron.python_tests.base import TestBase
from mos_tests import settings


class TestGlanceSecurity(TestBase):

    @pytest.mark.testrail_id('674709')
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
