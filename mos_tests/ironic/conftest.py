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
import os
import pytest
import shutil
from six.moves import urllib
import socket
import tarfile

from Crypto.PublicKey import RSA
from ironicclient import client
from six.moves import urllib

from mos_tests.environment import devops_client
from mos_tests.functions import common
from mos_tests import settings


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
    token = os_conn.keystone.auth_token
    ironic_endpoint = os_conn.keystone.service_catalog.url_for(
        service_type='baremetal', endpoint_type='publicURL')
    return client.get_client(api_version=1, os_auth_token=token,
                             ironic_url=ironic_endpoint)


@pytest.yield_fixture
def baremetal_node(env_name, suffix):
    devops_env = devops_client.DevopsClient.get_env(env_name=env_name)
    node = devops_env.add_node(
        memory=1024, name='baremetal_{}'.format(suffix[:4]))
    disk = node.attach_disk('system', settings.IRONIC_DISK_GB * (1024 ** 3))
    disk.volume.define()
    node.attach_to_networks(['baremetal'])
    node.define()
    node.start()
    yield node
    node.destroy()
    node.erase()
    disk.volume.erase()
    disk.delete()


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
    image_file = common.gen_temp_file(prefix='image', suffix='img')
    yield image_file
    image_file.unlink(image_file.name)


@pytest.yield_fixture
def ubuntu_image(os_conn, image_file):
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

    yield image
    os_conn.glance.images.delete(image.id)


@pytest.yield_fixture
def ironic_node(baremetal_node, os_conn, ironic, server_ssh_credentials):

    def get_image(name):
        return os_conn.nova.images.find(name=name)

    driver_info = {
        'ssh_address': server_ssh_credentials['ip'],
        'ssh_username': server_ssh_credentials['username'],
        'ssh_key_contents': server_ssh_credentials['key'],
        'ssh_virt_type': 'virsh',
        'deploy_kernel': get_image('ironic-deploy-linux').id,
        'deploy_ramdisk': get_image('ironic-deploy-initramfs').id,
        'deploy_squashfs': get_image('ironic-deploy-squashfs').id,
    }
    properties = {
        'cpus': baremetal_node.vcpu,
        'memory_mb': baremetal_node.memory,
        'local_gb': settings.IRONIC_DISK_GB,
        'cpu_arch': 'x86_64',
    }
    node = ironic.node.create(driver='fuel_ssh', driver_info=driver_info,
                              properties=properties)
    mac = baremetal_node.interface_by_network_name('baremetal')[0].mac_address
    port = ironic.port.create(node_uuid=node.uuid, address=mac)
    yield node
    instance_uuid = ironic.node.get(node.uuid).instance_uuid
    if instance_uuid:
        os_conn.nova.servers.delete(instance_uuid)
        common.wait(lambda: len(os_conn.nova.servers.findall(
                        id=instance_uuid)) == 0,
                    timeout_seconds=60, waiting_for='instance to be deleted')
    ironic.port.delete(port.uuid)
    ironic.node.delete(node.uuid)
