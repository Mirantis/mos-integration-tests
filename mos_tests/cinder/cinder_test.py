#    Copyright 2015 Mirantis, Inc.
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
import time

import pytest

from mos_tests.functions.base import OpenStackTestCase
from mos_tests.functions import common as common_functions

logger = logging.getLogger(__name__)


@pytest.mark.undestructive
class CinderIntegrationTests(OpenStackTestCase):
    """Basic automated tests for OpenStack Heat verification."""

    def setUp(self):
        super(self.__class__, self).setUp()

        self.volume_list = []
        self.snapshot_list = []
        self.project_id = self.session.get_project_id()
        self.quota = self.cinder.quotas.get(self.project_id).snapshots
        self.cinder.quotas.update(self.project_id, snapshots=200)

    def tearDown(self):
        try:
            for snapshot in self.snapshot_list:
                common_functions.delete_volume_snapshot(self.cinder, snapshot)
            self.snapshot_list = []
            for volume in self.volume_list:
                common_functions.delete_volume(self.cinder, volume)
            self.volume_list = []
        finally:
            self.cinder.quotas.update(self.project_id, snapshots=self.quota)

    @pytest.mark.testrail_id('543176')
    def test_creating_multiple_snapshots(self):
        """This test case checks creation of several snapshot at the same time

            Steps:
                1. Create a volume
                2. Create 70 snapshots for it. Wait for creation
                3. Delete all of them
                4. Launch creation of 50 snapshot without waiting of deletion
        """
        # 1. Create volume
        logger.info('Create volume')
        image_id = [image.id for image in self.nova.images.list() if
                    image.name == 'TestVM'][0]
        volume = common_functions.create_volume(self.cinder, image_id)
        self.volume_list.append(volume)

        # 2. Creation of 70 snapshots
        logger.info('Create 70 snapshots')
        count = 70
        initial_snapshot_lst = []
        for num in range(count):
            logger.info('Creating {} snapshot'.format(num))
            snapshot_id = self.cinder.volume_snapshots \
                .create(volume.id, name='1st_creation_{0}'.format(num))
            initial_snapshot_lst.append(snapshot_id)
            self.assertTrue(
                common_functions.check_volume_snapshot_status(self.cinder,
                                                              snapshot_id,
                                                              'available'))
        self.snapshot_list.extend(initial_snapshot_lst)

        # 3. Delete all snapshots
        logger.info('Delete all snapshots')
        for snapshot in initial_snapshot_lst:
            self.cinder.volume_snapshots.delete(snapshot)

        # 4. Launch creation of 50 snapshot without waiting of deletion
        logger.info('Launch creation of 50 snapshot without waiting '
                    'of deletion')
        new_count = 50
        new_snapshot_lst = []
        for num in range(new_count):
            logger.info('Creating {} snapshot'.format(num))
            snapshot_id = self.cinder.volume_snapshots \
                .create(volume.id, name='2nd_creation_{0}'.format(num))
            new_snapshot_lst.append(snapshot_id)
        self.snapshot_list.extend(new_snapshot_lst)

        timeout = time.time() + (new_count + count) * 10
        while [s.status for s in self.cinder.volume_snapshots.list() if
               s in new_snapshot_lst].count('available') != new_count:
            if time.time() < timeout:
                time.sleep(10)
            else:
                unavailable = [s.id for s in
                               self.cinder.volume_snapshots.list() if
                               s.status != 'available']
                raise AssertionError(
                    "All snapshots must be available. "
                    "List of unavailable snapshots:\n\t{0}".format(
                        "\n\t".join(unavailable)))
