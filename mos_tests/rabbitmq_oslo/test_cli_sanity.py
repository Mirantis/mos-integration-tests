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

import pytest

from mos_tests.neutron.python_tests.base import TestBase
from mos_tests.rabbitmq_oslo.utils import BashCommand

logger = logging.getLogger(__name__)


class CLIRabbitFunctions(TestBase):

    cmd = BashCommand
    timeout = 300

    bash_pcs_show_rabbit = cmd.pacemaker.show.format(
        service=cmd.pacemaker.rabbit_slave_name,
        timeout=timeout,
        fqdn='$(hostname)')

    bash_pcs_show_master_rabbit = cmd.pacemaker.show.format(
        service=cmd.pacemaker.rabbit_master_name,
        timeout=timeout,
        fqdn='$(hostname)')

    bash_pcs_disable_cluster = cmd.pacemaker.disable.format(
        service=cmd.pacemaker.rabbit_slave_name,
        timeout=timeout,
        fqdn='$(hostname)')

    bash_pcs_enable_cluster = cmd.pacemaker.enable.format(
        service=cmd.pacemaker.rabbit_slave_name,
        timeout=timeout,
        fqdn='$(hostname)')

    bash_pcs_restart_cluster = cmd.pacemaker.restart.format(
        service=cmd.pacemaker.rabbit_slave_name,
        timeout=timeout * 2,
        fqdn='$(hostname)')

    bash_grep_nova = (
        ' | grep -i nova')
    bash_grep_conductor = (
        ' | grep -i conductor')
    bash_grep_running_nodes = (
        ' |& grep -A1 running_nodes | grep -v cluster_name')
    bash_grep_role_fqdn = (
        ' | grep "rabbitmq-server.*{role}" | grep -o "node-.*" | head -1')

    def rabbit_nodes(self, fqdn_only=False):
        """Returns list of rabbit nodes or list of FQDNs of rabbit nodes.
        :param fqdn_only: Put True if you need only FQDNs of rabbit nodes.
        :return: List of rabbit nodes or list of FQDNs of nodes
        """
        detached_rabbit = self.env.get_nodes_by_role('standalone-rabbitmq')
        if len(detached_rabbit) > 0:
            nodes = detached_rabbit
        else:
            nodes = self.env.get_nodes_by_role('controller')

        if fqdn_only:
            return [x.data['fqdn'] for x in nodes]
        else:
            return nodes

    def short_rabbit_nodes_fqdns(self):
        """Returns list of short FQDNs of rabbit nodes.
        Like: [u'node-4', u'node-1', u'node-2']
        """
        fqdns = self.rabbit_nodes(fqdn_only=True)
        return [x.split('.')[0] for x in fqdns]

    def execute_on_all_rabbit_nodes(self, cmd, may_fail=False):
        """Execute command on all rabbit nodes.
        :param cmd: Bash command to execute
        :param may_fail: Expected that some commands may fail.
        :return: list of results from stdout from all nodes
        """
        result = []
        for node in self.rabbit_nodes():
            with node.ssh() as remote:
                if may_fail:
                    out = remote.execute(
                        cmd, verbose=False, merge_stderr=True).stdout_string
                else:
                    out = remote.check_call(cmd, verbose=False).stdout_string
                result.append(out)
        return result

    def master_fqdn(self):
        """Returns string with one FQDN of master node.
        :return: Str like 'node-1.test.domain.local' OR None
        """
        node = self.rabbit_nodes()[0]
        with node.ssh() as remote:
            out = remote.execute(
                self.cmd.pacemaker.full_status +
                self.bash_grep_role_fqdn.format(role='Master'))
        if out.is_ok:
            return out.stdout_string
        else:
            return None

    def slave_fqdn(self):
        """Returns string with one FQDN of slave node.
        :return: Str like 'node-1.test.domain.local' OR None
        """
        node = self.rabbit_nodes()[0]
        with node.ssh() as remote:
            out = remote.execute(
                self.cmd.pacemaker.full_status +
                self.bash_grep_role_fqdn.format(role='Started'))
        if out.is_ok:
            return out.stdout_string
        else:
            return None

    def rabbit_cluster_is_ok(self):
        """Performs execution of 'rabbitmqctl cluster_status' on all nodes.
        If exit_code was 0 on all hosts - return True.
        """
        self.execute_on_all_rabbit_nodes(
            cmd=(self.cmd.rabbitmqctl.cluster_status + ' && ' +
                 self.cmd.rabbitmqctl.status))
        # if cmd execution was ok- return True.
        # otherwise the will be an exception
        return True

    def rabbit_cluster_disabled(self):
        """Check that in output of 'rabbitmqctl cluster_status' from each node
        the will be an error message
        """
        err_msg = 'unable to connect to node'

        all_out = self.execute_on_all_rabbit_nodes(
            cmd=self.cmd.rabbitmqctl.cluster_status,
            may_fail=True)

        return all(err_msg in out for out in all_out)


@pytest.mark.undestructive
class TestRabbitCLISanityRabbitmqctl(CLIRabbitFunctions):

    @pytest.mark.testrail_id('1640520')
    def test_rabbitmqctl_get_cluster_status(self):
        """Tests Get cluster status command.

        Actions:
        1. Execute 'rabbitmqctl cluster_status' on all rabbit nodes.
        2. Check that exit_code is 0.
        3. Check that all rabbit nodes present in output.
        """
        all_out = self.execute_on_all_rabbit_nodes(
            self.cmd.rabbitmqctl.cluster_status)

        assert all(i in out
                   for i in self.short_rabbit_nodes_fqdns()
                   for out in all_out), (
            "Output of command does not contains some rabbit nodes:\n"
            "{0}".format(all_out))

    @pytest.mark.testrail_id('1640521')
    def test_rabbitmqctl_get_queues_list(self):
        """Tests Get queues list.

        Actions:
        1. Execute 'rabbitmqctl list_queues' on all rabbit nodes.
        2. Check that exit_code is 0.
        3. Output should contain "conductor" queues.
        """
        self.execute_on_all_rabbit_nodes(
            self.cmd.rabbitmqctl.list_queues + self.bash_grep_conductor)

    @pytest.mark.testrail_id('1640522')
    def test_rabbitmqctl_get_policy_list(self):
        """Tests Get policy list.

        Actions:
        1. Execute 'rabbitmqctl list_policies' on all rabbit nodes.
        2. Check that exit_code is 0.
        3. Check that output should contain policies (more than 2 rules).
        """
        policies_num = 2

        all_out = self.execute_on_all_rabbit_nodes(
            self.cmd.rabbitmqctl.list_policies)

        assert all(len(out.split('\n')) > policies_num + 1  # 1 line for header
                   for out in all_out), (
            "Output of command has less then 2 policies")

    @pytest.mark.testrail_id('1640523')
    def test_rabbitmqctl_get_exchanges_list(self):
        """Tests Get exchanges list.

        Actions:
        1. Execute 'rabbitmqctl list_exchanges' on all rabbit nodes.
        2. Check that exit_code is 0.
        3. Output should contain a 'nova' exchanges.
        """
        self.execute_on_all_rabbit_nodes(
            self.cmd.rabbitmqctl.list_exchanges + self.bash_grep_nova)

    @pytest.mark.testrail_id('1640524')
    def test_rabbitmqctl_get_bindings_list(self):
        """Tests Get bindings list.

        Actions:
        1. Execute 'rabbitmqctl list_bindings' on all rabbit nodes.
        2. Check that exit_code is 0.
        """
        self.execute_on_all_rabbit_nodes(self.cmd.rabbitmqctl.list_bindings)

    @pytest.mark.testrail_id('1640525')
    def test_rabbitmqctl_get_connection_list(self):
        """Tests Get connection list.

        Actions:
        1. Execute 'rabbitmqctl list_connections' on all rabbit nodes.
        2. Check that exit_code is 0.
        3. Output should contain many connections (for normal cluster works).
        """
        connect_num = 150

        all_out = self.execute_on_all_rabbit_nodes(
            self.cmd.rabbitmqctl.list_connections)

        assert all(len(out.split('\n')) > connect_num
                   for out in all_out), (
            "Output of command has less then %s connections" % connect_num)

    @pytest.mark.testrail_id('1640526')
    def test_rabbitmqctl_get_channels_list(self):
        """Tests Get channels list.

        Actions:
        1. Execute 'rabbitmqctl list_channels' on all rabbit nodes.
        2. Check that exit_code is 0.
        3. Output should contain channels for nova.
        """
        self.execute_on_all_rabbit_nodes(
            self.cmd.rabbitmqctl.list_channels + self.bash_grep_nova)

    @pytest.mark.testrail_id('1640527')
    def test_rabbitmqctl_get_consumers_list(self):
        """Tests Get consumers list.

        Actions:
        1. Execute 'rabbitmqctl list_consumers' on all rabbit nodes.
        2. Check that exit_code is 0.
        3. Output should contain nova consumers.
        """
        self.execute_on_all_rabbit_nodes(
            self.cmd.rabbitmqctl.list_consumers + self.bash_grep_conductor)


class TestRabbitCLISanityPCS(CLIRabbitFunctions):

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('1640528')
    def test_pcs_show(self):
        """Tests Get RabbitMQ resource status.

        Actions:
        1. Execute 'pcs resource show p_rabbitmq-server' on all rabbit nodes.
        2. Check that exit_code is 0.
        3. Output should contain status of RabbitMQ Cluster.
        """
        self.execute_on_all_rabbit_nodes(
            self.bash_pcs_show_rabbit + ' | grep "Resource:"' + ' && ' +
            self.bash_pcs_show_rabbit + ' | grep "Attributes:"' + ' && ' +
            self.bash_pcs_show_rabbit + ' | grep "Meta Attrs:"' + ' && ' +
            self.bash_pcs_show_rabbit + ' | grep "Operations:"')

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('1640529')
    def test_pcs_show_master(self):
        """Tests Get RabbitMQ Master resource status.

        Actions:
        1. Execute 'pcs resource show master_p_rabbitmq-server' on all rabbit
        nodes.
        2. Check that exit_code is 0.
        3. Output should contain status of RabbitMQ Cluster.
        """
        self.execute_on_all_rabbit_nodes(
            self.bash_pcs_show_master_rabbit + ' | grep "Master:"' + '&&' +
            self.bash_pcs_show_master_rabbit + ' | grep "Resource:"' + '&&' +
            self.bash_pcs_show_master_rabbit + ' | grep "Attributes:"' + '&&' +
            self.bash_pcs_show_master_rabbit + ' | grep "Meta Attrs:"' + '&&' +
            self.bash_pcs_show_master_rabbit + ' | grep "Operations:"')

    # destructive
    @pytest.mark.testrail_id('1640530')
    def test_pcs_disable_enable_cluster(self):
        """Tests Disable/Enable RabbitMQ cluster.

        Actions:
        1. Disable cluster with:
        'pcs resource disable p_rabbitmq --wait=300'.
        2. Check that all nodes has no connections to rabbit.
        3. Enable cluster with:
        'pcs resource clear p_rabbitmq-server $(hostname)'.
        2. Check that now status is ok.
        """
        # disable cluster and check that it is disabled
        self.execute_on_all_rabbit_nodes(self.bash_pcs_disable_cluster)
        assert self.rabbit_cluster_disabled(), (
            'Rabbit cluster is not disabled')

        # enable cluster and check status is ok
        self.execute_on_all_rabbit_nodes(self.bash_pcs_enable_cluster)
        assert self.rabbit_cluster_is_ok(), (
            'Rabbit cluster is not in OK state')

    # destructive
    @pytest.mark.testrail_id('1640531', params={'role': 'slave'})
    @pytest.mark.testrail_id('1640532', params={'role': 'master'})
    @pytest.mark.parametrize('role', ['slave', 'master'])
    def test_pcs_disable_enable_slave_master(self, role):
        """Tests Ban/Clear RabbitMQ Slave resource.

        Actions:
        1. Disable one slave/master rabbit host with:
        'pcs resource ban p_rabbitmq-server $(hostname) --wait=300'.
        2. Check that host is NOT in 'running_nodes' of output of
        'rabbitmqctl cluster_status' on all nodes.
        3. Enable back slave/master rabbit host with:
        'pcs resource clear p_rabbitmq-server $(hostname) --wait=300'
        4. Check that host is IN 'running_nodes' of output of
        'rabbitmqctl cluster_status' on all nodes.
        """
        if role == 'master':
            node_fqdn = self.master_fqdn()
            service = self.cmd.pacemaker.rabbit_master_name
        else:
            node_fqdn = self.slave_fqdn()
            service = self.cmd.pacemaker.rabbit_slave_name

        node_short_fqdn = node_fqdn.split('.')[0]  # like: 'node-2'
        host = self.rabbit_nodes()[0]

        # Disable one host
        with host.ssh() as remote:
            remote.check_call(
                self.cmd.pacemaker.ban.format(
                    service=service,
                    timeout=self.timeout,
                    fqdn=node_fqdn))

        # Get 'running_nodes' from 'rabbitmqctl cluster_status' from all nodes
        all_out = self.execute_on_all_rabbit_nodes(
            cmd=(self.cmd.rabbitmqctl.cluster_status +
                 self.bash_grep_running_nodes),
            may_fail=True)
        # Check that disabled host NOT in 'running_nodes'
        assert all(node_short_fqdn not in out
                   for out in all_out), (
            "Output of command contains disabled rabbit nodes:\n"
            "{0}".format(all_out))

        # Enable one host
        with host.ssh() as remote:
            remote.check_call(
                self.cmd.pacemaker.clear.format(
                    service=service,
                    timeout=self.timeout,
                    fqdn=node_fqdn))

        # Get 'running_nodes' from 'rabbitmqctl cluster_status' from all nodes
        all_out = self.execute_on_all_rabbit_nodes(
            cmd=(self.cmd.rabbitmqctl.cluster_status +
                 self.bash_grep_running_nodes),
            may_fail=False)
        # Check that enabled host IN 'running_nodes'
        assert all(node_short_fqdn in out
                   for out in all_out), (
            "Output of command does not contain enabled rabbit nodes:\n"
            "{0}".format(all_out))

    # destructive
    @pytest.mark.testrail_id('1640533')
    def test_pcs_restart_cluster(self):
        """Tests Restart RabbitMQ cluster.

        Actions:
        1. Make restart RabbitMQ cluster by command:
        'pcs resource restart p_rabbitmq-server --wait=600'.
        2. Exit code should be 0.
        3. Control into console should return after the actual restart.
        """
        host = self.rabbit_nodes()[0]
        with host.ssh() as remote:
            remote.check_call(self.bash_pcs_restart_cluster)

        assert self.rabbit_cluster_is_ok(), (
            'Rabbit cluster is not in OK state')
