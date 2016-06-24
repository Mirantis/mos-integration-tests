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
from mos_tests.functions import file_cache
from mos_tests.settings import UBUNTU_URL

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


@pytest.fixture
def ubuntu_image(os_conn, request):
    disk_format = getattr(request, 'param', 'qcow2')
    image = os_conn.glance.images.create(
        name="image_ubuntu", url=UBUNTU_URL, disk_format=disk_format,
        container_format='bare', visibility='public')
    with file_cache.get_file(UBUNTU_URL) as f:
        os_conn.glance.images.upload(image.id, f)
    return disk_format, image.id


@pytest.fixture
def disk_format(request):
    disk_format = getattr(request, 'param', 'qcow2')
    return disk_format


@pytest.yield_fixture
def cleanup(os_conn):
    vlms_before = os_conn.cinder.volumes.list()
    images_before = os_conn.nova.images.list()
    yield None
    vlms_after = os_conn.cinder.volumes.list()
    vlms_for_del = [vol for vol in vlms_after if vol not in vlms_before]
    for vlm in vlms_for_del:
        vlm.delete()
    common.wait(lambda: len(os_conn.cinder.volumes.list()) == len(vlms_before),
                timeout_seconds=10 * 60, waiting_for='volumes cleanup')

    images_after = os_conn.nova.images.list()
    img_for_del = [img for img in images_after if img not in images_before]
    for image in img_for_del:
        os_conn.glance.images.delete(image.id)
    common.wait(lambda: len(os_conn.nova.images.list()) == len(images_before),
                timeout_seconds=10 * 60, waiting_for='images cleanup')


def check_snapshot_status(
        os_conn, snapshot, status='available', positive=True):
    snp_status = os_conn.cinder.volume_snapshots.get(snapshot.id).status
    if positive:
        assert snp_status != 'error'
    return snp_status == status


def check_all_snapshots_statuses(
        os_conn, snapshots, status='available', positive=True):
    for snapshot in snapshots:
        if not check_snapshot_status(os_conn, snapshot, status, positive):
            return False
    return True


def is_snapshot_deleted(os_conn, snapshot):
    return len(os_conn.cinder.volume_snapshots.findall(id=snapshot.id)) == 0


def check_volume_status(os_conn, volume, status='available', positive=True):
    volume_status = os_conn.cinder.volumes.get(volume.id).status
    if positive:
        assert volume_status != 'error'
    return volume_status == status


def check_all_volumes_statuses(
        os_conn, volumes, status='available', positive=True):
    for volume in volumes:
        if not check_volume_status(os_conn, volume, status, positive):
            return False
    return True


def is_volume_deleted(os_conn, volume):
    return len(os_conn.cinder.volumes.findall(id=volume.id)) == 0


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


@pytest.mark.check_env_('not is_ceph_enabled')
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
        lambda: check_all_snapshots_statuses(os_conn, snp_list_1),
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
        lambda: check_all_snapshots_statuses(os_conn, snp_list_2),
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

    common.wait(lambda: check_snapshot_status(os_conn, snapshot),
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


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ceph_enabled')
@pytest.mark.testrail_id('857365')
def test_create_delete_volumes_in_parallel(os_conn):
    """This test case checks creation and deletion of 10 volumes in parallel
    Steps:
    1. Create 10 volumes in parallel
    2. Check that all volumes are in available status
    3. Delete 10 volumes in parallel
    4. Check that all volumes are deleted from the volumes list
    """
    image = os_conn.nova.images.find(name='TestVM')
    volumes = []

    logger.info('Create 10 volumes in parallel:')
    for i in range(1, 11):
        logger.info('Create volume #{}'.format(i))
        volume = os_conn.cinder.volumes.create(1, name='volume_{}'.format(i),
                                               imageRef=image.id)
        volumes.append(volume)

    common.wait(
        lambda: check_all_volumes_statuses(os_conn, volumes),
        timeout_seconds=1200,
        waiting_for='all volumes to become in available status')

    logger.info('Delete 10 volumes in parallel')
    for i, volume in enumerate(volumes, 1):
        logger.info('Delete volume #{}'.format(i))
        volume.delete()

    common.wait(
        lambda: all([is_volume_deleted(os_conn, x) for x in volumes]),
        timeout_seconds=1200,
        waiting_for='all volumes to be deleted')


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ceph_enabled')
@pytest.mark.testrail_id('857366')
def test_create_delete_snapshots_in_parallel(os_conn, volume):
    """This test case checks creation and deletion of 10 snapshots in parallel
    Steps:
    1. Create 10 snapshots in parallel
    2. Check that all snapshots are in available status
    3. Delete 10 snapshots in parallel
    4. Check that all snapshots are deleted from the snapshots list
    """
    snapshots = []

    logger.info('Create 10 snapshots in parallel:')
    for i in range(1, 11):
        logger.info('Create snapshot #{}'.format(i))
        snapshot = os_conn.cinder.volume_snapshots.create(
            volume.id, name='snapshot_{}'.format(i))
        snapshots.append(snapshot)

    common.wait(
        lambda: check_all_snapshots_statuses(os_conn, snapshots),
        timeout_seconds=800,
        waiting_for='all snapshots to become in available status')

    logger.info('Delete 10 snapshots in parallel')
    for i, snapshot in enumerate(snapshots, 1):
        logger.info('Delete snapshot #{}'.format(i))
        os_conn.cinder.volume_snapshots.delete(snapshot)

    common.wait(
        lambda: all([is_snapshot_deleted(os_conn, x) for x in snapshots]),
        timeout_seconds=1800,
        waiting_for='all snapshots to be deleted')


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ceph_enabled')
@pytest.mark.testrail_id('857361', ubuntu_image='qcow2')
@pytest.mark.testrail_id('857362', ubuntu_image='raw')
@pytest.mark.parametrize('ubuntu_image', ['qcow2', 'raw'],
                         indirect=['ubuntu_image'])
def test_create_volume_from_image(os_conn, ubuntu_image, cleanup):
    """This test case checks creation of volume with qcow2/raw image
    Steps:
    1. Create image with corresponding disk format(qcow2 or raw)
    2. Create a volume
    3. Check that volume is created without errors
    """
    disk_format, image_id = ubuntu_image
    logger.info('Create volume from image with disk format {}'.format(
        disk_format))
    volume = common.create_volume(os_conn.cinder, image_id=image_id,
                                  name='volume_{}'.format(disk_format))
    assert volume.volume_image_metadata['disk_format'] == disk_format
    assert volume.volume_image_metadata['image_id'] == image_id


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ceph_enabled')
@pytest.mark.testrail_id('857363', disk_format='qcow2')
@pytest.mark.testrail_id('857364', disk_format='raw')
@pytest.mark.parametrize('disk_format', ['qcow2', 'raw'],
                         indirect=['disk_format'])
def test_create_image_from_volume(os_conn, disk_format, volume, cleanup):
    """This test case checks creation of qcow2/raw image from volume
    Steps:
    1. Create a volume
    2. Create image with corresponding disk format(qcow2 or raw)
    3. Check that image is created without errors
    """

    logger.info('Create image with disk format {} from volume'.format(
        disk_format))

    image_id = os_conn.cinder.volumes.upload_to_image(
        volume=volume, force=True, image_name='image_{}'.format(disk_format),
        container_format='bare', disk_format=disk_format, visibility='public',
        protected=False)[1]['os-volume_upload_image']['image_id']

    def is_image_active():
        image = [img for img in os_conn.nova.images.list() if
                 img.id == image_id][0]
        if image.status == 'ERROR':
            raise ValueError("Image is in error state")
        else:
            return image.status == 'ACTIVE'

    common.wait(is_image_active, timeout_seconds=60 * 5,
                waiting_for='image became to active status')
