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
import os

import pytest

from mos_tests.environment.devops_client import DevopsClient
from mos_tests.environment.fuel_client import FuelClient
from mos_tests.settings import KEYSTONE_PASS
from mos_tests.settings import KEYSTONE_USER
from mos_tests.settings import SERVER_ADDRESS
from mos_tests.settings import SSH_CREDENTIALS

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption("--fuel-ip", '-I', action="store",
                     help="Fuel master server ip address")
    parser.addoption("--env", '-E', action="store",
                     help="Fuel devops env name")
    parser.addoption("--snapshot", '-S', action="store",
                     help="Fuel devops snapshot name")


def pytest_configure(config):
    # register an additional marker
    config.addinivalue_line("markers",
        "check_env_(check1, check2): mark test to run only on env, which pass "
        "all checks")
    config.addinivalue_line("markers",
        "need_devops: mark test wich need devops to run")
    config.addinivalue_line("markers",
        "neeed_tshark: mark test wich need tshark to be installed to run")
    config.addinivalue_line("markers",
        "undestructive: mark test wich has teardown")


def pytest_runtest_makereport(item, call):
    destroyed = True
    if 'undestructive' in item.keywords:
        destroyed = False
    if call.excinfo is not None:
        if call.excinfo.typename != 'Skipped':
            destroyed = True
    destroyed = destroyed or getattr(item, 'env_destroyed', False)
    setattr(item, 'env_destroyed', destroyed)


def pytest_runtest_teardown(item, nextitem):
    if nextitem is not None:
        setattr(nextitem, 'do_revert', getattr(item, 'env_destroyed', True))


@pytest.fixture(scope="session")
def env_name(request):
    return request.config.getoption("--env")


@pytest.fixture(scope="session")
def snapshot_name(request):
    return request.config.getoption("--snapshot")


@pytest.fixture
def revert_snapshot(request, env_name, snapshot_name):
    """Revert Fuel devops snapshot before test"""
    if not all([env_name, snapshot_name]):
        return
    if getattr(request.node, 'do_revert', True):
        DevopsClient.revert_snapshot(env_name=env_name,
                                     snapshot_name=snapshot_name)
        setattr(request.node, 'do_revert', False)
        setattr(request.node, 'reverted', True)


@pytest.fixture
def fuel_master_ip(request, env_name, revert_snapshot):
    """Get fuel master ip"""
    fuel_ip = request.config.getoption("--fuel-ip")
    if not fuel_ip:
        fuel_ip = DevopsClient.get_admin_node_ip(env_name=env_name)
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
def env(request, fuel):
    """Environment instance"""
    env = fuel.get_last_created_cluster()
    if getattr(request.node, 'reverted', False):
        env.wait_for_ostf_pass()
    return env


@pytest.fixture
def set_openstack_environ(env):
    """Set os.environ variables from openrc file"""
    if 'OS_AUTH_URL' in os.environ:
        return
    logger.info("read OpenStack openrc file")
    controllers = env.get_nodes_by_role('controller')[0]
    with controllers.ssh() as remote:
        result = remote.check_call('env -0')
        before_vars = set(result['stdout'][-1].strip().split('\x00'))
        result = remote.check_call('. openrc && env -0')
        after_vars = set(result['stdout'][-1].strip().split('\x00'))
        for os_var in after_vars - before_vars:
            k, v = os_var.split('=', 1)
            # if k == 'OS_AUTH_URL':
            #     parts = parse.urlparse(v)
            #     netloc = '{}:{}'.format(env.get_primary_controller_ip(),
            #                             parts.port)
            #     new_parts = parts._replace(netloc=netloc)
            #     v = parse.urlunparse(new_parts)
            os.environ[k] = v
