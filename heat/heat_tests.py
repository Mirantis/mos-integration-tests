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
import unittest
import time

from keystoneclient.v2_0 import client as keystone_client
from heatclient.v1.client import Client as heat_client


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

    def test_543337_HeatStackUpdate(self):
        """ This test case checks stack-update action.
            Steps:
            1. Create stack using template file empty_heat_templ.yaml
            2. Update stack parameter
        """
        # TODO Alexandra Allakhverdieva: Check about possibility to use common functions
        # Stack creation
        stack_name = 'empty'
        with open(r'./Templates/empty_heat_template.yaml', 'r') as template_file:
            template_content = template_file.read()
        d_initial = {'stack_name': stack_name, 'template': template_content, 'parameters': {'param': 'string'}}
        self.heat.stacks.create(**d_initial)
        stack_dict = {s.stack_name: s.id for s in self.heat.stacks.list() if s.stack_status == 'CREATE_COMPLETE'}
        self.assertIn(stack_name, stack_dict.keys(), "Unable to find stack in 'CREATE_COMPLETE' state")

        # Stack update
        stack_id = stack_dict[stack_name]
        d_updated = {'stack_name': stack_name, 'template': template_content, 'parameters': {'param': 'string2'}}
        self.heat.stacks.update(stack_id, **d_updated)
        timeout = time.time() + 10

        while True:
            stack_dict_upd = {s.stack_name: s.id for s in self.heat.stacks.list()
                              if s.stack_status == 'UPDATE_COMPLETE'}
            if stack_name in stack_dict_upd.keys():
                break
            elif time.time() > timeout:
                raise AssertionError("Unable to find stack 'empty' in 'UPDATE_COMPLETE' state")
            else:
                time.sleep(1)

        # Clean-up
        self.heat.stacks.delete(stack_id)



    def test_543329_HeatResourceTypeShow(self):
        """ This test case checks representation of all Heat resources.
            Steps:
             1. Get list of Heat resources.
             2. Check that all types of resources have correct representation.
        """
        resource_types = [r.resource_type for r in
                          self.heat.resource_types.list()]

        for resource in resource_types:
            resource_schema = self.heat.resource_types.get(resource)
            self.assertIsInstance(resource_schema, dict,
                                  "Schema of resource {0} is incorrect!".format(resource))

    def test_543330_HeatResourceTypeTemplate(self):
        """ This test case checks representation of templates for all Heat resources.
            Steps:
             1. Get list of Heat resources.
             2. Check that templates for all resources have correct representation.
        """
        resource_types = [r.resource_type for r in
                          self.heat.resource_types.list()]

        for resource in resource_types:
            resource_template_schema = self.heat.resource_types.generate_template(resource)
            self.assertIsInstance(resource_template_schema, dict,
                                  "Schema of resource template {0} is incorrect!".format(resource))
