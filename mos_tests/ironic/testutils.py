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

import json
import logging

from mos_tests.functions import file_cache
from mos_tests import settings

logger = logging.getLogger(__name__)


def make_image(os_conn):
    images = []

    def get_or_create_image(node_driver='fuel_libvirt'):
        if node_driver == 'fuel_ipmitool':
            image_name = 'ironic_ubuntu_baremetal'
            disk_info = settings.IRONIC_GLANCE_DISK_INFO_BAREMETAL
        else:
            image_name = 'ironic_ubuntu_virtual'
            disk_info = settings.IRONIC_GLANCE_DISK_INFO_VIRTUAL

        try:
            image = next(x for x in os_conn.glance.images.list()
                         if x['name'] == image_name)
        except StopIteration:
            logger.info('Creating %s image', image_name)
            image = os_conn.glance.images.create(
                name=image_name,
                disk_format='raw',
                container_format='bare',
                hypervisor_type='baremetal',
                visibility='public',
                cpu_arch='x86_64',
                fuel_disk_info=json.dumps(disk_info))

            images.append(image)

            with file_cache.get_and_unpack(settings.IRONIC_IMAGE_URL) as img:
                os_conn.glance.images.upload(image.id, img)

            logger.info('Creating %s image ... done', image_name)

        return image

    yield get_or_create_image

    for image in images:
        os_conn.glance.images.delete(image.id)
