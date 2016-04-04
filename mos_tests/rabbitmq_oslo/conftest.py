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


@pytest.yield_fixture
def fixt_iptables_drop_reject(env, request):
    """Choose one controller and apply IPTables rules"""
    i_am_chosen_mark = '/tmp/i_am_chosen_mark.txt'

    if request.param == 'drop':
        table_modif = (
            'iptables -I INPUT -p tcp -m tcp --dport 4369  -j DROP ; '
            'iptables -I INPUT -p tcp -m tcp --dport 25672 -j DROP ; '
            'iptables -I INPUT -p tcp -m tcp --dport 5672  -j DROP ; '
            'iptables -I INPUT -p tcp -m tcp --dport 5673  -j DROP ; ')
        table_modif_del = (
            'iptables -D INPUT -p tcp -m tcp --dport 4369  -j DROP ; '
            'iptables -D INPUT -p tcp -m tcp --dport 25672 -j DROP ; '
            'iptables -D INPUT -p tcp -m tcp --dport 5672  -j DROP ; '
            'iptables -D INPUT -p tcp -m tcp --dport 5673  -j DROP ; ')
    elif request.param == 'reject':
        table_modif = (
            'iptables -I INPUT -p tcp -m tcp --dport 4369'
            ' -j REJECT --reject-with icmp-host-prohibited ; '
            'iptables -I INPUT -p tcp -m tcp --dport 25672'
            ' -j REJECT --reject-with icmp-host-prohibited ; '
            'iptables -I INPUT -p tcp -m tcp --dport 5672'
            ' -j REJECT --reject-with icmp-host-prohibited ; '
            'iptables -I INPUT -p tcp -m tcp --dport 5673'
            ' -j REJECT --reject-with icmp-host-prohibited ; ')
        table_modif_del = (
            'iptables -D INPUT -p tcp -m tcp --dport 4369'
            ' -j REJECT --reject-with icmp-host-prohibited ; '
            'iptables -D INPUT -p tcp -m tcp --dport 25672'
            ' -j REJECT --reject-with icmp-host-prohibited ; '
            'iptables -D INPUT -p tcp -m tcp --dport 5672'
            ' -j REJECT --reject-with icmp-host-prohibited ; '
            'iptables -D INPUT -p tcp -m tcp --dport 5673'
            ' -j REJECT --reject-with icmp-host-prohibited ; ')
    else:
        raise ValueError("Does'n know such param [{0}]!".format(request.param))

    controller = random.choice(env.get_nodes_by_role('controller'))
    logger.debug('Applying IPTables rules [{0}] to {1}'.format(
        request.param, controller.data['ip']))
    with controller.ssh() as remote:
        # execute iptables DROP command
        remote.check_call(table_modif)
        # mark this controller
        with remote.open(i_am_chosen_mark, 'w') as f:
            f.write("Hello? Is it me you're looking for?\n")
    yield
    # revert changes
    with controller.ssh() as remote:
        remote.rm_rf(i_am_chosen_mark)
        remote.check_call(table_modif_del)
