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
import re

import pytest

import noop_common


logger = logging.getLogger(__name__)


@pytest.mark.testrail_id('1681266')
def test_non_operational_env(env, new_env, admin_remote):
    """Test to check negative case: noop run while env is not operational

    Steps to reproduce:
    1. Reset env and wait for 'new' state of it
    2. Execute 'deploy noop'
    3. Check that command was not successful
    4. Check error message
    """
    nodes = ' '.join([str(node.id) for node in env.get_all_nodes()])
    cmd = "fuel2 env nodes deploy -e {0} -n {1} -f --noop"
    cmd_res = admin_remote.execute(cmd.format(env.id, nodes))
    assert not cmd_res.is_ok, (
        'Noop run of fuel tasks should be failed for non operational env')
    assert "400 Client Error: Bad Request for url: " in cmd_res.stderr_string
    assert re.findall(
        r"Deployment operation cannot be started. Nodes with uids (.*) "
        r"are not provisioned yet.", cmd_res.stderr_string)


@pytest.mark.testrail_id('1681268')
def test_all_tasks_run_after_error(env, admin_remote, remove_service,
                                   rename_role, nova_conf_on_cmpt):
    """Test to check that all tasks are executed after 'error' state of one of them

    Steps to reproduce:
    1. Delete 'p_heat-engine' service in order to have error for 'primary-heat'
    2. Make change in os config
    3. Rename keystone role
    4. Run 'fuel2 env nodes deploy' with --noop option
    5. Check that all messages are in result
    """
    p_ctrl = env.primary_controller
    node2, changes = nova_conf_on_cmpt
    msg1 = ("/Pcmk_resource[p_heat-engine]/ensure', u'message': "
            "u'current_value absent, should be present (noop)'")
    msg2 = ("Nova_config[{0}/{1}]/value', u'message': u'current_value {2}, "
            "should be False (noop)").format(*changes[0])
    msg3 = ("/Keystone_role[SwiftOperator]/ensure', u'message': "
            "u'current_value absent, should be present (noop)'")
    task = noop_common.run_noop_nodes_deploy(admin_remote, env,
                                             nodes=[p_ctrl, node2])
    cmd_res_error = admin_remote.execute(
        "fuel deployment-tasks --tid {0} --status error".format(task.id))
    assert "primary-heat" in cmd_res_error.stdout_string
    exp_messages = [(p_ctrl.id, msg1), (node2.id, msg2), (p_ctrl.id, msg3)]
    assert noop_common.are_messages_in_summary_results(admin_remote, task.id,
                                                       exp_messages)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681271')
def test_change_puppet_file_owner(env, admin_remote, puppet_file_new_owner):
    """Test to check the noop run feature for puppet file metadata

    Steps to reproduce:
    1. Change owner of /etc/logrotate.d/apache2
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node = puppet_file_new_owner['node']
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("u'message': u'current_value {0}, "
           "should be root (noop)'".format(puppet_file_new_owner['new_owner']))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681376')
def test_change_cinder_conf(env, admin_remote, cinder_conf):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = cinder_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg_tmpl = "Cinder_config[{0}/{1}]/value', u'message': u'current_value {2}"
    for change in changes:
        assert noop_common.is_message_in_summary_results(
            admin_remote, task.id, node.id, msg_tmpl.format(*change))


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681377')
def test_change_glance_conf(env, admin_remote, glance_api_conf):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = glance_api_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Glance_api_config[{0}/{1}]/value', u'message': "
           "u'current_value {2}, should be False".format(*changes[0]))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681378')
def test_change_keystone_conf(env, admin_remote, keystone_conf):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
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
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = neutron_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Neutron_config[{0}/{1}]/value', u'message': u'current_value "
           "[\"{2}\"], should be [\"keystone\"]").format(*changes[0])
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681380')
def test_change_nova_conf(env, admin_remote, nova_conf_on_ctrl):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = nova_conf_on_ctrl
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Nova_config[{0}/{1}]/value', u'message': u'current_value {2}, "
           "should be True (noop)").format(*changes[0])
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681381')
def test_change_swift_conf(env, admin_remote, swift_conf):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = swift_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Swift_config[{0}/{1}]/value', u'message': "
           "u'current_value {2}, should be swift_secret").format(*changes[0])
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681382')
def test_change_heat_conf(env, admin_remote, heat_conf):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
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
@pytest.mark.testrail_id('1681397')
@pytest.mark.check_env_('is_ceilometer_enabled')
def test_change_ceilometer_config(env, fuel, admin_remote, ceilometer_conf):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = ceilometer_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Ceilometer_config[{0}/{1}]/value', "
           "u'message': u'current_value [\"{2}\"], "
           "should be [\"/var/log/ceilometer\"] (noop)'".format(*changes[0]))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681398')
@pytest.mark.check_env_('is_ironic_enabled')
def test_change_ironic_config(env, fuel, admin_remote, ironic_conf):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = ironic_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Ironic_config[{0}/{1}]/value', u'message': u'current_value {2}, "
           "should be True".format(*changes[0]))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681399')
@pytest.mark.check_env_('is_murano_enabled')
def test_change_murano_config(env, fuel, admin_remote, murano_conf):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = murano_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Murano_config[{0}/{1}]/value', u'message': u'current_value {2}, "
           "should be True (noop)'".format(*changes[0]))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_sahara_enabled')
@pytest.mark.testrail_id('1681400')
def test_change_sahara_config(env, fuel, admin_remote, sahara_conf):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = sahara_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Sahara_config[{0}/{1}]/value', u'message': u'current_value {2}, "
           "should be nova (noop)'".format(*changes[0]))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681401')
def test_change_puppet_file_mod(env, admin_remote, puppet_file_new_mod):
    """Test to check the noop run feature for puppet file metadata

    Steps to reproduce:
    1. Change permissions of /etc/logrotate.d/apache2
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
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
@pytest.mark.testrail_id('1681495')
@pytest.mark.check_env_('is_ceilometer_enabled')
def test_change_aodh_config(env, admin_remote, aodh_conf):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = aodh_conf
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Aodh_config[{0}/{1}]/value', u'message': u'current_value {2}, "
           "should be True (noop)'".format(*changes[0]))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681496')
def test_change_nova_conf_on_compute(env, admin_remote, nova_conf_on_cmpt):
    """Test to check the noop run feature for os config file

    Steps to reproduce:
    1. Change parameter in target config file
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """
    node, changes = nova_conf_on_cmpt
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Nova_config[{0}/{1}]/value', u'message': u'current_value {2}, "
           "should be False (noop)").format(*changes[0])
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.testrail_id('1681730')
def test_changes_for_several_nodes(env, admin_remote, nova_conf_on_cmpt,
                                   delete_micro_flavor, puppet_file_new_mod):
    """Test to check the noop run for several nodes at the same time

    Steps to reproduce:
    1. Make different custom changes for different nodes
    2. Execute 'fuel2 env nodes deploy' with --noop
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data for all nodes
    """
    node1, changes = nova_conf_on_cmpt
    node2 = env.primary_controller
    node3 = puppet_file_new_mod['node']
    task = noop_common.run_noop_nodes_deploy(admin_remote, env,
                                             nodes=[node1, node2, node3])
    msg1 = ("Nova_config[{0}/{1}]/value', u'message': u'current_value {2}, "
            "should be False (noop)").format(*changes[0])
    msg2 = ("/Exec[create-m1.micro-flavor]/returns', u'message': "
            "u'current_value notrun, should be 0 (noop)'")
    msg3 = ("u'message': u'current_value {0}, "
            "should be 0644 (noop)'".format(puppet_file_new_mod['new_mod']))
    exp_messages = [(node1.id, msg1), (node2.id, msg2), (node3.id, msg3)]
    assert noop_common.are_messages_in_summary_results(admin_remote, task.id,
                                                       exp_messages)
