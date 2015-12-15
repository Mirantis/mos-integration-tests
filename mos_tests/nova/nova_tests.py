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
    """ Basic automated tests for OpenStack Nova verification. """

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

        # Neutron connect
        self.neutron = neutron_client.Client(username=OS_USERNAME,
                                             password=OS_PASSWORD,
                                             tenant_name=OS_TENANT_NAME,
                                             auth_url=OS_AUTH_URL,
                                             insecure=True)

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
        self.instances = []
        self.floating_ips = []
        self.volumes = []

    def tearDown(self):
        for inst in self.instances:
            common_functions.delete_instance(self.nova, inst)
        self.instances = []
        for fip in self.floating_ips:
            common_functions.delete_floating_ip(self.nova, fip)
        self.floating_ips = []
        for volume in self.volumes:
            common_functions.delete_volume(self.cinder, volume)
        self.volumes = []

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
            self.floating_ips.append(floating_ip)
            self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                           self.nova.floating_ips.list()])
            inst = common_functions.create_instance(self.nova, "inst_543358_{}"
                                                    .format(flavor.name),
                                                    flavor.id, net,
                                                    security_group,
                                                    image_id=image_id)
            inst_id = inst.id
            self.instances.append(inst_id)
            inst.add_floating_ip(floating_ip.ip)
            self.assertTrue(common_functions.check_ip(self.nova, inst_id,
                                                      floating_ip.ip))
            ping = os.system("ping -c 4 -i 4 {}".format(floating_ip.ip))
            self.assertEqual(ping, 0, "Instance is not reachable")

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
        for flavor in flavor_list:
            floating_ip = self.nova.floating_ips.create()
            self.floating_ips.append(floating_ip)
            self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                           self.nova.floating_ips.list()])
            volume = common_functions.create_volume(self.cinder, image_id)
            self.volumes.append(volume)
            bdm = {'vda': volume.id}
            inst = common_functions.create_instance(self.nova, "inst_543360_{}"
                                                    .format(flavor.name),
                                                    flavor.id, net,
                                                    security_group,
                                                    block_device_mapping=bdm)
            inst_id = inst.id
            self.instances.append(inst_id)
            inst.add_floating_ip(floating_ip.ip)
            self.assertTrue(common_functions.check_ip(self.nova, inst_id,
                                                      floating_ip.ip))
            ping = os.system("ping -c 4 -i 4 {}".format(floating_ip.ip))
            self.assertEqual(ping, 0, "Instance is not reachable")

    def test_543355_ResizeDownAnInstanceBootedFromVolume(self):
        """ This test checks that nova allows
            resize down an instance booted from volume

            Steps:
            1. Create bootable volume
            2. Boot instance from newly created volume
            3. Resize instance from m1.small to m1.tiny
        """

        # 1. Create bootable volume
        image_id = [image.id for image in self.nova.images.list() if
                    image.name == 'TestVM'][0]

        volume = common_functions.create_volume(self.cinder, image_id, 60)
        self.volumes.append(volume)

        # 2. Create instance from newly created volume, associate floating_ip
        name = 'TestVM_543355_instance_to_resize'
        networks = self.neutron.list_networks()['networks']
        net = [net['id'] for net in networks if not net['router:external']][0]
        flavor_list = {f.name: f.id for f in self.nova.flavors.list()}
        initial_flavor = flavor_list['m1.small']
        resize_flavor = flavor_list['m1.tiny']
        bdm = {'vda': volume.id}
        security_group = self.nova.security_groups.list()[0].name
        instance = common_functions.create_instance(self.nova, name,
                                                    initial_flavor, net,
                                                    security_group,
                                                    block_device_mapping=bdm)
        self.instances.append(instance.id)

        # Assert for attached volumes
        attached_volumes = self.nova.servers.get(instance).to_dict()[
            'os-extended-volumes:volumes_attached']
        self.assertIn({'id': volume.id}, attached_volumes)

        # Assert to flavor size
        self.assertEqual(self.nova.servers.get(instance).flavor['id'],
                         initial_flavor,
                         "Unexpected instance flavor before resize")

        floating_ip = self.nova.floating_ips.create()
        self.floating_ips.append(floating_ip.ip)
        instance.add_floating_ip(floating_ip.ip)

        # 3. Resize from m1.small to m1.tiny
        self.nova.servers.resize(instance, resize_flavor)
        common_functions.check_inst_status(self.nova, instance.id,
                                           'VERIFY_RESIZE', 60)
        self.nova.servers.confirm_resize(instance)
        common_functions.check_inst_status(self.nova, instance.id,
                                           'ACTIVE', 60)
        self.assertEqual(self.nova.servers.get(instance).flavor['id'],
                         resize_flavor,
                         "Unexpected instance flavor after resize")

        # Check that instance is reachable
        ping = os.system("ping -c 4 -i 4 {}".format(floating_ip.ip))
        self.assertEqual(ping, 0, "Instance after resize is not reachable")

    def test_543359_MassivelySpawnVolumes(self):
        """ This test checks massively spawn volumes

            Steps:
                1. Create 10 volumes
                2. Check status of newly created volumes
                3. Delete all volumes
        """
        volume_count = 10
        volumes = []

        # Creation using Cinder
        for num in xrange(volume_count):
            volumes.append(
                self.cinder.volumes.create(
                    1, name='Volume_{}'.format(num + 1)))
        self.volumes.extend(volumes)

        for volume in self.cinder.volumes.list():
            self.assertTrue(
                common_functions.check_volume_status(self.cinder, volume.id,
                                                     'available', 60),
                "Volume '{0}' is not available".format(volume.id))
