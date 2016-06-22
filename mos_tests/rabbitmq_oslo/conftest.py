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

from mos_tests.rabbitmq_oslo.utils import control


logger = logging.getLogger(__name__)


@pytest.fixture
def check_tool():
    return control.MessagingCheckTool()


@pytest.fixture
def rabbitmq(env):
    datached_rabbit = len(env.get_nodes_by_role('standalone-rabbitmq'))

    if datached_rabbit > 0:
        return control.RabbitMQWrapper(env=env, datached_rabbit=True)
    else:
        return control.RabbitMQWrapper(env=env, datached_rabbit=False)


@pytest.fixture
def controllers(env):
    return env.get_nodes_by_role('controller')


@pytest.fixture
def controller(controllers):
    return random.choice(controllers)


@pytest.fixture
def computes(env):
    return env.get_nodes_by_role('compute')


@pytest.fixture
def compute(computes):
    return random.choice(computes)


@pytest.fixture
def install_messaging_check_tool(check_tool, computes, controllers):
    roles = controllers + computes
    for host in roles:
        with host.ssh() as session:
            check_tool.install(remote=session)
            check_tool.configure_oslomessagingchecktool(remote=session)


@pytest.yield_fixture
def admin_remote(fuel):
    with fuel.ssh_admin() as remote:
        yield remote
