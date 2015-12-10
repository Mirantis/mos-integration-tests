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
import time
import unittest
from heatclient.v1.client import Client as heat_client
from keystoneclient.v2_0 import client as keystone_client
from mos_tests.heat.functions import common as common_functions


class HeatIntegrationTests(unittest.TestCase):
    """ Basic automated tests for OpenStack Heat verification. """

    @classmethod
    def setUpClass(self):
        OS_AUTH_URL = os.environ.get('OS_AUTH_URL')
        OS_USERNAME = os.environ.get('OS_USERNAME')
        OS_PASSWORD = os.environ.get('OS_PASSWORD')
        OS_TENANT_NAME = os.environ.get('OS_TENANT_NAME')
        OS_PROJECT_NAME = os.environ.get('OS_PROJECT_NAME')

        keystone = keystone_client.Client(auth_url=OS_AUTH_URL,
                                          username=OS_USERNAME,
                                          password=OS_PASSWORD,
                                          tenat_name=OS_TENANT_NAME,
                                          project_name=OS_PROJECT_NAME)
        services = keystone.service_catalog
        heat_endpoint = services.url_for(service_type='orchestration',
                                         endpoint_type='internalURL')

        self.heat = heat_client(endpoint=heat_endpoint,
                                token=keystone.auth_token)

        self.templates_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'templates')

    def read_template(self, template_name):
        """Read template file and return it content.

        :param template_name: name of template,
            for ex.: empty_heat_template.yaml
        :return: template file content
        """
        template_path = os.path.join(self.templates_dir, template_name)
        try:
            with open(template_path) as template:
                return template.read()
        except IOError as e:
            raise IOError('Can\'t read template: {}'.format(e))

    def test_543328_HeatResourceTypeList(self):
        """ This test case checks list of available Heat resources.

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

    def test_543347_HeatCreateStack(self):
        """ This test performs creation of a new stack with
            a help of Heat. And then delete it.

            Steps:
                1. Read template from URL
                2. Create new stack.
                    + Check that stack became from
                      'CREATE_IN_PROGRESS' --> 'CREATE_COMPLETE'
                3. Delete created stack
                    + Check that stack became from
                      'DELETE_IN_PROGRESS' --> 'DELETE_COMPLETE'

        https://mirantis.testrail.com/index.php?/cases/view/543347
        [Alexander Koryagin]
        """
        # Be sure that this template file will be put on
        # controller during test preparation

        # File with template for stack creation
        file_name = './mos_tests/heat/templates/stack_create_template.yaml'
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

        # - 3 -
        # Delete created stack
        common_functions.delete_stack(self.heat, uid_of_new_stack)

    def test_543337_HeatStackUpdate(self):
        """ This test case checks stack-update action.
            Steps:
            1. Create stack using template file empty_heat_templ.yaml
            2. Update stack parameter
        """
        stack_name = 'empty_543337'
        template_content = self.read_template('empty_heat_templ.yaml')
        stack_id = common_functions.create_stack(self.heat, stack_name,
                                                 template_content,
                                                 {'param': 'string'})
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
        common_functions.delete_stack(self.heat, stack_id)

    def test_543329_HeatResourceTypeShow(self):
        """ This test case checks representation of all Heat resources.

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

    def test_543330_HeatResourceTypeTemplate(self):
        """ This test case checks representation of templates for all Heat
            resources.

            Steps:
                1. Get list of Heat resources.
                2. Check that templates for all resources have correct
                    representation.
        """
        resource_types = [r.resource_type for r in
                          self.heat.resource_types.list()]

        for resource in resource_types:
            schema = self.heat.resource_types.generate_template(resource)
            msg = "Schema of resource template {0} is incorrect!"
            self.assertIsInstance(schema, dict, msg.format(resource))

    def test_543335_HeatStackDelete(self):
        """ This test case checks deletion of stack.

            Steps:
                1. Create stack using template file empty_heat_templ.yaml.
                2. Check that the stack is in the list of stacks
                3. Delete the stack.
                4. Check that the stack is absent in the list of stacks
        """
        stack_name = 'empty_stack'
        if common_functions.check_stack(stack_name, self.heat):
            common_functions.clean_stack(stack_name, self.heat)

        file_name = './mos_tests/heat/templates/empty_heat_templ.yaml'
        with open(file_name, 'r') as f:
            template = f.read()
        stack_data = {'stack_name': stack_name, 'template': template,
                      'parameters': {'param': 'some_param_string'},
                      'timeout_mins': 60}
        self.heat.stacks.create(**stack_data)
        self.assertTrue(common_functions.check_stack_status(stack_name,
                                                            self.heat,
                                                            'CREATE_COMPLETE'))
        common_functions.clean_stack(stack_name, self.heat)
        stacks = [s.stack_name for s in self.heat.stacks.list()]
        self.assertNotIn(stack_name, stacks)

    def test_543339_CheckStackResourcesStatuses(self):
        """ This test case checks that stack resources are in expected states
            Steps:
             1. Create new stack
             2. Launch heat action-check stack_name
             3. Launch heat stack-list and check 'CHECK_COMPLETE' status
        """
        stack_name = 'stack_to_check_543339'
        template_content = self.read_template('empty_heat_templ.yaml')
        stack_id = common_functions.create_stack(self.heat, stack_name,
                                                 template_content,
                                                 {'param': 'just text'})
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
        common_functions.delete_stack(self.heat, stack_id)

    def test_543341_ShowStackEventList(self):
        """ This test checks list events for a stack
            Steps:
             1. Create new stack
             2. Launch heat event-list stack_name
        """
        stack_name = 'stack_to_show_event_543341'
        template_content = self.read_template('empty_heat_templ.yaml')
        stack_id = common_functions.create_stack(self.heat, stack_name,
                                                 template_content,
                                                 {'param': 'just text'})
        event_list = self.heat.events.list(stack_id)
        self.assertTrue(event_list, "NOK, event list is empty")
        resources = [event.resource_name for event in event_list]
        self.assertIn(stack_name, resources,
                      "Event list doesn't contain at least one event for {0}"
                      .format(stack_name))
        common_functions.delete_stack(self.heat, stack_id)
