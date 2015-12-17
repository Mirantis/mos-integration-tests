#    Copyright 2015 Mirantis, Inc.
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
from distutils.spawn import find_executable
from waiting import wait

from mos_tests.environment.devops_client import DevopsClient
from mos_tests.environment.fuel_client import FuelClient
from mos_tests.environment.os_actions import OpenStackActions
from mos_tests.settings import SERVER_ADDRESS
from mos_tests.settings import KEYSTONE_USER
from mos_tests.settings import KEYSTONE_PASS
from mos_tests.settings import SSH_CREDENTIALS

logger = logging.getLogger(__name__)


def pytest_runtest_makereport(item, call):
    if call.excinfo is not None and call.excinfo.typename == 'Skipped':
        setattr(item, 'env_destroyed', False)


def pytest_runtest_teardown(item, nextitem):
    if getattr(item, 'destroyed', True) and nextitem is not None:
        setattr(nextitem, 'do_revert', True)


@pytest.fixture
def env_name(request):
    return request.config.getoption("--env")


@pytest.fixture
def snapshot_name(request):
    return request.config.getoption("--snapshot")


@pytest.fixture
def revert_snapshot(request, env_name, snapshot_name):
    """Revert Fuel devops snapshot before test"""
    if getattr(request.node, 'do_revert', True):
        DevopsClient.revert_snapshot(env_name=env_name,
                                     snapshot_name=snapshot_name)


@pytest.fixture
def fuel_master_ip(request, env_name, snapshot_name):
    """Get fuel master ip"""
    fuel_ip = request.config.getoption("--fuel-ip")
    if not fuel_ip:
        fuel_ip = DevopsClient.get_admin_node_ip(env_name=env_name)
        revert_snapshot(request, env_name, snapshot_name)
        setattr(request.node, 'do_revert', False)
    if not fuel_ip:
        fuel_ip = SERVER_ADDRESS
    return fuel_ip


@pytest.fixture
def fuel(fuel_master_ip):
    """Initialized fuel client"""
    return FuelClient(ip=fuel_master_ip,
                      login=KEYSTONE_USER,
                      password=KEYSTONE_PASS,
                      ssh_login=SSH_CREDENTIALS['login'],
                      ssh_password=SSH_CREDENTIALS['password'])


@pytest.fixture
def env(fuel):
    """Environment instance"""
    return fuel.get_last_created_cluster()


@pytest.fixture
def os_conn(env):
    """Openstack common actions"""
    os_conn = OpenStackActions(
        controller_ip=env.get_primary_controller_ip(),
        cert=env.certificate)

    def nova_ready():
        hosts = os_conn.nova.availability_zones.find(zoneName="nova").hosts
        return all(x['available'] for y in hosts.values()
                   for x in y.values() if x['active'])

    wait(nova_ready,
         timeout_seconds=60 * 5,
         expected_exceptions=Exception,
         waiting_for="OpenStack nova computes is ready")
    return os_conn


@pytest.yield_fixture
def clear_l3_ban(env, os_conn):
    """Clear all l3-agent bans after test"""
    yield
    controllers = env.get_nodes_by_role('controller')
    ip = controllers[0].data['ip']
    with env.get_ssh_to_node(ip) as remote:
        for node in controllers:
            remote.execute("pcs resource clear p_neutron-l3-agent {0}".format(
                node.data['fqdn']))


@pytest.fixture
def clean_os(os_conn):
    """Cleanup OpenStack"""
    os_conn.cleanup_network()


@pytest.yield_fixture(scope="function")
def setup(request, env_name, snapshot_name, env, os_conn):
    if env_name:
        revert_snapshot(request, env_name, snapshot_name)
    yield
    if not env_name:
        clear_l3_ban(env, os_conn)
        clean_os(os_conn)


@pytest.fixture
def tshark():
    """Returns tshark bin path"""
    path = find_executable('tshark')
    if path is None:
        pytest.skip('requires tshark executable')
    return path


@pytest.fixture
def check_ha_env(env):
    """Check that deployment type is HA"""
    if not env.is_ha or len(env.get_nodes_by_role('controller')) < 3:
        pytest.skip('requires HA cluster')


@pytest.fixture
def check_several_computes(env):
    """Check that count of compute nodes not less than 2"""
    if len(env.get_nodes_by_role('compute')) < 2:
        pytest.skip('requires at least 2 compute node')


@pytest.fixture
def check_devops(env_name):
    """Check that devops env is defined"""
    try:
        DevopsClient.get_env(env_name=env_name)
    except Exception:
        pytest.skip('requires devops env to be defined')


@pytest.fixture
def check_vxlan(env):
    """Check that env has vxlan network segmentation"""
    if env.network_segmentation_type != 'tun':
        pytest.skip('requires vxlan segmentation')


@pytest.fixture
def check_l2pop(env, check_vxlan):
    """Check that env has vxlan segmentation woth l2 population"""
    cmd = 'grep -q ^l2_population=True /etc/neutron/plugin.ini'
    controller = env.get_nodes_by_role('controller')[0]
    with env.get_ssh_to_node(controller.data['ip']) as remote:
        result = remote.execute(cmd)
    if result['exit_code'] != 0:
        pytest.skip('requires vxlan with l2 population')
