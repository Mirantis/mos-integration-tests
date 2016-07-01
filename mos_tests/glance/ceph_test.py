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
