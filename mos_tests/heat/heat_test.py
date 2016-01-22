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

import os
from random import randint
import re
import time

import pytest

from mos_tests.functions.base import OpenStackTestCase
from mos_tests.functions import common as common_functions


@pytest.mark.undestructive
class HeatIntegrationTests(OpenStackTestCase):
    """Basic automated tests for OpenStack Heat verification."""

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

    def test_heat_resource_type_list(self):
        """This test case checks list of available Heat resources.

        Steps:
        1. Get list of Heat resources.
        2. Check count of resources.
        3. Check that list of resources contains required resources.
        """
        resource_types = [r.resource_type for r in
                          self.heat.resource_types.list()]
        self.assertEqual(len(resource_types), 96)

        required_resources = ["OS::Nova::Server", "AWS::EC2::Instance",
                              "DockerInc::Docker::Container",
                              "AWS::S3::Bucket"]

        for resource in required_resources:
            self.assertIn(resource, resource_types,
                          "Resource {0} not found!".format(resource))

    def test_heat_create_stack(self):
        """This test performs creation of a new stack with
            a help of Heat. And then delete it.

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
        file_name = './mos_tests/heat/templates/empty_heat_template_v2.yaml'
        # Like: 'Test_1449484927'
        new_stack_name = 'Test_{0}'.format(str(time.time())[0:10:])
        # - 1 -
        # Read Heat stack-create template from file
        try:
            with open(file_name, 'r') as template:
                template_content = template.read()
        except IOError:
            raise Exception("ERROR: can not find template-file [{0}]"
                            "on controller or read data".format(file_name))
        # - 2 -
        # Create new stack
        uid_of_new_stack = common_functions.create_stack(self.heat,
                                                         new_stack_name,
                                                         template_content)
        self.uid_list.append(uid_of_new_stack)

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

    def test_heat_stack_template_show(self):
        """This test case checks representation of template of created stack.

        Steps:
        1. Create stack using template file empty_heat_templ.yaml.
        2. Check that template of created stack has correct \
        representation.
        """
        stack_name = 'empty_stack'
        timeout = 60
        parameter = "some_string"
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
                                                            'CREATE_COMPLETE'))
        stack_dict = {s.stack_name: s.id for s in self.heat.stacks.list()}
        stack_id = stack_dict[stack_name]
        stack_template = self.heat.stacks.template(stack_id)
        self.assertIsInstance(stack_template, dict)

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
        event_to_show = even_list[-1]
        resource_name, event_id = event_to_show.resource_name, event_to_show.id
        event_info = self.heat.events.get(stack_id, resource_name, event_id)
        self.assertEqual(event_info.resource_name, stack_name,
                         "Expected resource name: {0}, actual: {1}"
                         .format(event_info.resource_name, stack_id))
        self.assertEqual(event_info.resource_status, stack_status,
                         "Expected resource status: {0}, actual: {1}"
                         .format(event_info.resource_status, stack_status))
        common_functions.delete_stack(self.heat, stack_id)

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

    def test_heat_stack_preview(self):
        """This test case previews a stack.

        Steps:
        1. Execute stack preview.
        2. Check output result.
        """
        stack_name = 'empty__543332'
        parameter = 'some_param_string'
        parameters = {'OS::project_id': self.keystone.auth_tenant_id,
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
        try:
            create_template = common_functions.read_template(
                self.templates_dir, template_name)
            sid = common_functions.create_stack(
                self.heat, stack_name, create_template)
            self.uid_list.append(sid)
            first_resource_id = common_functions.get_resource_id(
                self.heat, sid)
            format_change = {'disk_format': 'ami', 'container_format': 'ami'}
            common_functions.update_template_file(
                template_path, 'format', **format_change)
            update_template = common_functions.read_template(
                self.templates_dir, template_name)
            common_functions.update_stack(self.heat, sid, update_template)
            second_resource_id = common_functions.get_resource_id(
                self.heat, sid)
            self.assertNotEqual(first_resource_id, second_resource_id,
                                msg='Resource id should be changed'
                                    ' after modifying stack')
        finally:
            back_format_change = {'disk_format': 'qcow2',
                                  'container_format': 'bare'}
            common_functions.update_template_file(
                template_path, 'format', **back_format_change)

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
            self.assertEqual(first_resource_id, second_resource_id,
                                msg='Resource id should not be changed'
                                    ' after modifying stack')
        finally:
            common_functions.delete_stack(self.heat, sid)
            back_flavor_change = {'flavor': 'm1.tiny'}
            common_functions.update_template_file(template_path, 'flavor',
                                                  **back_flavor_change)

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
        parameters = {'OS::project_id': self.keystone.auth_tenant_id,
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
        instance_type = 'm1.tiny'

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
                      'InstanceType': 'm1.small'}
        d_updated = {'stack_name': stack_name, 'template': template_content,
                     'parameters': upd_params}
        self.heat.stacks.update(stack_id, **d_updated)

        # Perform cancel-update operation
        # when stack status is 'UPDATE_IN_PROGRESS'
        timeout = time.time() + 60
        while True:
            status = self.heat.stacks.get(stack_id).to_dict()['stack_status']
            if status == 'UPDATE_IN_PROGRESS':
                self.heat.actions.cancel_update(stack_id)
                break
            elif time.time() > timeout:
                raise AttributeError(
                    "Unable to find stack in 'UPDATE_IN_PROGRESS' state. "
                    "Status '{0}' doesn't allow to perform cancel-update"
                    .format(status))
            else:
                time.sleep(1)

        # Wait for rollback competed and check
        self.assertTrue(common_functions.check_stack_status
                        (stack_name, self.heat, "ROLLBACK_COMPLETE", 120))

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

        file_name = 'fedora_22-docker-image.qcow2.txt'
        image_name = '543346_Fedora-docker' + '_' + str(randint(100, 10000))

        # Prepare full path to image file. Return e.g.
        # like: /root/mos_tests/heat/images/fedora_22-docker-image.qcow2.txt
        image_link_location = os.path.join(self.images_dir, file_name)

        # Download image on node. Like: /tmp/fedora-software-config.qcow2
        image_path = common_functions.download_image(image_link_location)

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
                                             'timeout': 600},
                                            15)

        # Get resource ID of 'docker_server'. We know this name from template
        instance_id = self.heat.resources.get(uid, 'docker_server').to_dict()
        instance_id = instance_id['physical_resource_id']

        # Get public floating IP of created server instance in stack
        floating_ip_list = self.nova.floating_ips.list()
        floating_ip = [x.ip for x in floating_ip_list
                       if x.instance_id == instance_id]
        floating_ip = floating_ip[0]

        # Check that floating IP is not empty
        self.assertIsNotNone(
            floating_ip,
            'ERROR: Floating IP of Docker host instance is empty')

        # Read template for Docker stack creation
        template = common_functions.read_template(
            self.templates_dir,
            'Heat_Docker_Resources_543346_docker.yaml')

        # Before creating new docker stack give a few second too start
        # Docker bind in first stack. We have a WaitCondition in it, but
        # anyway there may be a need to wait several seconds.
        time.sleep(5)

        # Prepare docker endpoint. Like: 'tcp://172.16.0.161:2376'
        # Where IP is a floating IP of host instance. And port# is in template.
        docker_endpoint = 'tcp://{0}:2376'.format(floating_ip)

        # Create Docker stack
        docker_uid = \
            common_functions.create_stack(self.heat,
                                          'Heat_Docker_543346_docker',
                                          template,
                                          {'docker_endpoint': docker_endpoint},
                                          15)
        # CLEANUP
        # First we need to delete second docker stack
        common_functions.delete_stack(self.heat, docker_uid)
        # Delete host stack with tearDown:
        self.uid_list.append(uid)
        # Delete image:
        self.glance.images.delete(image.id)
        # Delete keypair:
        keypair.delete()
