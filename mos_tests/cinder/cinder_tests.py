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

import os
import time
import unittest

from keystoneclient.v2_0 import client as keystone_client
from novaclient import client as nova_client
from cinderclient import client as cinder_client

from mos_tests.functions import common as common_functions


class CinderIntegrationTests(unittest.TestCase):
    """ Basic automated tests for OpenStack Heat verification. """

    @classmethod
    def setUpClass(self):
        OS_AUTH_URL = os.environ.get('OS_AUTH_URL')
        OS_USERNAME = os.environ.get('OS_USERNAME')
        OS_PASSWORD = os.environ.get('OS_PASSWORD')
        OS_TENANT_NAME = os.environ.get('OS_TENANT_NAME')
        OS_PROJECT_NAME = os.environ.get('OS_PROJECT_NAME')

        self.keystone = keystone_client.Client(auth_url=OS_AUTH_URL,
                                               username=OS_USERNAME,
                                               password=OS_PASSWORD,
                                               tenat_name=OS_TENANT_NAME,
                                               project_name=OS_PROJECT_NAME)

        # Nova connect
        OS_TOKEN = self.keystone.get_token(self.keystone.session)
        RAW_TOKEN = self.keystone.get_raw_token_from_identity_service(
            auth_url=OS_AUTH_URL,
            username=OS_USERNAME,
            password=OS_PASSWORD,
            tenant_name=OS_TENANT_NAME)
        OS_TENANT_ID = RAW_TOKEN['token']['tenant']['id']

        self.nova = nova_client.Client('2',
                                       auth_url=OS_AUTH_URL,
                                       username=OS_USERNAME,
                                       auth_token=OS_TOKEN,
                                       tenant_id=OS_TENANT_ID,
                                       insecure=True)

        # Cinder endpoint
        self.cinder = cinder_client.Client('2', OS_USERNAME, OS_PASSWORD,
                                           OS_TENANT_NAME,
                                           auth_url=OS_AUTH_URL)
        self.volume_list = []
        self.snapshot_list = []

    def tearDown(self):
        for snapshot in self.snapshot_list:
            common_functions.delete_volume_snapshot(self.cinder, snapshot)
        self.snapshot_list = []
        for volume in self.volume_list:
            common_functions.delete_volume(self.cinder, volume)
        self.volume_list = []

    def test_543176_CreatingMultipleSnapshots(self):
        """ This test case checks creation of several snapshot at the same time

            Steps:
                1. Create a volume
                2. Create 70 snapshots for it. Wait for creation
                3. Delete all of them
                4. Launch creation of 50 snapshot without waiting of deletion
        """

        # Precondition: change quota limit for snapshots
        tenant_id = [t.id for t in self.keystone.tenants.list() if
                     t.name == os.environ.get('OS_TENANT_NAME')][0]
        quota = self.cinder.quotas.get(tenant_id).snapshots
        self.cinder.quotas.update(tenant_id, snapshots=200)

        # 1. Create volume
        image_id = [image.id for image in self.nova.images.list() if
                    image.name == 'TestVM'][0]
        volume = common_functions.create_volume(self.cinder, image_id, 60)
        self.volume_list.append(volume)

        # 2. Creation of 70 snapshots
        count = 70
        initial_snapshot_lst = []
        for num in xrange(count):
            snapshot_id = self.cinder.volume_snapshots \
                .create(volume.id, name='1st_creation_{0}'.format(num + 1))
            initial_snapshot_lst.append(snapshot_id)
            self.assertTrue(
                common_functions.check_volume_snapshot_status(self.cinder,
                                                              snapshot_id,
                                                              'available',
                                                              timeout=60))
        self.snapshot_list.extend(initial_snapshot_lst)

        # 3. Delete all snapshots
        for snapshot in initial_snapshot_lst:
            self.cinder.volume_snapshots.delete(snapshot)

        # 4. Launch creation of 50 snapshot without waiting of deletion
        new_count = 50
        new_snapshot_lst = []
        for num in xrange(new_count):
            snapshot_id = self.cinder.volume_snapshots \
                .create(volume.id, name='2nd_creation_{0}'.format(num + 1))
            new_snapshot_lst.append(snapshot_id)
        self.snapshot_list.extend(new_snapshot_lst)

        timeout = time.time() + (new_count + count) * 10
        while [s.status for s in self.cinder.volume_snapshots.list() if
               s in new_snapshot_lst].count('available') != new_count:
            if time.time() < timeout:
                time.sleep(10)
            else:
                raise AssertionError("At least one snapshot is not available")

        # Return defaults
        self.cinder.quotas.update(tenant_id, snapshots=quota)
