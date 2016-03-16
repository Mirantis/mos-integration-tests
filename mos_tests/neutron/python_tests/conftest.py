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


logger = logging.getLogger(__name__)


@pytest.yield_fixture
def clear_l3_ban(env, os_conn):
    """Clear all l3-agent bans after test"""
    yield
    controllers = env.get_nodes_by_role('controller')
    ip = controllers[0].data['ip']
    with env.get_ssh_to_node(ip) as remote:
        for node in controllers:
            remote.execute("pcs resource clear neutron-l3-agent {0}".format(
                node.data['fqdn']))


@pytest.fixture
def setup(request, env_name, snapshot_name, env, os_conn):
    # TODO(gdyuldin) remove this fixture
    pass
