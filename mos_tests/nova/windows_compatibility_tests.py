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

from heatclient.v1.client import Client as heat_client
from keystoneclient.v2_0 import client as keystone_client
from neutronclient.v2_0 import client as neutron_client


class WindowCompatibilityIntegrationTests(unittest.TestCase):
    """ Basic automated tests for OpenStack Windows Compatibility verification. """

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

        cls.templates_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'templates')

        # Neutron connect
        cls.neutron = neutron_client.Client(username=OS_USERNAME,
                                            password=OS_PASSWORD,
                                            tenant_name=OS_TENANT_NAME,
                                            auth_url=OS_AUTH_URL,
                                            insecure=True)

    def setUp(self):
        """

        :return: Nothing
        """

    def tearDown(self):
        """

        :return:
        """

    def test_542825_CreateInstanceWithWindowsImage(self):
        """

        :return: Nothing
        """

    def test_542826_PauseAndUnpauseInstanceWithWindowsImage(self):
        """

        :return: Nothing
        """

    def test_542826_SuspendAndResumeInstanceWithWindowsImage(self):
        """

        :return: Nothing
        """
