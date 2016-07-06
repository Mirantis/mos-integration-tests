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

from mos_tests.functions.common import wait
from mos_tests.functions import file_cache
from mos_tests.settings import VANILLA_UBUNTU_QCOW2_URL

logger = logging.getLogger(__name__)


@pytest.yield_fixture
def vanilla_image_id(os_conn):
    logger.info('Creating vanilla image')
    image = os_conn.glance.images.create(name="image_vanilla",
                                         url=VANILLA_UBUNTU_QCOW2_URL,
                                         disk_format='qcow2',
                                         container_format='bare')
    with file_cache.get_file(VANILLA_UBUNTU_QCOW2_URL) as f:
        os_conn.glance.images.upload(image.id, f)

    logger.info('Vanilla image created')
    yield image.id
    os_conn.glance.images.delete(image.id)


@pytest.yield_fixture
def sahara_image(vanilla_image_id, sahara):
    logger.info('Register vanilla image')
    sahara.images.update_image(vanilla_image_id, user_name='ubuntu')
    sahara_image = sahara.images.update_tags(vanilla_image_id,
                                             ['vanilla', '2.7.1'])
    yield sahara_image.id
    sahara.images.unregister_image(vanilla_image_id)


@pytest.yield_fixture
def cluster(os_conn, sahara_image, keypair, sahara):
    def is_cluster_active(cluster):
        cluster = sahara.clusters.get(cluster.id)
        assert cluster.status != 'Error', 'cluster is in error state'
        return cluster.status == 'Active'

    logger.info('Creating sahara cluster based on default template')
    template = sahara.cluster_templates.find(plugin_name='vanilla')[0]
    cluster = sahara.clusters.create(name='cluster',
                                     plugin_name='vanilla',
                                     hadoop_version='2.7.1',
                                     cluster_template_id=template.id,
                                     default_image_id=sahara_image,
                                     user_keypair_id=keypair.name,
                                     net_id=os_conn.int_networks[0]['id'])
    wait(lambda: is_cluster_active(cluster), timeout_seconds=30 * 60,
         sleep_seconds=30, waiting_for='cluster changes status to Active')
    yield cluster.id
    sahara.clusters.delete(cluster.id)
    wait(lambda: len(sahara.clusters.list()) == 0, timeout_seconds=10 * 60,
         sleep_seconds=10, waiting_for='cluster remove')
