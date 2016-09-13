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

import noop_common


logger = logging.getLogger(__name__)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681386')
def test_rename_role(env, admin_remote, rename_role):
    """Test to check the noop run feature for renamed role

    Steps to reproduce:
    1. Rename role 'SwiftOperator'
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """

    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    expected_message = ("/Keystone_role[SwiftOperator]/ensure', u'message': "
                        "u'current_value absent, should be present (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote,
                                                     task.id, node.id,
                                                     expected_message)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681388')
def test_disable_user(env, admin_remote, disable_user):
    """Test to check the noop run feature for disabled user

    Steps to reproduce:
    1. Disable user 'glare'
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """

    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    expected_message = ("/Keystone_user[glare]/enabled', u'message': "
                        "u'current_value false, should be true (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote,
                                                     task.id, node.id,
                                                     expected_message)


@pytest.mark.testrail_id('1681389')
def test_delete_project(env, admin_remote, delete_project):
    """Test to check the noop run feature for deleted project

    Steps to reproduce:
    1. Delete project 'services'
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """

    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    expected_message = ("/Keystone_tenant[services]/ensure', u'message': "
                        "u'current_value absent, should be present (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote,
                                                     task.id, node.id,
                                                     expected_message)
