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

from novaclient import client as nova_client
from neutronclient.v2_0 import client as neutron_client
from keystoneclient.v2_0 import client as keystone_client

from mos_tests.nova.functions import common as common_functions


class HeatIntegrationTests(unittest.TestCase):
    """ Basic automated tests for OpenStack Heat verification. """

    @classmethod
    def setUpClass(self):
        OS_AUTH_URL = os.environ.get('OS_AUTH_URL')
        OS_USERNAME = os.environ.get('OS_USERNAME')
        OS_PASSWORD = os.environ.get('OS_PASSWORD')
        OS_TENANT_NAME = os.environ.get('OS_TENANT_NAME')
        OS_PROJECT_NAME = os.environ.get('OS_PROJECT_NAME')

        self.keystone = keystone_client.Client(auth_url=OS_AUTH_URL,
                                               username=OS_USERNAME,
                                               password=OS_PASSWORD,
                                               tenat_name=OS_TENANT_NAME,
                                               project_name=OS_PROJECT_NAME)
        # Nova connect
        OS_TOKEN = self.keystone.get_token(self.keystone.session)
        RAW_TOKEN = self.keystone.get_raw_token_from_identity_service(
            auth_url=OS_AUTH_URL,
            username=OS_USERNAME,
            password=OS_PASSWORD,
            tenant_name=OS_TENANT_NAME)
        OS_TENANT_ID = RAW_TOKEN['token']['tenant']['id']

        self.nova = nova_client.Client('2',
                                       auth_url=OS_AUTH_URL,
                                       username=OS_USERNAME,
                                       auth_token=OS_TOKEN,
                                       tenant_id=OS_TENANT_ID,
                                       insecure=True)

        # Neutron connect
        self.neutron = neutron_client.Client(username=OS_USERNAME,
                                             password=OS_PASSWORD,
                                             tenant_name=OS_TENANT_NAME,
                                             auth_url=OS_AUTH_URL,
                                             insecure=True)

    def test_543358_NovaLaunchVMFromImageWithAllFlavours(self):
        """ This test case checks creation of instance from image with all
        types of flavor. For this test needs 2 nodes with compute role:
        20Gb RAM and 150GB disk for each

            Steps:
             1. Create a floating ip
             2. Create an instance from an image with some flavor
             3. Add the floating ip to the instance
             4. Ping the instance by the floating ip
             5. Delete the floating ip
             6. delete the instance
             7. Repeat all steps for all types of flavor
        """
        networks = self.neutron.list_networks()['networks']
        internal_net = [net['id'] for net in networks
                        if not net['router:external']][0]
        image_id = self.nova.images.list()[0].id
        security_group = self.nova.security_groups.list()[0].name
        flavor_list = self.nova.flavors.list()
        for flavor in flavor_list:
            floating_ip = self.nova.floating_ips.create()
            self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                            self.nova.floating_ips.list()])

            inst = self.nova.servers.create(name='inst_543358_{}'.format(
                                                                  flavor.name),
                                            image=image_id,
                                            flavor=flavor.id,
                                            nics=[{"net-id": internal_net}],
                                            security_groups=[security_group])
            inst_id = inst.id
            self.assertTrue(common_functions.check_inst_status(self.nova,
                                                               inst_id,
                                                               'ACTIVE',
                                                               1))
            inst.add_floating_ip(floating_ip.ip)
            self.assertTrue(common_functions.check_ip(self.nova, inst_id,
                                                      floating_ip.ip))
            ping = os.system("ping -c 3 -W 60 {}".format(floating_ip.ip))
            self.assertEqual(ping, 0, "Instance is not reachable")
            self.nova.floating_ips.delete(floating_ip)
            common_functions.delete_instance(self.nova, inst_id)
