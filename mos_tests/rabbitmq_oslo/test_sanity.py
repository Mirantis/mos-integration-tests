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
import uuid

from mos_tests.functions.common import wait

logger = logging.getLogger(__name__)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.usefixtures('install_messaging_check_tool')
@pytest.mark.parametrize('message_type', ['message', 'event'])
def test_generator_and_consumer(check_tool, compute, controller, message_type):

    except_consume_messages = 10000
    topic = "{0}.test_generator_and_consumer_{1}".format(
        message_type,
        str(uuid.uuid4()))

    with controller.ssh() as remote:
        check_tool.generate_msg(
            remote=remote,
            num_of_msg_to_gen=except_consume_messages,
            topic=topic)

    with compute.ssh() as remote:
        actual_consume_messages = check_tool.consume_msg(
            remote=remote,
            infinite=False,
            topic=topic)

    assert actual_consume_messages == except_consume_messages, (
        "Consumed and generated number of messages is different [{0}/{1}]"
        "".format(actual_consume_messages, except_consume_messages))


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.usefixtures('install_messaging_check_tool')
@pytest.mark.parametrize('testing_type', ['normal', 'stress'])
def test_rpc_server_and_client(check_tool, compute, controller, testing_type):

    count_of_rpc_messages = 100

    topic = "event.test_rpc_server_and_client_{0}".format(
        str(uuid.uuid4()))

    with controller.ssh() as remote:
        check_tool.rpc_server_start(
            remote=remote)
        if testing_type == 'stress':
            check_tool.generate_msg(
                remote=remote,
                num_of_msg_to_gen=-1,
                topic=topic)

    with compute.ssh() as remote:
        check_tool.rpc_client_start(
            remote=remote)
        if testing_type == 'stress':
            check_tool.consume_msg(
                remote=remote,
                infinite=True,
                topic=topic)

        wait(lambda: check_tool.get_http_code(remote) != 000,
             timeout_seconds=60 * 3,
             sleep_seconds=30,
             waiting_for='wait for starting oslo.messaging-check-tool '
                         'RPC server/client app')

        for step in range(1, count_of_rpc_messages):
            response_status_code = check_tool.get_http_code(remote)
            assert 200 == response_status_code, (
                'Verify rabbitmq connection was failed | Step [%d/%d]' % (
                    step, count_of_rpc_messages))
