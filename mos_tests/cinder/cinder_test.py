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
    os_conn.delete_volume(volume)


def is_snapshot_available(os_conn, snapshot):
    snp_status = os_conn.cinder.volume_snapshots.get(snapshot.id).status
    assert snp_status != 'error'
    return snp_status == 'available'


def is_snapshot_deleted(os_conn, snapshot):
    snp_ids = [s.id for s in os_conn.cinder.volume_snapshots.list()]
    return snapshot.id not in snp_ids


def check_volume_status(os_conn, volume, status='available', positive=True):
    volume_status = os_conn.cinder.volumes.get(volume.id).status
    if positive:
        assert volume_status != 'error'
    return volume_status == status


def check_backup_status(os_conn, backup, status='available', positive=True):
    backup_status = os_conn.cinder.backups.get(backup.id).status
    if positive:
        assert backup_status != 'error'
    return backup_status == status


def check_all_backups_statuses(
        os_conn, backups, status='available', positive=True):
    for backup in backups:
        if not check_backup_status(os_conn, backup, status, positive):
            return False
    return True


def is_backup_deleted(os_conn, backup):
    return len(os_conn.cinder.backups.findall(id=backup.id)) == 0


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


# NOTE(rpromyshlennikov): this test is not marked as @pytest.mark.undestructive
# because it creates object storage container to store backups
@pytest.mark.testrail_id('857215')
def test_create_backup_snapshot(os_conn, volume):
    """This test case checks creation a backup of a snapshot

        Steps:
            1. Create a volume
            2. Create a snapshot of the volume and check it availability
            3. Create a backup of the snapshot and check it availability

    """
    snapshot = os_conn.cinder.volume_snapshots.create(
        volume.id, name='volume_snapshot')

    common.wait(lambda: is_snapshot_available(os_conn, snapshot),
                timeout_seconds=300,
                waiting_for='Snapshot to become in available status')

    backup = os_conn.cinder.backups.create(
        volume.id, name='volume_backup', snapshot_id=snapshot.id)

    common.wait(lambda: check_backup_status(os_conn, backup),
                timeout_seconds=300,
                waiting_for='Backup to become in available status')


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ceph_enabled')
@pytest.mark.testrail_id('857367')
def test_delete_backups_in_parallel(os_conn, volume):
    """This test case checks deletion of 10 backups in parallel
    Steps:
    1. Create 10 backups
    2. Check that all backups are in available status
    3. Delete 10 backups in parallel
    4. Check that all backups are deleted from the backups list
    """
    logger.info('Create 10 backups:')
    backups = []
    for i in range(1, 11):
        logger.info('Create backup #{}'.format(i))
        backup = os_conn.cinder.backups.create(
            volume.id, name='backup_{}'.format(i))
        backups.append(backup)
        common.wait(lambda: check_volume_status(os_conn, volume),
                    timeout_seconds=300,
                    waiting_for='volume to become in available status')

    common.wait(
        lambda: check_all_backups_statuses(os_conn, backups),
        timeout_seconds=600,
        waiting_for='all backups to become in available status')

    logger.info('Delete 10 backups in parallel')
    for i, backup in enumerate(backups, 1):
        logger.info('Delete backup #{}'.format(i))
        os_conn.cinder.backups.delete(backup)

    common.wait(
        lambda: all([is_backup_deleted(os_conn, x) for x in backups]),
        timeout_seconds=1200,
        waiting_for='all backups to be deleted')
