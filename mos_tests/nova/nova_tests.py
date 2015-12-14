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
from neutronclient.v2_0 import client as neutron_client
from novaclient import client as nova_client
from glanceclient.v2 import client as glance_client
from cinderclient import client as cinder_client

from mos_tests.nova.functions import common as common_functions


class NovaTests(unittest.TestCase):
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
        services = self.keystone.service_catalog
        heat_endpoint = services.url_for(service_type='orchestration',
                                         endpoint_type='internalURL')

        self.heat = heat_client(endpoint=heat_endpoint,
                                token=self.keystone.auth_token)

        # Get path on node to 'templates' dir
        self.templates_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'templates')
        # Get path on node to 'images' dir
        self.images_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'images')

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

        # Glance connect
        glance_endpoint = services.url_for(service_type='image',
                                           endpoint_type='publicURL')
        self.glance = glance_client.Client(endpoint=glance_endpoint,
                                           token=OS_TOKEN,
                                           insecure=True)

        # Cinder endpoint
        self.cinder = cinder_client.Client('2', OS_USERNAME, OS_PASSWORD,
                                           OS_TENANT_NAME,
                                           auth_url=OS_AUTH_URL)

    def test_543355_ResizeDownAnInstanceBootedFromVolume(self):
        """ This test checks that nova allows
            resize down an instance booted from volume

            Steps:
            1. Create bootable volume
            2. Boot instance from newly created volume
            3. Resize instance from m1.small to m1.tiny
        """

        # 0. Add ALL ICMP rule to Default security group


        # 1. Create bootable volume
        image_id = [image.id for image in self.nova.images.list() if
                    image.name == 'TestVM'][0]
        volume = self.cinder.volumes.create(1, name='TestVM_volume',
                                            imageRef=image_id)
        timeout = time.time() + 60
        while True:
            status = self.cinder.volumes.get(volume.id).status
            if status == 'available':
                break
            elif time.time() > timeout:
                raise AssertionError(
                    "Volume status is '{0}' instead of 'available".format(
                        status))
            else:
                time.sleep(1)

        # 2. Create instance from newly created volume, associate floating_ip
        name = 'TestVM_543355_instance_to_resize'
        networks = self.neutron.list_networks()['networks']
        net = [net['id'] for net in networks if not net['router:external']][0]
        flavor_list = {f.name: f.id for f in self.nova.flavors.list()}
        initial_flavor = flavor_list['m1.small']
        resize_flavor = flavor_list['m1.tiny']
        bdm = {'vda': volume.id}

        instance_id = self.nova.servers.create(name=name, image='',
                                               flavor=initial_flavor,
                                               block_device_mapping=bdm,
                                               nics=[{'net-id': net}])
        timeout = time.time() + 60
        while True:
            status = self.nova.servers.get(instance_id).status
            if status == 'ACTIVE':
                break
            elif time.time() > timeout:
                raise AssertionError("Unable to find running instance")
            else:
                time.sleep(1)

        # Assert for attached volumes
        attached_volumes = self.nova.servers.get(instance_id).to_dict()[
            'os-extended-volumes:volumes_attached']
        self.assertIn({'id': volume.id}, attached_volumes)

        # Assert to flavor size
        self.assertEqual(self.nova.servers.get(instance_id).flavor['id'],
                         initial_flavor,
                         "Unexpected instance flavor before resize")

        floating_ip = self.nova.floating_ips.create()
        instance_id.add_floating_ip(floating_ip.ip)

        # 3. Resize from m1.small to m1.tiny
        self.nova.servers.resize(instance_id, resize_flavor)
        timeout = time.time() + 60
        while True:
            status = self.nova.servers.get(instance_id).status
            if status == 'VERIFY_RESIZE':
                self.nova.servers.confirm_resize(instance_id)
                break
            elif time.time() > timeout:
                raise AssertionError(
                    "Unable to find instance in 'VERIFY_RESIZE' state")
            else:
                time.sleep(1)

        timeout = time.time() + 120
        while True:
            status = self.nova.servers.get(instance_id).status
            if status == 'ACTIVE':
                break
            elif time.time() > timeout:
                raise AssertionError("Unable to find running instance")
            else:
                time.sleep(1)

        self.assertEqual(self.nova.servers.get(instance_id).flavor['id'],
                         resize_flavor,
                         "Unexpected instance flavor before resize")

        # Check that instance is reachable
        ping = os.system("ping -c 2 -w 60 {}".format(floating_ip.ip))
        self.assertEqual(ping, 0, "Instance after resize is not reachable")

        # Clean-up (to be re-worked)
        self.nova.servers.delete(instance_id)
        timeout = time.time() + 120
        while True:
            if instance_id not in self.nova.servers.list():
                self.cinder.volumes.delete(volume)
                break
            elif time.time() > timeout:
                raise AssertionError("Instance is not removed")
            else:
                time.sleep(1)





