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
import logging

from heatclient.v1.client import Client as heat_client
from keystoneclient.v2_0 import client as keystone_client
from neutronclient.v2_0 import client as neutron_client
from novaclient import client as nova_client
from glanceclient.v2 import client as glance_client

from mos_tests.functions import common as common_functions

logger = logging.getLogger(__name__)


class WindowCompatibilityIntegrationTests(unittest.TestCase):
    """ Basic automated tests for OpenStack Windows Compatibility verification.
    """

    @classmethod
    def setUpClass(cls):
        OS_AUTH_URL = os.environ.get('OS_AUTH_URL')
        OS_USERNAME = os.environ.get('OS_USERNAME')
        OS_PASSWORD = os.environ.get('OS_PASSWORD')
        OS_TENANT_NAME = os.environ.get('OS_TENANT_NAME')
        OS_PROJECT_NAME = os.environ.get('OS_PROJECT_NAME')

        cls.keystone = keystone_client.Client(
                auth_url=OS_AUTH_URL,
                username=OS_USERNAME,
                password=OS_PASSWORD,
                tenat_name=OS_TENANT_NAME,
                project_name=OS_PROJECT_NAME)

        services = cls.keystone.service_catalog

        # Get path on node to 'templates' dir
        cls.templates_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'templates')
        # Get path on node to 'images' dir
        cls.images_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'images')

        # Neutron connect
        cls.neutron = neutron_client.Client(
                username=OS_USERNAME,
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

        cls.nova = nova_client.Client(
                '2',
                auth_url=OS_AUTH_URL,
                username=OS_USERNAME,
                auth_token=OS_TOKEN,
                tenant_id=OS_TENANT_ID,
                insecure=True)

        # Glance connect
        glance_endpoint = services.url_for(
                service_type='image',
                endpoint_type='publicURL')

        cls.glance = glance_client.Client(
                endpoint=glance_endpoint,
                token=OS_TOKEN,
                insecure=True)

        cls.uid_list = []

    def setUp(self):
        """

        :return: Nothing
        """
        self.amount_of_images_before = len(list(self.glance.images.list()))
        self.image = None
        self.our_own_flavor_was_created = False
        self.expected_flavor_id = 3
        self.node_to_boot = None
        self.security_group_name = "ms_compatibility"
        # protect for multiple definition of the same group
        for sg in self.nova.security_groups.list():
            if sg.name == self.security_group_name:
                self.nova.security_groups.delete(sg)
        # adding required security group
        self.the_security_group = self.nova.security_groups.create(
                name=self.security_group_name,
                description="Windows Compatibility")
        # Add rules for ICMP, TCP/22
        self.icmp_rule = self.nova.security_group_rules.create(
                self.the_security_group.id,
                ip_protocol="icmp",
                from_port=-1,
                to_port=-1,
                cidr="0.0.0.0/0")
        self.tcp_rule = self.nova.security_group_rules.create(
                self.the_security_group.id,
                ip_protocol="tcp",
                from_port=22,
                to_port=22,
                cidr="0.0.0.0/0")
        # Add both rules to default group
        self.default_security_group_id = 0
        for sg in self.nova.security_groups.list():
            if sg.name == 'default':
                self.default_security_group_id = sg.id
                break
        self.icmp_rule_default = self.nova.security_group_rules.create(
                self.default_security_group_id,
                ip_protocol="icmp",
                from_port=-1,
                to_port=-1,
                cidr="0.0.0.0/0")
        self.tcp_rule_default = self.nova.security_group_rules.create(
                self.default_security_group_id,
                ip_protocol="tcp",
                from_port=22,
                to_port=22,
                cidr="0.0.0.0/0")
        # adding floating ip
        self.floating_ip = self.nova.floating_ips.create(
                self.nova.floating_ip_pools.list()[0].name)

        # creating of the image
        self.image = self.glance.images.create(
                name='MyTestSystem',
                disk_format='qcow2',
                container_format='bare')
        self.glance.images.upload(
                self.image.id,
                open('/tmp/trusty-server-cloudimg-amd64-disk1.img', 'rb'))
        # check that required image in active state
        is_activated = False
        while not is_activated:
            for image_object in self.glance.images.list():
                if image_object.id == self.image.id:
                    self.image = image_object
                    logger.debug("Image in the {} state".
                                 format(self.image.status))
                    if self.image.status == 'active':
                        is_activated = True
                        break
            time.sleep(1)

        # Default - the first
        network_id = self.nova.networks.list()[0].id
        # More detailed check of network list
        for network in self.nova.networks.list():
            if 'internal' in network.label:
                network_id = network.id
        logger.debug("Starting with network interface id {}".
                     format(network_id))

        # TODO: add check flavor parameters vs. vm parameters
        # Collect information about the medium flavor and create a copy of it
        for flavor in self.nova.flavors.list():
            if 'medium' in flavor.name and 'copy.of.' not in flavor.name:
                new_flavor_name = "copy.of." + flavor.name
                new_flavor_id = common_functions.get_flavor_id_by_name(
                        self.nova,
                        new_flavor_name)
                # delete the flavor if it already exists
                if new_flavor_id is not None:
                    common_functions.delete_flavor(
                            self.nova,
                            new_flavor_id)
                # create the flavor for our needs
                expected_flavor = self.nova.flavors.create(
                        name=new_flavor_name,
                        ram=flavor.ram,
                        vcpus=1,  # Only one VCPU
                        disk=flavor.disk
                )
                self.expected_flavor_id = expected_flavor.id
                self.our_own_flavor_was_created = True
                break
        logger.debug("Starting with flavor {}".format(
                self.nova.flavors.get(self.expected_flavor_id)))
        # nova boot
        self.node_to_boot = common_functions.create_instance(
                    nova_client=self.nova,
                    inst_name="MyTestSystemWithNova",
                    flavor_id=self.expected_flavor_id,
                    net_id=network_id,
                    security_group=self.the_security_group.name,
                    image_id=self.image.id)
        # check that boot returns expected results
        self.assertEqual(self.node_to_boot.status, 'ACTIVE',
                         "The node not in active state!")

        logger.debug("Using following floating ip {}".format(
                self.floating_ip.ip))

        self.node_to_boot.add_floating_ip(self.floating_ip)

        self.assertTrue(common_functions.check_ip(
                self.nova,
                self.node_to_boot.id,
                self.floating_ip.ip))

    def tearDown(self):
        """

        :return:
        """
        if self.node_to_boot is not None:
            common_functions.delete_instance(self.nova, self.node_to_boot.id)
        if self.image is not None:
            common_functions.delete_image(self.glance, self.image.id)
        if self.our_own_flavor_was_created:
            common_functions.delete_flavor(self.nova, self.expected_flavor_id)
        # delete the floating ip
        self.nova.floating_ips.delete(self.floating_ip)
        # delete the security group
        self.nova.security_group_rules.delete(self.icmp_rule)
        self.nova.security_group_rules.delete(self.tcp_rule)
        self.nova.security_groups.delete(self.the_security_group.id)
        # delete security rules from the 'default' group
        self.nova.security_group_rules.delete(self.icmp_rule_default)
        self.nova.security_group_rules.delete(self.tcp_rule_default)
        self.assertEqual(self.amount_of_images_before,
                         len(list(self.glance.images.list())),
                         "Length of list with images should be the same")

    def test_542825_CreateInstanceWithWindowsImage(self):
        """ This test checks that instance with Windows image could be created

        Steps:
        1. Create image
        2. Check that VM is reachable
        :return: Nothing
        """
        end_time = time.time() + 120
        ping_result = False
        attempt_id = 1
        while time.time() < end_time:
            logger.debug("Attempt #{} to ping the instance".format(attempt_id))
            ping_result = common_functions.ping_command(self.floating_ip.ip)
            attempt_id += 1
            if ping_result:
                break
        self.assertTrue(ping_result, "Instance is not reachable")

    def test_542826_PauseAndUnpauseInstanceWithWindowsImage(self):
        """ This test checks that instance with Windows image could be paused
        and unpaused

        Steps:
        1. Create image
        2. Check that VM is reachable
        3. Put the image on 'Pause' state
        4. Check that the VM is unreachable
        5. Put the image on 'Unpause' state
        6. Check that the VM is reachable again
        :return: Nothing
        """
        # Initial check
        end_time = time.time() + 120
        ping_result = False
        attempt_id = 1
        while time.time() < end_time:
            logger.debug("Attempt #{} to ping the instance".format(attempt_id))
            ping_result = common_functions.ping_command(self.floating_ip.ip)
            attempt_id += 1
            if ping_result:
                break
        self.assertTrue(ping_result, "Instance is not reachable")
        # Paused state check
        self.node_to_boot.pause()
        # TODO: Make sure that the VM in 'Paused' state
        end_time = time.time() + 60
        ping_result = False
        attempt_id = 1
        while time.time() < end_time:
            logger.debug("Attempt #{} to ping the instance".format(attempt_id))
            ping_result = common_functions.ping_command(self.floating_ip.ip)
            attempt_id += 1
            if ping_result:
                break
        self.assertFalse(ping_result, "Instance is reachable")
        # Unpaused state check
        self.node_to_boot.unpause()
        # TODO: Make sure that the VM in 'Unpaused' state
        end_time = time.time() + 120
        ping_result = False
        attempt_id = 1
        while time.time() < end_time:
            logger.debug("Attempt #{} to ping the instance".format(attempt_id))
            ping_result = common_functions.ping_command(self.floating_ip.ip)
            attempt_id += 1
            if ping_result:
                break
        self.assertTrue(ping_result, "Instance is not reachable")

    @unittest.skip("Not Implemented")
    def test_542826_SuspendAndResumeInstanceWithWindowsImage(self):
        """ This test checks that instance with Windows image can be suspended
        and resumed

        Steps:
        1. Create image
        2. Check that VM is reachable
        3. Put the image on 'Suspend' state
        4. Check that the VM is unreachable
        5. Put the image on 'Resume' state
        6. Check that the VM is reachable again
        :return: Nothing
        """
        # Initial check
        end_time = time.time() + 120
        ping_result = False
        attempt_id = 1
        while time.time() < end_time:
            logger.debug("Attempt #{} to ping the instance".format(attempt_id))
            ping_result = common_functions.ping_command(self.floating_ip.ip)
            attempt_id += 1
            if ping_result:
                break
        self.assertTrue(ping_result, "Instance is not reachable")
        # Suspend state check
        self.node_to_boot.suspend()
        # TODO: Make sure that the VM in 'Suspended' state
        end_time = time.time() + 60
        ping_result = False
        attempt_id = 1
        while time.time() < end_time:
            logger.debug("Attempt #{} to ping the instance".format(attempt_id))
            ping_result = common_functions.ping_command(self.floating_ip.ip)
            attempt_id += 1
            if ping_result:
                break
        self.assertFalse(ping_result, "Instance is reachable")
        # Resume state check
        self.node_to_boot.resume()
        # TODO: Make sure that the VM in 'Resume' state
        end_time = time.time() + 120
        ping_result = False
        attempt_id = 1
        while time.time() < end_time:
            logger.debug("Attempt #{} to ping the instance".format(attempt_id))
            ping_result = common_functions.ping_command(self.floating_ip.ip)
            attempt_id += 1
            if ping_result:
                break
        self.assertTrue(ping_result, "Instance is not reachable")
