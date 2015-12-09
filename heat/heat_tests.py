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
import urllib2
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

    def test_543347_HeatCreateStack(self):
        """ This test performs creation of a new stack with a help of Heat. And then delete it.
            Steps:
            1. Read template from URL
            2. Create new stack.
                + Check that stack became from 'CREATE_IN_PROGRESS' --> 'CREATE_COMPLETE'
            3. Delete created stack
                + Check that stack became from 'DELETE_IN_PROGRESS' --> 'DELETE_COMPLETE'

        https://mirantis.testrail.com/index.php?/cases/view/543347
        [Alexander Koryagin]
        """

        # Variables
        # TODO :akoryagin: Be sure that this template file will be put on controller during test preparation
        file_name = './Templates/stack_create_template.yaml'  # File with template for stack creation

        new_stack_name = 'Test_{0}'.format(str(time.time())[0:10:])  # Like: 'Test_1449484927'
        timeout_value = 10  # Timeout in minutes to wait for stack status change

        def create_stack(heatclient, stack_name, template):
            """ Create a stack from template and check STATUS == CREATE_COMPLETE
                    :param heatclient: Heat API client connection point
                    :param stack_name: Name of a new stack
                    :param template:   Content of a template name
                    :return uid: UID of stack
            """
            stack = heatclient.stacks.create(
                stack_name=stack_name,
                template=template,
                parameters={})
            uid = stack['stack']['id']

            stack = heatclient.stacks.get(stack_id=uid).to_dict()
            timeout = time.time() + 60 * timeout_value  # default: 10 minutes of timeout to change stack status
            while stack['stack_status'] == 'CREATE_IN_PROGRESS':
                stack = heatclient.stacks.get(stack_id=uid).to_dict()
                if time.time() > timeout:
                    break
                else:
                    time.sleep(5)

            # Check that final status of a newly created stack is 'CREATE_COMPLETE'
            self.assertEqual(
                (stack['stack_status']), 'CREATE_COMPLETE',
                msg='Stack failed to create: {}'.format(stack)
            )
            return uid

        def delete_stack(heatclient, uid):
            """ Delete stack and check STATUS == DELETE_COMPLETE
                    :param heatclient: Heat API client connection point
                    :param uid:        UID of stack
            """
            heatclient.stacks.delete(uid)

            stack = heatclient.stacks.get(stack_id=uid).to_dict()
            timeout = time.time() + 60 * timeout_value   # default: 10 minutes of timeout to change stack status
            while stack['stack_status'] == 'DELETE_IN_PROGRESS':
                stack = heatclient.stacks.get(stack_id=uid).to_dict()
                if time.time() > timeout:
                    break
                else:
                    time.sleep(5)

            # Check that final status of a newly deleted stack is 'DELETE_COMPLETE'
            self.assertEqual(
                (stack['stack_status']), 'DELETE_COMPLETE',
                msg='Stack fall to unknown status: {}'.format(stack)
            )

        # - 1 -
        # Read Heat stack-create template from file
        try:
            with open(file_name, 'r') as template:
                template_content = template.read()
        except IOError:
            raise Exception("ERROR: can not find template-file [{0}] on controller or read data".format(file_name))

        # - 2 -
        # Create new stack
        uid_of_new_stack = create_stack(self.heat, new_stack_name, template_content)

        # - 3 -
        # Delete created stack
        delete_stack(self.heat, uid_of_new_stack)
