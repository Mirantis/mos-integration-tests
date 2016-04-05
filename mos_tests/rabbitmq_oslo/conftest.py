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
import random

import pytest


logger = logging.getLogger(__name__)


@pytest.yield_fixture
def fixt_open_5000_port_on_nodes(env):
    """Required to be able to send GET request from non management IP"""
    for node in env.get_all_nodes():
        with node.ssh() as remote:
            cmd = 'iptables -A INPUT -p tcp --dport 5000 -j ACCEPT'
            remote.check_call(cmd)
    yield
    for node in env.get_all_nodes():
        with node.ssh() as remote:
            # delete rule
            cmd = 'iptables -D INPUT -p tcp --dport 5000 -j ACCEPT'
            remote.check_call(cmd)


@pytest.yield_fixture
def fixt_kill_rpc_server_client(env):
    """Stop oslo_msg_check_server AND oslo_msg_check_client after test"""
    yield
    for node in env.get_all_nodes():
        with node.ssh() as remote:
            cmd = 'pkill -f oslo_msg_check_'
            remote.execute(cmd)


@pytest.fixture
def controller(env):
    return random.choice(env.get_nodes_by_role('controller'))


@pytest.yield_fixture
def patch_iptables(controller, request):
    """Apply IPTables rules"""

    def add_ports(tmpl):
        ports = [4369, 5672, 5673, 25672]
        return ' '.join(map(lambda portnum: tmpl.format(portnum=portnum),
                            ports))

    if request.param == 'drop':
        tbl_modif = add_ports(
            'iptables -I INPUT -p tcp -m tcp --dport {portnum} -j DROP ;')
        tbl_modif_del = add_ports(
            'iptables -D INPUT -p tcp -m tcp --dport {portnum} -j DROP ;')
    elif request.param == 'reject':
        tbl_modif = add_ports(
            'iptables -I INPUT -p tcp -m tcp --dport {portnum} -j REJECT'
            ' --reject-with icmp-host-prohibited ;')
        tbl_modif_del = add_ports(
            'iptables -D INPUT -p tcp -m tcp --dport {portnum} -j REJECT'
            ' --reject-with icmp-host-prohibited ;')
    else:
        raise ValueError("Does'n know such param [{0}]!".format(request.param))

    logger.debug('Applying IPTables rules [{0}] to {1}'.format(
        request.param, controller.data['ip']))
    with controller.ssh() as remote:
        remote.check_call(tbl_modif)
    yield

    # revert changes
    with controller.ssh() as remote:
        remote.check_call(tbl_modif_del)
