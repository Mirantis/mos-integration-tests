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
import tarfile

from mos_tests.functions import file_cache
from mos_tests import settings

logger = logging.getLogger(__name__)


def ubuntu_image(os_conn):
    image_name = 'ironic_trusty'

    logger.info('Creating ubuntu image')
    image = os_conn.glance.images.create(
        name=image_name,
        disk_format='raw',
        container_format='bare',
        hypervisor_type='baremetal',
        visibility='public',
        cpu_arch='x86_64',
        fuel_disk_info=json.dumps(settings.IRONIC_GLANCE_DISK_INFO))

    with file_cache.get_file(settings.IRONIC_IMAGE_URL) as src:
        with tarfile.open(fileobj=src, mode='r|gz') as tar:
            img = tar.extractfile(tar.firstmember)
            os_conn.glance.images.upload(image.id, img)

    logger.info('Creating ubuntu image ... done')

    yield image

    os_conn.glance.images.delete(image.id)
