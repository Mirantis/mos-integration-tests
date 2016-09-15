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
@pytest.mark.testrail_id('1681271')
def test_change_puppet_file_owner(env, admin_remote, puppet_file_new_owner):
    node = puppet_file_new_owner['node']
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("u'message': u'current_value {0}, "
           "should be root (noop)'".format(puppet_file_new_owner['new_owner']))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681376')
def test_change_cinder_conf(env, admin_remote, cinder_conf):
    node, changes = cinder_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg_tmpl = "Cinder_config[{0}/{1}]/value', u'message': u'current_value {2}"
    for change in changes:
        assert noop_common.is_message_in_summary_results(
            admin_remote, task.id, node.id, msg_tmpl.format(*change))


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681377')
def test_change_glance_conf(env, admin_remote, glance_api_conf):
    node, changes = glance_api_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Glance_api_config[{0}/{1}]/value', u'message': "
           "u'current_value {2}, should be False".format(*changes[0]))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681378')
def test_change_keystone_conf(env, admin_remote, keystone_conf):
    node, changes = keystone_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    for change in changes:
        msg = ("Keystone_config[{0}/{1}]/value', "
               "u'message': u'current_value {2}").format(*change)
        assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                         node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681379')
def test_change_neutron_conf(env, admin_remote, neutron_conf):
    node, changes = neutron_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Neutron_config[{0}/{1}]/value', u'message': u'current_value "
           "[\"{2}\"], should be [\"keystone\"]").format(*changes[0])
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681380')
def test_change_nova_conf(env, admin_remote, nova_conf_on_ctrl):
    node, changes = nova_conf_on_ctrl
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Nova_config[{0}/{1}]/value', u'message': u'current_value {2}, "
           "should be True (noop)").format(*changes[0])
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681382')
def test_change_heat_conf(env, admin_remote, heat_conf):
    node, changes = heat_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Heat_config[{0}/{1}]/value', u'message': u'current_value {2}, "
           "should be True".format(*changes[0]))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681383')
def test_stop_service(env, admin_remote, stop_service):
    """Test to check the noop run feature for stopped service

    Steps to reproduce:
    1. Stop the service neutron-metadata-agent on controller
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """

    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    expected_message = ("/Service[neutron-metadata]/ensure', u'message': "
                        "u'current_value stopped, should be running (noop)")
    assert noop_common.is_message_in_summary_results(admin_remote,
                                                     task.id, node.id,
                                                     expected_message)


# destructive
@pytest.mark.testrail_id('1681385')
def test_remove_service(env, admin_remote, remove_service):
    """Test to check the noop run feature for removed service

    Steps to reproduce:
    1. Delete the service p_heat-engine on controller
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """

    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    expected_message = ("/Pcmk_resource[p_heat-engine]/ensure', u'message': "
                        "u'current_value absent, should be present (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote,
                                                     task.id, node.id,
                                                     expected_message)


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


# destructive
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


# destructive
@pytest.mark.testrail_id('1681390')
def test_remove_default_router(env, admin_remote, without_router):
    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Routers/Neutron_router[router04]/ensure', "
           "u'message': u'current_value absent, should be present (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681401')
def test_change_puppet_file_mod(env, admin_remote, puppet_file_new_mod):
    node = puppet_file_new_mod['node']
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("u'message': u'current_value {0}, "
           "should be 0644 (noop)'".format(puppet_file_new_mod['new_mod']))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


# destructive
@pytest.mark.testrail_id('1681480')
def test_delete_micro_flavor(env, admin_remote, delete_micro_flavor):
    """Test to check the noop run feature for deleted cirros image

    Steps to reproduce:
    1. Delete m1.micro-flavor
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """

    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    expected_message = ("/Exec[create-m1.micro-flavor]/returns', u'message': "
                        "u'current_value notrun, should be 0 (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote,
                                                     task.id, node.id,
                                                     expected_message)


# destructive
@pytest.mark.testrail_id('1681481')
def test_delete_cirros_image(env, admin_remote, delete_cirros_image):
    """Test to check the noop run feature for deleted cirros image

    Steps to reproduce:
    1. Delete the cirros image
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """

    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    expected_message = ("/Exec[upload_cirros_shell]/returns', u'message': "
                        "u'current_value notrun, should be 0 (noop)")
    assert noop_common.is_message_in_summary_results(admin_remote,
                                                     task.id, node.id,
                                                     expected_message)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681496')
def test_change_nova_conf_on_compute(env, admin_remote, nova_conf_on_cmpt):
    node, changes = nova_conf_on_cmpt
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Nova_config[{0}/{1}]/value', u'message': u'current_value {2}, "
           "should be False (noop)").format(*changes[0])
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)
