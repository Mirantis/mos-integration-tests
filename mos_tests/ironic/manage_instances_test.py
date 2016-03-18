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
import tarfile

import pytest
from six.moves import urllib

from mos_tests.functions import common
from mos_tests import settings


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
    with open(image_file.name) as f:
        os_conn.glance.images.upload(image.id, f)
    src.close()

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


@pytest.yield_fixture
def instance(os_conn, ubuntu_image, flavor, keypair):
    baremetal_net = os_conn.nova.networks.find(label='baremetal')
    instance = os_conn.create_server('ironic-server', image_id=ubuntu_image.id,
                                     flavor=flavor.id, key_name=keypair.name,
                                     nics=[{'net-id': baremetal_net.id}],
                                     timeout=60 * 10)
    yield instance
    instance.delete()


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
def test_instance_terminate(env, ironic, os_conn, ironic_node, ubuntu_image,
                            flavor, keypair, env_name):
    """Check terminate instance

    Scenario:
        1. Boot Ironic instance
        2. Terminate Ironic instance
        3. Wait and check that instance not present in nova list
    """

    baremetal_net = os_conn.nova.networks.find(label='baremetal')
    instance = os_conn.create_server('ironic-server', image_id=ubuntu_image.id,
                                     flavor=flavor.id, key_name=keypair.name,
                                     nics=[{'net-id': baremetal_net.id}],
                                     timeout=60 * 10)

    instance.delete()
    common.wait(lambda: not os_conn.nova.servers.list().count(instance),
                timeout_seconds=60, waiting_for="instance is terminated")


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
def test_instance_rebuild(env, ironic, os_conn, ironic_node, ubuntu_image,
                          flavor, keypair, env_name, instance):
    """Check rebuild instance

    Scenario:
        1. Boot Ironic instance
        2. Rebuild Ironic instance (nova rebuild <server> <image>)
        3. Check that instance status became REBUILD
        4. Wait until instance returns back to ACTIVE status.
    """
    server = os_conn.rebuild_server(instance, ubuntu_image.id)
    common.wait(lambda: os_conn.nova.servers.get(server).status == 'ACTIVE',
                timeout_seconds=60 * 10, waiting_for="instance is active")
