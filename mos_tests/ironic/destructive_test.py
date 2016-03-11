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
import shutil
import socket
import tarfile
import time

from Crypto.PublicKey import RSA
from ironicclient import client
import pytest
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


@pytest.yield_fixture
def keypair(os_conn):
    keypair = os_conn.create_key(key_name='ironic-key')
    yield keypair
    os_conn.delete_key(key_name=keypair.name)


@pytest.fixture
def ironic(os_conn):
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
def flavor(baremetal_node, os_conn):
    flavor = os_conn.nova.flavors.create(name=baremetal_node.name,
                                         ram=baremetal_node.memory,
                                         vcpus=baremetal_node.vcpu,
                                         disk=settings.IRONIC_DISK_GB)

    yield flavor

    flavor.delete()


@pytest.yield_fixture
def ubuntu_image(os_conn):
    image = os_conn.glance.images.create(
        name='ironic_trusty',
        disk_format='raw',
        container_format='bare',
        hypervisor_type='baremetal',
        cpu_arch='x86_64',
        fuel_disk_info=json.dumps(settings.IRONIC_GLANCE_DISK_INFO))

    src = urllib.request.urlopen(settings.IRONIC_IMAGE_URL)
    with tarfile.open(fileobj=src, mode='r|gz') as tar:
        img = tar.extractfile(tar.firstmember)
        os_conn.glance.images.upload(image.id, img)
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
    ironic.port.delete(port.uuid)
    ironic.node.delete(node.uuid)


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
def test_reboot_conductor(env, ironic, os_conn, ironic_node, ubuntu_image,
                          flavor, keypair, env_name):
    """Check ironic state after restart conductor node

    Scenario:
        1. Reboot Ironic conductor.
        2. Wait 5-10 minutes.
        3. Run network verification.
        4. Run OSTF including Ironic tests.
        5. Verify that CLI ironicclient can list nodes, ports, chassis, drivers
        6. Boot new Ironic instance.
    """
    conductor = env.get_nodes_by_role('ironic')[0]

    devops_node = devops_client.DevopsClient.get_node_by_mac(
        env_name=env_name, mac=conductor.data['mac'])
    devops_node.reset()

    time.sleep(10)

    common.wait(conductor.is_ssh_avaliable, timeout_seconds=60 * 5,
                sleep_seconds=20,
                waiting_for='ironic conductor node to reboot')

    def is_ironic_available():
        try:
            ironic.driver.list()
            return True
        except Exception:
            return False

    common.wait(is_ironic_available, timeout_seconds=60 * 5,
                sleep_seconds=20,
                waiting_for='ironic conductor service to start')

    result = env.wait_network_verification()
    assert result.status == 'ready'

    common.wait(lambda: env.is_ostf_tests_pass('sanity'),
                timeout_seconds=60 * 5,
                waiting_for='OSTF sanity tests to pass')

    baremetal_net = os_conn.nova.networks.find(label='baremetal')
    instance = os_conn.create_server('ironic-server', image_id=ubuntu_image.id,
                                     flavor=flavor.id, key_name=keypair.name,
                                     nics=[{'net-id': baremetal_net.id}],
                                     timeout=60 * 10)
    instance.delete()

    common.wait(lambda: len(os_conn.nova.servers.findall(id=instance.id)) == 0,
                timeout_seconds=60, waiting_for='instance to be deleted')
