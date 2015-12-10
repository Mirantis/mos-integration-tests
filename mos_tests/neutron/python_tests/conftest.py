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

import pytest

from environment.fuel_client import FuelClient
from environment.os_actions import OpenStackActions
from mos_tests.settings import SERVER_ADDRESS
from mos_tests.settings import KEYSTONE_USER
from mos_tests.settings import KEYSTONE_PASS
from mos_tests.settings import SSH_CREDENTIALS


@pytest.fixture
def fuel():
    """Initialized fuel client"""
    return FuelClient(ip=SERVER_ADDRESS,
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
    return OpenStackActions(
        controller_ip=env.get_primary_controller_ip())


@pytest.fixture
def clean_os(os_conn):
    """Cleanup OpenStack"""
    os_conn.cleanup_network()


@pytest.yield_fixture
def clear_l3_ban(fuel, env, os_conn):
    """Clear all l3-agent bans after test"""
    yield
    controllers = env.get_nodes_by_role('controller')
    ip = controllers[0].data['ip']
    with env.get_ssh_to_node(ip) as remote:
        for node in controllers:
            remote.execute("pcs resource clear p_neutron-l3-agent {0}".format(
                node.data['fqdn']))


@pytest.fixture
def check_ha_env(env):
    """Check that deployment type is HA"""
    if not env.is_ha:
        pytest.skip('requires HA cluster')


@pytest.fixture
def check_several_computes(env):
    """Check that count of compute nodes not less than 2"""
    if len(env.get_nodes_by_role('compute')) < 2:
        pytest.skip('requires at least 2 compute node')
