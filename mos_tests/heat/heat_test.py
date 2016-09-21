#    Copyright 2015 Mirantis, Inc.
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
import os
from random import randint
import re
from shutil import copyfile
import time

import pytest

from mos_tests.functions.base import OpenStackTestCase
from mos_tests.functions import common as common_functions
from mos_tests.functions import file_cache
from mos_tests import settings

from keystoneclient.v3 import Client as KeystoneClientV3

logger = logging.getLogger(__name__)


@pytest.mark.undestructive
class HeatIntegrationTests(OpenStackTestCase):
    """Basic automated tests for OpenStack Heat verification."""

    heat_tmp_file_dir = '/tmp/'
    heat_tmp_file_mask = 'heat_'

    def setUp(self):
        super(self.__class__, self).setUp()
        # Get path on node to 'templates' dir
        self.templates_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'templates')
        # Get path on node to 'images' dir
        self.images_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'images')

        self.uid_list = []

    def tearDown(self):
        for stack_uid in self.uid_list:
            common_functions.delete_stack(self.heat, stack_uid)
        self.uid_list = []
        # clean tmp files
        os.system("rm -rf {0}{1}*".format(self.heat_tmp_file_dir,
                                          self.heat_tmp_file_mask))

    @pytest.mark.testrail_id('631860')
    def test_heat_resource_type_list(self):
        """This test case checks list of available Heat resources.

        Steps:
        1. Get list of Heat resources.
        2. Check count of resources.
        3. Check that list of resources contains required resources.
        """
        resource_types = [r.resource_type for r in
                          self.heat.resource_types.list()]
        required_resources = ["OS::Nova::Server", "AWS::EC2::Instance",
                              "DockerInc::Docker::Container",
                              "AWS::S3::Bucket"]

        self.assertGreaterEqual(len(resource_types), len(required_resources))

        for resource in required_resources:
            self.assertIn(resource, resource_types,
                          "Resource {0} not found!".format(resource))

    @pytest.mark.testrail_id('631878')
    def test_heat_create_stack(self):
        """This test performs creation of a new stack with Heat.
        After that it will be deleted.

        Steps:
        1. Read template from URL
        2. Create new stack. \
        Check that stack became from \
        'CREATE_IN_PROGRESS' --> 'CREATE_COMPLETE'
        3. Delete created stack \
        Check that stack became from \
        'DELETE_IN_PROGRESS' --> 'DELETE_COMPLETE'

        """
        # Be sure that this template file will be put on
        # controller during test preparation
        # File with template for stack creation
        # Like: 'Test_1449484927'
        new_stack_name = 'Test_{0}'.format(str(time.time())[0:10:])
        # - 1 -
        # Read Heat stack-create template from file
        template = common_functions.read_template(
            self.templates_dir, 'empty_heat_template_v2.yaml')
        # - 2 -
        # Create new stack
        uid_of_new_stack = common_functions.create_stack(self.heat,
                                                         new_stack_name,
                                                         template)
        self.uid_list.append(uid_of_new_stack)

    @pytest.mark.testrail_id('631868')
    def test_heat_stack_update(self):
        """This test case checks stack-update action.
        Steps:
        1. Create stack using template file empty_heat_templ.yaml
        2. Update stack parameter
        """
        stack_name = 'empty_543337'
        template_content = common_functions.read_template(
            self.templates_dir, 'empty_heat_templ.yaml')
        stack_id = common_functions.create_stack(self.heat, stack_name,
                                                 template_content,
                                                 {'param': 'string'})
        self.uid_list.append(stack_id)
        d_updated = {'stack_name': stack_name, 'template': template_content,
                     'parameters': {'param': 'string2'}}
        self.heat.stacks.update(stack_id, **d_updated)
        timeout = time.time() + 10
        while True:
            stack_dict_upd = {s.stack_name: s.id for s in
                              self.heat.stacks.list()
                              if s.stack_status == 'UPDATE_COMPLETE'}
            if stack_name in stack_dict_upd.keys():
                break
            elif time.time() > timeout:
                raise AssertionError("Unable to find stack 'empty' in "
                                     "'UPDATE_COMPLETE' state")
            else:
                time.sleep(1)

    @pytest.mark.testrail_id('844925')
    def test_heat_immutabel_parameter(self):
        """This test case checks stack-update action.
        Steps:
        1. Create stack using template file heat_immutable.yaml
        2. Try to update stack parameter
        """
        # Create new stack with immutabel parameter. Can't update this param.
        stack_name = 'heat-stack-' + str(randint(1, 0x7fffffff))
        template_content = common_functions.read_template(
            self.templates_dir, 'heat_immutable.yaml')
        stack_id = common_functions.create_stack(self.heat,
                                                 stack_name,
                                                 template_content,
                                                 {'param': 'string'})
        self.uid_list.append(stack_id)

        stack_updated = {'stack_name': stack_name,
                         'template': template_content,
                         'parameters': {'param': 'string2'}}
        with pytest.raises(Exception) as exc:
            self.heat.stacks.update(stack_id, **stack_updated)

        expected_err_msg = ('ERROR: The following parameters are '
                            'immutable and may not be updated: param')
        err_msg = str(exc.value)
        self.assertEqual(expected_err_msg, err_msg)

    @pytest.mark.testrail_id('844930')
    def test_heat_sub_net_pool(self):
        """This test case checks stack-create action.

        Steps:
        1. Create stack using template file heat_region.yaml
        2. Find stack parameter on keystone region list
        """
        timeout = 20
        pool_name = 'SubPool'
        stack_name = 'heat-stack-' + str(randint(1, 0x7fffffff))
        template_content = common_functions.read_template(
            self.templates_dir, 'heat_subnetpool.yaml')
        uid = common_functions.create_stack(self.heat, stack_name,
                                            template_content)

        self.uid_list.append(uid)
        stacks_id = [s.id for s in self.heat.stacks.list()]
        self.assertIn(uid, stacks_id)
        self.assertTrue(common_functions.check_stack_status(stack_name,
                                                            self.heat,
                                                            'CREATE_COMPLETE',
                                                            timeout))
        subnet_pools = self.neutron.list_subnetpools()
        subnet_pools_names = [x['name'] for x in subnet_pools['subnetpools']]
        self.assertIn(pool_name, subnet_pools_names)

    @pytest.mark.testrail_id('844933')
    def test_heat_sub_net(self):
        """This test case checks stack-create action.

        Steps:
        1. Create stack using template file heat_sub_net.yaml
        2. Find subnet on subnets list
        """
        timeout = 20
        pool_name = 'someSub'
        stack_name = 'heat-stack-' + str(randint(1, 0x7fffffff))
        template_content = common_functions.read_template(
            self.templates_dir, 'heat_sub_net.yaml')
        uid = common_functions.create_stack(self.heat, stack_name,
                                            template_content)

        self.uid_list.append(uid)
        stacks_id = [s.id for s in self.heat.stacks.list()]
        self.assertIn(uid, stacks_id)
        self.assertTrue(common_functions.check_stack_status(stack_name,
                                                            self.heat,
                                                            'CREATE_COMPLETE',
                                                            timeout))
        sub_net = self.neutron.list_subnets()
        sub_net_names = [x['name'] for x in sub_net['subnets']]
        self.assertIn(pool_name, sub_net_names)

    @pytest.mark.testrail_id('844932')
    def test_heat_address_scope(self):
        """This test case checks stack-create action.

        Steps:
        1. Create stack using template file heat_addres_scope.yaml
        2. Find address scope in some subnet pool
        """
        timeout = 20
        scope_name = 'someScope'
        stack_name = 'heat-stack-' + str(randint(1, 0x7fffffff))
        template_content = common_functions.read_template(
            self.templates_dir, 'heat_addres_scope.yaml')
        uid = common_functions.create_stack(self.heat, stack_name,
                                            template_content)

        self.uid_list.append(uid)
        stacks_id = [s.id for s in self.heat.stacks.list()]
        self.assertIn(uid, stacks_id)
        self.assertTrue(common_functions.check_stack_status(stack_name,
                                                            self.heat,
                                                            'CREATE_COMPLETE',
                                                            timeout))
        # Find scope in scope list
        list_scope = self.neutron.list_address_scopes()
        scopes_names = [x['name'] for x in list_scope['address_scopes']]
        scopes_id = [x['id'] for x in list_scope['address_scopes']]
        self.assertIn(scope_name, scopes_names)
        # Find scope in sub-pool list
        subnet_pools = self.neutron.list_subnetpools()
        id_in_subnet_pool = [x['address_scope_id']
                             for x in subnet_pools['subnetpools']]
        self.assertEqual(scopes_id, id_in_subnet_pool)

    @pytest.mark.testrail_id('631861')
    def test_heat_resource_type_show(self):
        """This test case checks representation of all Heat resources.

        Steps:
        1. Get list of Heat resources.
        2. Check that all types of resources have correct \
        representation.
        """
        resource_types = [r.resource_type for r in
                          self.heat.resource_types.list()]
        for resource in resource_types:
            resource_schema = self.heat.resource_types.get(resource)
            msg = "Schema of resource {0} is incorrect!"
            self.assertIsInstance(resource_schema, dict, msg.format(resource))

    @pytest.mark.testrail_id('631862')
    def test_heat_resource_type_template(self):
        """This test case checks representation of templates for all Heat
            resources.

        Steps:
        1. Get list of Heat resources.
        2. Check that templates for all resources have correct \
        representation.
        """
        resource_types = [r.resource_type for r in
                          self.heat.resource_types.list()]
        for resource in resource_types:
            schema = self.heat.resource_types.generate_template(resource)
            msg = "Schema of resource template {0} is incorrect!"
            self.assertIsInstance(schema, dict, msg.format(resource))

    @pytest.mark.testrail_id('631866')
    def test_heat_stack_delete(self):
        """This test case checks deletion of stack.

        Steps:
        1. Create stack using template file empty_heat_templ.yaml.
        2. Check that the stack is in the list of stacks
        3. Delete the stack.
        4. Check that the stack is absent in the list of stacks

        """
        stack_name = 'empty_543335'
        timeout = 20
        parameter = 'some_param_string'
        if common_functions.is_stack_exists(stack_name, self.heat):
            uid = common_functions.get_stack_id(self.heat, stack_name)
            common_functions.delete_stack(self.heat, uid)
        template = common_functions.read_template(
            self.templates_dir, 'empty_heat_templ.yaml')
        uid = common_functions.create_stack(self.heat, stack_name,
                                            template, timeout=timeout,
                                            parameters={'param': parameter})
        self.assertTrue(common_functions.check_stack_status(stack_name,
                                                            self.heat,
                                                            'CREATE_COMPLETE',
                                                            timeout))
        common_functions.delete_stack(self.heat, uid)
        stacks = [s.stack_name for s in self.heat.stacks.list()]
        self.assertNotIn(stack_name, stacks)

    @pytest.mark.testrail_id('631864')
    def test_heat_stack_create_with_template(self):
        """This test case checks creation of stack.

        Steps:
        1. Create stack using template file empty_heat_templ.yaml.
        2. Check that the stack is in the list of stacks
        3. Check that stack status is 'CREATE_COMPLETE'
        4. Delete stack
        """
        stack_name = 'empty__543333'
        parameter = 'some_param_string'
        timeout = 20
        if common_functions.is_stack_exists(stack_name, self.heat):
            uid = common_functions.get_stack_id(self.heat, stack_name)
            common_functions.delete_stack(self.heat, uid)
        template = common_functions.read_template(
            self.templates_dir, 'empty_heat_templ.yaml')
        uid = common_functions.create_stack(self.heat, stack_name,
                                            template, timeout=timeout,
                                            parameters={'param': parameter})
        self.uid_list.append(uid)
        stacks_id = [s.id for s in self.heat.stacks.list()]
        self.assertIn(uid, stacks_id)
        self.assertTrue(common_functions.check_stack_status(stack_name,
                                                            self.heat,
                                                            'CREATE_COMPLETE',
                                                            timeout))

    @pytest.mark.testrail_id('631865')
    def test_heat_stack_create_with_url(self):
        """This test case checks creation of stack using template URL.

        Steps:
        1. Create stack using template URL.
        2. Check that the stack is in the list of stacks
        3. Check that stack status is 'CREATE_COMPLETE'
        4. Delete stack
        """
        stack_name = 'empty__543334'
        template_url = 'https://raw.githubusercontent.com/tkuterina/' \
                       'mos-integration-tests/master/mos_tests/heat/' \
                       'templates/empty_heat_templ.yaml'
        timeout = 20
        if common_functions.is_stack_exists(stack_name, self.heat):
            uid = common_functions.get_stack_id(self.heat, stack_name)
            common_functions.delete_stack(self.heat, uid)
        stack_data = {'stack_name': stack_name, 'template_url': template_url,
                      'parameters': {'param': 'some_param_string'},
                      'timeout_mins': timeout}
        output = self.heat.stacks.create(**stack_data)
        stack_id = output['stack']['id']
        self.uid_list.append(stack_id)
        stacks_id = [s.id for s in self.heat.stacks.list()]
        self.assertIn(stack_id, stacks_id)
        self.assertTrue(common_functions.check_stack_status(stack_name,
                                                            self.heat,
                                                            'CREATE_COMPLETE',
                                                            timeout))

    @pytest.mark.testrail_id('631870')
    def test_check_stack_resources_statuses(self):
        """This test case checks that stack resources are in expected states
        Steps:
        1. Create new stack
        2. Launch heat action-check stack_name
        3. Launch heat stack-list and check 'CHECK_COMPLETE' status
        """
        stack_name = 'stack_to_check_543339'
        template_content = common_functions.read_template(
            self.templates_dir, 'empty_heat_templ.yaml')
        stack_id = common_functions.create_stack(self.heat, stack_name,
                                                 template_content,
                                                 {'param': 'just text'})
        self.uid_list.append(stack_id)
        self.heat.actions.check(stack_id)
        timeout = time.time() + 10
        while True:
            stack_dict = {s.stack_name: s.id for s in self.heat.stacks.list()
                          if s.stack_status == 'CHECK_COMPLETE'}
            if stack_name in stack_dict.keys():
                break
            elif time.time() > timeout:
                raise AssertionError(
                    "Stack {0} is not in CHECK_COMPLETE state".format(
                        stack_name))
            else:
                time.sleep(1)
        self.assertIn(stack_name, stack_dict,
                      "Stack {0} is not in CHECK_COMPLETE state".format(
                          stack_name))

    @pytest.mark.testrail_id('631872')
    def test_show_stack_event_list(self):
        """This test checks list events for a stack

        Steps:
        1. Create new stack
        2. Launch heat event-list stack_name
        """
        stack_name = 'stack_to_show_event_543341'
        template_content = common_functions.read_template(
            self.templates_dir, 'empty_heat_templ.yaml')
        stack_id = common_functions.create_stack(self.heat, stack_name,
                                                 template_content,
                                                 {'param': 'just text'})
        self.uid_list.append(stack_id)
        event_list = self.heat.events.list(stack_id)
        self.assertTrue(event_list, "NOK, event list is empty")
        resources = [event.resource_name for event in event_list]
        self.assertIn(stack_name, resources,
                      "Event list doesn't contain at least one event for {0}"
                      .format(stack_name))

    @pytest.mark.testrail_id('631875')
    def test_heat_stack_template_show(self):
        """This test case checks representation of template of created stack.

        Steps:
        1. Create stack using template file empty_heat_templ.yaml.
        2. Check that template of created stack has correct \
        representation.
        """
        stack_name = 'empty_stack'
        timeout = 20
        parameter = 'some_string'
        if common_functions.is_stack_exists(stack_name, self.heat):
            uid = common_functions.get_stack_id(self.heat, stack_name)
            common_functions.delete_stack(self.heat, uid)
        template = common_functions.read_template(
            self.templates_dir, 'empty_heat_templ.yaml')
        uid = common_functions.create_stack(self.heat, stack_name,
                                            template, timeout=timeout,
                                            parameters={'param': parameter})
        self.uid_list.append(uid)
        self.assertTrue(common_functions.check_stack_status(stack_name,
                                                            self.heat,
                                                            'CREATE_COMPLETE',
                                                            timeout))
        stack_template = self.heat.stacks.template(uid)
        self.assertIsInstance(stack_template, dict)

    @pytest.mark.testrail_id('631873')
    def test_show_info_of_specified_stack_event(self):
        """This test checks info about stack event

        Steps:
        1. Create new stack
        2. Launch heat event-list stack_name
        3. Launch heat event-show <NAME or ID> <RESOURCE> <EVENT> \
        for specified event and check result
        """
        stack_name = 'stack_to_show_event_info_543342'
        template_content = common_functions.read_template(
            self.templates_dir, 'empty_heat_templ.yaml')
        stack_id = common_functions.create_stack(self.heat, stack_name,
                                                 template_content,
                                                 {'param': 123})
        self.uid_list.append(stack_id)
        stack_status = self.heat.stacks.get(stack_id).to_dict()['stack_status']
        even_list = self.heat.events.list(stack_id)
        self.assertTrue(even_list, "NOK, event list is empty")
        event_to_show = even_list[0]
        resource_name, event_id = event_to_show.resource_name, event_to_show.id
        event_info = self.heat.events.get(stack_id, resource_name, event_id)
        self.assertEqual(event_info.resource_name, stack_name,
                         "Expected resource name: {0}, actual: {1}"
                         .format(event_info.resource_name, stack_id))
        self.assertEqual(event_info.resource_status, stack_status,
                         "Expected resource status: {0}, actual: {1}"
                         .format(event_info.resource_status, stack_status))
        common_functions.delete_stack(self.heat, stack_id)

    @pytest.mark.testrail_id('631876')
    def test_heat_create_stack_a_w_s(self):
        """This test creates stack using AWS format template

        Steps:
        1. Connect to Neutron and get ID of internal_network
        2. Get ID of external_network
        3. Get ID of internal_subnet of internal_network
        4. Find IP for internal_subnet
        5. Create stack
        6. Delete stack

        """
        # Prepare new name. Like: 'Test_1449484927'
        new_stack_name = 'Test_{0}'.format(str(time.time())[0:10:])

        # Get networks from Neutron
        networks = self.neutron.list_networks()

        # Check if Neutron has more then 1 network. We need intern and extern.
        if len(networks['networks']) < 2:
            raise AssertionError("ERROR: Need to have at least 2 networks")

        # - 1,2,3 -
        # Get IDs of networks
        network_1_id = networks['networks'][1]['id']
        network_1_subnet = networks['networks'][1]['subnets'][0]
        network_2_id = networks['networks'][0]['id']

        # - 4 -
        # Get list of occupied IPs in "network_1_id"
        neutron_list_ports = self.neutron.list_ports()['ports']
        occupied_ips = [x['fixed_ips'][0]['ip_address']
                        for x in neutron_list_ports
                        if network_1_subnet in x['fixed_ips'][0]['subnet_id']]

        # Cut last part of IPs: '192.168.111.3 --> 192.168.111._'
        ips_without_last_part = [".".join(x.split('.')[0:-1]) + '.'
                                 for x in occupied_ips]

        # Get unique IP without last part: '192.168.111._'
        seen = set()
        seen_add = seen.add
        ip_no_last_part = [x for x in ips_without_last_part
                           if not (x in seen or seen_add(x))]
        ip_no_last_part = ip_no_last_part[0]

        # Generate new IP and check that it is free
        internal_subnet_ip = ip_no_last_part + str(randint(100, 240))
        while internal_subnet_ip in occupied_ips:
            internal_subnet_ip = ip_no_last_part + str(randint(100, 240))

        # - 5 -
        # Prepare parameters
        parameters = {'internal_network': network_1_id,
                      'internal_subnet': network_1_subnet,
                      'internal_subnet_ip': internal_subnet_ip,
                      'external_network': network_2_id}

        # Read template
        template = common_functions.read_template(
            self.templates_dir, 'Heat_template_AWL_543345.yaml')

        # Create stack
        uid = common_functions.create_stack(self.heat,
                                            new_stack_name,
                                            template,
                                            parameters)
        self.uid_list.append(uid)

    @pytest.mark.testrail_id('631863')
    def test_heat_stack_preview(self):
        """This test case previews a stack.

        Steps:
        1. Execute stack preview.
        2. Check output result.
        """
        stack_name = 'empty__543332'
        parameter = 'some_param_string'
        parameters = {'OS::project_id': self.session.get_project_id(),
                      'OS::stack_id': 'None', 'OS::stack_name': stack_name,
                      'param': parameter}
        correct_data = {'description': 'Sample template',
                        'stack_name': stack_name,
                        'disable_rollback': True,
                        'template_description': 'Sample template',
                        'parameters': parameters}
        if common_functions.is_stack_exists(stack_name, self.heat):
            uid = common_functions.get_stack_id(self.heat, stack_name)
            common_functions.delete_stack(self.heat, uid)
        template = common_functions.read_template(
            self.templates_dir, 'empty_heat_templ.yaml')
        stack_data = {'stack_name': stack_name, 'template': template,
                      'parameters': {'param': parameter}}
        output = self.heat.stacks.preview(**stack_data)
        preview_data = {'description': output.description,
                        'stack_name': output.stack_name,
                        'disable_rollback': output.disable_rollback,
                        'template_description': output.template_description,
                        'parameters': output.parameters}
        self.assertDictEqual(preview_data, correct_data)
        self.assertEqual(len(output.links), 1)
        self.assertEqual(len(output.links[0]), 2)
        self.assertNotEqual(output.links[0]['href'].find(stack_name), -1)
        self.assertEqual(output.links[0]['rel'], 'self')

    @pytest.mark.testrail_id('631874')
    def test_heat_stack_template_validate(self):
        """This test case checks representation of template file.

        Steps:
        1. Check that selected template file has correct \
        representation.
        """
        template_content = common_functions.read_template(
            self.templates_dir, 'heat_create_nova_stack_template.yaml')
        template_data = {'template': template_content}
        result = self.heat.stacks.validate(**template_data)
        self.assertIsInstance(result, dict)

    @pytest.mark.testrail_id('631871')
    def test_stack_resume_suspend(self):
        """Suspend and resume stack
        (with its resources for which that feature works)

        Steps:
        1. Create new stack
        2. Launch heat action-suspend stack_name. Check status
        3. Launch heat action-resume stack_name. Check status
        """

        # Create stack with resource
        stack_name = 'stack_to_suspend_resume_543340'
        template_content = common_functions.read_template(
            self.templates_dir, 'resource_group_template.yaml')
        stack_id = common_functions.create_stack(self.heat, stack_name,
                                                 template_content)
        self.uid_list.append(stack_id)

        # Suspend stack, check statuses of stack and its resources
        self.heat.actions.suspend(stack_id)
        timeout = time.time() + 60
        while True:
            status = self.heat.stacks.get(stack_id).to_dict()['stack_status']
            if status == 'SUSPEND_COMPLETE':
                break
            elif time.time() > timeout:
                raise AssertionError(
                    "Unable to find stack in 'SUSPEND_COMPLETE' state")
            else:
                time.sleep(1)
        res = self.heat.resources.list(stack_id)
        res_states = {r.resource_name: r.resource_status for r in res}
        for name, status in res_states.items():
            self.assertEqual(status, 'SUSPEND_COMPLETE',
                             "Resource '{0}' has '{1}' "
                             "status instead of 'SUSPEND_COMPLETE'"
                             .format(name, status))

        # Resume stack, check statuses of stack and its resources
        self.heat.actions.resume(stack_id)
        timeout = time.time() + 60
        while True:
            status = self.heat.stacks.get(stack_id).to_dict()['stack_status']
            if status == 'RESUME_COMPLETE':
                break
            elif time.time() > timeout:
                raise AssertionError(
                    "Unable to find stack in 'RESUME_COMPLETE' state")
            else:
                time.sleep(1)
        res = self.heat.resources.list(stack_id)
        res_states = {r.resource_name: r.resource_status for r in res}
        for name, status in res_states.items():
            self.assertEqual(status, 'RESUME_COMPLETE',
                             "Resource '{0}' has '{1}' "
                             "status instead of 'RESUME_COMPLETE'"
                             .format(name, status))

    @pytest.mark.testrail_id('631882')
    def test_heat_stack_update_replace(self):
        """This test case checks change stack id after stack update.

        Steps:
        1. Create stack using template.
        2. Check id of created image.
        3. Update stack template:
        disk_format = 'ami',
        container_format = 'ami'
        4. Update stack.
        5. Check id of updated image.
        """
        stack_name = 'image_stack'
        template_name = 'cirros_image_tmpl.yaml'
        template_path = os.path.join(self.templates_dir, template_name)

        tmp_template_dir = self.heat_tmp_file_dir
        tmp_template_name = self.heat_tmp_file_mask + template_name
        tmp_template_path = os.path.join(tmp_template_dir, tmp_template_name)

        # copy template to be able to modify it
        copyfile(template_path, tmp_template_path)

        # create stack
        create_template = common_functions.read_template(
            tmp_template_dir, tmp_template_name)
        sid = common_functions.create_stack(
            self.heat, stack_name, create_template)
        self.uid_list.append(sid)

        # update stack template
        first_resource_id = common_functions.get_resource_id(
            self.heat, sid)
        format_change = {'disk_format': 'ami', 'container_format': 'ami'}
        common_functions.update_template_file(
            tmp_template_path, 'format', **format_change)
        update_template = common_functions.read_template(
            tmp_template_dir, tmp_template_name)

        # update stack
        common_functions.update_stack(self.heat, sid, update_template)
        second_resource_id = common_functions.get_resource_id(
            self.heat, sid)
        self.assertNotEqual(first_resource_id, second_resource_id,
                            msg='Resource id should be changed '
                                'after modifying stack')

    @pytest.mark.testrail_id('631883')
    def test_heat_stack_update_in_place(self):
        """This test case checks stack id doesn't change after stack update.

        Steps:
        1. Create stack using template nova_server.yaml.
        2. Check id of created image.
        3. Update stack template: flavor = 'm1.small'
        4. Update stack.
        5. Check id of updated image.
        """
        stack_name = 'vm_stack'
        template_name = 'nova_server.yaml'
        template_path = os.path.join(self.templates_dir, template_name)
        try:
            networks = self.neutron.list_networks()
            if len(networks['networks']) < 2:
                raise AssertionError("ERROR: Need to have at least 2 networks")
            internal_network_id = networks['networks'][1]['id']
            create_template = common_functions.read_template(
                self.templates_dir, template_name)
            parameters = {'network': internal_network_id}
            sid = common_functions.create_stack(self.heat, stack_name,
                                                create_template, parameters)
            first_resource_id = common_functions.get_specific_resource_id(
                self.heat, sid, 'vm')
            flavor_change = {'flavor': 'm1.small'}
            common_functions.update_template_file(template_path, 'flavor',
                                                  **flavor_change)
            update_template = common_functions.read_template(
                self.templates_dir, template_name)
            common_functions.update_stack(self.heat, sid, update_template,
                                          parameters)
            second_resource_id = common_functions.get_specific_resource_id(
                self.heat, sid, 'vm')
            self.assertEqual(
                first_resource_id, second_resource_id,
                msg='Resource id should not be changed after modifying stack')
        finally:
            common_functions.delete_stack(self.heat, sid)
            back_flavor_change = {'flavor': 'm1.tiny'}
            common_functions.update_template_file(template_path, 'flavor',
                                                  **back_flavor_change)

    @pytest.mark.testrail_id('631867')
    def test_heat_stack_show(self):
        """This test case checks detailed stack's information.

        Steps:
        1. Create stack using template file empty_heat_templ.yaml
        2. Check that the stack is in the list of stacks
        3. Check that stack status is 'CREATE_COMPLETE'
        4. Check stack's information
        5. Delete stack
        """
        stack_name = 'empty__543336'
        parameter = 'some_param_string'
        timeout = 20
        if common_functions.is_stack_exists(stack_name, self.heat):
            uid = common_functions.get_stack_id(self.heat, stack_name)
            common_functions.delete_stack(self.heat, uid)
        template = common_functions.read_template(
            self.templates_dir, 'empty_heat_templ.yaml')
        uid = common_functions.create_stack(self.heat, stack_name,
                                            template, timeout=timeout,
                                            parameters={'param': parameter})
        self.uid_list.append(uid)
        parameters = {'OS::project_id': self.session.get_project_id(),
                      'OS::stack_id': uid,
                      'OS::stack_name': stack_name,
                      'param': parameter}
        correct_data = {'description': 'Sample template',
                        'stack_name': stack_name,
                        'disable_rollback': True,
                        'template_description': 'Sample template',
                        'timeout_mins': timeout,
                        'stack_status': 'CREATE_COMPLETE',
                        'id': uid,
                        'stack_status_reason': 'Stack CREATE completed '
                                               'successfully',
                        'parameters': parameters}
        output = self.heat.stacks.get(uid)
        show_data = {'description': output.description,
                     'stack_name': output.stack_name,
                     'disable_rollback': output.disable_rollback,
                     'template_description': output.template_description,
                     'timeout_mins': output.timeout_mins,
                     'stack_status': output.stack_status,
                     'id': output.id,
                     'stack_status_reason': output.stack_status_reason,
                     'parameters': output.parameters}
        self.assertDictEqual(show_data, correct_data)
        self.assertEqual(len(output.links), 1)
        self.assertEqual(len(output.links[0]), 2)
        self.assertNotEqual(output.links[0]['href'].find(stack_name), -1)
        self.assertEqual(output.links[0]['rel'], 'self')

    @pytest.mark.testrail_id('631869')
    def test_stack_cancel_update(self):
        """This test check the possibility to cancel update

        Steps:
        1. Create new stack
        2. Launch heat action-suspend stack_name
        3. Launch heat stack-update stack_name
        4. Launch heat stack-cancel-update stack_name while update
        operation is in progress
        5. Check state of stack after cancel update
        """

        # network ID, image ID, InstanceType
        networks = self.neutron.list_networks()['networks']
        internal_net = [net['id'] for net in networks
                        if not net['router:external']][0]
        image_id = self.nova.images.list()[0].id
        instance_type = 'm1.small'

        # Stack creation
        stack_name = 'stack_to_cancel_update_543338'
        template_content = common_functions.read_template(
            self.templates_dir, 'heat_create_neutron_stack_template.yaml')
        initial_params = {'network': internal_net, 'ImageId': image_id,
                          'InstanceType': instance_type}
        stack_id = common_functions.create_stack(
            self.heat, stack_name, template_content, initial_params)
        self.uid_list.append(stack_id)

        # Stack update (from m1.tiny to m1.small)
        upd_params = {'network': internal_net, 'ImageId': image_id,
                      'InstanceType': 'm1.medium'}
        d_updated = {'stack_name': stack_name, 'template': template_content,
                     'parameters': upd_params}
        self.heat.stacks.update(stack_id, **d_updated)

        # Perform cancel-update operation
        # when stack status is 'UPDATE_IN_PROGRESS'
        common_functions.wait(
            lambda: self.heat.stacks.get(
                stack_id).stack_status == 'UPDATE_IN_PROGRESS',
            timeout_seconds=60,
            waiting_for="stack status to change to 'UPDATE_IN_PROGRESS'")

        self.heat.actions.cancel_update(stack_id)

        # Wait for rollback competed and check
        common_functions.wait(
            lambda: not self.heat.stacks.get(
                stack_id).stack_status.endswith('IN_PROGRESS'),
            timeout_seconds=3 * 60,
            waiting_for="stack status not to ends with 'IN_PROGRESS'")

        stack = self.heat.stacks.get(stack_id)
        self.assertEqual(stack.stack_status, 'ROLLBACK_COMPLETE')

    @pytest.mark.testrail_id('631884')
    def test_heat_stack_output_list(self):
        """This test case checks list of all stack attributes.

        Steps:
        1. Create stack using template.
        2. Check list of all attributes in format:
        output_key - description.
        """
        stack_name = 'random_str_stack'
        template_name = 'random_str.yaml'
        create_template = common_functions.read_template(
            self.templates_dir, template_name)
        sid = common_functions.create_stack(
            self.heat, stack_name, create_template)
        self.uid_list.append(sid)
        correct_attributes = [{'output_key': 'random_str1',
                               'description': 'The random string generated by'
                               ' resource random_str1'},
                              {'output_key': 'random_str2',
                               'description': 'The random string generated by'
                               ' resource random_str2'}]
        data = self.heat.stacks.get(stack_id=sid)
        outputs = data.to_dict()['outputs']
        stack_attributes = [{k: item[k] for k in
                            ('output_key', 'description')} for item in
                            outputs]
        self.assertEqual(stack_attributes, correct_attributes)

    @pytest.mark.testrail_id('631885')
    def test_heat_stack_output_show(self):
        """This test case checks value of specific attribute
            as well as list of all stack attributes.

        Steps:
        1. Create stack using template.
        2. Check value of attribute random_str1.
        3. Check list of all stack outputs (value, key and description)
        """
        stack_name = 'random_str_stack'
        template_name = 'random_str.yaml'
        create_template = common_functions.read_template(
            self.templates_dir, template_name)
        sid = common_functions.create_stack(
            self.heat, stack_name, create_template)
        self.uid_list.append(sid)
        data = self.heat.stacks.get(stack_id=sid)
        outputs = data.to_dict()['outputs']
        output_value = [item['output_value'] for item in outputs
                        if item['output_key'] == 'random_str1']
        for item in output_value:
            self.assertIsNotNone(re.match('^[a-zA-Z0-9]{32}$', item))
        correct_attributes = [{'output_key': 'random_str1',
                               'description': 'The random string generated by'
                               ' resource random_str1'},
                              {'output_key': 'random_str2',
                               'description': 'The random string generated by'
                               ' resource random_str2'}]
        stack_attributes = [{k: item[k] for k in item.keys()
                             if k != 'output_value'} for item in outputs]
        self.assertEqual(stack_attributes, correct_attributes)

    @pytest.mark.testrail_id('631879')
    def test_heat_create_stack_wait_condition(self):
        """This test creates stack with WaitCondition resources

        Steps:
        1. Download Cirros image
        2. Create image with Glance and check that it is 'Active'
        3. Create new key-pair with Nova
        4. Find ID of internal network with Neutron
        5. Create stack with WaitCondition and check that it was \
        created successfully
        6. CleanUp

        """
        file_name = 'cirros-0.3.4-x86_64-disk.img.txt'
        image_name = '543348_Cirros-image' + '_' + str(randint(100, 10000))

        # Prepare full path to image file. Return e.g.:
        # Like: /root/mos_tests/heat/images/cirros-0.3.4-x86_64-disk.img.txt
        image_link_location = os.path.join(self.images_dir, file_name)

        # Download image on node. Like: /tmp/cirros-0.3.4-x86_64-disk.img
        image_path = common_functions.download_image(image_link_location)

        # Create image in Glance
        image = self.glance.images.create(name=image_name,
                                          os_distro='Cirros',
                                          disk_format='qcow2',
                                          visibility='public',
                                          container_format='bare')
        # Check that status is 'queued'
        if image.status != 'queued':
            raise AssertionError("ERROR: Image status after creation is:"
                                 "[{0}]. "
                                 "Expected [queued]".format(image.status))

        # Put image-file in created Image
        with open(image_path, 'rb') as image_content:
            self.glance.images.upload(image.id, image_content)

        # Check that status of image is 'active'
        self.assertEqual(
            self.glance.images.get(image.id)['status'],
            'active',
            'After creation in Glance image status is [{0}]. '
            'Expected is [active]'
                .format(self.glance.images.get(image.id)['status']))

        # Create new keypair
        keypair = self.nova.keypairs.create(name=image_name)

        # Get list of networks
        networks = self.neutron.list_networks()

        # Find network ID if network name contains 'inter'
        int_network_id = [x['id'] for x in networks['networks']
                          if 'intern' in x['name']]

        # If can't find 'inter' in networks -> get ID of any network
        if not int_network_id:
            int_network_id = networks['networks'][-1]['id']
        else:
            int_network_id = int_network_id[0]

        # Create stack with Heat
        template = common_functions.read_template(
            self.templates_dir,
            'Heat_WaitCondition_543348.yaml')

        uid = common_functions.create_stack(self.heat,
                                            'Wait_Condition_Stack_543348',
                                            template,
                                            {'key_name': image_name,
                                             'image': image_name,
                                             'flavor': 'm1.small',
                                             'timeout': 600,  # 10 min
                                             'int_network_id': int_network_id},
                                            20)
        # CLEANUP
        # Delete stack with tearDown:
        self.uid_list.append(uid)
        # Delete image:
        self.glance.images.delete(image.id)
        # Delete keypair:
        keypair.delete()

    @pytest.mark.testrail_id('631880')
    def test_heat_create_stack_neutron_resources(self):
        """This test creates stack with Neutron resources

        Steps:
        1. Download Cirros image
        2. Create image with Glance and check that it is 'Active'
        3. Create new key-pair with Nova
        4. Find ID of internal network with Neutron
        5. Find ID of internal sub network with Neutron
        6. Find ID of public network with Neutron
        7. Create stack with Neutron resources and check that it was \
        created successfully
        8. CleanUp

        """
        file_name = 'cirros-0.3.4-x86_64-disk.img.txt'
        image_name = '543349_Cirros-image' + '_' + str(randint(100, 10000))

        # Prepare full path to image file. Return e.g.:
        # Like: /root/mos_tests/heat/images/cirros-0.3.4-x86_64-disk.img.txt
        image_link_location = os.path.join(self.images_dir, file_name)

        # Download image on node. Like: /tmp/cirros-0.3.4-x86_64-disk.img
        image_path = common_functions.download_image(image_link_location)

        # Create image in Glance
        image = self.glance.images.create(name=image_name,
                                          os_distro='Cirros',
                                          disk_format='qcow2',
                                          visibility='public',
                                          container_format='bare')
        # Check that status is 'queued'
        if image.status != 'queued':
            raise AssertionError("ERROR: Image status after creation is:"
                                 "[{0}]. "
                                 "Expected [queued]".format(image.status))

        # Put image-file in created Image
        with open(image_path, 'rb') as image_content:
            self.glance.images.upload(image.id, image_content)

        # Check that status of image is 'active'
        self.assertEqual(
            self.glance.images.get(image.id)['status'],
            'active',
            'After creation in Glance image status is [{0}]. '
            'Expected is [active]'
                .format(self.glance.images.get(image.id)['status']))

        # Create new keypair
        keypair = self.nova.keypairs.create(name=image_name)

        # Get list of networks
        networks = self.neutron.list_networks()

        # Check if Neutron has more then 1 network. We need intern and extern.
        if len(networks['networks']) < 2:
            raise AssertionError("ERROR: Need to have at least 2 networks")

        # Find internal network ID if network name contains 'inter'
        int_network_id = [x['id'] for x in networks['networks']
                          if 'intern' in x['name'] and
                          x['status'] == 'ACTIVE']
        # If can't find 'inter' in networks -> get ID of last network
        if not int_network_id:
            int_network_id = networks['networks'][-1]['id']
        else:
            int_network_id = int_network_id[0]

        # Find private subnet ID
        int_sub_network_id = [x['subnets'][0] for x in networks['networks']
                              if int_network_id in x['id'] and
                              x['status'] == 'ACTIVE']
        int_sub_network_id = int_sub_network_id[0]

        # Find public network ID
        pub_network_id = [x['id'] for x in networks['networks']
                          if 'float' in x['name'] and
                          x['status'] == 'ACTIVE']
        # If can't find 'float' in networks -> get ID of 0 network
        if not int_network_id:
            pub_network_id = networks['networks'][0]['id']
        else:
            pub_network_id = pub_network_id[0]

        # Create stack with Heat
        template = common_functions.read_template(
            self.templates_dir,
            'Heat_Neutron_resources_543349.yaml')

        uid = common_functions.create_stack(self.heat,
                                            'Heat_Neutron_resources_543349',
                                            template,
                                            {'key_name': image_name,
                                             'image': image_name,
                                             'flavor': 'm1.small',
                                             'public_net_id': pub_network_id,
                                             'private_net_id': int_network_id,
                                             'private_subnet_id':
                                                 int_sub_network_id},
                                            15)
        # CLEANUP
        # Delete stack with tearDown:
        self.uid_list.append(uid)
        # Delete image:
        self.glance.images.delete(image.id)
        # Delete keypair:
        keypair.delete()

    @pytest.mark.testrail_id('631881')
    def test_heat_create_stack_nova_resources(self):
        """This test creates stack with Nova resources

        Steps:
        1. Download Cirros image
        2. Create image with Glance and check that it is 'Active'
        3. Create new key-pair with Nova
        4. Find network ID
        5. Prepare template and reference template
        6. Create stack
        7. CleanUp

        """
        file_name = 'cirros-0.3.4-x86_64-disk.img.txt'
        image_name = '543350_Cirros-image' + '_' + str(randint(100, 10000))

        # Prepare full path to image file. Return e.g.:
        # Like: /root/mos_tests/heat/images/cirros-0.3.4-x86_64-disk.img.txt
        image_link_location = os.path.join(self.images_dir, file_name)

        # Download image on node. Like: /tmp/cirros-0.3.4-x86_64-disk.img
        image_path = common_functions.download_image(image_link_location)

        # Create image in Glance
        image = self.glance.images.create(name=image_name,
                                          os_distro='Cirros',
                                          disk_format='qcow2',
                                          visibility='public',
                                          container_format='bare')
        # Check that status is 'queued'
        if image.status != 'queued':
            raise AssertionError("ERROR: Image status after creation is:"
                                 "[{0}]. "
                                 "Expected [queued]".format(image.status))

        # Put image-file in created Image
        with open(image_path, 'rb') as image_content:
            self.glance.images.upload(image.id, image_content)

        # Check that status of image is 'active'
        self.assertEqual(
            self.glance.images.get(image.id)['status'],
            'active',
            'After creation in Glance image status is [{0}]. '
            'Expected is [active]'
                .format(self.glance.images.get(image.id)['status']))

        # Create new keypair
        keypair = self.nova.keypairs.create(name=image_name)

        # Get list of networks
        networks = self.neutron.list_networks()

        # Find internal network ID if network name contains 'inter'
        int_network_id = [x['id'] for x in networks['networks']
                          if 'intern' in x['name'] and
                          x['status'] == 'ACTIVE']
        # If can't find 'inter' in networks -> get ID of last network
        if not int_network_id:
            int_network_id = networks['networks'][-1]['id']
        else:
            int_network_id = int_network_id[0]

        # Read main template for creation
        template = common_functions.read_template(
            self.templates_dir,
            'Heat_Nova_resources_543350.yaml')

        # Read additional reference template for creation
        template_additional = common_functions.read_template(
            self.templates_dir,
            'Heat_Nova_resources_543350_volume_with_attachment.yaml')

        # Create stack
        uid = common_functions.create_stack(self.heat,
                                            'Heat_Nova_resources_543350',
                                            template,
                                            {'key_name': image_name,
                                             'image_id': image_name,
                                             'volume_size': 1,
                                             'num_volumes': 1,
                                             'flavor': 'm1.tiny',
                                             'network_id': int_network_id},
                                            15,
                                            {'Heat_Nova_resources_543350'
                                             '_volume_with_attachment.yaml':
                                                 template_additional})
        # CLEANUP
        # Delete stack with tearDown:
        self.uid_list.append(uid)
        # Delete image:
        self.glance.images.delete(image.id)
        # Delete keypair:
        keypair.delete()

    @pytest.mark.testrail_id('631877')
    def test_heat_create_stack_docker_resources(self):
        """This test creates stack with Docker resource

        Steps:
        1. Download custom Fedora image
        2. Create image in Glance and check status
        3. With Nova create new key-pair
        4. Find internal network ID
        5. Find name of public network
        6. Create stack with Docker host
        7. Get public floating IP of Docker host instance
        8. Prepare docker endpoint URL
        9. Create Docker stack
        10. CleanUp

        """
        # At first we need to check that heat has Docker resources
        # but it was already verified in "test_543328_HeatResourceTypeList".
        # So nothing to do here.

        image_name = '543346_Fedora-docker' + '_' + str(randint(100, 10000))

        # Create image in Glance
        image = self.glance.images.create(name=image_name,
                                          os_distro='Fedora',
                                          disk_format='qcow2',
                                          visibility='public',
                                          container_format='bare')
        # Check that status is 'queued'
        if image.status != 'queued':
            raise AssertionError("ERROR: Image status after creation is:"
                                 "[{0}]. "
                                 "Expected [queued]".format(image.status))

        # Put image-file in created Image
        with file_cache.get_file(settings.FEDORA_QCOW2_URL) as image_content:
            self.glance.images.upload(image.id, image_content)

        # Check that status of image is 'active'
        self.assertEqual(
            self.glance.images.get(image.id)['status'],
            'active',
            'After creation in Glance image status is [{0}]. '
            'Expected is [active]'
                .format(self.glance.images.get(image.id)['status']))

        # Create new keypair
        keypair = self.nova.keypairs.create(name=image_name)

        # Get list of networks
        networks = self.neutron.list_networks()

        # Find internal network ID if network name contains 'inter'
        int_network_id = [x['id'] for x in networks['networks']
                          if 'intern' in x['name'] and
                          x['status'] == 'ACTIVE']
        # If can't find 'inter' in networks -> get ID of last network
        if not int_network_id:
            int_network_id = networks['networks'][-1]['id']
        else:
            int_network_id = int_network_id[0]

        # Find name of public network
        pub_network_name = [x['name'] for x in networks['networks']
                            if 'float' in x['name'] or
                            'public' in x['name'] and
                            x['status'] == 'ACTIVE']
        # If can't find 'float/public' in networks -> get ID of first network
        if not pub_network_name:
            pub_network_name = pub_network_name['networks'][0]['name']
        else:
            pub_network_name = pub_network_name[0]

        # Read template for Docker host creation
        template = common_functions.read_template(
            self.templates_dir,
            'Heat_Docker_Resources_543346_Host.yaml')

        # Create stack for Docker host
        uid = common_functions.create_stack(self.heat,
                                            'Heat_Docker_543346_Host',
                                            template,
                                            {'key': image_name,
                                             'flavor': 'm1.small',
                                             'image': image_name,
                                             'public_net': pub_network_name,
                                             'int_network_id': int_network_id,
                                             'timeout': 600}, 15)

        # Get resource ID of 'docker_server'. We know this name from template
        instance = self.heat.resources.get(uid, 'docker_server')

        # Get public floating IP of created server instance in stack
        addresses = {x['OS-EXT-IPS:type']: x['addr']
                     for y in instance.attributes['addresses'].values()
                     for x in y}
        floating_ip = addresses['floating']

        # Before creating new docker stack give a few second too start
        # Docker bind in first stack. We have a WaitCondition in it, but
        # anyway there may be a need to wait several seconds.
        time.sleep(5)

        # Read template for Docker stack creation
        template = common_functions.read_template(
            self.templates_dir,
            'Heat_Docker_Resources_543346_docker.yaml')

        # Prepare docker endpoint. Like: 'tcp://172.16.0.161:2376'
        # Where IP is a floating IP of host instance. And port# is in template.
        docker_endpoint = 'tcp://{0}:2376'.format(floating_ip)

        # Create Docker stack
        docker_uid = common_functions.create_stack(
            self.heat, 'Heat_Docker_543346_docker', template,
            {'docker_endpoint': docker_endpoint}, 15)
        # CLEANUP
        # First we need to delete second docker stack
        common_functions.delete_stack(self.heat, docker_uid)
        # Delete host stack with tearDown:
        self.uid_list.append(uid)
        # Delete image:
        self.glance.images.delete(image.id)
        # Delete keypair:
        keypair.delete()

    @pytest.mark.testrail_id('844927')
    def test_check_search_for_resources_based_name(self):
        """This test case checks resource-list searched for resources based
        name
        Steps:
        1. Create new stack by sample template
        2. Launch heat resource-list and specify stack name
        """
        stack_name = 'stack_search_by_name'
        resource_name = 'new_resource'
        template_content = common_functions.read_template(
            self.templates_dir, 'sample_tmpl.yaml')
        stack_id = common_functions.create_stack(
            self.heat, stack_name, template_content, {'param': 'just text'})
        self.uid_list.append(stack_id)
        resources = self.heat.resources.list(stack_name, name=resource_name)
        assert len(resources) == 1
        resource = resources[0]
        assert resource.stack_name == stack_name
        assert resource.resource_status == 'CREATE_COMPLETE'
        assert resource.resource_name == resource_name

    @pytest.mark.testrail_id('844929')
    def test_check_search_for_resources_based_id(self):
        """This test case checks resource-list searched for resources based id
        Steps:
        1. Create new stack by sample template
        2. Launch heat resource-list and specify stack id
        """
        stack_name = 'stack_search_by_id'
        resource_name = 'new_resource'
        template_content = common_functions.read_template(
            self.templates_dir, 'sample_tmpl.yaml')
        stack_id = common_functions.create_stack(
            self.heat, stack_name, template_content, {'param': 'just text'})
        self.uid_list.append(stack_id)
        physical_resource_id = self.heat.resources.get(
            stack_id, resource_name).physical_resource_id

        resources = self.heat.resources.list(
            stack_name, physical_resource_id=physical_resource_id)
        assert len(resources) == 1
        resource = resources[0]
        assert resource.stack_name == stack_name
        assert resource.resource_status == 'CREATE_COMPLETE'
        assert resource.resource_name == resource_name

    @pytest.mark.testrail_id('844928')
    def test_check_search_for_resources_based_status(self):
        """This test case checks resource-list searched for resources based
        status
        Steps:
        1. Create new stack by sample template
        2. Launch heat resource-list and specify stack name and status
        """
        stack_name = 'stack_search_by_status'
        template_content = common_functions.read_template(
            self.templates_dir, 'sample_tmpl.yaml')
        stack_id = common_functions.create_stack(
            self.heat, stack_name, template_content, {'param': 'just text'})
        self.uid_list.append(stack_id)

        resources = self.heat.resources.list(stack_name,
                                             status='CREATE_COMPLETE')
        assert len(resources) == 1
        resource = resources[0]
        assert resource.stack_name == stack_name
        assert resource.resource_status == 'CREATE_COMPLETE'
        assert resource.resource_name == 'new_resource'

    @pytest.mark.testrail_id('844923')
    def test_check_show_particular_stack_output(self):
        """This test case checks show only one particular stack output
        Steps:
        1. Create new stack by 'check_output_tmpl' template
        2. Launch heat output-show
        """
        stack_name = 'stack_show_particular_output'
        template_content = common_functions.read_template(
            self.templates_dir, 'check_output_tmpl.yaml')
        stack_id = common_functions.create_stack(
            self.heat, stack_name, template_content)
        self.uid_list.append(stack_id)

        for i in ('a', 'b'):
            resource = self.heat.stacks.output_show(
                stack_id, 'resource_id_{}'.format(i))
            err_msg = 'Output info is incorrect'
            assert resource['output']['output_value'] == i, err_msg
            description = 'ID of resource {}'.format(i)
            assert resource['output']['description'] == description, err_msg
        try:
            self.heat.stacks.output_show(stack_id, 'resource_id_c')
        except Exception as err:
            err_msg = 'Error message is incorrect'
            self.assertIn('Not found', err.message, err_msg)

    @pytest.mark.testrail_id('844943')
    def test_check_output_show_during_stack_creation(self):
        """This test case checks support output resolution during stack
        creation
        Steps:
        1. Create new stack by 'check_output_tmpl' template
        2. Launch heat output-show while stack is in 'CREATE_IN_PROGRESS' state
        """
        stack_name = 'stack_show_output'
        template_content = common_functions.read_template(
            self.templates_dir, 'check_output_tmpl.yaml')
        stack = self.heat.stacks.create(stack_name=stack_name,
                                        template=template_content,
                                        timeout_mins=20)
        stack_id = stack['stack']['id']
        self.uid_list.append(stack_id)

        resource = self.heat.stacks.output_show(stack_id, 'resource_id_a')
        assert self.heat.stacks.get(stack_id).stack_status == 'CREATE_IN_' \
                                                              'PROGRESS'
        err_msg = 'Output info is incorrect'
        assert resource['output']['output_value'] == 'a', err_msg
        assert resource['output']['description'] == 'ID of resource a', err_msg

        self.assertTrue(common_functions.check_stack_status(
            stack_name, self.heat, 'CREATE_COMPLETE', 300))

    @pytest.mark.testrail_id('844926')
    def test_check_property_user_data_update_policy(self):
        """This test case checks user_data_update_policy property applying
        Steps:
        1. Create new stack by 'userdata_tmpl.yaml' template with IGNORE policy
        2. Update stack with new userdata
        3. Check that vm's id isn't changed
        4. Create new stack by 'userdata_tmpl.yaml' template with REPLACE
        policy
        5. Update stack with new userdata
        6. Check that vm's id is changed
        """
        template_content = common_functions.read_template(
            self.templates_dir, 'userdata_tmpl.yaml')
        for policy in ('IGNORE', 'REPLACE'):
            stack_name = 'stack_user_data_update_policy_{}'.format(policy)

            stack_id = common_functions.create_stack(
                self.heat, stack_name, template_content, {
                    'user_data': 'data', 'update_policy': policy})
            self.uid_list.append(stack_id)
            vms = [vm for vm in self.nova.servers.list() if policy in vm.name]
            assert len(vms) == 1
            vm_id_before = vms[0].id

            stack_updated = {'stack_name': stack_name,
                             'template': template_content,
                             'parameters': {'user_data': 'new_data',
                                            'update_policy': policy}}
            self.heat.stacks.update(stack_id, **stack_updated)
            self.assertTrue(
                common_functions.check_stack_status(stack_name, self.heat,
                                                    'UPDATE_COMPLETE', 120))
            vms = [vm for vm in self.nova.servers.list() if policy in vm.name]
            vm_id_after = vms[0].id
            assert len(vms) == 1
            if policy == 'IGNORE':
                err_mes = 'Error: Instance id is changed after stack update'
                assert vm_id_after == vm_id_before, err_mes
            else:
                err_mes = "Error: Instance id isn't changed after stack update"
                assert vm_id_after != vm_id_before, err_mes

    @pytest.mark.testrail_id('844931')
    def test_check_rbac_policy_resource(self):
        """This test case checks OS::Neutron::RBACPolicy resource
        Steps:
        1. Create some net wit name: heat_net
        2. Create new stack by 'RBAC_Policy_tmpl.yaml' template
        3. Check that new RBAC policy is present in policies list with
        correct data
        """
        stack_name = 'stack_rbac_policy'
        net_id = self.create_network('heat_net')['network']['id']
        rbac_before = self.neutron.list_rbac_policies()['rbac_policies']

        template_content = common_functions.read_template(
            self.templates_dir, 'RBAC_Policy_tmpl.yaml')
        stack_id = common_functions.create_stack(
            self.heat, stack_name, template_content, {'net_id': net_id})
        self.uid_list.append(stack_id)

        rbac_after = self.neutron.list_rbac_policies()['rbac_policies']
        assert len(rbac_after) == len(rbac_before) + 1
        stack_rbac = [r for r in rbac_after if r not in rbac_before][0]
        assert stack_rbac['object_id'] == net_id
        assert stack_rbac['action'] == 'access_as_shared'
        self.delete_network(net_id)

    @pytest.mark.testrail_id('844924')
    def test_check_keystone_region_resource(self):
        """This test case checks OS::Keystone::Region resource
        Steps:
        1. Create new stack by 'keystone_region_tmpl.yaml' template
        2. Check that region is present in regions list with correct data
        """
        keystone_v3 = KeystoneClientV3(session=self.session)
        regions_before = keystone_v3.regions.list()
        stack_name = 'stack_keystone_region'
        region_id = '123456'
        template_content = common_functions.read_template(
            self.templates_dir, 'keystone_region_tmpl.yaml')
        stack_id = common_functions.create_stack(
            self.heat, stack_name, template_content, {'region_id': region_id})
        self.uid_list.append(stack_id)
        regions_after = keystone_v3.regions.list()
        assert len(regions_after) == len(regions_before) + 1
        stack_region = [r for r in regions_after if r not in regions_before][0]
        assert stack_region.id == region_id
        assert stack_region.enabled
