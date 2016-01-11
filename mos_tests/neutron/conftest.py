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

from distutils.spawn import find_executable
import pytest
from six.moves import configparser

from mos_tests.environment.devops_client import DevopsClient


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
    controller = env.get_nodes_by_role('controller')[0]
    with env.get_ssh_to_node(controller.data['ip']) as remote:
        with remote.open('/etc/neutron/plugin.ini') as f:
            return get_config_option(f, 'l2_population', bool) is True


def is_dvr(env):
    """Env deployed with enabled distributed routers support"""
    controller = env.get_nodes_by_role('controller')[0]
    with env.get_ssh_to_node(controller.data['ip']) as remote:
        with remote.open('/etc/neutron/plugin.ini') as f:
            return get_config_option(
                f, 'enable_distributed_routing', bool) is True


def is_l3_ha(env):
    """Env deployed with enabled distributed routers support"""
    controller = env.get_nodes_by_role('controller')[0]
    with env.get_ssh_to_node(controller.data['ip']) as remote:
        with remote.open('/etc/neutron/neutron.conf') as f:
            return get_config_option(f, 'l3_ha', bool) is True


@pytest.fixture(autouse=True)
def env_requirements(request, env):
    if request.node.get_marker('check_env_'):
        for func_name in request.node.get_marker('check_env_').args:
            func = globals().get(func_name)
            if func is not None and not func(env):
                doc = func.__doc__ or 'Env {}'.format(
                    func_name.replace('_', ' '))
                pytest.skip('Requires: {}'.format(doc))


@pytest.fixture(autouse=True)
def devops_requirements(request, env_name):
    if request.node.get_marker('need_devops'):
        try:
            DevopsClient.get_env(env_name=env_name)
        except Exception:
            pytest.skip('requires devops env to be defined')


@pytest.fixture(autouse=True)
def tshark_requirements(request, env_name):
    if request.node.get_marker('need_tshark'):
        path = find_executable('tshark')
        if path is None:
            pytest.skip('requires tshark executable')
