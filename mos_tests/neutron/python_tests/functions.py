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

from mos_tests.functions.common import gen_random_resource_name
from mos_tests.functions.common import wait


logger = logging.getLogger(__name__)


def ban_dhcp_agent(os_conn, env, node_to_ban, host, network_name=None,
                   wait_for_die=True, wait_for_rescheduling=True):
    """Ban DHCP agent and wait until agents rescheduling.

    Ban dhcp agent on same node as network placed and wait until agents
    rescheduling.

    :param node_to_ban: dhcp-agent host to ban
    :param host: host or ip of controller onto execute ban command
    :param network_name: name of network to determine node with dhcp agents
    :param wait_for_die: wait until dhcp-agent die
    :param wait_for_rescheduling: wait new dhcp-agent starts
    :returns: str, name of banned node
    """
    list_hosts_with_dhcp_agents = lambda: os_conn.list_all_neutron_agents(
        agent_type='dhcp', filter_attr='host')
    if network_name:
        network = os_conn.neutron.list_networks(
            name=network_name)['networks'][0]
        list_hosts_with_dhcp_agents = (
            lambda: os_conn.get_node_with_dhcp_for_network(
                network['id']))
    current_agents = list_hosts_with_dhcp_agents()

    # ban dhcp agent on provided node
    with env.get_ssh_to_node(host) as remote:
        remote.check_call(
            "pcs resource ban neutron-dhcp-agent {0}".format(
                node_to_ban))

    # Wait to die banned dhcp agent
    if wait_for_die:
        wait(
            lambda: (node_to_ban not in list_hosts_with_dhcp_agents()),
            timeout_seconds=60 * 3,
            sleep_seconds=(1, 60, 5),
            waiting_for='DHCP agent on {0} to ban'.format(node_to_ban))
    # Wait to reschedule dhcp agent
    if wait_for_rescheduling:
        wait(
            lambda: (set(list_hosts_with_dhcp_agents()) - set(current_agents)),
            timeout_seconds=60 * 3,
            sleep_seconds=(1, 60, 5),
            waiting_for="DHCP agent to reschedule")
    return node_to_ban


def check_neutron_logs(controllers_list, logs_path, logs_start_marker,
                       log_msg):
    """Check neutron log, search for ERRORS.

    Ban dhcp agent on same node as network placed and wait until agents
    rescheduling.

    :param controllers_list: list of controllers which we check logs on
    :param logs_path: path to the log file
    :param logs_start_marker: place where log of this test starts
    :param log_msg: message to search
    :returns: -
    """
    logger.debug("Verify that the error log is absent in {}".format(
        logs_path))
    for controller in controllers_list:
        with controller.ssh() as remote:
            with remote.open(logs_path) as f:
                # check only generated during the test logs
                lines = iter(f)
                for line in lines:
                    if logs_start_marker in line:
                        break
                for line in lines:
                    assert log_msg not in line


def mark_neutron_logs(controllers):
    """Mark logs to know which logs are generated during the test"""
    logs_path = "/var/log/neutron/server.log"
    logs_start_marker = gen_random_resource_name(
        prefix='neutron')

    for controller in controllers:
        with controller.ssh() as remote:
            remote.check_call("echo {0} >> {1}".format(logs_start_marker,
                                                       logs_path))
    return logs_path, logs_start_marker
