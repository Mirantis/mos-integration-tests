# -*- coding: utf-8 -*-
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
import random
import string

from cinderclient.exceptions import BadRequest
from cinderclient.exceptions import NotFound
from cinderclient.exceptions import OverLimit
import pytest

from mos_tests.environment.os_actions import OpenStackActions
from mos_tests.functions import common


logger = logging.getLogger(__name__)

name = "シンダー"
description = "Я люблю синдер"

normal_name = 'n_name'
normal_description = 'n_description'


@pytest.yield_fixture
def cleanup(os_conn):
    vlms_ids_before = [x.id for x in os_conn.cinder.volumes.list()]
    images_ids_before = [x.id for x in os_conn.glance.images.list()]
    vol_type_ids_before = [x.id for x in os_conn.cinder.volume_types.list()]

    yield None

    vlms_after = os_conn.cinder.volumes.list()
    vlms_for_del = [x for x in vlms_after if x.id not in vlms_ids_before]
    for transfer in os_conn.cinder.transfers.list():
        os_conn.cinder.transfers.delete(transfer.id)
    os_conn.delete_volumes(vlms_for_del)

    vol_type_ids_after = [x.id for x in os_conn.cinder.volume_types.list()]
    vol_types_for_del = set(vol_type_ids_after) - set(vol_type_ids_before)

    for vol_type_id in vol_types_for_del:
        os_conn.cinder.volume_types.delete(vol_type_id)

    images_ids_after = [x.id for x in os_conn.glance.images.list()]
    img_ids_for_del = set(images_ids_after) - set(images_ids_before)
    for image_id in img_ids_for_del:
        os_conn.glance.images.delete(image_id)
    common.wait(
        lambda: all(x.id not in img_ids_for_del
                    for x in os_conn.glance.images.list()),
        timeout_seconds=5 * 60,
        waiting_for='images cleanup')


@pytest.yield_fixture
def new_os_conn(env, openstack_client):
    """Returns OpenStackActions class (os_conn) for new tenant and new user.
    """
    new_user = {'name': 'someuser', 'password': 'somepassword'}
    new_prj_name = 'newprj'

    # create new tenant
    tenant = openstack_client.project_create(new_prj_name)
    # create user in new tenant
    user = openstack_client.user_create(project=tenant['id'], **new_user)
    # add admin role for a new tenant to a new user
    openstack_client.assign_role_to_user(
        role_name='admin', user=user['id'], project=tenant['id'])

    # login to env as a new user from a new tenant
    new_os_conn = OpenStackActions(
        controller_ip=env.get_primary_controller_ip(),
        user=new_user['name'],
        password=new_user['password'],
        tenant=tenant['name'],
        cert=env.certificate,
        env=env)

    yield new_os_conn
    # cleanUp
    openstack_client.user_delete(new_user['name'])
    openstack_client.project_delete(tenant['name'])


@pytest.yield_fixture
def quota(os_conn):
    project_id = os_conn.session.get_project_id()
    quota = os_conn.cinder.quotas.get(project_id).snapshots
    os_conn.cinder.quotas.update(project_id, snapshots=200)
    yield {'old_quota': quota, 'new_quota': 200}
    os_conn.cinder.quotas.update(project_id, snapshots=quota)


@pytest.yield_fixture
def vol_size_quota(os_conn):
    new_quota = 20
    project_id = os_conn.session.get_project_id()
    quota = os_conn.cinder.quotas.get(project_id).gigabytes
    os_conn.cinder.quotas.update(project_id, gigabytes=new_quota)
    yield new_quota
    os_conn.cinder.quotas.update(project_id, gigabytes=quota)


@pytest.yield_fixture
def volume(os_conn):
    logger.info('Create volume')
    image = os_conn.nova.images.find(name='TestVM')
    volume = common.create_volume(os_conn.cinder, image.id)
    yield volume
    os_conn.delete_volume(volume)


def image_factory(disk_format):
    @pytest.fixture
    def image(os_conn, cleanup):
        image = os_conn.glance.images.create(
            name="image_{0}".format(disk_format), disk_format=disk_format,
            container_format='bare', visibility='public')
        os_conn.glance.images.upload(image.id, 'image content')
        return image, disk_format

    return image


qcow2_image = image_factory('qcow2')
raw_image = image_factory('raw')


@pytest.fixture
def cinder_lvm_hosts(os_conn):
    hosts = [node.host + '#LVM-backend' for node in
             os_conn.cinder.services.list(binary='cinder-volume') if
             node.status == 'enabled']
    if len(hosts) < 2:
        pytest.skip("Insufficient count of cinder lvm nodes")
    return hosts


@pytest.yield_fixture
def keypair(os_conn):
    key = os_conn.create_key(key_name='cinder_key')
    yield key
    os_conn.delete_key(key_name=key.name)


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


def mount_volume(os_conn, env, vm, volume, keypair):
    os_conn.nova.volumes.create_server_volume(vm.id, volume.id)
    common.wait(
        lambda: check_volume_status(os_conn, volume, status='in-use'),
        timeout_seconds=300,
        waiting_for='volume to be attached')

    with os_conn.ssh_to_instance(
            env, vm, vm_keypair=keypair, username='ubuntu') as remote:
        dev_name = remote.check_call(
            'lsblk -rdn -o NAME | tail -n1')['stdout'][0].strip()
        mount_path = '/mnt/{}'.format(dev_name)
        remote.check_call('sudo mkfs -t ext3 /dev/{}'.format(dev_name))
        remote.check_call('sudo mkdir {}'.format(mount_path))
        remote.check_call('sudo mount /dev/{0} {1}'.format(
            dev_name, mount_path))
        return mount_path


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
@pytest.mark.testrail_id('857361', image_fixture='qcow2_image')
@pytest.mark.testrail_id('857362', image_fixture='raw_image')
@pytest.mark.parametrize('image_fixture', ['qcow2_image', 'raw_image'])
def test_create_volume_from_image(request, os_conn, image_fixture):
    """This test case checks creation of volume with qcow2/raw image

    Steps:
        1. Create image with corresponding disk format(qcow2 or raw)
        2. Create a volume
        3. Check that volume is created without errors
    """
    image, disk_format = request.getfuncargvalue(image_fixture)
    logger.info('Create volume from image with disk format {}'.format(
        disk_format))
    volume = common.create_volume(os_conn.cinder,
                                  image_id=image.id,
                                  name='volume_{}'.format(disk_format))
    assert volume.volume_image_metadata['disk_format'] == disk_format
    assert volume.volume_image_metadata['image_id'] == image.id


@pytest.mark.testrail_id('1640540')
def test_create_volume_from_snapshot(os_conn, volume, cleanup):
    """Check creating volume from snapshot

    Steps:
        1. Create volume V1
        2. Make snapshot S1 from V1
        3. Create volume V2 from S1
        4. Check ant V2 are present in list
    """

    snapshot = os_conn.cinder.volume_snapshots.create(volume.id,
                                                      name='volume_snapshot')

    common.wait(lambda: check_snapshot_status(os_conn, snapshot),
                timeout_seconds=300,
                waiting_for='Snapshot to become in available status')

    volume2 = os_conn.cinder.volumes.create(size=snapshot.size,
                                            snapshot_id=snapshot.id,
                                            name='V2')

    common.wait(lambda: check_volume_status(os_conn, volume2),
                timeout_seconds=300,
                waiting_for='Volume to become in available status')

    volume2.get()
    assert volume2 in os_conn.cinder.volumes.list()


@pytest.mark.undestructive
@pytest.mark.testrail_id('857363', disk_format='qcow2')
@pytest.mark.testrail_id('857364', disk_format='raw')
@pytest.mark.testrail_id('1663423', disk_format='vdi')
@pytest.mark.testrail_id('1663424', disk_format='vmdk')
@pytest.mark.parametrize('disk_format', ['qcow2', 'raw', 'vdi', 'vmdk'])
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
        volume=volume,
        force=True,
        image_name='image_{}'.format(disk_format),
        container_format='bare',
        disk_format=disk_format)[1]['os-volume_upload_image']['image_id']

    def is_image_active():
        image = os_conn.glance.images.get(image_id)
        if image.status == 'error':
            raise ValueError("Image is in error state")
        else:
            return image.status == 'active'

    common.wait(is_image_active,
                timeout_seconds=60 * 5,
                waiting_for='image became to active status')


@pytest.mark.undestructive
@pytest.mark.check_env_('not is_ceph_enabled')
@pytest.mark.testrail_id('857389')
def test_cinder_migrate(os_conn, volume, cinder_lvm_hosts):
    """This test case checks cinder migration for volume

    Steps:
        1. Create volume
        2. Check volume host
        3. Migrate volume
        4. Check that migration is finished without errors
        5. Check that host is changed
    """
    volume_host = getattr(volume, 'os-vol-host-attr:host')
    assert volume_host in cinder_lvm_hosts
    cinder_lvm_hosts.remove(volume_host)
    new_host = cinder_lvm_hosts[0]
    os_conn.cinder.volumes.migrate_volume(volume, new_host,
                                          force_host_copy=False,
                                          lock_volume=False)

    def is_migration_success():
        volume.get()
        assert volume.migration_status != 'error'
        return volume.migration_status == 'success'

    common.wait(is_migration_success, timeout_seconds=300,
                waiting_for='volume migration')
    new_volume_host = getattr(volume, 'os-vol-host-attr:host')
    assert new_host == new_volume_host
    assert new_volume_host in cinder_lvm_hosts


@pytest.mark.testrail_id('1295471')
def test_restart_all_cinder_services(os_conn, env, ubuntu_image_id, keypair):
    """This test case checks cinder works after restart all cinder services

    Steps:
        1. Create vm using Ubuntu image
        2. Create volume 1, attach it to vm
        3. Mount volume 1 and create file on it
        4. Restart all cinder services
        5. Create volume 2, attach it to vm
        6. Mount volume 2 and copy the file from volume 1 to volume 2
        7. Check that file is not changed
        8. Detach volume 1 and volume 2 from vm
        9. Delete vm
        10. Delete volume 1 and volume 2
    """
    internal_net = os_conn.int_networks[0]
    security_group = os_conn.create_sec_group_for_ssh()
    flavor = os_conn.nova.flavors.find(name='m1.small')

    # Boot vm from ubuntu
    logger.info('Create instance with Ubuntu image')
    vm = os_conn.create_server(name='test_vm', image_id=ubuntu_image_id,
                               flavor=flavor, key_name=keypair.name,
                               security_groups=[security_group.id],
                               nics=[{'net-id': internal_net['id']}])

    # Create 1 volume
    logger.info("Create volume 'test_volume_1' with size 10Gb")
    vlm_1 = os_conn.cinder.volumes.create(size=10, name='test_volume_1')
    common.wait(
        lambda: check_volume_status(os_conn, vlm_1),
        timeout_seconds=300,
        waiting_for='volume to become in available status')
    file_1 = mount_volume(os_conn, env, vm, vlm_1, keypair) + '/file_test'

    with os_conn.ssh_to_instance(
            env, vm, vm_keypair=keypair, username='ubuntu') as remote:
        cmd_1 = 'sudo dd if=/dev/urandom of={} bs=1M count=100'.format(file_1)
        remote.check_call(cmd_1)
        result = remote.check_call('md5sum {}'.format(file_1))['stdout'][0]
    md5_1 = result.split('  /')[0]

    # Restart cinder services on all controllers
    cinder_services_cmd = ("service --status-all 2>&1 | grep '+' | "
                           "grep cinder | awk '{ print $4 }'")
    for node in env.get_nodes_by_role('controller'):
        with node.ssh() as remote:
            output = remote.check_call(cinder_services_cmd).stdout_string
            for service in output.splitlines():
                remote.check_call('service {0} restart'.format(service))

    # Create 2 volume
    logger.info("Create volume 'test_volume_2' with size 10Gb")
    vlm_2 = os_conn.cinder.volumes.create(size=10, name='test_volume_2')
    volumes = [vlm_1, vlm_2]
    common.wait(
        lambda: check_volume_status(os_conn, vlm_2),
        timeout_seconds=300,
        waiting_for='volume to become in available status')

    file_2 = mount_volume(os_conn, env, vm, vlm_2, keypair) + '/file_test'
    with os_conn.ssh_to_instance(
            env, vm, vm_keypair=keypair, username='ubuntu') as remote:
        cmd_1 = 'sudo cp {} {}'.format(file_1, file_2)
        remote.check_call(cmd_1)
        result = remote.check_call('md5sum {}'.format(file_2))['stdout'][0]
    md5_2 = result.split('  /')[0]

    err_msg = 'File is changed'
    assert md5_1 == md5_2, err_msg

    # Detach volumes from vm
    for vlm in volumes:
        vlm.detach()
    common.wait(
        lambda: check_all_volumes_statuses(os_conn, volumes),
        timeout_seconds=300,
        waiting_for='volumes to become in available status')

    # Delete vm
    vm.delete()
    common.wait(lambda: vm.id in [i.id for i in os_conn.nova.servers.list()],
                timeout_seconds=10 * 60, waiting_for='instance cleanup')

    # Delete volumes
    for vlm in volumes:
        vlm.delete()
    common.wait(
        lambda: all([is_volume_deleted(os_conn, vlm) for vlm in volumes]),
        timeout_seconds=300,
        waiting_for='all volumes to be deleted')


@pytest.mark.testrail_id('1640534')
def test_create_volume_without_name(os_conn, cleanup):
    """This test case checks volume creation without name

    Steps:
        1. Create volume without name
        2. Check that volume is created
    """
    vol = common.create_volume(os_conn.cinder, image_id=None, name='')
    assert vol.name == ''
    assert vol in os_conn.cinder.volumes.list()


@pytest.mark.testrail_id('1640537')
def test_create_volume_with_long_name(os_conn, cleanup):
    """This test case checks volume creation with name > 255 symbols

    Steps:
        1. Create volume with too long name (more that 255 symbols)
        2. Check that volume is not created
        3. Check error message
    """
    name = ''.join(random.choice(string.ascii_lowercase + string.digits)
                   for x in range(256))
    with pytest.raises(BadRequest) as e:
        common.create_volume(os_conn.cinder, image_id=None, name=name)

    exp_msg = "Name has more than 255 characters"
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1640539', description_len=50)
@pytest.mark.testrail_id('1640538', description_len=255)
@pytest.mark.parametrize('description_len', [50, 255])
def test_create_volume_with_description(os_conn, description_len, cleanup):
    """This test case checks volume creation description

    Steps:
        1. Create volume with description
        2. Check that volume is available
        3. Check that volume description is expected one
    """
    desc = ''.join(random.choice(string.ascii_lowercase + string.digits)
                   for x in range(description_len))
    vol = common.create_volume(os_conn.cinder, image_id=None, description=desc)
    assert vol.description == desc


@pytest.mark.testrail_id('1640542', size_diff=0)
@pytest.mark.testrail_id('1663427', size_diff=1)
@pytest.mark.parametrize('size_diff', [0, 1],
                         ids=['same_size', 'more_than_first_volume'])
def test_create_volume_from_volume(os_conn, volume, size_diff, cleanup):
    """This test case checks volume creation from snapshot

    Steps:
        1. Create volume1
        2. Create volume2 from volume1
        3. Check that volume2 is created and available
    """
    vol = os_conn.cinder.volumes.create(name='Volume_from_volume',
                                        size=volume.size + size_diff,
                                        source_volid=volume.id)
    common.wait(lambda: check_volume_status(os_conn, vol),
                waiting_for='volume became in available status')
    vol.get()
    assert vol in os_conn.cinder.volumes.list()


@pytest.mark.testrail_id('1640543', empty_name=False)
@pytest.mark.testrail_id('1664199', empty_name=True)
@pytest.mark.parametrize('empty_name', [False, True],
                         ids=['new name', 'empty name'])
def test_edit_volume_name(os_conn, volume, empty_name, cleanup):
    """This test case checks ability to change volume name

    Steps:
        1. Create volume1
        2. Edit name of volume
        3. Check that name of volume changed
    """
    old_name = volume.name
    new_name = ''
    if not empty_name:
        new_name = '{}_updated'.format(old_name)

    upd = {'name': new_name}
    os_conn.cinder.volumes.update(volume, **upd)
    volume.get()
    assert volume.name == new_name


@pytest.mark.testrail_id('1640544', empty_desc=False)
@pytest.mark.testrail_id('1664200', empty_desc=True)
@pytest.mark.parametrize('empty_desc', [False, True],
                         ids=['new description', 'empty description'])
def test_edit_volume_description(os_conn, empty_desc, cleanup):
    """This test case checks ability to change volume name

    Steps:
        1. Create volume1
        2. Edit description of volume
        3. Check that description of volume changed
    """
    description = 'volume_description'
    new_description = ''
    if not empty_desc:
        new_description = '{}_updated'.format(description)

    volume = common.create_volume(os_conn.cinder, 'TestVM',
                                  description=description)
    upd = {'description': new_description}
    os_conn.cinder.volumes.update(volume, **upd)
    volume.get()
    assert volume.description == new_description


@pytest.mark.testrail_id('1640545')
def test_edit_volume_name_to_long_name(os_conn, volume, cleanup):
    """This test case checks that not possible to edit volume new if new name
    length more than 255 symbols

    Steps:
        1. Create volume1
        2. Edit name of volume in order to have more than 255 symbols
        3. Check edit operation is failed with correct reason
    """
    new_name = ''.join(random.choice(string.ascii_lowercase + string.digits)
                       for x in range(256))
    upd = {'name': '{}_updated'.format(new_name)}
    with pytest.raises(BadRequest) as e:
        os_conn.cinder.volumes.update(volume, **upd)

    exp_msg = "Name has more than 255 characters"
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1640546', bootable='false')
@pytest.mark.testrail_id('1640548', bootable='true')
@pytest.mark.parametrize('bootable', ['false', 'true'])
def test_enable_disable_bootable_checkbox(os_conn, bootable, cleanup):
    """This test case checks ability to enable/disable bootable checkbox

    Steps:
        1. Create volume
        2. Enable ot disable checkbox "Bootable"
        3. Check that value is "Yes"/"No" in section "BOOTABLE"
    """
    image = None
    if bootable == 'true':
        image = os_conn.nova.images.find(name='TestVM').id

    vol = common.create_volume(os_conn.cinder, image_id=image)
    os_conn.cinder.volumes.set_bootable(vol, bootable)

    vol.get()
    assert vol.bootable == bootable


@pytest.mark.testrail_id('1640554')
def test_volume_extend(os_conn, volume, cleanup):
    """This test case checks ability to extend volume with correct size

    Steps:
        1. Create volume with size=1
        2. Extend volume (set size=2)
        3. Check that volume is extended
    """
    new_size = volume.size + 1
    os_conn.cinder.volumes.extend(volume, new_size=new_size)
    common.wait(
        lambda: os_conn.cinder.volumes.get(volume.id).size == new_size,
        timeout_seconds=2 * 60, waiting_for='extend volume')


@pytest.mark.testrail_id('1640555', size=1)
@pytest.mark.testrail_id('1640556', size=-1)
@pytest.mark.parametrize('size', [1, -1])
def test_negative_volume_extend(os_conn, size, cleanup):
    """This test case checks error case for volume extend operation

    Steps:
        1. Create volume with size=2
        2. Extend volume - set size=1 or size=-1
        3. Check that extend is not performed
        4. Check error message
    """
    image = os_conn.nova.images.find(name='TestVM')
    vol = common.create_volume(os_conn.cinder, size=2, image_id=image.id)
    with pytest.raises(BadRequest) as e:
        os_conn.cinder.volumes.extend(vol, new_size=size)

    exp_msg = "New size for extend must be greater than current size"
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1663148')
def test_create_volume_snapshot_with_long_name(os_conn, volume, cleanup):
    """This test case checks volume snapshot creation with name > 255 symbols

    Steps:
        1. Create volume
        2. Try to create volume snapshot with too long name (> 255 symbols)
        3. Check that volume snapshot is not created
        4. Check error message
    """
    name = ''.join(random.choice(string.ascii_lowercase + string.digits)
                   for x in range(256))
    with pytest.raises(BadRequest) as e:
        os_conn.cinder.volume_snapshots.create(volume.id, name=name)

    exp_msg = "Name has more than 255 characters"
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1663150', desc_len=50)
@pytest.mark.testrail_id('1663151', desc_len=255)
@pytest.mark.parametrize('desc_len', [50, 255],
                         ids=['desc length is 50', 'desc length is 255'])
def test_create_snapshot_with_description(os_conn, volume, desc_len):
    """This test case checks volume snapshot creation with description

    Steps:
        1. Create volume
        2. Create volume snapshot with description
        3. Check that volume snapshot is available
        4. Check that volume snapshot description is expected one
    """
    desc = ''.join(random.choice(string.ascii_lowercase + string.digits)
                   for x in range(desc_len))
    snapshot = os_conn.cinder.volume_snapshots.create(volume_id=volume.id,
                                                      description=desc)
    common.wait(lambda: check_snapshot_status(os_conn, snapshot),
                timeout_seconds=60, waiting_for='snapshot in available status')
    assert snapshot.description == desc


@pytest.mark.testrail_id('1663152')
def test_create_volume_snapshot(os_conn, volume):
    """This test case checks volume snapshot creation

    Steps:
        1. Create volume
        2. Create volume snapshot
        3. Check that volume snapshot is available
    """
    snapshot = os_conn.cinder.volume_snapshots.create(volume_id=volume.id,
                                                      name='volume_snapshot')
    common.wait(lambda: check_snapshot_status(os_conn, snapshot),
                timeout_seconds=60, waiting_for='snapshot in available status')


@pytest.mark.testrail_id('1663407', container=None)
@pytest.mark.testrail_id('1664211', container='test_cont')
@pytest.mark.parametrize('container', [None, 'test_cont'],
                         ids=['without container', 'with container'])
def test_create_volume_backup(os_conn, volume, container):
    """This test case checks volume backup creation

    Steps:
        1. Create volume
        2. Create volume backup
        3. Check that volume backup is available

    Related bug (ceph only): https://bugs.launchpad.net/mos/+bug/1604755
    """
    backup = os_conn.cinder.backups.create(volume_id=volume.id,
                                           name='volume_backup',
                                           container=container)
    common.wait(lambda: check_backup_status(os_conn, backup),
                timeout_seconds=60, waiting_for='backup in available status')
    if container is not None:
        assert backup.container == container


@pytest.mark.testrail_id('1663409')
def test_create_volume_backup_with_long_name(os_conn, volume):
    """This test case checks volume backup creation

    Steps:
        1. Create volume
        2. Create volume backup with name > 255 symbols
        3. Check that volume backup is not created
        4. Check error message
    """
    name = ''.join(random.choice(string.ascii_lowercase + string.digits)
                   for x in range(256))
    with pytest.raises(BadRequest) as e:
        os_conn.cinder.backups.create(volume_id=volume.id, name=name)

    exp_msg = "Name has more than 255 characters"
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1663410', desc_len=50)
@pytest.mark.testrail_id('1663411', desc_len=255)
@pytest.mark.parametrize('desc_len', [50, 255],
                         ids=['desc length is 50', 'desc length is 255'])
def test_create_backup_with_description(os_conn, volume, desc_len):
    """This test case checks volume backup creation with description

    Steps:
        1. Create volume
        2. Create volume snapshot with description
        3. Check that volume snapshot is available
        4. Check that volume snapshot description is expected one
    """
    desc = ''.join(random.choice(string.ascii_lowercase + string.digits)
                   for x in range(desc_len))
    backup = os_conn.cinder.backups.create(volume_id=volume.id,
                                           description=desc)
    common.wait(lambda: check_backup_status(os_conn, backup),
                timeout_seconds=60, waiting_for='backup in available status')
    assert backup.description == desc


@pytest.mark.testrail_id('1663421')
def test_change_volume_type_from_empty(os_conn, volume, cleanup):
    """This test case checks ability to change volume type none -> new type

    Steps:
        1. Create volume without volume type
        2. Change volume type to any (volumes_lvm or volumes_ceph for example)
        3. Check that volume type is changed
    """
    new_type = os_conn.cinder.volume_types.list()[0].name
    volume.retype(volume_type=new_type, policy='never')
    common.wait(
        lambda: os_conn.cinder.volumes.get(volume.id).volume_type == new_type,
        timeout_seconds=60, waiting_for='new type of volume')


@pytest.mark.testrail_id('1664209')
def test_volume_transfer_accept(os_conn, new_os_conn, volume):
    """This test checks volume transfer workflow

    Steps:
        1. Create volume for project1 using user1
        2. Wait for available status
        3. Create volume transfer and remember transfer_id and auth_key
        4. Switch to for project2 as user2
        5. Accept volume transfer by id and auth_key
        6. Check that volume is available for project2
        7. Check that volume is not available anymore for 1st project
    """
    new_user = new_os_conn.session.get_user_id()
    new_prj = new_os_conn.session.get_project_id()

    transfer = os_conn.cinder.transfers.create(volume_id=volume.id,
                                               name='volume_transfer')
    common.wait(
        lambda: check_volume_status(os_conn, volume, 'awaiting-transfer'),
        timeout_seconds=300, waiting_for='volume in awaiting-transfer status')

    new_os_conn.cinder.transfers.accept(transfer.id, transfer.auth_key)
    common.wait(lambda: check_volume_status(new_os_conn, volume),
                timeout_seconds=300, waiting_for='volume in available status')

    volume = new_os_conn.cinder.volumes.get(volume.id)
    assert volume not in os_conn.cinder.volumes.list()
    assert volume in new_os_conn.cinder.volumes.list()
    assert new_user == volume.user_id, 'Wrong user after volume transfer'
    assert new_prj == getattr(volume, 'os-vol-tenant-attr:tenant_id'), (
        'Wrong project after volume transfer')


@pytest.mark.testrail_id('1664210')
def test_volume_transfer_cancel(os_conn, volume):
    """This test checks volume transfer workflow for cancel

    Steps:
        1. Create volume for project1 using user1
        2. Wait for available status
        3. Create volume transfer and remember transfer_id and auth_key
        4. Cancel volume transfer by id
        5. Check that volume is available for project1
        6. Check that transfer doesn't exist anymore
    """
    transfer = os_conn.cinder.transfers.create(volume_id=volume.id,
                                               name='volume_transfer')
    common.wait(
        lambda: check_volume_status(os_conn, volume, 'awaiting-transfer'),
        timeout_seconds=300, waiting_for='volume in awaiting-transfer status')

    os_conn.cinder.transfers.delete(transfer.id)
    common.wait(lambda: check_volume_status(os_conn, volume),
                timeout_seconds=300, waiting_for='volume in available status')
    assert transfer not in os_conn.cinder.transfers.list()


@pytest.mark.testrail_id('1664192')
def test_create_volume_with_image_name(os_conn, cleanup):
    """This test case checks ability to create volume using image name

    Steps:
        1. Create volume using image name (TestVM)
        2. Check that volume is created and it's available
        3. Check image id
    """

    vol = os_conn.cinder.volumes.create(size=1, name='Test_volume',
                                        imageRef='TestVM')
    common.wait(lambda: check_volume_status(os_conn, vol), timeout_seconds=60,
                waiting_for='volume in available state')
    used_image_id = vol.volume_image_metadata['image_id']
    assert used_image_id == os_conn.nova.images.find(name='TestVM').id


@pytest.mark.testrail_id('1664194')
def test_create_volume_with_wrong_image_name(os_conn, cleanup):
    """This test case checks ability to create volume using image name

    Steps:
        1. Create volume using wrong image name (TestVM)
        2. Check that volume is not created
        3. Check error message
    """
    wrong_name = common.gen_random_resource_name(prefix='image', reduce_by=6)
    with pytest.raises(BadRequest) as e:
        os_conn.cinder.volumes.create(size=1, name='Test_volume',
                                      imageRef=wrong_name)

    exp_msg = "Invalid image identifier or unable to access requested image"
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1664195')
def test_create_volume_with_wrong_volume_type(os_conn, cleanup):
    """This test case checks ability to create volume using image name

    Steps:
        1. Create volume using wrong volume_type
        2. Check that volume is not created
        3. Check error message
    """
    wrong_type = common.gen_random_resource_name(prefix='type', reduce_by=6)
    with pytest.raises(NotFound) as e:
        os_conn.cinder.volumes.create(size=1, name='Test_volume',
                                      volume_type=wrong_type)

    exp_msg = "Volume type with name {0} could not be found".format(wrong_type)
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1664191')
def test_create_volume_with_incorrect_image_id(os_conn, cleanup):
    """This test case checks error in case of wrong image id during volume
    creation

    Steps:
        1. Try to create volume with wrong image id
        2. Check that volume is not created
        3. Check error message
    """
    with pytest.raises(BadRequest) as e:
        os_conn.cinder.volumes.create(size=1, name='Test_volume',
                                      imageRef='77777777777777777')

    exp_msg = "Invalid image identifier or unable to access requested image"
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1664196')
def test_volume_delete_with_wrong_id(os_conn, volume):
    """This test case checks error in case of wrong volume id during deletion

    Steps:
        1. Create volume
        2. Try to create volume using wring id
        3. Check that volume is not removed
        4. Check error message
    """
    wrong_volume_id = common.gen_random_resource_name()
    with pytest.raises(NotFound) as e:
        os_conn.cinder.volumes.delete(wrong_volume_id)

    exp_msg = "Volume {0} could not be found".format(wrong_volume_id)
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))

    assert check_volume_status(os_conn, volume)


@pytest.mark.testrail_id('1664197')
def test_volume_delete_cascade(os_conn, cleanup):
    """This test case checks cascade deletion of volume

    Steps:
        1. Create volume
        2. Create snapshot along with this volume
        3. Delete volume with cascade option
        4. Check that volume and snapshot are deleted
    """
    volume = common.create_volume(os_conn.cinder, image_id='TestVM')
    snapshot = os_conn.cinder.volume_snapshots.create(volume.id)
    common.wait(lambda: check_snapshot_status(os_conn, snapshot),
                timeout_seconds=60, waiting_for='snapshot in available status')

    os_conn.cinder.volumes.delete(volume, cascade=True)
    os_conn.wait_volumes_deleted([volume])
    assert snapshot not in os_conn.cinder.volume_snapshots.list()


@pytest.mark.testrail_id('1664198')
def test_volume_delete_without_cascade(os_conn, cleanup):
    """This test case checks not cascade deletion of volume

    Steps:
        1. Create volume
        2. Create snapshot along with this volume
        3. Delete volume without cascade option
        4. Check that error occurs
    """
    volume = common.create_volume(os_conn.cinder, image_id='TestVM')
    snapshot = os_conn.cinder.volume_snapshots.create(volume.id)
    common.wait(lambda: check_snapshot_status(os_conn, snapshot),
                timeout_seconds=60, waiting_for='snapshot in available status')

    with pytest.raises(BadRequest) as e:
        os_conn.cinder.volumes.delete(volume)

    exp_msg = ("must not be migrating, attached, belong to a consistency group"
               " or have snapshots")
    assert exp_msg in str(e.value), (
        "Unexpected reason of error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1664205')
def test_volume_extend_more_than_limit(os_conn, volume):
    """This test case checks error case for extend action

    Steps:
        1. Create volume
        2. Try to extend volume - new size more than limit
        3. Check that volume is not extended
        4. Check error message
    """
    size = os_conn.cinder.quotas.defaults(os_conn.tenant).gigabytes + 1
    with pytest.raises(OverLimit) as e:
        os_conn.cinder.volumes.extend(volume, new_size=size)

    exp_msg = "Requested volume or snapshot exceeds allowed gigabytes quota"
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1664206')
def test_create_volume_transfer_with_long_name(os_conn, volume):
    """This test case checks volume transfer creation with too long name

    Steps:
        1. Create volume
        2. Create volume transfer with name > 255 symbols
        3. Check that volume transfer is not created
        4. Check error message
    """
    name = ''.join(random.choice(string.ascii_lowercase + string.digits)
                   for x in range(256))

    with pytest.raises(BadRequest) as e:
        os_conn.cinder.transfers.create(volume_id=volume.id, name=name)

    exp_msg = "Transfer name has more than 255 characters."
    assert exp_msg in str(e.value), (
        "Unexpected reason of error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1664201')
def test_create_volume_with_size_more_than_limit(os_conn, cleanup):
    """This test case checks error case for volume with size > volume limit

    Steps:
        1. Create volume with size > volume limit
        2. Check that creation is failed
        3. Check error message
    """
    size = os_conn.cinder.quotas.defaults(os_conn.tenant).gigabytes + 1
    image = os_conn.nova.images.find(name='TestVM')

    with pytest.raises(OverLimit) as e:
        common.create_volume(os_conn.cinder, size=size, image_id=image.id)

    exp_msg = "Requested volume or snapshot exceeds allowed gigabytes quota"
    assert exp_msg in str(e.value), (
        "Unexpected reason of volume error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1664203', size=0)
@pytest.mark.testrail_id('1664204', size=-1)
@pytest.mark.parametrize('size, errors', [
    (0, ['must be an integer and greater than 0']),
    (-1, ['size argument must be an integer', 'greater than zero'])],
    ids=['size is 0', 'size is -1'])
def test_create_volume_with_different_size(os_conn, size, errors, cleanup):
    """This test case checks error cases for zero or negative volume size

    Steps:
        1. Try to create volume with size 0 or -1
        2. Check that creation is failed
        3. Check error message
    """
    image = os_conn.nova.images.find(name='TestVM')
    with pytest.raises(BadRequest) as e:
        common.create_volume(os_conn.cinder, size=size, image_id=image.id)

    for err in errors:
        assert err in str(e.value), (
            "{0} should be in {1}".format(err, str(e.value)))


@pytest.mark.testrail_id('1664202')
def test_create_volume_with_max_limit_size(os_conn, vol_size_quota, cleanup):
    """This test case checks ability to create volume with max size

    Steps:
        1. Try to create volume with size more than limit
        2. Check that volume is available
    """
    image = os_conn.nova.images.find(name='TestVM')
    vol = common.create_volume(os_conn.cinder, image.id, size=vol_size_quota)
    assert vol.size == vol_size_quota


@pytest.mark.skip(reason='https://bugs.launchpad.net/mos/+bug/1606474')
@pytest.mark.testrail_id('1664212')
def test_create_backup_with_container_with_long_name(os_conn, volume, cleanup):
    """This test case checks error message in case of too long name of
    container during backup creation

    Steps:
        1. Create volume
        2. Create volume backup with container name - name length > 255 symbols
        3. Check that backup is not created
        4. Check error message

    Bug: https://bugs.launchpad.net/mos/+bug/1606474
    """
    container = ''.join(random.choice(string.ascii_lowercase + string.digits)
                        for x in range(256))

    with pytest.raises(BadRequest) as e:
        os_conn.cinder.backups.create(volume_id=volume.id,
                                      name="volume_backup_with_container",
                                      container=container)

    exp_msg = "has more than 255 characters"
    assert exp_msg in str(e.value), (
        "Unexpected reason of error:\n got {0} instead of {1}".format(
            str(e.value), exp_msg))


@pytest.mark.testrail_id('1664213')
def test_change_volume_type(os_conn, cleanup):
    """This test case checks ability to change volume to newly created type

    Steps:
        1. Create volume with any type
        2. Create new volume type
        3. Change volume type
        4. Check that new type is applied
    """
    vol_type = os_conn.cinder.volume_types.list()[0].name
    vol = common.create_volume(os_conn.cinder, 'TestVM', volume_type=vol_type)

    new_vol_type = os_conn.cinder.volume_types.create('custom_type').name
    vol.retype(volume_type=new_vol_type, policy='never')

    common.wait(
        lambda: os_conn.cinder.volumes.get(vol.id).volume_type == new_vol_type,
        timeout_seconds=60, waiting_for='new type of volume')


@pytest.mark.skip(reason='https://bugs.launchpad.net/mos/+bug/1604255')
@pytest.mark.testrail_id('1664240', v_desc=description)
@pytest.mark.testrail_id('1664239', v_name=name)
@pytest.mark.parametrize('v_name, v_desc', [(normal_name, description),
                                            (name, normal_description)],
                         ids=['description', 'name'])
def test_create_volume_non_unicode(os_conn, cleanup, v_name, v_desc):
    """This test case checks ability to use non unicode chars

    Steps:
        1. Create volume with name/description with non unicode chars
    """
    volume = common.create_volume(os_conn.cinder, image_id=None,
                                  name=v_name, description=v_desc)
    assert volume.name == v_name.decode('utf-8')
    assert volume.description == v_desc.decode('utf-8')


@pytest.mark.testrail_id('1664243', s_name=name)
@pytest.mark.testrail_id('1664244', s_desc=description)
@pytest.mark.parametrize('s_name, s_desc', [(normal_name, description),
                                            (name, normal_description)],
                         ids=['description', 'name'])
def test_create_snapshot_non_unicode(os_conn, volume, s_name, s_desc):
    """This test case checks ability to use non unicode chars

    Steps:
        1. Create volume
        2. Create snapshot with name/description with non unicode chars
    """
    snapshot = os_conn.cinder.volume_snapshots.create(volume.id, name=s_name,
                                                      description=s_desc)
    common.wait(lambda: check_snapshot_status(os_conn, snapshot),
                timeout_seconds=60, waiting_for='available snapshot')
    assert snapshot.name == s_name.decode('utf-8')
    assert snapshot.description == s_desc.decode('utf-8')


@pytest.mark.testrail_id('1664247')
def test_create_backup_with_non_unicode_container(os_conn, volume):
    """This test case checks ability to use non unicode chars

    Steps:
        1. Create volume
        2. Create volume backup with container name with non unicode chars
    """
    backup = os_conn.cinder.backups.create(volume.id, container=name)
    common.wait(lambda: check_backup_status(os_conn, backup),
                timeout_seconds=60, waiting_for='available backup')
    assert backup.container == name.decode('utf-8')


@pytest.mark.testrail_id('1664248')
def test_create_transfer_non_unicode_name(os_conn, volume, cleanup):
    """This test case checks ability to use non unicode chars

    Steps:
        1. Create volume
        2. Create volume transfer with name with non unicode chars
    """
    transfer = os_conn.cinder.transfers.create(volume.id, name=name)
    common.wait(
        lambda: check_volume_status(os_conn, volume, 'awaiting-transfer'),
        timeout_seconds=60, waiting_for='vol in awaiting-transfer state')
    assert transfer.name == name.decode('utf-8')


@pytest.mark.testrail_id('1664245', b_name=name)
@pytest.mark.testrail_id('1664246', b_desc=description)
@pytest.mark.parametrize('b_name, b_desc', [(normal_name, description),
                                            (name, normal_description)],
                         ids=['description', 'name'])
def test_create_backup_non_unicode(os_conn, volume, b_name, b_desc):
    """This test case checks ability to use non unicode chars

    Steps:
        1. Create volume
        2. Create backup with name/description with non unicode chars
    """
    backup = os_conn.cinder.backups.create(volume.id, name=b_name,
                                           description=b_desc)
    common.wait(lambda: check_backup_status(os_conn, backup),
                timeout_seconds=60, waiting_for='available backup')
    assert backup.name == b_name.decode('utf-8')
    assert backup.description == b_desc.decode('utf-8')


@pytest.mark.testrail_id('1664242', v_desc=description)
@pytest.mark.testrail_id('1664241', v_name=name)
@pytest.mark.parametrize('v_name, v_desc', [(normal_name, description),
                                            (name, normal_description)],
                         ids=['description', 'name'])
def test_edit_volume_to_non_unicode(os_conn, volume, v_name, v_desc):
    """This test case checks ability to use non unicode chars

    Steps:
        1. Create volume
        2. Edit name/description to non unicode chars
    """
    upd = {'name': v_name, 'description': v_desc}
    os_conn.cinder.volumes.update(volume, **upd)
    volume.get()
    assert volume.name == v_name.decode('utf-8')
    assert volume.description == v_desc.decode('utf-8')
