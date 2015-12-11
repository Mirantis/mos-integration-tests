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
from random import randint

from heatclient.v1.client import Client as heat_client
from keystoneclient.v2_0 import client as keystone_client
from neutronclient.v2_0 import client as neutron_client
from novaclient import client as nova_client
from glanceclient.v2 import client as glance_client

from mos_tests.heat.functions import common as common_functions


class HeatIntegrationTests(unittest.TestCase):
    """ Basic automated tests for OpenStack Heat verification. """

    @classmethod
    def setUpClass(cls):
        OS_AUTH_URL = os.environ.get('OS_AUTH_URL')
        OS_USERNAME = os.environ.get('OS_USERNAME')
        OS_PASSWORD = os.environ.get('OS_PASSWORD')
        OS_TENANT_NAME = os.environ.get('OS_TENANT_NAME')
        OS_PROJECT_NAME = os.environ.get('OS_PROJECT_NAME')

        cls.keystone = keystone_client.Client(auth_url=OS_AUTH_URL,
                                              username=OS_USERNAME,
                                              password=OS_PASSWORD,
                                              tenat_name=OS_TENANT_NAME,
                                              project_name=OS_PROJECT_NAME)
        services = cls.keystone.service_catalog
        heat_endpoint = services.url_for(service_type='orchestration',
                                         endpoint_type='internalURL')

        cls.heat = heat_client(endpoint=heat_endpoint,
                               token=cls.keystone.auth_token)

        # Get path on node to 'templates' dir
        cls.templates_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'templates')
        # Get path on node to 'images' dir
        cls.images_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'images')

        # Neutron connect
        cls.neutron = neutron_client.Client(username=OS_USERNAME,
                                            password=OS_PASSWORD,
                                            tenant_name=OS_TENANT_NAME,
                                            auth_url=OS_AUTH_URL,
                                            insecure=True)

        # Nova connect
        OS_TOKEN = cls.keystone.get_token(cls.keystone.session)
        RAW_TOKEN = cls.keystone.get_raw_token_from_identity_service(
            auth_url=OS_AUTH_URL,
            username=OS_USERNAME,
            password=OS_PASSWORD,
            tenant_name=OS_TENANT_NAME)
        OS_TENANT_ID = RAW_TOKEN['token']['tenant']['id']

        cls.nova = nova_client.Client('2',
                                      auth_url=OS_AUTH_URL,
                                      username=OS_USERNAME,
                                      auth_token=OS_TOKEN,
                                      tenant_id=OS_TENANT_ID,
                                      insecure=True)

        # Glance connect
        glance_endpoint = services.url_for(service_type='image',
                                           endpoint_type='publicURL')
        cls.glance = glance_client.Client(endpoint=glance_endpoint,
                                          token=OS_TOKEN,
                                          insecure=True)
        cls.uid_list = []

    def tearDown(self):
        for stack_uid in self.uid_list:
            common_functions.delete_stack(self.heat, stack_uid)
        self.uid_list = []

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

    def test_543337_HeatStackUpdate(self):
        """ This test case checks stack-update action.
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
        stack_name = 'empty_543335'
        timeout = 20
        parameter = 'some_param_string'
        if common_functions.check_stack(stack_name, self.heat):
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

    def test_543333_HeatStackCreateWithTemplate(self):
        """ This test case checks creation of stack.
            Steps:
             1. Create stack using template file empty_heat_templ.yaml.
             2. Check that the stack is in the list of stacks
             3. Check that stack status is 'CREATE_COMPLETE'
             4. Delete stack
        """
        stack_name = 'empty__543333'
        parameter = 'some_param_string'
        timeout = 20
        if common_functions.check_stack(stack_name, self.heat):
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

    def test_543334_HeatStackCreateWithURL(self):
        """ This test case checks creation of stack using template URL.
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
        if common_functions.check_stack(stack_name, self.heat):
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

    def test_543339_CheckStackResourcesStatuses(self):
        """ This test case checks that stack resources are in expected states
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

    def test_543341_ShowStackEventList(self):
        """ This test checks list events for a stack
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

    def test_543344_HeatStackTemplateShow(self):
        """ This test case checks representation of template of created stack.
            Steps:
                1. Create stack using template file empty_heat_templ.yaml.
                2. Check that template of created stack has correct
                 representation.
        """
        stack_name = 'empty_stack'
        timeout = 60
        parameter = "some_string"
        if common_functions.check_stack(stack_name, self.heat):
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

    def test_543342_ShowInfoOfSpecifiedStackEvent(self):
        """ This test checks info about stack event
            Steps:
             1. Create new stack
             2. Launch heat event-list stack_name
             3. Launch heat event-show <NAME or ID> <RESOURCE> <EVENT>
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

    def test_543345_HeatCreateStackAWS(self):
        """ This test creates stack using AWS format template
            Steps:
             1. Connect to Neutron and get ID of internal_network
             2. Get ID of external_network
             3. Get ID of internal_subnet of internal_network
             4. Find IP for internal_subnet
             5. Create stack
             6. Delete stack
        https://mirantis.testrail.com/index.php?/cases/view/543345
        [Alexander Koryagin]
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

    def test_543332_HeatStackPreview(self):
        """ This test case previews a stack.
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
        if common_functions.check_stack(stack_name, self.heat):
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

    def test_543343_HeatStackTemplateValidate(self):
        """ This test case checks representation of template file.
            Steps:
                1. Check that selected template file has correct
                 representation.
        """
        template_content = common_functions.read_template(
            self.templates_dir, 'heat_create_nova_stack_template.yaml')
        template_data = {'template': template_content}
        result = self.heat.stacks.validate(**template_data)
        self.assertIsInstance(result, dict)

    def test_543340_StackResumeSuspend(self):
        """ Suspend and resume stack
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

    def test_543351_HeatStackUpdateReplace(self):
        """ This test case checks change stack id after stack update.
            Steps:
             1. Create stack using template.
             2. Check id of created image.
             3. Update stack template: disk_format = 'ami',
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

    def test_543352_HeatStackUpdateInPlace(self):
        """ This test case checks stack id doesn't change after stack update.
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

    def test_543336_HeatStackShow(self):
        """ This test case checks detailed stack's information.
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
        if common_functions.check_stack(stack_name, self.heat):
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
