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
import pytest

from mos_tests.functions import common

logger = logging.getLogger(__name__)


@pytest.yield_fixture
def quota(os_conn):
    project_id = os_conn.session.get_project_id()
    quota = os_conn.cinder.quotas.get(project_id).snapshots
    os_conn.cinder.quotas.update(project_id, snapshots=200)
    yield {'old_quota': quota, 'new_quota': 200}
    os_conn.cinder.quotas.update(project_id, snapshots=quota)


@pytest.yield_fixture
def volume(os_conn):
    logger.info('Create volume')
    image = os_conn.nova.images.find(name='TestVM')
    volume = common.create_volume(os_conn.cinder, image.id)
    yield volume
    snp_list = os_conn.cinder.volume_snapshots.findall(volume_id=volume.id)
    for snp in snp_list:
        os_conn.cinder.volume_snapshots.delete(snp)
    common.wait(
        lambda: all([is_snapshot_deleted(os_conn, x) for x in snp_list]),
        timeout_seconds=1000,
        waiting_for='snapshots to be deleted')
    os_conn.delete_volume(volume)


def is_snapshot_available(os_conn, snapshot):
    snp_status = os_conn.cinder.volume_snapshots.get(snapshot.id).status
    assert snp_status != 'error'
    return snp_status == 'available'


def is_snapshot_deleted(os_conn, snapshot):
    snp_ids = [s.id for s in os_conn.cinder.volume_snapshots.list()]
    return snapshot.id not in snp_ids


@pytest.mark.undestructive
@pytest.mark.testrail_id('543176')
def test_creating_multiple_snapshots(os_conn, quota, volume):
    """This test case checks creation of several snapshot at the same time

        Steps:
            1. Create a volume
            2. Create 70 snapshots for it. Wait for all snapshots to become in
            available status
            3. Delete all of them
            4. Launch creation of 50 snapshot without waiting of deletion
            5. Wait for all old snapshots to be deleted
            6. Wait for all new snapshots to become in available status
    """
    #  Creation of 70 snapshots
    logger.info('Create 70 snapshots')
    snp_list_1 = []
    for num in range(70):
        logger.info('{} snapshot is creating'.format(num + 1))
        snapshot = os_conn.cinder.volume_snapshots.create(
            volume.id, name='1st_creation_{0}'.format(num))
        snp_list_1.append(snapshot)
    common.wait(
        lambda: all([is_snapshot_available(os_conn, x) for x in snp_list_1]),
        timeout_seconds=800,
        waiting_for='all snapshots to become in available status')

    #  Delete all snapshots
    logger.info('Delete all snapshots')
    for snapshot in snp_list_1:
        os_conn.cinder.volume_snapshots.delete(snapshot)

    #  Launch creation of 50 snapshot without waiting of deletion
    logger.info('Launch creation of 50 snapshot without waiting '
                'of deletion')
    snp_list_2 = []

    for num in range(50):
        logger.info('{} snapshot is creating'.format(num + 1))
        snapshot = os_conn.cinder.volume_snapshots.create(
            volume.id, name='2nd_creation_{0}'.format(num))
        snp_list_2.append(snapshot)

    common.wait(
        lambda: all([is_snapshot_deleted(os_conn, x) for x in snp_list_1]),
        timeout_seconds=1800,
        waiting_for='old snapshots to be deleted')
    common.wait(
        lambda: all([is_snapshot_available(os_conn, x) for x in snp_list_2]),
        timeout_seconds=1800,
        waiting_for='new snapshots to become in available status')
