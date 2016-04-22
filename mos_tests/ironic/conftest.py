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
import os
import pytest

import yaml

from mos_tests.functions import common
from mos_tests.ironic import actions
from mos_tests.ironic import testutils

logger = logging.getLogger(__name__)


def idfn(val):
    if isinstance(val, (list, tuple)):
        return ','.join(val)


@pytest.fixture
def ironic(os_conn):
    return actions.IronicActions(os_conn)


@pytest.fixture(scope='session')
def ironic_drivers_params(devops_env):
    server_ip = str(devops_env.get_network(name='public').default_gw)
    base_dir = os.path.dirname(__file__)

    with open(os.path.join(base_dir, 'ironic_nodes.yaml')) as f:
        config = yaml.load(f)
    for i, node in enumerate(config):
        if node['driver'] != 'fuel_libvirt':
            continue
        driver_info = node['driver_info']
        if driver_info['libvirt_uri'] is None:
            driver_info['libvirt_uri'] = 'qemu+tcp://{ip}/system'.format(
                ip=server_ip)
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


ubuntu_image = pytest.yield_fixture()(testutils.ubuntu_image)


def make_ironic_node(config, devops_env, ironic, name, fuel_env):

    baremetal_interface = devops_env.get_interface_by_fuel_name('baremetal',
                                                                fuel_env)
    baremetal_net_name = baremetal_interface.network.name

    devops_node = None
    if config['driver'] == 'fuel_libvirt':
        devops_node = devops_env.add_node(
            name=name,
            vcpu=config['node_properties']['cpus'],
            memory=config['node_properties']['memory_mb'],
            disks=[config['node_properties']['local_gb']],
            networks=[baremetal_net_name],
            role='ironic_slave')
        mac = devops_node.interface_by_network_name(baremetal_net_name)[
            0].mac_address
        config['mac_address'] = mac
    node = ironic.create_node(config['driver'], config['driver_info'],
                              config['node_properties'], config['mac_address'])
    return devops_node, node


@pytest.yield_fixture(ids=idfn)
def ironic_nodes(request, env, ironic_drivers_params, ironic, devops_env):

    node_count = getattr(request, 'param', 1)
    devops_nodes = []
    nodes = []

    for i, config in enumerate(ironic_drivers_params[:node_count]):
        devops_node, node = make_ironic_node(config=config,
                                             devops_env=devops_env,
                                             ironic=ironic,
                                             name='baremetal_{i}'.format(i=i),
                                             fuel_env=env)
        nodes.append(node)
        if devops_node is not None:
            devops_nodes.append(devops_node)

    common.wait(lambda: env.is_ostf_tests_pass('sanity'),
                timeout_seconds=60 * 5,
                waiting_for='OSTF sanity tests to pass')
    yield nodes

    for node in nodes:
        ironic.delete_node(node)

    for node in devops_nodes:
        devops_env.del_node(node)
