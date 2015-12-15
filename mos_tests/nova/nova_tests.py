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
from cinderclient import client as cinder_client

from mos_tests.functions import common as common_functions


class NovaIntegrationTests(unittest.TestCase):
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

        # Cinder endpoint
        self.cinder = cinder_client.Client('2', OS_USERNAME, OS_PASSWORD,
                                           OS_TENANT_NAME,
                                           auth_url=OS_AUTH_URL)

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
        net = [net['id'] for net in networks
                        if not net['router:external']][0]
        image_id = self.nova.images.list()[0].id
        security_group = self.nova.security_groups.list()[0].name
        flavor_list = self.nova.flavors.list()
        for flavor in flavor_list:
            floating_ip = self.nova.floating_ips.create()
            self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                           self.nova.floating_ips.list()])
            inst = common_functions.create_instance(self.nova, "inst_543358_{}"
                                                    .format(flavor.name),
                                                    flavor.id, net,
                                                    security_group,
                                                    image_id=image_id)
            inst_id = inst.id
            inst.add_floating_ip(floating_ip.ip)
            self.assertTrue(common_functions.check_ip(self.nova, inst_id,
                                                      floating_ip.ip))
            ping = os.system("ping -c 4 -i 4 {}".format(floating_ip.ip))
            self.assertEqual(ping, 0, "Instance is not reachable")
            self.nova.floating_ips.delete(floating_ip)
            common_functions.delete_instance(self.nova, inst_id)

    def test_543360_NovaLaunchVMFromVolumeWithAllFlavours(self):
        """ This test case checks creation of instance from volume with all
        types of flavor. For this test needs 2 nodes with compute role:
        20Gb RAM and 150GB disk for each

            Steps:
             1. Create bootable volume
             1. Create a floating ip
             2. Create an instance from an image with some flavor
             3. Add the floating ip to the instance
             4. Ping the instance by the floating ip
             5. Delete the floating ip
             6. delete the instance
             7. Repeat all steps for all types of flavor
        """
        image_id = self.nova.images.list()[0].id

        networks = self.neutron.list_networks()['networks']
        net = [net['id'] for net in networks if not net['router:external']][0]
        security_group = self.nova.security_groups.list()[0].name
        flavor_list = self.nova.flavors.list()
        volume_id = common_functions.create_volume(self.cinder, image_id)
        bdm = {'vda': volume_id}
        for flavor in flavor_list:
            floating_ip = self.nova.floating_ips.create()
            self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                           self.nova.floating_ips.list()])
            inst = common_functions.create_instance(self.nova, "inst_543360_{}"
                                                    .format(flavor.name),
                                                    flavor.id, net,
                                                    security_group,
                                                    block_device_mapping=bdm)
            inst_id = inst.id
            inst.add_floating_ip(floating_ip.ip)
            self.assertTrue(common_functions.check_ip(self.nova, inst_id,
                                                      floating_ip.ip))
            ping = os.system("ping -c 4 -i 4 {}".format(floating_ip.ip))
            self.assertEqual(ping, 0, "Instance is not reachable")
            self.nova.floating_ips.delete(floating_ip)
            common_functions.delete_instance(self.nova, inst_id)
