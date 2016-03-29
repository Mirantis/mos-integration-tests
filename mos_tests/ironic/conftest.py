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
import yaml

from mos_tests.environment import devops_client
from mos_tests.functions import common
from mos_tests.ironic import actions
from mos_tests import settings

logger = logging.getLogger(__name__)


def pytest_runtest_makereport(item, call):
    if "incremental" in item.keywords:
        if call.excinfo is not None:
            parent = item.parent
            parent._previousfailed = {str(item.callspec.params): item}


def pytest_runtest_setup(item):
    if "incremental" in item.keywords:
        previousfailed_info = getattr(item.parent, "_previousfailed", {})
        previousfailed = previousfailed_info.get(str(item.callspec.params))
        if previousfailed is not None:
            pytest.xfail("previous test failed ({0.name})".format(
                previousfailed))


@pytest.yield_fixture(scope='session')
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
def ironic(os_conn):
    return actions.IronicActions(os_conn)


@pytest.fixture(scope='session')
def ironic_drivers_params(server_ssh_credentials):
    base_dir = os.path.dirname(__file__)
    with open(os.path.join(base_dir, 'ironic_nodes.yaml')) as f:
        config = yaml.load(f)
    for i, node in enumerate(config):
        if node['driver'] != 'fuel_ssh':
            continue
        driver_info = node['driver_info']
        if driver_info['ssh_address'] is None:
            driver_info['ssh_address'] = server_ssh_credentials['ip']
        if driver_info['ssh_username'] is None:
            driver_info['ssh_username'] = server_ssh_credentials['username']
            driver_info['ssh_key_contents'] = server_ssh_credentials['key']
    return config


@pytest.yield_fixture
def keypair(os_conn):
    keypair = os_conn.create_key(key_name='ironic-key')
    yield keypair
    os_conn.delete_key(key_name=keypair.name)


@pytest.yield_fixture
def flavors(ironic_drivers_params, os_conn):
    flavors = []
    for i, config in enumerate(ironic_drivers_params):
        flavor = os_conn.nova.flavors.create(
            name='baremetal_{}'.format(i),
            ram=config['node_properties']['memory_mb'],
            vcpus=config['node_properties']['cpus'],
            disk=config['node_properties']['local_gb'])
        flavors.append(flavor)

    yield flavors

    for flavor in flavors:
        flavor.delete()


@pytest.yield_fixture(scope='module')
def image_file():
    image_file = common.gen_temp_file(prefix='image', suffix='.img')
    yield image_file
    image_file.unlink(image_file.name)


@pytest.yield_fixture(params=[['create', 'delete']])
def ubuntu_image(request, os_conn, image_file):
    actions = request.param
    image_name = 'ironic_trusty'

    if 'create' in actions:
        logger.info('Creating ubuntu image')
        image = os_conn.glance.images.create(
            name=image_name,
            disk_format='raw',
            container_format='bare',
            hypervisor_type='baremetal',
            visibility='public',
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
    else:
        image = os_conn.nova.images.find(name=image_name)

    yield image

    if 'delete' in actions:
        os_conn.glance.images.delete(image.id)


@pytest.yield_fixture
def ironic_nodes(request, env, ironic_drivers_params, ironic, env_name):
    devops_env = devops_client.DevopsClient.get_env(env_name=env_name)

    node_count = getattr(request, 'param', 1)
    devops_nodes = []
    nodes = []

    baremetal_interface = devops_env.get_interface_by_fuel_name('baremetal',
                                                                env)
    baremetal_net_name = baremetal_interface.network.name

    for i, config in enumerate(ironic_drivers_params[:node_count]):
        if config['driver'] == 'fuel_ssh':
            devops_node = devops_env.add_node(
                name='baremetal_{i}'.format(i=i),
                vcpu=config['node_properties']['cpus'],
                memory=config['node_properties']['memory_mb'],
                disks=[config['node_properties']['local_gb']],
                networks=[baremetal_net_name],
                role='ironic_slave')
            devops_nodes.append(devops_node)
            mac = devops_node.interface_by_network_name(baremetal_net_name)[
                0].mac_address
            config['mac_address'] = mac
        node = ironic.create_node(config['driver'], config['driver_info'],
                                  config['node_properties'],
                                  config['mac_address'])
        nodes.append(node)

    common.wait(lambda: env.is_ostf_tests_pass('sanity'),
                timeout_seconds=60 * 5,
                waiting_for='OSTF sanity tests to pass')
    yield nodes

    for node in nodes:
        ironic.delete_node(node)

    for node in devops_nodes:
        devops_env.del_node(node)
