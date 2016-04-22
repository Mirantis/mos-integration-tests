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

from collections import namedtuple
from distutils.spawn import find_executable
import logging
import os
import uuid

import pytest
from six.moves import configparser

from mos_tests.environment.devops_client import DevopsClient
from mos_tests.environment.fuel_client import FuelClient
from mos_tests.functions.common import gen_temp_file
from mos_tests.functions.common import get_os_conn
from mos_tests.functions.common import wait
from mos_tests.functions import os_cli
from mos_tests.settings import KEYSTONE_PASS
from mos_tests.settings import KEYSTONE_USER
from mos_tests.settings import SERVER_ADDRESS
from mos_tests.settings import SSH_CREDENTIALS

logger = logging.getLogger(__name__)


# Define pytest plugins to use
pytest_plugins = ("plugins.incremental",
                  "plugins.testrail_id")


def pytest_addoption(parser):
    parser.addoption("--fuel-ip", '-I', action="store",
                     help="Fuel master server ip address")
    parser.addoption("--env", '-E', action="store",
                     help="Fuel devops env name")
    parser.addoption("--snapshot", '-S', action="store",
                     help="Fuel devops snapshot name")
    parser.addoption("--cluster", '-C', action="append",
                     help="Fuel cluster name to test on it")


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
    config.addinivalue_line("markers",
        "testrail_id(id, params={'name': value,...}): add suffix to "
        "test name. If defined, `params` apply case_id only if it "
        "matches test params.")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # execute all other hooks to obtain the report object
    outcome = yield
    rep = outcome.get_result()

    # set an report attribute for each phase of a call, which can
    # be "setup", "call", "teardown"
    setattr(item, "rep_" + rep.when, rep)


def pytest_runtest_teardown(item, nextitem):
    setattr(item.session, "nextitem", nextitem)


@pytest.fixture
def suffix():
    return str(uuid.uuid4())


@pytest.fixture(scope="session")
def env_name(request):
    return request.config.getoption("--env")


@pytest.fixture(scope='session')
def devops_env(env_name):
    return DevopsClient.get_env(env_name=env_name)


@pytest.fixture(scope="session")
def snapshot_name(request):
    return request.config.getoption("--snapshot")


@pytest.fixture(scope="session")
def fuel_master_ip(request, env_name, snapshot_name):
    """Get fuel master ip"""
    fuel_ip = request.config.getoption("--fuel-ip")
    if not fuel_ip:
        fuel_ip = DevopsClient.get_admin_node_ip(env_name=env_name)
    if not fuel_ip:
        fuel_ip = SERVER_ADDRESS
    return fuel_ip


def revert_snapshot(env_name, snapshot_name):
    DevopsClient.revert_snapshot(env_name=env_name,
                                 snapshot_name=snapshot_name)


@pytest.fixture(scope="session", autouse=True)
def setup_session(request, env_name, snapshot_name):
    """Revert Fuel devops snapshot before test session"""
    if not all([env_name, snapshot_name]):
        setattr(request.session, 'reverted', False)
        return
    revert_snapshot(env_name, snapshot_name)


def reinit_fixtures(request):
    """Refresh some session fixtures (after revert, for example)"""
    logger.info('refresh clients fixtures')
    for fixture in ('fuel', 'env', 'os_conn'):
        try:
            fixturedef = request._get_active_fixturedef(fixture)
        except Exception:
            continue
        fixturedef.cached_result = None


@pytest.yield_fixture(autouse=True)
def cleanup(request, env_name, snapshot_name):
    yield
    item = request.node
    if hasattr(item.session, 'nextitem') and item.session.nextitem is None:
        return
    test_results = [getattr(item, 'rep_{}'.format(name), None)
                    for name in ("setup", "call", "teardown")]
    failed = any(x for x in test_results if x is not None and x.failed)
    if request.config.option.exitfirst and failed:
        return
    skipped = any(x for x in test_results if x is not None and x.skipped)
    destructive = 'undestructive' not in item.keywords
    reverted = False
    if destructive and not skipped:
        if all([env_name, snapshot_name]):
            revert_snapshot(env_name, snapshot_name)
            reverted = True
    setattr(request.session, 'reverted', reverted)

    # reinitialize fixtures
    reinit_fixtures(request)


def get_fuel_client(fuel_ip):
    return FuelClient(ip=fuel_ip,
                      login=KEYSTONE_USER,
                      password=KEYSTONE_PASS,
                      ssh_login=SSH_CREDENTIALS['login'],
                      ssh_password=SSH_CREDENTIALS['password'])


@pytest.fixture(scope="session")
def credentials(setup_session, fuel_master_ip):
    Credentials = namedtuple(
        'Credentials',
        ['fuel_ip', 'controller_ip', 'keystone_url', 'username', 'password',
            'project', 'cert'])

    fuel = get_fuel_client(fuel_master_ip)
    env = fuel.get_last_created_cluster()
    controller_ip = env.get_primary_controller_ip()
    cert = env.certificate
    if cert is None:
        keystone_url = 'http://{0}:5000/v2.0/'.format(controller_ip)
        path_to_cert = None
    else:
        keystone_url = 'https://{0}:5000/v2.0/'.format(controller_ip)
        with gen_temp_file(prefix="fuel_cert_", suffix=".pem") as f:
            f.write(cert)
        path_to_cert = f.name
    return Credentials(fuel_ip=fuel_master_ip,
                       controller_ip=controller_ip,
                       keystone_url=keystone_url,
                       username='admin',
                       password='admin',
                       project='admin',
                       cert=path_to_cert)


@pytest.fixture(scope='session')
def fuel(fuel_master_ip):
    """Initialized fuel client"""
    return get_fuel_client(fuel_master_ip)


@pytest.fixture(scope='session')
def env(request, fuel):
    """Environment instance"""
    names = request.config.getoption('--cluster')
    if not names:
        env = fuel.get_last_created_cluster()
    else:
        envs = fuel.get_clustres_by_names(names)
        if len(envs) == 0:
            raise Exception(
                "Can't find fuel cluster with name in {}".format(names))
        env = envs[0]
    assert env.is_operational
    if getattr(request.session, 'reverted', True):
        env.wait_for_ostf_pass()
        wait(env.os_conn.is_nova_ready,
             timeout_seconds=60 * 5,
             expected_exceptions=Exception,
             waiting_for="OpenStack nova computes is ready")
    return env


@pytest.fixture(scope="session")
def set_openstack_environ(fuel_master_ip):
    fuel = get_fuel_client(fuel_master_ip)
    env = fuel.get_last_created_cluster()
    """Set os.environ variables from openrc file"""
    logger.info("read OpenStack openrc file")
    controllers = env.get_nodes_by_role('controller')[0]
    with controllers.ssh() as remote:
        result = remote.check_call('env -0')
        before_vars = set(result['stdout'][-1].strip().split('\x00'))
        result = remote.check_call('. openrc && env -0')
        after_vars = set(result['stdout'][-1].strip().split('\x00'))
        for os_var in after_vars - before_vars:
            k, v = os_var.split('=', 1)
            if v == 'internalURL':
                v = 'publicURL'
            os.environ[k] = v


@pytest.fixture(scope='class')
def os_conn_for_unittests(request, fuel_master_ip):
    fuel_client = get_fuel_client(fuel_master_ip)
    environment = fuel_client.get_last_created_cluster()
    request.cls.env = environment
    request.cls.os_conn = environment.os_conn


@pytest.fixture(scope='session')
def os_conn(env):
    """Openstack common actions"""
    return env.os_conn


@pytest.fixture
def clean_os(os_conn):
    """Cleanup OpenStack"""
    os_conn.cleanup_network()


def is_ha(env):
    """Env deployed with HA (3 controllers)"""
    return env.is_ha and len(env.get_nodes_by_role('controller')) >= 3


def has_1_or_more_computes(env):
    """Env deployed with 1 or more computes"""
    return len(env.get_nodes_by_role('compute')) >= 1


def has_2_or_more_computes(env):
    """Env deployed with 2 or more computes"""
    return len(env.get_nodes_by_role('compute')) >= 2


def has_3_or_more_computes(env):
    """Env deployed with 3 or more computes"""
    return len(env.get_nodes_by_role('compute')) >= 3


def has_ironic_conductor(env):
    """Env deployed with at least one ironic conductor node"""
    return len(env.get_nodes_by_role('ironic')) >= 1


def has_2_or_more_ironic_conductors(env):
    """Env deployed with at least two ironic conductor nodes"""
    return len(env.get_nodes_by_role('ironic')) >= 2


def is_any_compute_suitable_for_max_flavor(env):
    attrs_to_check = {
        "vcpus": 8,
        "free_disk_gb": 160,
        "free_ram_mb": 16000,
    }

    def check_hypervisor_fit(hv):
        hv_result = all(
            [getattr(hv, attr) >= value
             for attr, value in attrs_to_check.items()])
        return hv_result

    os_connection = get_os_conn(env)
    result = any(
        check_hypervisor_fit(hv)
        for hv in os_connection.nova.hypervisors.list())
    return result


def is_vlan(env):
    """Env deployed with vlan segmentation"""
    return env.network_segmentation_type == 'vlan'


def is_vxlan(env):
    """Env deployed with vxlan segmentation"""
    return env.network_segmentation_type == 'tun'


def get_config_option(fp, key, res_type):
    """Find and return value for key in INI-like file"""
    parser = configparser.RawConfigParser()
    parser.readfp(fp)
    if res_type is bool:
        getter = parser.getboolean
    else:
        getter = parser.get
    for section in parser.sections():
        if parser.has_option(section, key):
            return getter(section, key)


def is_l2pop(env):
    """Env deployed with vxlan segmentation and l2 population"""
    data = env.get_settings_data()['editable']
    return data['neutron_advanced_configuration']['neutron_l2_pop']['value']


def is_dvr(env):
    """Env deployed with enabled distributed routers support"""
    data = env.get_settings_data()['editable']
    return data['neutron_advanced_configuration']['neutron_dvr']['value']


def is_l3_ha(env):
    """Env deployed with enabled distributed routers support"""
    data = env.get_settings_data()['editable']
    return data['neutron_advanced_configuration']['neutron_l3_ha']['value']


def is_ironic_enabled(env):
    data = env.get_settings_data()['editable']['additional_components']
    return data['ironic']['value']


def is_ceph_enabled(env):
    data = env.get_settings_data()['editable']['storage']
    return data['volumes_ceph']['value']


def is_qos_enabled(env):
    data = env.get_settings_data()['editable']
    return data['neutron_advanced_configuration']['neutron_qos']['value']


@pytest.fixture(autouse=True)
def executable_requirements(request, env_name):
    marker = request.node.get_marker('requires_')
    if marker:
        for arg in marker.args:
            path = find_executable(arg)
            if path is None:
                pytest.skip('requires {arg} executable'.format(arg=arg))


@pytest.fixture(autouse=True)
def env_requirements(request, env):
    reserved = {'or', 'and', 'not', '(', ')'}
    marker = request.node.get_marker('check_env_')
    if not marker:
        return
    marker_str = ' and '.join(marker.args)
    marker_str = marker_str.replace(
        '(', ' ( '
    ).replace(
        ')', ' ) '
    ).replace(
        '  ', ' ')
    functions = marker_str.split()
    marker_str_evalued = marker_str
    for func in functions:
        if func in reserved:
            continue
        function = globals().get(func)
        if function is None:
            logger.critical('Guard with name {} not found'.format(func))
            raise ValueError('Parse error')
        if not (func.startswith('is_') or func.startswith('has_')):
            logger.critical(
                'Guard must start with "is_" or "has_", got {} instead'.format(
                    func))
            raise ValueError('Parse error')
        marker_str_evalued = marker_str_evalued.replace(
            func, str(function(env)))

    if not eval(marker_str_evalued):
        pytest.skip('Requires criteria: {}, computed instead: {}'.format(
            marker_str, marker_str_evalued))


@pytest.fixture(autouse=True)
def devops_requirements(request, env_name):
    if request.node.get_marker('need_devops'):
        try:
            DevopsClient.get_env(env_name=env_name)
        except Exception:
            pytest.skip('requires devops env to be defined')


@pytest.yield_fixture
def controller_remote(env):
    with env.get_nodes_by_role('controller')[0].ssh() as remote:
        yield remote


@pytest.fixture
def openstack_client(controller_remote):
    return os_cli.OpenStack(controller_remote)
