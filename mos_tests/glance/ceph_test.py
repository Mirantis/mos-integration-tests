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

import hashlib
import json
import logging
import random
import time
import xml.etree.ElementTree as ET

import pytest

from mos_tests.functions import common

logger = logging.getLogger(__name__)


class FakeFile(object):
    """Semi-random file-like object with md5 generation"""
    chars = [chr(x) for x in range(256)]

    def __init__(self, size):
        self.size = size
        self.pos = 0
        self.md5 = hashlib.md5()

    def read(self, size=None):
        if size is None:
            size = self.size - self.pos
        else:
            size = min(self.size - self.pos, size)
        self.pos += size
        chunk = random.choice(self.chars) * size
        self.md5.update(chunk)
        return chunk

    @property
    def digest(self):
        return self.md5.hexdigest()


@pytest.fixture
def ceph_nodes_osds(env):
    controller = env.get_nodes_by_role('controller')[0]
    ceph_nodes = env.get_nodes_by_role('ceph-osd')

    with controller.ssh() as remote:
        result = remote.check_call('ceph report', verbose=False)
    ceph_data = json.loads(result.stdout_string)
    nodes_with_osd_count = {}
    for node in ceph_nodes:
        osd_ids = [x['id'] for x in ceph_data['osd_metadata'] if
                   x['hostname'] == node.data['fqdn']]
        nodes_with_osd_count[node] = len(osd_ids)
    return nodes_with_osd_count


@pytest.fixture
def replication_factor(env):
    storage_data = env.get_settings_data()['editable']['storage']
    return int(storage_data['osd_pool_size']['value'])


def get_glance_image_md5(os_conn, image):
    md5 = hashlib.md5()
    response, _ = os_conn.glance.http_client.get(image.file,
                                                 log=False,
                                                 stream=True)
    try:
        for chunk in response.iter_content(65536):
            md5.update(chunk)
    finally:
        response.close()
    return md5.hexdigest()


def get_ceph_status(remote):
    output = remote.check_call('ceph status -f json-pretty',
                               verbose=False).stdout_string
    return json.loads(output)


def is_ceph_time_sync(remote):
    health = get_ceph_status(remote)['health']
    mons = health['timechecks']['mons']
    ok = all([x['health'] == 'HEALTH_OK' for x in mons])
    if not ok:
        logger.info('ceph healt detail:\n'
                    '{0}'.format('\n'.join(health['detail'])))
    return ok


def up_down_nodes(controller):
    with controller.ssh() as remote:
        output = remote.check_call(
            'ceph status -f xml-pretty').stdout_string

    root = ET.fromstring(output)
    nodes = int(root.find('osdmap/osdmap/num_osds').text)
    up_nodes = int(root.find('osdmap/osdmap/num_up_osds').text)
    return {'up': up_nodes, 'down': nodes - up_nodes}


def ceph_nodes_down(controller, devops_nodes, osd_count):
    down_number = up_down_nodes(controller)['down']
    for devops_node in devops_nodes:
        devops_node.destroy()
    common.wait(
        lambda: up_down_nodes(
            controller)['down'] == down_number + osd_count,
        timeout_seconds=600,
        waiting_for='ceph nodes becomes down',
        sleep_seconds=30)


def ceph_nodes_up(controller, devops_nodes, osd_count):
    up_number = up_down_nodes(controller)['up']
    for devops_node in devops_nodes:
        devops_node.start()
    common.wait(
        lambda: up_down_nodes(
            controller)['up'] == up_number + osd_count,
        timeout_seconds=600,
        waiting_for='ceph nodes becomes up',
        sleep_seconds=30)


def is_replication_finished(controller):
    with controller.ssh() as remote:
        output = remote.check_call(
            'ceph status -f xml-pretty').stdout_string
    states = ET.fromstring(output).findall(
        'pgmap/pgs_by_state/pgs_by_state_element')
    if len(states) == 1 and states[0].find(
            'state_name').text == 'active+clean':
        return True
    return False


@pytest.mark.testrail_id('1295484')
@pytest.mark.check_env_('is_images_ceph_enabled')
def test_sync_type_on_ceph(devops_env, env, os_conn, controller_remote):
    """Check file on ceph after time unsync/sync

    Scenario:
        1. Generate random 6 GB file and calc md5 summ of it
        2. Upload file as "image1" to glance
        3. Disable ntp on all controllers
        4. Unsync time on all controller nodes with
            `date -u -s "new date"` command
        5. Wait until Ceph detected clock skew
        6. Upload file as "image1" to glance
        7. Enable ntp on all controllers
        8. Wait until Ceph monitors clock skew to be gone
        9. Download image "image1" from Glance and compare it with file
        10. Download image "image2" from Glance and compare it with file
    """

    size = 6 * 1024**3  # 6GB

    f1 = FakeFile(size=size)
    f2 = FakeFile(size=size)

    image1 = os_conn.glance.images.create(name='image1',
                                          disk_format='raw',
                                          container_format='bare')

    logger.info('Start uploading {0}GB file'.format(size / 1024**3))
    os_conn.glance.images.upload(image1.id, f1)

    # Change time on controllers
    controller_remote.check_call('pcs resource disable p_ntp')
    controllers = env.get_nodes_by_role('controller')
    date = None
    for node in controllers:
        with node.ssh() as remote:
            if date is None:
                date = remote.check_call('date -u').stdout_string.strip()
            remote.execute('service ntp stop')
            time.sleep(5)
            remote.check_call('date -u -s "{0}"'.format(date))

    common.wait(lambda: not is_ceph_time_sync(controller_remote),
                timeout_seconds=10 * 60,
                sleep_seconds=30,
                waiting_for='ceph monitors to detect clock skew')

    image2 = os_conn.glance.images.create(name='image1',
                                          disk_format='raw',
                                          container_format='bare')

    logger.info('Start uploading {0}GB file'.format(size / 1024**3))
    os_conn.glance.images.upload(image2.id, f2)

    # Sync time on controllers
    for node in controllers:
        with node.ssh() as remote:
            remote.check_call('ntpdate ntp.ubuntu.com')
            remote.check_call('service ntp start')

    controller_remote.check_call('pcs resource enable p_ntp')

    # Ceph clock sync time take up to 300 seconds, according documentation
    common.wait(lambda: is_ceph_time_sync(controller_remote),
                timeout_seconds=10 * 60,
                sleep_seconds=60,
                waiting_for='ceph monitors to detect clock sync')

    assert f1.digest == get_glance_image_md5(os_conn, image1)
    assert f2.digest == get_glance_image_md5(os_conn, image2)


@pytest.mark.testrail_id('1295465')
@pytest.mark.check_env_('is_images_ceph_enabled')
def test_data_replication_with_factor_2(
        env, devops_env, os_conn, ceph_nodes_osds, replication_factor):
    """This test case checks data replication with replication factor 2 if
    only 2 node with ceph-osd role is present

    Steps:
        1. Shutdown one CEPH node
        2. Generate random file in 20Gb and get md5 sum of it
        3. Upload this file as an image to Glance
        4. Enable second CEPH node (which was shut down)
        5. Wait while CEPH cluster will be in OK state and replication is
        finished
        6. Shut down another CEPH node (which was available on step #3)
        7. Download image from Glance and check MD5 sum of the image.
    """
    ceph_nodes = ceph_nodes_osds.keys()
    if replication_factor != 2:
        pytest.skip("Incorrect replication factor")
    if len(ceph_nodes) != replication_factor:
        pytest.skip("Incorrect count of node with ceph-osd role")

    controller = env.get_nodes_by_role('controller')[0]
    devops_nodes = [devops_env.get_node_by_fuel_node(node_off) for
                    node_off in ceph_nodes]

    name = "Test_ceph_2"

    logger.info("Shutdown one ceph node")
    ceph_nodes_down(controller, [devops_nodes[0]],
                    ceph_nodes_osds[ceph_nodes[0]])

    logger.info("Upload file 20Gb to glance")
    image = os_conn.glance.images.create(
        name=name, disk_format='qcow2', container_format='bare')
    image_file = FakeFile(size=20 * 1024 ** 3)
    os_conn.glance.images.upload(image.id, image_file)

    logger.info("Enable the ceph node")
    ceph_nodes_up(controller, [devops_nodes[0]],
                  ceph_nodes_osds[ceph_nodes[0]])

    # Wait for data replication
    common.wait(lambda: is_replication_finished(controller),
                timeout_seconds=1500,
                waiting_for='replication',
                sleep_seconds=60)

    logger.info("Shutdown another ceph node")
    ceph_nodes_down(controller, [devops_nodes[1]],
                    ceph_nodes_osds[ceph_nodes[1]])

    logger.info("Check MD5 sum of the image.")
    assert image_file.digest == get_glance_image_md5(os_conn, image)


@pytest.mark.testrail_id('1295466')
@pytest.mark.check_env_('is_images_ceph_enabled')
def test_data_replication_with_factor_3(
        env, devops_env, os_conn, ceph_nodes_osds, replication_factor):
    """This test case checks data replication with replication factor 3 if
    only 3 node with ceph-osd role is present

    Steps:
        1. Shutdown CEPH nodes #2 and #3
        2. Generate random file in 20Gb and get md5 sum of it
        3. Upload this file as an image to Glance
        4. Enable CEPH nodes #2 and #3
        5. Wait while CEPH cluster will be in OK state and replication is
        finished
        6. Shutdown CEPH nodes #1 and #3
        7. Download image from Glance and check MD5 sum of the image.
        8. Enable CEPH node #3 and shutdown #2
        9. Download image from Glance and check MD5 sum of the image.
        10. Delete this image in Glance and enable all CEPH nodes. Verify
        that this file will be moved from all CEPH nodes.
    """
    ceph_nodes = ceph_nodes_osds.keys()
    if replication_factor != 3:
        pytest.skip("Incorrect replication factor")
    if len(ceph_nodes) != replication_factor:
        pytest.skip("Incorrect count of node with ceph-osd role")

    controller = env.get_nodes_by_role('controller')[0]
    devops_nodes = [devops_env.get_node_by_fuel_node(node_off) for
                    node_off in ceph_nodes]
    name = "Test_ceph_3"

    logger.info("Shutdown ceph nodes 2 and 3")
    ceph_nodes_down(
        controller, [devops_nodes[1], devops_nodes[2]],
        ceph_nodes_osds[ceph_nodes[1]] + ceph_nodes_osds[ceph_nodes[2]])

    logger.info("Upload file 20Gb to glance")
    image = os_conn.glance.images.create(
        name=name, disk_format='qcow2', container_format='bare')
    image_file = FakeFile(size=20 * 1024 ** 3)
    os_conn.glance.images.upload(image.id, image_file)

    logger.info("Enable the ceph nodes 2 and 3")
    ceph_nodes_up(
        controller, [devops_nodes[1], devops_nodes[2]],
        ceph_nodes_osds[ceph_nodes[1]] + ceph_nodes_osds[ceph_nodes[2]])

    # Wait for data replication
    common.wait(lambda: is_replication_finished(controller),
                timeout_seconds=1500,
                waiting_for='replication',
                sleep_seconds=60)

    logger.info("Shutdown ceph nodes 1 and 3")
    ceph_nodes_down(
        controller, [devops_nodes[0], devops_nodes[2]],
        ceph_nodes_osds[ceph_nodes[0]] + ceph_nodes_osds[ceph_nodes[2]])

    logger.info("Check MD5 sum of the image.")
    assert image_file.digest == get_glance_image_md5(os_conn, image)

    logger.info("Enable the ceph node 3")
    ceph_nodes_up(controller, [devops_nodes[2]],
                  ceph_nodes_osds[ceph_nodes[2]])

    logger.info("Shutdown ceph nodes 2 ")
    ceph_nodes_down(controller, [devops_nodes[1]],
                    ceph_nodes_osds[ceph_nodes[1]])

    logger.info("Check MD5 sum of the image.")
    assert image_file.digest == get_glance_image_md5(os_conn, image)
