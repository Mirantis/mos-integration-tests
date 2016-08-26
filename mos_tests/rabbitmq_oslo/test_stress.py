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

from mos_tests.neutron.python_tests.base import TestBase
from mos_tests.rabbitmq_oslo.utils import BashCommand

logger = logging.getLogger(__name__)


class RabbitStressFunctions(TestBase):

    TIMEOUT = 500  # seconds

    @pytest.fixture(autouse=True)
    def tools(self, rabbitmq, check_tool):
        self.rabbitmq = rabbitmq
        self.oslo_tool = check_tool
        self.cmd = BashCommand

    def start_load_generator(self, msg_topic, rpc_topic):
        """Install oslo tool on 2 nodes, start rpc_server and rpc_client,
        launch infinite msg generation and consumption.

        :param msg_topic: Topic for messages for generation.
        :param rpc_topic: Topic for rpc server/client start.
        :return: Dict with roles and nodes.
        """
        controller = random.choice(self.env.get_nodes_by_role('controller'))
        compute = random.choice(self.env.get_nodes_by_role('compute'))

        with controller.ssh() as remote:
            self.oslo_tool.install(remote)
            self.oslo_tool.configure_oslomessagingchecktool(remote)
            self.oslo_tool.rpc_server_start(remote=remote, topic=rpc_topic)
            self.oslo_tool.generate_msg(
                remote=remote,
                num_of_msg_to_gen=-1,
                topic=msg_topic)

        with compute.ssh() as remote:
            self.oslo_tool.install(remote)
            self.oslo_tool.configure_oslomessagingchecktool(remote)
            self.oslo_tool.rpc_client_start(remote=remote, topic=rpc_topic)
            self.oslo_tool.consume_msg(
                remote=remote,
                infinite=True,
                topic=msg_topic)

            self.oslo_tool.wait_oslomessagingchecktool_is_ok(
                remote, timeout=self.TIMEOUT)
            assert self.oslo_tool.get_http_code(remote) == 200

        return {'generator': controller,
                'consumer': compute}


@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
class TestRabbitStress(RabbitStressFunctions):

    # messages
    @pytest.mark.testrail_id('1640512', params={
        'msg_type': 'message', 'role': 'master', 'stop_method': 'kill'})
    @pytest.mark.testrail_id('1640513', params={
        'msg_type': 'message', 'role': 'slave', 'stop_method': 'kill'})
    @pytest.mark.testrail_id('1640514', params={
        'msg_type': 'message', 'role': 'master', 'stop_method': 'ban'})
    @pytest.mark.testrail_id('1640515', params={
        'msg_type': 'message', 'role': 'slave', 'stop_method': 'ban'})
    # events
    @pytest.mark.testrail_id('1640516', params={
        'msg_type': 'event', 'role': 'master', 'stop_method': 'kill'})
    @pytest.mark.testrail_id('1640517', params={
        'msg_type': 'event', 'role': 'slave', 'stop_method': 'kill'})
    @pytest.mark.testrail_id('1640518', params={
        'msg_type': 'event', 'role': 'master', 'stop_method': 'ban'})
    @pytest.mark.testrail_id('1640519', params={
        'msg_type': 'event', 'role': 'slave', 'stop_method': 'ban'})
    # - - - -
    @pytest.mark.parametrize('msg_type', ['message', 'event'])
    @pytest.mark.parametrize('role', ['master', 'slave'])
    @pytest.mark.parametrize('stop_method', ['kill', 'ban'])
    def test_kill_ban_rabbit_on_node(self, msg_type, role, stop_method):
        """Stop/ban RabbitMQ master/slave node.

        Actions:
        1) Install oslo.messaging-check-tool on two nodes.
        2) Start RPC server oslo_msg_check_server from one of the controllers.
        3) Run oslo_msg_load_generator on infinity loop on the same controller.
        4) Start RPC client oslo_msg_check_client from one of the computes.
        5) Run oslo_msg_load_consumer on infinity loop from the same compute
        with 'event' or 'message' topic.
        6) Check that oslo.messaging-check-tool will return '200' for curl GET.
        7) Find RabbitMQ master/slave node and kill rabbitmq processes on it
        OR ban it with a peacemaker.
        8) Wait till RabbitMQ Cluster will recover. (Timeout 500 sec)
        9) Check that oslo.messaging-check-tool will return '200' for curl GET.
        """
        rand_num = random.randint(0, 10000)

        msg_topic = "{0}.stress_{1}_msg".format(msg_type, rand_num)
        rpc_topic = "{0}.stress_{1}_rpc".format(msg_type, rand_num)

        nodes = self.start_load_generator(msg_topic=msg_topic,
                                          rpc_topic=rpc_topic)

        # Get required rabbit node
        rabbit_node = self.rabbitmq.rabbit_node_by_role(role=role)

        # Stop selected rabbit node
        if stop_method == 'kill':
            self.rabbitmq.kill_rabbitmq_node(node=rabbit_node)
            self.rabbitmq.wait_rabbit_cluster_is_ok(timeout=500)
        elif stop_method == 'ban':
            self.rabbitmq.stop_rabbitmq_node(node=rabbit_node)
            self.rabbitmq.wait_rabbit_cluster_is_ok(
                timeout=500, exclude_node=rabbit_node)
        else:
            raise ValueError("No such stop_method: %s" % stop_method)

        # Check that master node has been changed
        if role == 'master' and stop_method == 'ban':
            new_master_fqdn = self.rabbitmq.nodes_list()['master'][0]
            assert rabbit_node.data['fqdn'] != new_master_fqdn, (
                "Master node has not been changed after stopping")

        # Check that RabbitMQ cluster recovered
        with nodes['consumer'].ssh() as remote:
            self.oslo_tool.wait_oslomessagingchecktool_is_ok(
                remote, timeout=self.TIMEOUT)
            assert self.oslo_tool.get_http_code(remote) == 200, (
                "HTTP code is not 200")
