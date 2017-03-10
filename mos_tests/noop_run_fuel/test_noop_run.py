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
    """Test to check noop run while env is not operational

    Steps to reproduce:
    1. Reset env and wait for 'new' state of it
    2. Execute 'deploy noop'
    3. Check that command is successfully launched
    """
    nodes = ' '.join([str(node.id) for node in env.get_all_nodes()])
    cmd = "fuel2 env nodes deploy -e {0} -n {1} -f --noop"
    cmd_res = admin_remote.execute(cmd.format(env.id, nodes))
    assert cmd_res.is_ok, (
        "It should be possible to run noop task for non operational env")
    assert re.search(
        r"Deployment task with id \d+ for the nodes .* "
        r"within the environment {0} has been started".format(env.id),
        cmd_res.stdout_string)


@pytest.mark.testrail_id('1683908')
def test_noop_run_second_time(env, admin_remote):
    """Test to check that it's not possible to run 2nd task

    Steps to reproduce:
    1. Run 'fuel2 env nodes deploy' task with --noop
    2. Run 'fuel2 env redeploy' without waiting for finish of 1st run
    3. Check error status of 2nd run
    """
    nodes_ids = ' '.join([str(node.id) for node in env.get_all_nodes()])
    cmd1 = "fuel2 env nodes deploy -e {0} -n {1} -f --noop"
    cmd2 = "fuel2 env redeploy --noop {0}"
    cmd_res1 = admin_remote.execute(cmd1.format(env.id, nodes_ids))
    assert cmd_res1.is_ok, "1st run of noop run should be OK"
    cmd_res2 = admin_remote.execute(cmd2.format(env.id))
    assert not cmd_res2.is_ok, (
        "It shouldn't be possible run task if at least on task is in progress")
    error_messages = [
        "400 Client Error: Bad Request for url: ",
        "Cannot perform the actions because there are another running tasks"]
    for error_message in error_messages:
        assert error_message in cmd_res2.stderr_string


@pytest.mark.testrail_id('1681268')
def test_all_tasks_run_after_error(env, admin_remote, remove_service,
                                   rename_role):
    """Test to check that all tasks are executed after 'error' state of one of them

    Steps to reproduce:
    1. Delete 'p_heat-engine' service in order to have error for 'primary-heat'
    2. Make change in os config
    3. Rename keystone role
    4. Run 'fuel2 env nodes deploy' with --noop option
    5. Check that all messages are in result
    """
    p_ctrl = env.primary_controller
    msg1 = ("/Pcmk_resource[p_heat-engine]/ensure', u'message': "
            "u'current_value absent, should be present (noop)'")
    msg3 = ("/Keystone_role[SwiftOperator]/ensure', u'message': "
            "u'current_value absent, should be present (noop)'")
    task = noop_common.run_noop_nodes_deploy(admin_remote, env,
                                             nodes=[p_ctrl])
    cmd_res_error = admin_remote.execute(
        "fuel deployment-tasks --tid {0} --status error".format(task.id))
    assert "primary-heat" in cmd_res_error.stdout_string
    exp_messages = [(p_ctrl.id, msg1), (p_ctrl.id, msg3)]
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
@pytest.mark.testrail_id('1681278')
def test_redeploy_whole_env(env, admin_remote, stop_service,
                            disable_user):
    """Test to check the noop run feature for changes in whole env

    Steps to reproduce:
    1. Stop the service neutron-metadata-agent on controller
    2. Modify nova config on compute
    3. Disable user 'glare'
    4. Execute 'fuel2 env redeploy --noop'
    5. Wait for task finishing
    6. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    7. Check that result contains the expected data
    """

    task = noop_common.run_noop_env_deploy(admin_remote, env,
                                           command='redeploy')

    expected_messages = []
    msg1 = ("/Service[neutron-metadata]/ensure', u'message': "
            "u'current_value stopped, should be running (noop)")
    for node in env.get_nodes_by_role('controller'):
        expected_messages.append((node.id, msg1))
    node3 = env.primary_controller
    msg3 = ("/Keystone_user[glare]/enabled', u'message': "
            "u'current_value false, should be true (noop)'")
    expected_messages.append((node3.id, msg3))
    assert noop_common.are_messages_in_summary_results(admin_remote, task.id,
                                                       expected_messages)


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

    nodes = env.get_nodes_by_role('controller')
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=nodes)
    msg = ("/Service[neutron-metadata]/ensure', u'message': "
           "u'current_value stopped, should be running (noop)")
    expected_messages = []
    for node in nodes:
        expected_messages.append((node.id, msg))
    assert noop_common.are_messages_in_summary_results(admin_remote, task.id,
                                                       expected_messages)


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
    msg = ("/Pcmk_resource[p_heat-engine]/ensure', u'message': "
           "u'current_value absent, should be present (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


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
    msg = ("/Keystone_role[SwiftOperator]/ensure', u'message': "
           "u'current_value absent, should be present (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


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
    msg = ("/Keystone_user[glare]/enabled', u'message': "
           "u'current_value false, should be true (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


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
    msg = ("/Keystone_tenant[services]/ensure', u'message': "
           "u'current_value absent, should be present (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


# destructive
@pytest.mark.testrail_id('1681390')
def test_remove_default_router(env, admin_remote, without_router):
    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Routers/Neutron_router[router04]/ensure', "
           "u'message': u'current_value absent, should be present (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


# destructive
@pytest.mark.testrail_id('1681391')
def test_clear_router_gateway(env, admin_remote, clear_router_gateway):
    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("Routers/Neutron_router[router04]/gateway_network_name', "
           "u'message': u'current_value , should be admin_floating_net "
           "(noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681392')
def test_rename_network(env, admin_remote, rename_network):
    """Test to check the noop run feature for renamed network

    Steps to reproduce:
    1. Rename admin_floating_net network
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """

    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("/Neutron_network[admin_floating_net]/ensure', u'message': "
           "u'current_value absent, should be present (noop)'")
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


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681469')
def test_custom_graph(env, admin_remote, puppet_file_new_owner):
    """Test to check the noop run feature for custom graph

    Steps to reproduce:
    1. Change owner of /etc/logrotate.d/apache2 on controller
    2. Create a custom graph by copying the default graph and upload it
    3. Execute 'fuel2 graph execute -t custom'
    4. Wait for task finishing
    5. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    6. Check that result contains the expected data
    7. Delete data for apache from custom graph
    8. Execute 'fuel2 graph execute -t custom'
    9. Wait for task finishing
    10. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    11. Check that result does not contains data
    """

    node = puppet_file_new_owner['node']
    # Custom graph = default
    noop_common.create_and_upload_custom_graph(admin_remote, env)
    task = noop_common.run_noop_graph_execute(admin_remote, env, nodes=[node],
                                              g_type='custom')
    msg = ("u'message': u'current_value {0}, "
           "should be root (noop)'".format(puppet_file_new_owner['new_owner']))
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)

    # Custom graph = default without data related to apache
    noop_common.create_and_upload_custom_graph(admin_remote, env,
                                               modify='delete_apache')
    task = noop_common.run_noop_graph_execute(admin_remote, env, nodes=[node],
                                              g_type='custom')
    assert not noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                         node.id, msg,
                                                         is_expected=False)


# destructive
@pytest.mark.testrail_id('1681480')
def test_delete_micro_flavor(env, admin_remote, delete_micro_flavor):
    """Test to check the noop run feature for deleted default flavor

    Steps to reproduce:
    1. Delete m1.micro-flavor
    2. Execute 'deploy noop'
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data
    """

    node = env.primary_controller
    task = noop_common.run_noop_nodes_deploy(admin_remote, env, nodes=[node])
    msg = ("/Exec[create-m1.micro-flavor]/returns', u'message': "
           "u'current_value notrun, should be 0 (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


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
    msg = ("Upload_cirros/Glance_image[TestVM]/ensure', "
           "u'message': u'current_value absent, should be present (noop)'")
    assert noop_common.is_message_in_summary_results(admin_remote, task.id,
                                                     node.id, msg)


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


@pytest.mark.skip(reason='amqp_durable_queues is deprecated in newton')
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
def test_changes_for_several_nodes(env, admin_remote,
                                   delete_micro_flavor, puppet_file_new_mod):
    """Test to check the noop run for several nodes at the same time

    Steps to reproduce:
    1. Make different custom changes for different nodes
    2. Execute 'fuel2 env nodes deploy' with --noop
    3. Wait for task finishing
    4. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    5. Check that result contains the expected data for all nodes
    """
    node2 = env.primary_controller
    node3 = puppet_file_new_mod['node']
    task = noop_common.run_noop_nodes_deploy(admin_remote, env,
                                             nodes=[node2, node3])
    msg2 = ("/Exec[create-m1.micro-flavor]/returns', u'message': "
            "u'current_value notrun, should be 0 (noop)'")
    msg3 = ("u'message': u'current_value {0}, "
            "should be 0644 (noop)'".format(puppet_file_new_mod['new_mod']))
    exp_messages = [(node2.id, msg2), (node3.id, msg3)]
    assert noop_common.are_messages_in_summary_results(admin_remote, task.id,
                                                       exp_messages)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1682405')
def test_default_graph(env, admin_remote,
                       glance_api_conf, puppet_file_new_owner):
    """Test to check the noop run feature for changes in whole env

    Steps to reproduce:
    1. Modify glance config on controller
    2. Modify nova config on compute
    3. Change owner of /etc/logrotate.d/apache2 on controller
    4. Execute 'fuel2 graph execute -t custom'
    5. Wait for task finishing
    6. Execute 'fuel deployment-tasks --tid <task_id> --include-summary'
    7. Check that result contains the expected data
    """

    nodes = []
    expected_messages = []

    node1, changes = glance_api_conf
    msg1 = ("Glance_api_config[{0}/{1}]/value', u'message': "
            "u'current_value {2}, should be False".format(*changes[0]))
    nodes.append(node1)
    expected_messages.append((node1.id, msg1))

    node3 = puppet_file_new_owner['node']
    msg4 = ("u'message': u'current_value {0}, should be root (noop)'".
            format(puppet_file_new_owner['new_owner']))
    nodes.append(node3)
    expected_messages.append((node3.id, msg4))

    task = noop_common.run_noop_graph_execute(admin_remote, env,
                                              nodes=nodes,
                                              g_type='default')
    assert noop_common.are_messages_in_summary_results(admin_remote, task.id,
                                                       expected_messages)
