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
import subprocess
from time import time, sleep
import six
import paramiko

from novaclient import client as nova_client
from neutronclient.v2_0 import client as neutron_client
from keystoneclient.v2_0 import client as keystone_client
from cinderclient import client as cinder_client

from mos_tests.functions import common as common_functions
from mos_tests.environment.ssh import SSHClient


class NovaIntegrationTests(unittest.TestCase):
    """ Basic automated tests for OpenStack Nova verification. """

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

        # Neutron connect
        cls.neutron = neutron_client.Client(
                username=OS_USERNAME,
                password=OS_PASSWORD,
                tenant_name=OS_TENANT_NAME,
                auth_url=OS_AUTH_URL,
                insecure=True)

        # Cinder endpoint
        cls.cinder = cinder_client.Client(
                '2',
                OS_USERNAME,
                OS_PASSWORD,
                OS_TENANT_NAME,
                auth_url=OS_AUTH_URL)

        cls.instances = []
        cls.floating_ips = []
        cls.volumes = []
        cls.flavors = []
        cls.keys = []

        cls.sec_group = cls.nova.security_groups.create('security_nova',
                                                        'Security group, '
                                                        'created for Nova '
                                                        'automatic tests')
        rules = [
            {
                # ssh
                'ip_protocol': 'tcp',
                'from_port': 22,
                'to_port': 22,
                'cidr': '0.0.0.0/0',
            },
            {
                # ping
                'ip_protocol': 'icmp',
                'from_port': -1,
                'to_port': -1,
                'cidr': '0.0.0.0/0',
            }
        ]
        for rule in rules:
            cls.nova.security_group_rules.create(cls.sec_group.id, **rule)

    @classmethod
    def tearDownClass(cls):
        cls.nova.security_groups.delete(cls.sec_group)

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
        for flavor in self.flavors:
            common_functions.delete_flavor(self.nova, flavor.id)
        self.flavors = []
        for key in self.keys:
            common_functions.delete_keys(self.nova, key.name)
        self.keys = []

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
        image_id = [image.id for image in self.nova.images.list() if
                    image.name == 'TestVM'][0]
        flavor_list = self.nova.flavors.list()
        for flavor in flavor_list:
            floating_ip = self.nova.floating_ips.create()
            self.floating_ips.append(floating_ip)
            self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                           self.nova.floating_ips.list()])
            inst = common_functions.create_instance(self.nova,
                                                    "inst_543358_{}"
                                                    .format(flavor.name),
                                                    flavor.id, net,
                                                    [self.sec_group.name],
                                                    image_id=image_id,
                                                    inst_list=self.instances)
            inst_id = inst.id
            self.instances.append(inst_id)
            inst.add_floating_ip(floating_ip.ip)
            self.assertTrue(common_functions.check_ip(self.nova, inst_id,
                                                      floating_ip.ip))
            ping = common_functions.ping_command(floating_ip.ip)
            self.assertTrue(ping, "Instance is not reachable")

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
        image_id = [image.id for image in self.nova.images.list() if
                    image.name == 'TestVM'][0]
        networks = self.neutron.list_networks()['networks']
        net = [net['id'] for net in networks if not net['router:external']][0]
        flavor_list = self.nova.flavors.list()
        for flavor in flavor_list:
            floating_ip = self.nova.floating_ips.create()
            self.floating_ips.append(floating_ip)
            self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                           self.nova.floating_ips.list()])
            volume = common_functions.create_volume(self.cinder, image_id)
            self.volumes.append(volume)
            bdm = {'vda': volume.id}
            inst = common_functions.create_instance(self.nova,
                                                    "inst_543360_{}"
                                                    .format(flavor.name),
                                                    flavor.id, net,
                                                    [self.sec_group.name],
                                                    block_device_mapping=bdm,
                                                    inst_list=self.instances)
            inst_id = inst.id
            self.instances.append(inst_id)
            inst.add_floating_ip(floating_ip.ip)
            self.assertTrue(common_functions.check_ip(self.nova, inst_id,
                                                      floating_ip.ip))
            ping = common_functions.ping_command(floating_ip.ip)
            self.assertTrue(ping, "Instance is not reachable")

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
        instance = common_functions.create_instance(self.nova,
                                                    name, initial_flavor, net,
                                                    [self.sec_group.name],
                                                    block_device_mapping=bdm,
                                                    inst_list=self.instances)
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
        ping = common_functions.ping_command(floating_ip.ip)
        self.assertTrue(ping, "Instance after resize is not reachable")

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

    def test_543356_NovaMassivelySpawnVMsWithBootLocal(self):
        """ This test case creates a lot of VMs with boot local, checks it
        state and availability and then deletes it.
            Steps:
                1. Boot 10-100 instances from image.
                2. Check that list of instances contains created VMs.
                3. Check state of created instances
                4. Add the floating ips to the instances
                5. Ping the instances by the floating ips
        """
        initial_instances = self.nova.servers.list()
        primary_name = "testVM_543356"
        count = 10
        image_dict = {im.name: im.id for im in self.nova.images.list()}
        image_id = image_dict["TestVM"]
        flavor_dict = {f.name: f.id for f in self.nova.flavors.list()}
        flavor_id = flavor_dict["m1.micro"]
        networks = self.neutron.list_networks()["networks"]
        net_dict = {net["name"]: net["id"] for net in networks}
        net_internal_id = net_dict["admin_internal_net"]

        self.floating_ips = [self.nova.floating_ips.create()
                             for _ in xrange(count)]
        fip_new = [fip_info.ip for fip_info in self.floating_ips]
        fip_all = [fip_info.ip for fip_info in self.nova.floating_ips.list()]
        for fip in fip_new:
            self.assertIn(fip, fip_all)

        self.nova.servers.create(primary_name, image_id, flavor_id,
                                 max_count=count,
                                 security_groups=[self.sec_group.name],
                                 nics=[{"net-id": net_internal_id}])
        start_time = time()
        timeout = 5
        while len(self.nova.servers.list()) < len(initial_instances) + count \
                and time() < start_time + timeout * 60:
            sleep(5)

        instances = [inst for inst in self.nova.servers.list()
                     if inst not in initial_instances]
        self.instances = [inst.id for inst in instances]
        for inst_id in self.instances:
            self.assertTrue(common_functions.check_inst_status(self.nova,
                                                               inst_id,
                                                               'ACTIVE'))
        fip_dict = {}
        for inst in instances:
            fip = fip_new.pop()
            inst.add_floating_ip(fip)
            fip_dict[inst.id] = fip

        for inst_id in self.instances:
            self.assertTrue(common_functions.check_ip(
                self.nova, inst_id, fip_dict[inst_id]))

        for inst_id in self.instances:
            ping = common_functions.ping_command(fip_dict[inst_id], i=8)
            self.assertTrue(ping,
                            "Instance {} is not reachable".format(inst_id))

    def test_543357_NovaMassivelySpawnVMsBootFromCinder(self):
        """ This test case creates a lot of VMs which boot from Cinder, checks
        it state and availability and then deletes it.
            Steps:
                1. Create 10-100 volumes.
                2. Boot 10-100 instances from volumes.
                3. Check that list of instances contains created VMs.
                4. Check state of created instances
                5. Add the floating ips to the instances
                6. Ping the instances by the floating ips
        """
        initial_instances = self.nova.servers.list()
        count = 10
        primary_name = "testVM_543357"
        image_dict = {im.name: im.id for im in self.nova.images.list()}
        image_id = image_dict["TestVM"]
        flavor_dict = {f.name: f.id for f in self.nova.flavors.list()}
        flavor_id = flavor_dict["m1.tiny"]
        networks = self.neutron.list_networks()["networks"]
        net_dict = {net["name"]: net["id"] for net in networks}
        net_internal_id = net_dict["admin_internal_net"]

        initial_volumes = self.cinder.volumes.list()
        for i in xrange(count):
            common_functions.create_volume(self.cinder, image_id, size=1)
        self.volumes = [volume for volume in self.cinder.volumes.list()
                        if volume not in initial_volumes]
        msg = "Count of created volumes is incorrect!"
        self.assertEqual(len(self.volumes), 10, msg)

        self.floating_ips = [self.nova.floating_ips.create()
                             for _ in xrange(count)]
        fip_new = [fip_info.ip for fip_info in self.floating_ips]
        fip_all = [fip_info.ip for fip_info in self.nova.floating_ips.list()]
        for fip in fip_new:
            self.assertIn(fip, fip_all)

        for volume in self.volumes:
            bdm = {'vda': volume.id}
            self.nova.servers.create(primary_name, '', flavor_id,
                                     security_groups=[self.sec_group.name],
                                     block_device_mapping=bdm,
                                     nics=[{"net-id": net_internal_id}])
        start_time = time()
        timeout = 5
        while len(self.nova.servers.list()) < len(initial_instances) + count \
                and time() < start_time + timeout * 60:
            sleep(5)

        instances = [inst for inst in self.nova.servers.list()
                     if inst not in initial_instances]
        self.instances = [inst.id for inst in instances]
        for inst_id in self.instances:
            self.assertTrue(common_functions.check_inst_status(self.nova,
                                                               inst_id,
                                                               'ACTIVE'))
        fip_dict = {}
        for inst in instances:
            fip = fip_new.pop()
            inst.add_floating_ip(fip)
            fip_dict[inst.id] = fip

        for inst_id in self.instances:
            self.assertTrue(common_functions.check_ip(
                self.nova, inst_id, fip_dict[inst_id]))

        for inst_id in self.instances:
            ping = common_functions.ping_command(fip_dict[inst_id], i=8)
            self.assertTrue(ping,
                            "Instance {} is not reachable".format(inst_id))

    def test_2238776_NetworkConnectivityToVMDuringLiveMigration(self):
        """ This test checks network connectivity to VM during Live Migration

            Steps:
             1. Create a floating ip
             2. Create an instance from an image with 'm1.micro' flavor
             3. Add the floating ip to the instance
             4. Ping the instance by the floating ip
             5. Execute live migration
             6. Check current hypervisor and status of instance
             7. Check that packets loss was minimal
        """
        networks = self.neutron.list_networks()['networks']
        net = [net['id'] for net in networks if not net['router:external']][0]
        image_id = [image.id for image in self.nova.images.list() if
                    image.name == 'TestVM'][0]
        flavor = [flavor for flavor in self.nova.flavors.list() if
                  flavor.name == 'm1.micro'][0]
        floating_ip = self.nova.floating_ips.create()
        self.floating_ips.append(floating_ip)
        self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                       self.nova.floating_ips.list()])
        inst = common_functions.create_instance(self.nova,
                                                "inst_2238776_{}"
                                                .format(flavor.name),
                                                flavor.id, net,
                                                [self.sec_group.name],
                                                image_id=image_id,
                                                inst_list=self.instances)
        self.instances.append(inst.id)
        inst.add_floating_ip(floating_ip.ip)
        ping = common_functions.ping_command(floating_ip.ip)
        self.assertTrue(ping, "Instance is not reachable")
        hypervisors = {h.hypervisor_hostname: h for h
                       in self.nova.hypervisors.list()}
        old_hyper = getattr(inst, "OS-EXT-SRV-ATTR:hypervisor_hostname")
        new_hyper = [h for h in hypervisors.keys() if h != old_hyper][0]
        ping = subprocess.Popen(["/bin/ping", "-c100", "-i1", floating_ip.ip],
                                stdout=subprocess.PIPE)
        self.nova.servers.live_migrate(inst, new_hyper, block_migration=False,
                                       disk_over_commit=False)
        inst = self.nova.servers.get(inst.id)
        timeout = 5
        end_time = time() + 60 * timeout
        while getattr(inst, "OS-EXT-SRV-ATTR:hypervisor_hostname") != \
                new_hyper:
            if time() > end_time:
                raise AssertionError(
                    "Hypervisor is not changed after live migration")
            sleep(1)
            inst = self.nova.servers.get(inst.id)
        self.assertEqual(inst.status, 'ACTIVE')
        ping.wait()
        output = ping.stdout.read().split('\n')[-3].split()
        packets = {'transmitted': int(output[0]), 'received': int(output[3])}
        loss = packets['transmitted'] - packets['received']
        if loss > 5:
            msg = "Packets loss exceeds the limit, {} packets were lost"
            raise AssertionError(msg.format(loss))

    def test_2238777_LiveMigrationOfVMsWithDataOnRootAndEphemeralDisk(self):
        """ This test checks Live Migration of VMs with data on root and
        ephemeral disk

            Steps:
             1. Create flavor with ephemeral disk
             2. Create a floating ip
             3. Create an instance from an image with 'm1.ephemeral' flavor
             4. Add the floating ip to the instance
             5. Ssh to instance and create timestamp on root and ephemeral
                disks
             6. Ping the instance by the floating ip
             7. Execute live migration
             8. Check current hypervisor and status of instance
             9. Check that packets loss was minimal
             10. Ssh to instance and check timestamp on root and ephemeral
                 disks
        """
        networks = self.neutron.list_networks()['networks']
        net = [net['id'] for net in networks if not net['router:external']][0]
        image_id = [image.id for image in self.nova.images.list() if
                    image.name == 'TestVM'][0]
        flavor = self.nova.flavors.create("m1.ephemeral", 64, 1, 1,
                                          ephemeral=1, is_public=True)
        self.flavors.append(flavor)
        floating_ip = self.nova.floating_ips.create()
        self.floating_ips.append(floating_ip)
        self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                       self.nova.floating_ips.list()])
        keys = self.nova.keypairs.create('key_2238776')
        self.keys.append(keys)
        private_key = paramiko.RSAKey.from_private_key(six.StringIO(str(
            keys.private_key)))
        inst = common_functions.create_instance(self.nova,
                                                "inst_2238776_{}"
                                                .format(flavor.name),
                                                flavor.id, net,
                                                [self.sec_group.name],
                                                image_id=image_id,
                                                key_name='key_2238776',
                                                inst_list=self.instances)
        inst.add_floating_ip(floating_ip.ip)
        ping = common_functions.ping_command(floating_ip.ip, i=10)
        self.assertTrue(ping, "Instance is not reachable")
        out = []
        with SSHClient(host=floating_ip.ip, username="cirros", password=None,
                       private_keys=[private_key]) as vm_r:
            out.append(vm_r.execute("sudo sh -c 'date > /timestamp.txt'"))
            out.append(vm_r.execute("sudo sh -c 'date > /mnt/timestamp.txt'"))
            out.append(vm_r.execute("sudo -i cat /timestamp.txt"))
            out.append(vm_r.execute("sudo -i cat /mnt/timestamp.txt"))

        for i in out:
            if i.get('stderr'):
                raise Exception("ssh commands were executed with errors")

        root_data = out[-2]['stdout'][0]
        ephem_data = out[-1]['stdout'][0]

        # live migration
        hypervisors = {h.hypervisor_hostname: h for h in
                       self.nova.hypervisors.list()}
        old_hyper = getattr(inst, "OS-EXT-SRV-ATTR:hypervisor_hostname")
        new_hyper = [h for h in hypervisors.keys() if h != old_hyper][0]
        ping = subprocess.Popen(["/bin/ping", "-c100", "-i1", floating_ip.ip],
                                stdout=subprocess.PIPE)
        self.nova.servers.live_migrate(inst, new_hyper, block_migration=False,
                                       disk_over_commit=False)
        inst = self.nova.servers.get(inst.id)
        timeout = 10
        end_time = time() + 60 * timeout
        while getattr(inst, "OS-EXT-SRV-ATTR:hypervisor_hostname") != \
                new_hyper:
            if time() > end_time:
                raise AssertionError(
                    "Hypervisor is not changed after live migration")
            sleep(1)
            inst = self.nova.servers.get(inst.id)
        self.assertEqual(inst.status, 'ACTIVE')
        ping.wait()
        output = ping.stdout.read().split('\n')[-3].split()
        packets = {'transmitted': int(output[0]), 'received': int(output[3])}
        loss = packets['transmitted'] - packets['received']
        if loss > 5:
            msg = "Packets loss exceeds the limit, {} packets were lost"
            raise AssertionError(msg.format(loss))
        out = []
        with SSHClient(host=floating_ip.ip, username="cirros", password=None,
                       private_keys=[private_key]) as vm_r:
            out.append(vm_r.execute("sudo -i cat /timestamp.txt"))
            out.append(vm_r.execute("sudo -i cat /mnt/timestamp.txt"))

        for i in out:
            if i.get('stderr'):
                raise Exception("ssh commands were executed with errors")

        r_data = out[0]['stdout'][0]
        ep_data = out[1]['stdout'][0]
        self.assertEqual(root_data, r_data, "Data on root disk is changed")
        self.assertEqual(ephem_data, ep_data, "Data on ephemeral disk is "
                                              "changed")
