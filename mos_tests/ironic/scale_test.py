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

import pytest

from mos_tests import conftest
from mos_tests.environment import devops_client
from mos_tests.functions import common
from mos_tests.ironic import testutils

logger = logging.getLogger(__name__)

ubuntu_image = pytest.yield_fixture(scope='class')(testutils.ubuntu_image)


def map_interfaces(devops_env, fuel_node):
    """Return pairs of fuel_node interfaces and devops interfaces"""
    pairs = []
    devops_node = devops_env.get_node_by_fuel_node(fuel_node)
    for fuel_interface in fuel_node.get_attribute('interfaces'):
        for devops_interface in devops_node.interfaces:
            if fuel_interface['mac'] == devops_interface.mac_address:
                pairs.append((fuel_interface, devops_interface))
                continue
    return pairs


def remove_ceph_from_node(remote):
    def is_pg_clean():
        result = remote.check_call('ceph pg stat -f json-pretty',
                                   verbose=False)
        pg_stat = json.loads(result.stdout_string)
        states = pg_stat['num_pg_by_state']
        return len(states) == 1 and states[0]['name'] == 'active+clean'

    hostname = remote.check_call('hostname -f', verbose=False).stdout_string
    result = remote.check_call('ceph report', verbose=False)
    ceph_data = json.loads(result.stdout_string)
    osd_ids = [x['id'] for x in ceph_data['osd_metadata']
               if x['hostname'] == hostname]
    for osd_id in osd_ids:
        remote.check_call('ceph osd out {0}'.format(osd_id), verbose=False)
    common.wait(is_pg_clean,
                timeout_seconds=5 * 60,
                sleep_seconds=15,
                waiting_for='Ceph data migration to be done')
    for osd_id in osd_ids:
        remote.check_call("stop ceph-osd id={}".format(osd_id),
                          verbose=False)
        remote.check_call("ceph osd crush remove osd.{}".format(osd_id),
                          verbose=False)
        remote.check_call("ceph auth del osd.{}".format(osd_id),
                          verbose=False)
        remote.check_call("ceph osd rm osd.{}".format(osd_id),
                          verbose=False)

    remote.check_call("ceph osd crush remove {}".format(hostname),
                      verbose=False)


@pytest.yield_fixture(scope='class')
def cleanup_nodes(devops_env):
    nodes = devops_env.nodes().all
    yield
    for node in devops_env.nodes().all:
        if node not in nodes:
            devops_env.del_node(node)


def idfn(val):
    if isinstance(val, (list, tuple)):
        return ','.join(val)


@pytest.mark.undestructive
@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.incremental
@pytest.mark.usefixtures('cleanup_nodes')
class TestScale(object):

    node_name = 'new_ironic'

    @pytest.fixture(scope='class',
                    params=[['ironic'], ['ironic', 'controller'],
                            ['ironic', 'controller', 'ceph-osd']],
                    ids=idfn)
    def roles(self, request):
        return request.param

    @pytest.mark.testrail_id('631895', roles=['ironic'])
    @pytest.mark.testrail_id('631897', roles=['ironic', 'controller'])
    @pytest.mark.testrail_id('631899',
                             roles=['ironic', 'controller', 'ceph-osd'])
    def test_add_node(self, env, env_name, suffix, os_conn, ubuntu_image,
                      flavors, keypair, ironic, ironic_nodes, roles):
        """Test ironic work after add new ironic-conductor node to cluster

        Scenario:
            1. Create fuel-slave devops node
            2. Add node to cluster with 'ironic' role
            3. Deploy changes
            4. Run network verification
            5. Run OSTF sanity tests
            6. Boot ironic instance
        BUG: https://bugs.launchpad.net/fuel/+bug/1578724
        """
        if 'ceph-osd' in roles and not conftest.is_ceph_enabled(env):
            pytest.skip('This test requires CEPH')

        devops_env = devops_client.DevopsClient.get_env(env_name)
        devops_node = devops_env.add_node(
            name='new-ironic_{}'.format(suffix[:4]),
            memory=4096,
            disks=(50, 50, 50))

        fuel_node = common.wait(
            lambda: env.get_node_by_devops_node(devops_node),
            timeout_seconds=10 * 60,
            sleep_seconds=20,
            waiting_for='node to be discovered')

        # Rename node
        fuel_node.set({'name': self.node_name})

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

        common.wait(lambda: common.is_task_ready(task),
                    timeout_seconds=120 * 60,
                    sleep_seconds=60,
                    waiting_for='changes to be deployed')

        fuel_node = env.get_node_by_devops_node(devops_node)

        result = env.wait_network_verification()
        assert result.status == 'ready'

        env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)

        with fuel_node.ssh() as remote:
            remote.check_call('service ironic-conductor status | grep running')

        instance = ironic.boot_instance(image=ubuntu_image,
                                        flavor=flavors[0],
                                        keypair=keypair)

        assert os_conn.nova.servers.get(instance.id).status == 'ACTIVE'

        if 'ceph-osd' in roles:
            with fuel_node.ssh() as remote:
                result = remote.check_call('ceph -s')
            stdout = result.stdout_string
            assert 'HEALTH_OK' in stdout or 'HEALTH_WARN' in stdout

    @pytest.mark.testrail_id('631896', roles=['ironic'])
    @pytest.mark.testrail_id('631898', roles=['ironic', 'controller'])
    @pytest.mark.testrail_id('631900',
                             roles=['ironic', 'controller', 'ceph-osd'])
    def test_delete_node(self, env, roles, ironic, ubuntu_image, flavors,
                         keypair, os_conn, ironic_nodes):
        """Delete one of multiple ironic nodes.

        Scenario:
            1. Remove created ironic node from cluster
            2. Boot new ironic instance
            3. Check ironic instance status is ACTIVE
        """
        fuel_node = [x for x in env.get_all_nodes()
                     if x.data['name'] == self.node_name][0]
        if 'ceph-osd' in roles:
            with fuel_node.ssh() as remote:
                remove_ceph_from_node(remote)

        env.unassign([fuel_node.id])

        # Deploy changes
        task = env.deploy_changes()

        common.wait(lambda: common.is_task_ready(task),
                    timeout_seconds=60 * 60,
                    sleep_seconds=60,
                    waiting_for='changes to be deployed')

        instance = ironic.boot_instance(image=ubuntu_image,
                                        flavor=flavors[0],
                                        keypair=keypair)

        assert os_conn.nova.servers.get(instance.id).status == 'ACTIVE'
