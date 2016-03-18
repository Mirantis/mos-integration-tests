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
import os
import pytest
import shutil
import socket
import tarfile

from Crypto.PublicKey import RSA
from six.moves import urllib

from mos_tests.environment import devops_client
from mos_tests.functions import common
from mos_tests.ironic import actions
from mos_tests import settings

logger = logging.getLogger(__name__)


@pytest.yield_fixture
def server_ssh_credentials():
    # determine server ip
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 53))
    server_ip = s.getsockname()[0]
    s.close()

    # backup original authorized_keys file
    ssh_folder = os.path.expanduser('~/.ssh')
    if not os.path.exists(ssh_folder):
        os.mkdir(ssh_folder)
    authorized_keys = os.path.join(ssh_folder, 'authorized_keys')
    authorized_keys_backup = os.path.join(ssh_folder, 'authorized_keys.backup')
    if os.path.exists(authorized_keys):
        shutil.copy(authorized_keys, authorized_keys_backup)

    # make ssh key pair
    key = RSA.generate(2048)
    with open(authorized_keys, 'a+') as f:
        f.write(key.publickey().exportKey('OpenSSH'))
        f.write('\n')

    credentials = {
        'username': os.getlogin(),
        'ip': server_ip,
        'key': key.exportKey('PEM')
    }

    yield credentials

    # revert authorized_keys
    os.unlink(authorized_keys)
    if os.path.exists(authorized_keys_backup):
        shutil.move(authorized_keys_backup, authorized_keys)


@pytest.fixture
def wait_sanity_test(env):
    common.wait(lambda: env.is_ostf_tests_pass('sanity'),
                timeout_seconds=60 * 5,
                waiting_for='OSTF sanity tests to pass')


@pytest.fixture
def ironic(os_conn, wait_sanity_test):
    return actions.IronicActions(os_conn)


@pytest.yield_fixture
def baremetal_node(env_name, suffix):
    devops_env = devops_client.DevopsClient.get_env(env_name=env_name)
    node = devops_env.add_node(name='baremetal_{}'.format(suffix[:4]),
                               memory=1024,
                               networks=['baremetal'],
                               disks=[settings.IRONIC_DISK_GB],
                               role='ironic_slave')
    yield node
    devops_env.del_node(node)


@pytest.yield_fixture
def keypair(os_conn):
    keypair = os_conn.create_key(key_name='ironic-key')
    yield keypair
    os_conn.delete_key(key_name=keypair.name)


@pytest.yield_fixture
def flavor(baremetal_node, os_conn):
    flavor = os_conn.nova.flavors.create(name=baremetal_node.name,
                                         ram=baremetal_node.memory,
                                         vcpus=baremetal_node.vcpu,
                                         disk=settings.IRONIC_DISK_GB)

    yield flavor

    flavor.delete()


@pytest.yield_fixture(scope='module')
def image_file():
    image_file = common.gen_temp_file(prefix='image', suffix='.img')
    yield image_file
    image_file.unlink(image_file.name)


@pytest.yield_fixture
def ubuntu_image(os_conn, image_file):
    logger.info('Creating ubuntu image')
    image = os_conn.glance.images.create(
        name='ironic_trusty',
        disk_format='raw',
        container_format='bare',
        hypervisor_type='baremetal',
        cpu_arch='x86_64',
        fuel_disk_info=json.dumps(settings.IRONIC_GLANCE_DISK_INFO))

    if not image_file.file.closed:
        src = urllib.request.urlopen(settings.IRONIC_IMAGE_URL)
        with tarfile.open(fileobj=src, mode='r|gz') as tar:
            img = tar.extractfile(tar.firstmember)
            while True:
                data = img.read(1024)
                if not data:
                    break
                image_file.file.write(data)
            image_file.file.close()
        src.close()
    with open(image_file.name) as f:
        os_conn.glance.images.upload(image.id, f)

    logger.info('Creating ubuntu image ... done')
    yield image
    os_conn.glance.images.delete(image.id)


@pytest.yield_fixture
def ironic_node(baremetal_node, ironic, server_ssh_credentials):
    node = ironic.create_node(baremetal_node, server_ssh_credentials)
    yield node
    ironic.delete_node(node)
