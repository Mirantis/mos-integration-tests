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
from time import sleep

import pytest

from mos_tests.functions.common import wait
from mos_tests.rabbitmq_oslo.utils import BashCommand as cmd


logger = logging.getLogger(__name__)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('844786')
def test_disable_ha_for_rpc_queues_by_default(env, rabbitmq):
    """Check that HA RPC is disabled by default.

    Actions:
    1. Get launch parameters for p_rabbitmq-server from pacemaker;
    2. Check that 'enable_notifications_ha=true' and 'enable_rpc_ha=false';
    """
    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)

    with controller.ssh() as remote:
        # wait when rabbit will be ok after snapshot revert
        rabbitmq.wait_for_rabbit_running_nodes(exp_nodes=len(controllers))
        resp_pcs = remote.execute(
            cmd.pacemaker.show.format(
                service=cmd.pacemaker.rabbit_slave_name,
                timeout=5,
                fqdn='$(hostname)'))
        resp_pcs = resp_pcs['stdout']

    assert (
        filter(
            lambda x: 'enable_notifications_ha=true' in x, resp_pcs) != [] and
        filter(
            lambda x: 'enable_notifications_ha=false' not in x, resp_pcs) != []
    ), 'Disabled HA notifications (should be enabled)'

    assert (
        filter(lambda x: 'enable_rpc_ha=false' in x, resp_pcs) != [] and
        filter(lambda x: 'enable_rpc_ha=true' not in x, resp_pcs) != []
    ), 'Enabled HA RPC (should be disabled)'


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('857403')
def test_check_rabbitmq_policy(env, rabbitmq):
    """Check that rabbitmq policy have rules.

    Actions:
    1. Execute `rabbitmqctl list_policies` command on one of controllers and
    verify that contain more than one non-empty strings.
    """
    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)
    with controller.ssh() as remote:
        # wait when rabbit will be ok after snapshot revert
        rabbitmq.wait_for_rabbit_running_nodes(exp_nodes=len(controllers))
        result = remote.check_call(
            cmd.rabbitmqctl.list_policies)['stdout']

    count_non_empty_lines = 0
    for line in result:
        if len(line):
            count_non_empty_lines += 1

    assert 1 < count_non_empty_lines, 'RabbitMQ has lost some policies'


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('851872')
def test_check_hipe_compilation(env, rabbitmq):
    """Check that rabbitmq is running with HiPE compilation files.

    Actions:
    1. Get rabbitmq run command, parse HiPE native code location.
    2. Check that count of files in this location <> 0.
    """
    controllers = env.get_nodes_by_role('controller')
    controller = random.choice(controllers)
    with controller.ssh() as remote:
        # wait when rabbit will be ok after snapshot revert
        rabbitmq.wait_for_rabbit_running_nodes(exp_nodes=len(controllers))
        result = remote.check_call(cmd.system.hipe_files_count).stdout_string

    assert 0 < int(result), ("RabbitMQ don't use HiPE or invalid location to "
                             "precompiled files or files wasn't found.")


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.testrail_id('844794')
def test_check_appropriate_async_thread_pool_size(env, rabbitmq):
    """Check appropriate async thread pool size.

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
        rabbitmq.wait_for_rabbit_running_nodes(exp_nodes=len(controllers))
        cpu_count = int(
            remote.check_call(cmd.system.cpu_count).stdout_string)
        thread_pool_size = int(
            remote.check_call(cmd.system.thread_pool_size).stdout_string)

    calculated_pool_size = cpu_count * 16
    if calculated_pool_size < 64:
        calculated_pool_size = 64

    assert 64 <= thread_pool_size, ("Rabbit appropriate async thread pool "
                                    "size smaller then 64.")

    assert 1024 >= thread_pool_size, ("Rabbit appropriate async thread pool "
                                      "size bigger then 1024.")

    assert calculated_pool_size == thread_pool_size, (
        "Real rabbit thread_pool_size != calculated.")


# Destructive
class TestRabbitSegfaultsAndInteraction(object):

    def control_rabbit_service(self, admin_remote, action='start'):
        """Performs 'service rabbitmq-server {action}' on fuel admin node.
        And checks that output does not contains error words from 'err_words'
        """
        err_words = ['segfault', 'error', 'failed']
        err_msg = ('Some of the err messages {0} are in service '
                   'rabbitmq-server {1} output.'.format(err_words, action))

        if action == 'start':
            action_cmd = cmd.rabbit_srv_service.start
        else:
            action_cmd = cmd.rabbit_srv_service.stop

        out = admin_remote.check_call(action_cmd)

        # Check that there are no error words in cmd output
        combined_out = out.stdout_string + out.stderr_string

        # Workaround for invalid stderr from dbus+systemd.
        # More info: http://paste.openstack.org/show/594837
        if 'error=n/a' in str(combined_out).lower():
            err_words.remove("error")

        assert not any(
            i in str(combined_out).lower()
            for i in err_words), err_msg

    def wait_rabbit_became_active(self, admin_remote, timeout_min=1):
        """Wait till Rabbit on fuel master node has
        [Active: active (running)] in it's status.
        """
        wait(
            lambda: admin_remote.execute(
                cmd.rabbit_srv_service.grep_active).is_ok,
            timeout_seconds=60 * timeout_min,
            sleep_seconds=20,
            waiting_for='service rabbitmq-server became active')

    def wait_rabbit_became_exited(self, admin_remote, timeout_min=1):
        """Wait till Rabbit on fuel master node has
        [Status: "Exited."] in it's status.
        """
        wait(
            lambda: admin_remote.execute(
                cmd.rabbit_srv_service.grep_exited).is_ok,
            timeout_seconds=60 * timeout_min,
            sleep_seconds=20,
            waiting_for='service rabbitmq-server became exited')

    @pytest.mark.testrail_id('844790')
    def test_no_segfaults_on_master(self, admin_remote):
        """Check rabbitmqctl segfaults on master node

        Actions:
        1. Stop rabbit service and check that there are no errors in output;
        2. Wait till rabbitmq-server status has DIAGNOSTICS info;
        3. Start rabbit service and check that there are no errors in output;
        4. Wait till rabbitmq-server status has
        "Active: active (running)" string.
        """
        timeout = 1  # minute

        # Stop rabbit and check that there are no errors in output
        self.control_rabbit_service(admin_remote, 'stop')

        # Wait till rabbitmq-server status has DIAGNOSTICS info
        wait(
            lambda: admin_remote.execute(
                cmd.rabbitmqctl.grep_diagnostics).is_ok,
            timeout_seconds=60 * timeout,
            sleep_seconds=20,
            waiting_for='service rabbitmq-server has DIAGNOSTICS info')

        # Start rabbit and check that there are no errors in output
        self.control_rabbit_service(admin_remote, 'start')

        # Wait till rabbitmq-server has "Active: active (running)" string
        self.wait_rabbit_became_active(admin_remote, timeout)

    @pytest.mark.testrail_id('844787')
    def test_interaction_on_master(self, admin_remote):
        """Validate RabbitMQ/systemd interaction on master node.

        Actions:
        1. Stop rabbit service and check that there are no errors in output;
        2. Wait till rabbitmq-server status has "Status: "Exited."" string;
        3. Perform several rabbit start-stops with sleep between actions;
        4. Start rabbit service and check that there are no errors in output;
        5. Wait till rabbitmq-server status has
        "Active: active (running)" string
        """
        timeout = 1                # minute
        sleep_between_restart = 1  # minute

        # Stop rabbit and check that there are no errors in output
        self.control_rabbit_service(admin_remote, 'stop')

        # Wait till rabbitmq-server has "Status: "Exited."" string
        self.wait_rabbit_became_exited(admin_remote, timeout)
        sleep(60 * sleep_between_restart)

        # Rabbit start-stops with check that there are no errors in output
        for i in range(5):
            self.control_rabbit_service(admin_remote, 'start')
            sleep(60 * sleep_between_restart)
            self.control_rabbit_service(admin_remote, 'stop')

        # Wait till rabbitmq-server has "Active: active (running)" string
        self.control_rabbit_service(admin_remote, 'start')
        self.wait_rabbit_became_active(admin_remote, timeout)
