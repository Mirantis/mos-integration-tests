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

from mos_tests.functions.common import wait


logger = logging.getLogger(__name__)


def num_of_rabbit_running_nodes(remote):
    """Get number of 'Started/Master' hosts from pacemaker.
    :param remote: SSH connection point to controller.
    """
    result = remote.execute('pcs status --full | '
                            'grep p_rabbitmq-server | '
                            'grep ocf | '
                            'grep -c -E "Master|Started"', verbose=False)
    count = result['stdout'][0].strip()
    if count.isdigit():
        return int(count)
    else:
        return 0


def wait_for_rabbit_running_nodes(remote, exp_nodes, timeout_min=5):
    """Waits until number of 'Started/Master' hosts from pacemaker
    will be as expected number of controllers.
    :param remote: SSH connection point to controller.
    :param exp_nodes: Expected number of rabbit nodes.
    :param timeout_min: Timeout in minutes to wait.
    """
    wait(lambda: num_of_rabbit_running_nodes(remote) == exp_nodes,
         timeout_seconds=60 * timeout_min,
         sleep_seconds=30,
         waiting_for='number of running nodes will be %s.' % exp_nodes)

# ----------------------------------------------------------------------------


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('844786')
def test_disable_ha_for_rpc_queues_by_default(env):
    """Check that HA RPC is disabled by default.

    :param env: Environment

    Actions:
    1. Get launch parameters for p_rabbitmq-server from pacemaker;
    2. Check that 'enable_notifications_ha=true' and 'enable_rpc_ha=false';
    """
    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)

    # Install tool on one controller and generate messages
    with controller.ssh() as remote:
        # wait when rabbit will be ok after snapshot revert
        wait_for_rabbit_running_nodes(remote, len(controllers))
        resp_pcs = remote.execute('pcs resource show '
                                  'p_rabbitmq-server')['stdout']
    assert (
        filter(
            lambda x: 'enable_notifications_ha=true' in x, resp_pcs) != [] and
        filter(
            lambda x: 'enable_notifications_ha=false' not in x, resp_pcs) != []
    ), 'Disabled HA notifications (should be enabled)'

    assert (filter(lambda x: 'enable_rpc_ha=false' in x, resp_pcs) != [] and
            filter(lambda x: 'enable_rpc_ha=true' not in x, resp_pcs) != []), (
        'Enabled HA RPC (should be disabled)')


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('857403')
def test_check_rabbitmq_policy(env):
    """Check that rabbitmq policy have rules.

    :param env: Environment

    Actions:
    1. Execute `rabbitmqctl list_policies` command on one of controllers and
    verify that contain more than one non-empty strings.
    """
    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)
    with controller.ssh() as remote:
        # wait when rabbit will be ok after snapshot revert
        wait_for_rabbit_running_nodes(remote, len(controllers))
        result = remote.check_call('rabbitmqctl list_policies')['stdout']
    count_non_empty_lines = 0
    for line in result:
        if len(line):
            count_non_empty_lines += 1
    assert 1 < count_non_empty_lines, 'RabbitMQ was lost any policy'


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('851872')
def test_check_hipe_compilation(env):
    """Check that rabbitmq was runned with HiPE compilation files.

    :param env: Environment

    Actions:
    1. Get rabbitmq run command, parce HiPE native code location.
    2. Check that count of files in this location <> 0.
    """
    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)
    with controller.ssh() as remote:
        # wait when rabbit will be ok after snapshot revert
        wait_for_rabbit_running_nodes(remote, len(controllers))
        cmd = 'ls -la $(for i in $(ps aux | grep rabbitmq ); ' \
              'do echo $i | grep "native"; done) | grep -c ".beam"'
        result = remote.check_call(cmd)['stdout'][0]
    assert 0 < int(result), "RabbitMQ don't use HiPE or invalid location to " \
                            "precompiled files or files wasn't found."


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('844794')
def test_check_appropriate_async_thread_pool_size(env):
    """Check appropriate async thread pool size.

    :param env: Environment

    Actions:
    1. Make ssh to one of controllers.
    2. Get cpu count and get get result `ps ax | perl -nE
    '/beam.*-sname rabbit/ && /^\s*(\d+).*?-A (\d+)/ && say "$2"'` command.
    3. Compare this results, number value should be between (64, 1024),
    closest to 16*(cpu count).
    """

    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)
    with controller.ssh() as remote:
        # wait when rabbit will be ok after snapshot revert
        wait_for_rabbit_running_nodes(remote, len(controllers))
        cpu_count = int(remote.check_call("grep -c ^processor /proc/cpuinfo")
                        ['stdout'][0].strip())
        thread_pool_size = int(remote.check_call(
            "ps ax | perl -nE '/beam.*-sname rabbit/ && /^\s*(\d+).*?-A "
            "(\d+)/ && say $2'")['stdout'][0].strip())

    calculated_pool_size = cpu_count * 16
    if calculated_pool_size < 64:
        calculated_pool_size = 64

    assert 64 <= thread_pool_size, "Rabbit appropriate async thread pool " \
                                   "size smaller then 64."

    assert 1024 >= thread_pool_size, "Rabbit appropriate async thread pool " \
                                     "size bigger then 1024."

    assert calculated_pool_size == thread_pool_size, \
        "Real rabbit thread_pool_size != calculated."
