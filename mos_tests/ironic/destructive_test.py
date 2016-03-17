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
from mos_tests.functions import os_cli
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


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631921', params={'boot_instance_before': False})
@pytest.mark.testrail_id('631922', params={'boot_instance_before': True})
@pytest.mark.parametrize('boot_instance_before', [True, False])
def test_reboot_conductor(env, ironic, os_conn, ironic_node, ubuntu_image,
                          flavor, keypair, env_name, boot_instance_before):
    """Check ironic state after restart conductor node

    Scenario:
        1. Boot Ironic instance (if `boot_instance_before`)
        2. Reboot Ironic conductor.
        3. Wait 5-10 minutes.
        4. Run network verification.
        5. Run OSTF including Ironic tests.
        6. Verify that CLI ironicclient can list nodes, ports, chassis, drivers
        7. Boot new Ironic instance (if not `boot_instance_before`).
    """

    def boot_instance():
        baremetal_net = os_conn.nova.networks.find(label='baremetal')
        return os_conn.create_server('ironic-server', image_id=ubuntu_image.id,
                                     flavor=flavor.id, key_name=keypair.name,
                                     nics=[{'net-id': baremetal_net.id}],
                                     timeout=60 * 10)

    if boot_instance_before:
        instance = boot_instance()

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

    with env.get_nodes_by_role('controller')[0].ssh() as remote:
        ironic_cli = os_cli.Ironic(remote)
        for cmd in ['node-list', 'port-list', 'chassis-list', 'driver-list']:
            ironic_cli(cmd)

    if not boot_instance_before:
        instance = boot_instance()

    assert os_conn.nova.servers.get(instance.id).status == 'ACTIVE'


@pytest.mark.check_env_('has_2_or_more_ironic_conductors')
@pytest.mark.need_devops
@pytest.mark.testrail_id('638353')
def test_reboot_all_ironic_conductors(env, env_name):
    """Check ironic state after restart all conductor nodes

    Scenario:
        1. Ensure ironic conductor service works correctly on each conductor
            node (e.g., ensure "ironic driver-list" returns correct list of
            drivers)
        2. Shutdown all ironic conductor nodes
        3. Turn on all ironic conductor nodes
        4. SSH to every conductor and ensure conductor service works fine.
    """

    controller = env.get_nodes_by_role('controller')[0]
    with controller.ssh() as remote:
        with remote.open('/root/openrc') as f:
            openrc = f.read()

    conductors = env.get_nodes_by_role('ironic')
    drivers = None
    for conductor in conductors:
        with conductor.ssh() as remote:
            with remote.open('/root/openrc', 'w') as f:
                f.write(openrc)
            drivers_data = os_cli.Ironic(remote)('driver-list').listing()
            assert len(drivers_data) > 0
            if drivers is None:
                drivers = drivers_data
            else:
                assert drivers == drivers_data

    devops_nodes = [devops_client.DevopsClient.get_node_by_mac(
                    env_name=env_name, mac=x.data['mac']) for x in conductors]

    for node in devops_nodes:
        node.destroy()

    for node in devops_nodes:
        node.start()

    common.wait(lambda: all(x.is_ssh_avaliable() for x in conductors),
                timeout_seconds=10 * 60, waiting_for='conductor nodes to boot')

    for conductor in conductors:
        with conductor.ssh() as remote:
            with remote.open('/root/openrc', 'w') as f:
                f.write(openrc)
            ironic = os_cli.Ironic(remote)
            assert ironic('driver-list').listing() == drivers


@pytest.mark.check_env_('has_2_or_more_ironic_conductors')
@pytest.mark.need_devops
@pytest.mark.testrail_id('675246')
def test_kill_conductor_service(env, os_conn, ironic_node, ubuntu_image,
                                flavor, keypair, env_name):
    """Kill ironic-conductor service with one bare-metal node

    Scenario:
        1. Launch baremetal instance
        2. Kill Ironic-conductor service for conductor node that had booted
            instance
        3. Wait some time
        4. Baremetal node must be reassigned to another Ironic-conductor
        5. Run OSTF including Ironic tests.
        6. Check that Ironic instance still ACTIVE and operable
    """

    def find_conductor_node(ironic_node_uuid, conductors):
        cmd = 'ls /var/log/remote/ironic/{0}/'.format(ironic_node_uuid)
        for conductor in conductors:
            with conductor.ssh() as remote:
                result = remote.execute(cmd)
                if result.is_ok:
                    return conductor

    baremetal_net = os_conn.nova.networks.find(label='baremetal')
    instance = os_conn.create_server('ironic-server', image_id=ubuntu_image.id,
                                     flavor=flavor.id, key_name=keypair.name,
                                     nics=[{'net-id': baremetal_net.id}],
                                     timeout=60 * 10)

    conductors = env.get_nodes_by_role('ironic')
    conductor = find_conductor_node(ironic_node.uuid, conductors)
    if conductor is None:
        raise Exception("Can't find conductor node booted istance")

    with conductor.ssh() as remote:
        remote.check_call('service ironic-conductor stop')

    conductors.remove(conductor)
    common.wait(lambda: find_conductor_node(
                    ironic_node.uuid, conductors) not in (conductor, None),
                timeout_seconds=10 * 60,
                waiting_for='node to migrate to another conductor',
                sleep_seconds=20)

    common.wait(lambda: env.is_ostf_tests_pass('sanity'),
                timeout_seconds=5 * 60,
                waiting_for='OSTF sanity tests to pass')

    assert os_conn.nova.servers.get(instance.id).status == 'ACTIVE'

    with os_conn.ssh_to_instance(env, instance, vm_keypair=keypair,
                                 username='ubuntu') as remote:
        remote.check_call('uname')
