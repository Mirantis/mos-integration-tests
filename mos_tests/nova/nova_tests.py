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


class NovaIntegrationTests(unittest.TestCase):
    """ Basic automated tests for OpenStack Nova Basic verification. """

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
                                               tenant_name=OS_TENANT_NAME,
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

    def test_543356_NovaMassivelySpawnVMsWithBootLocal(self):
        """ This test case creates a lot of VMs with boot local, checks it
        state and availability and then deletes it.

            Steps:
                1. Boot 10-100 instances from image.
                2. Check that list of instances contains created VMs.
                3. Check state of created instances
                4. Add the floating ips to the instances
                5. Ping the instances by the floating ips
                6. Delete all created instances
        """
        primary_name = "testVM_543356"
        count = 10
        image_dict = {im.name: im.id for im in self.nova.images.list()}
        image_id = image_dict["TestVM"]
        flavor_dict = {f.name: f.id for f in self.nova.flavors.list()}
        flavor_id = flavor_dict["m1.micro"]
        networks = self.neutron.list_networks()["networks"]
        net_dict = {net["name"]: net["id"] for net in networks}
        net_internal_id = net_dict["admin_internal_net"]

        floating_ips = [self.nova.floating_ips.create() for i in xrange(count)]
        fip_new = [fip_info.ip for fip_info in floating_ips]
        fip_all = [fip_info.ip for fip_info in self.nova.floating_ips.list()]
        for fip in fip_new:
            self.assertIn(fip, fip_all)

        self.nova.servers.create(primary_name, image_id, flavor_id,
                                 max_count=count,
                                 nics=[{"net-id": net_internal_id}])

        inst_ids = [inst.id for inst in self.nova.servers.list()]
        msg = "Count of instances is incorrect"
        self.assertEqual(len(inst_ids), count, msg)
        for inst_id in inst_ids:
            self.assertTrue(common_functions.check_inst_status(self.nova,
                                                               inst_id,
                                                               'ACTIVE'))
        fip_dict = {}
        for inst in self.nova.servers.list():
            fip = fip_new.pop()
            inst.add_floating_ip(fip)
            fip_dict[inst.id] = fip

        for inst_id in inst_ids:
            self.assertTrue(common_functions.check_ip(
                self.nova, inst_id, fip_dict[inst_id]))

        for inst_id in inst_ids:
            ping = os.system("ping -c 3 -W 60 {}".format(fip_dict[inst_id]))
            msg = "Instance {0} is not reachable".format(inst_id)
            self.assertEqual(ping, 0, msg)

        #clean up
        for fip in [fip_info.ip for fip_info in floating_ips]:
            self.nova.floating_ips.delete(fip)
        for fip in floating_ips:
            self.nova.floating_ips.delete(fip)

        for inst in self.nova.servers.list():
            common_functions.delete_instance(self.nova, inst)
