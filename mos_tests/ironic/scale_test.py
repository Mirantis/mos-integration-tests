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

from mos_tests.environment import devops_client
from mos_tests.functions import common

logger = logging.getLogger(__name__)


def map_interfaces(devops_env, fuel_node):
    """Return pairs of fuel_node interfaces and devops interfaces"""
    pairs = []
    devops_node = devops_env.get_node_by_mac(fuel_node.data['mac'])
    for fuel_interface in fuel_node.get_attribute('interfaces'):
        for devops_interface in devops_node.interfaces:
            if fuel_interface['mac'] == devops_interface.mac_address:
                pairs.append((fuel_interface, devops_interface))
                continue
    return pairs


def is_task_ready(task):
    logger.debug('Task progress is {0.progress}'.format(task))
    if task.status == 'ready':
        return True
    elif task.status == 'running':
        return False
    else:
        raise Exception('Task is {0.status}. {0.data}'.format(task))


@pytest.yield_fixture
def cleanup_nodes(env_name):
    devops_env = devops_client.DevopsClient.get_env(env_name)
    nodes = devops_env.nodes().all
    yield
    for node in devops_env.nodes().all:
        if node not in nodes:
            devops_env.del_node(node)


def idfn(val):
    if isinstance(val, (list, tuple)):
        return ','.join(val)


@pytest.mark.testrail_id('631895', params={'roles': ['ironic']})
@pytest.mark.testrail_id('631897', params={'roles': ['ironic', 'controller']})
@pytest.mark.testrail_id('631899',
                         params={'roles': ['ironic', 'controller', 'ceph']})
@pytest.mark.check_env_('has_ironic_conductor', 'is_ceph_enabled')
@pytest.mark.parametrize(
    'roles',
    [['ironic'], ['ironic', 'controller'], ['ironic', 'controller', 'ceph']],
    ids=idfn)
def test_add_node(env, env_name, suffix, cleanup_nodes, os_conn, ubuntu_image,
                  flavors, keypair, ironic, ironic_nodes, roles):
    """Test ironic work after add new ironic-conductor node to deployed cluster

    Scenario:
        1. Create fuel-slave devops node
        2. Add node to cluster with 'ironic' role
        3. Deploy changes
        4. Run network verification
        5. Run OSTF sanity tests
        6. Boot ironic instance
    """
    devops_env = devops_client.DevopsClient.get_env(env_name)
    devops_node = devops_env.add_node(
        name='new-ironic_{}'.format(suffix[:4]),
        memory=4096,
        networks=('admin', 'private', 'public', 'storage', 'management',
                  'baremetal'),
        disks=(50, 50, 50))

    fuel_node = common.wait(lambda: env.get_node_by_devops_node(devops_node),
                            timeout_seconds=10 * 60,
                            sleep_seconds=20,
                            waiting_for='node to be discovered')

    # Rename node
    fuel_node.set({'name': 'new_ironic'})

    env.assign([fuel_node], roles)

    # Make devops network.id -> fuel networks mapping
    controller = env.get_nodes_by_role('controller')[0]
    interfaces_map = {}
    for fuel_if, devop_if in map_interfaces(devops_env, controller):
        interfaces_map[devop_if.network_id] = fuel_if['assigned_networks']

    # Assign fuel networks to corresponding interfaces
    interfaces = []
    for fuel_if, devop_if in map_interfaces(devops_env, fuel_node):
        fuel_if['assigned_networks'] = interfaces_map[devop_if.network_id]
        interfaces.append(fuel_if)

    fuel_node.upload_node_attribute('interfaces', interfaces)

    # Verify network
    result = env.wait_network_verification()
    assert result.status == 'ready'

    # Deploy changes
    task = env.deploy_changes()

    common.wait(lambda: is_task_ready(task),
                timeout_seconds=40 * 60,
                sleep_seconds=60,
                waiting_for='changes to be deployed')

    fuel_node = env.get_node_by_devops_node(devops_node)

    result = env.wait_network_verification()
    assert result.status == 'ready'

    common.wait(lambda: env.is_ostf_tests_pass('sanity'),
                timeout_seconds=5 * 60,
                waiting_for='OSTF sanity tests to pass')

    with fuel_node.ssh() as remote:
        remote.check_call('service ironic-conductor status | grep running')

    instance = ironic.boot_instance(image=ubuntu_image,
                                    flavor=flavors[0],
                                    keypair=keypair)

    assert os_conn.nova.servers.get(instance.id).status == 'ACTIVE'

    if 'ceph' in roles:
        with fuel_node.ssh() as remote:
            result = remote.check_call('ceph -s')
    stdout = result.stdout_string
    assert 'HEALTH_OK' in stdout or 'HEALTH_WARN' in stdout
