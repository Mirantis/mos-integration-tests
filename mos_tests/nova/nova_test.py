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

import logging
from time import sleep
from time import time
import xml.etree.ElementTree as ElementTree

import paramiko
import pytest
import six

from mos_tests.environment.ssh import SSHClient
from mos_tests.functions.base import OpenStackTestCase
from mos_tests.functions import common as common_functions
from mos_tests.neutron.python_tests.base import TestBase
from novaclient.exceptions import ClientException as NovaClientException


logger = logging.getLogger(__name__)


@pytest.mark.undestructive
class NovaIntegrationTests(OpenStackTestCase):
    """Basic automated tests for OpenStack Nova verification. """

    @pytest.yield_fixture
    def cleanup_ports(self, os_conn):
        """Ports cleanUp"""
        yield
        for port_id in self.ports:
            os_conn.remove_port(port_id)

    def setUp(self):
        super(self.__class__, self).setUp()

        self.instances = []
        self.floating_ips = []
        self.volumes = []
        self.flavors = []
        self.keys = []
        self.ports = []

        self.sec_group = self.nova.security_groups.create('security_nova',
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
            self.nova.security_group_rules.create(self.sec_group.id, **rule)

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
        self.nova.security_groups.delete(self.sec_group)

    def get_admin_int_net_id(self):
        networks = self.neutron.list_networks()['networks']
        net_id = [net['id'] for net in networks if
                  not net['router:external'] and
                  'admin' in net['name']][0]
        return net_id

    @pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
    @pytest.mark.testrail_id('543358')
    def test_nova_launch_v_m_from_image_with_all_flavours(self):
        """This test case checks creation of instance from image with all
        types of flavor. For this test we need node with compute role:
        8 VCPUs, 16+GB RAM and 160+GB disk for any compute

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
            inst.add_floating_ip(floating_ip.ip)
            self.assertTrue(common_functions.check_ip(self.nova, inst.id,
                                                      floating_ip.ip))
            ping = common_functions.ping_command(floating_ip.ip)
            common_functions.delete_instance(self.nova, inst.id)
            self.assertTrue(ping, "Instance is not reachable")

    @pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
    @pytest.mark.testrail_id('543360')
    def test_nova_launch_v_m_from_volume_with_all_flavours(self):
        """This test case checks creation of instance from volume with all
        types of flavor. For this test we need node with compute role:
        8 VCPUs, 16+GB RAM and 160+GB disk for any compute

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
        volume = common_functions.create_volume(self.cinder, image_id)
        self.volumes.append(volume)
        bdm = {'vda': volume.id}
        for flavor in flavor_list:
            floating_ip = self.nova.floating_ips.create()
            self.floating_ips.append(floating_ip)
            self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                           self.nova.floating_ips.list()])
            inst = common_functions.create_instance(self.nova,
                                                    "inst_543360_{}"
                                                    .format(flavor.name),
                                                    flavor.id, net,
                                                    [self.sec_group.name],
                                                    block_device_mapping=bdm,
                                                    inst_list=self.instances)
            inst.add_floating_ip(floating_ip.ip)
            self.assertTrue(common_functions.check_ip(self.nova, inst.id,
                                                      floating_ip.ip))
            ping = common_functions.ping_command(floating_ip.ip)
            common_functions.delete_instance(self.nova, inst.id)
            self.assertTrue(ping, "Instance is not reachable")

    @pytest.mark.testrail_id('543355')
    def test_resize_down_an_instance_booted_from_volume(self):
        """This test checks that nova allows
            resize down an instance booted from volume
            Steps:
            1. Create bootable volume
            2. Boot instance from newly created volume
            3. Resize instance from m1.small to m1.tiny
        """

        # 1. Create bootable volume
        image_id = [image.id for image in self.nova.images.list() if
                    image.name == 'TestVM'][0]

        volume = common_functions.create_volume(self.cinder, image_id,
                                                timeout=60)
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

    @pytest.mark.testrail_id('543359')
    def test_massively_spawn_volumes(self):
        """This test checks massively spawn volumes

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

    @pytest.mark.testrail_id('543356')
    def test_nova_massively_spawn_v_ms_with_boot_local(self):
        """This test case creates a lot of VMs with boot local, checks it
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

    @pytest.mark.testrail_id('543357')
    def test_nova_massively_spawn_v_ms_boot_from_cinder(self):
        """This test case creates a lot of VMs which boot from Cinder, checks
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

    @pytest.mark.testrail_id('542823')
    def test_network_connectivity_to_v_m_during_live_migration(self):
        """This test checks network connectivity to VM during Live Migration

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

        self.os_conn.live_migration(inst, floating_ip.ip)

    @pytest.mark.testrail_id('542824')
    def test_live_migration_of_v_ms_with_data_on_root_and_ephemeral_disk(self):
        """This test checks Live Migration of VMs with data on root and
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
        self.instances.append(inst.id)
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

        self.os_conn.live_migration(inst, floating_ip.ip)

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

    @pytest.mark.testrail_id('843882')
    def test_boot_instance_from_volume_bigger_than_flavor_size(self):
        """This test checks that nova allows creation instance
            from volume with size bigger than flavor size

            Steps:
            1. Create volume with size 2Gb.
            2. Boot instance with flavor size 'tiny' from newly created volume
            3. Check that instance created with correct values
        """

        # 1. Create volume
        image_id = self.nova.images.find(name='TestVM').id

        volume = common_functions.create_volume(self.cinder, image_id,
                                                size=2, timeout=60)
        self.volumes.append(volume)

        # 2. Create router, network, subnet, connect them to external network
        ext_network_id = self.os_conn.ext_network['id']
        router_id = self.os_conn.create_router(name="router01")['router']['id']
        self.os_conn.router_gateway_add(router_id=router_id,
                                        network_id=ext_network_id)
        net_id = self.os_conn.add_net(router_id)

        # 3. Create instance from newly created volume, associate floating_ip
        name = 'TestVM_1517671_instance'
        initial_flavor = self.nova.flavors.find(name='m1.tiny')
        bdm = {'vda': volume.id}
        instance = common_functions.create_instance(self.nova, name,
                                                    initial_flavor, net_id,
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
                         initial_flavor.id,
                         "Unexpected instance flavor after creation")

        floating_ip = self.nova.floating_ips.create()
        self.floating_ips.append(floating_ip.ip)
        instance.add_floating_ip(floating_ip.ip)

        # Check that instance is reachable
        ping = common_functions.ping_command(floating_ip.ip)
        self.assertTrue(ping, "Instance after creation is not reachable")

    @pytest.mark.testrail_id('857431')
    def test_delete_instance_in_resize_state(self):
        """Delete an instance while it is in resize state

        Steps:
            1. Create a new instance
            2. Resize instance from m1.small to m1.tiny
            3. Delete the instance immediately after vm_state is 'RESIZE'
            4. Check that the instance was successfully deleted
            5. Repeat steps 1-4 some times
        """
        name = 'TestVM_857431_instance_to_resize'
        admin_net = self.get_admin_int_net_id()
        initial_flavor = self.nova.flavors.find(name='m1.small')
        resize_flavor = self.nova.flavors.find(name='m1.tiny')
        image_id = self.nova.images.find(name='TestVM')

        for _ in range(10):
            instance = common_functions.create_instance(
                self.nova,
                name,
                initial_flavor,
                admin_net,
                [self.sec_group.id],
                image_id=image_id,
                inst_list=self.instances)

            # resize instance
            instance.resize(resize_flavor)
            common_functions.wait(
                lambda: (self.os_conn.server_status_is(instance, 'RESIZE') or
                         self.os_conn.server_status_is(instance,
                                                       'VERIFY_RESIZE')),
                timeout_seconds=2 * 60,
                waiting_for='instance state is RESIZE or VERIFY_RESIZE')

            # check that instance can be deleted
            common_functions.delete_instance(self.nova, instance.id)
            assert instance not in self.nova.servers.list()

    @pytest.mark.usefixtures('cleanup_ports')
    @pytest.mark.testrail_id('857191')
    def test_delete_instance_with_precreated_port(self):
        """This test checks pre-created port is not deleted after deletion
        instance created with this pre-created port

        Steps:
            1. Create a port
            2. Boot a VM using created port
            3. Delete VM
            4. Check that corresponding pre-created port is not deleted
        """
        net_id = self.os_conn.int_networks[0]['id']
        precreated_port_id = self.os_conn.create_port(net_id)['port']['id']
        self.ports.append(precreated_port_id)

        ports_ids_for_network = [
            port['id'] for port in self.os_conn.list_ports_for_network(
                network_id=net_id, device_owner='')]
        assert precreated_port_id in ports_ids_for_network

        instance = self.os_conn.create_server(
            name='server01',
            nics=[{'port-id': precreated_port_id}],
            availability_zone='nova',
            wait_for_avaliable=False)
        self.instances.append(instance.id)

        ports_for_instance = [
            port['id'] for port in self.os_conn.list_ports_for_network(
                network_id=net_id, device_owner='compute:nova')]
        assert precreated_port_id in ports_for_instance

        common_functions.delete_instance(self.os_conn.nova, instance.id)

        ports_ids_for_network = [
            port['id'] for port in self.os_conn.list_ports_for_network(
                network_id=net_id, device_owner='')]
        assert precreated_port_id in ports_ids_for_network

    @pytest.mark.testrail_id('1696116')
    def test_check_floating_ip_after_quota_exceeded(self):
        """Create floating IP after quota was exceeded and pool of IPs
        was cleaned.

        Steps:
            1. Create 50 floating IPs
            2. Create floating IP that exceed quota - unsuccessfully.
            3. Delete all floating IPs
            4. Create new floating IP
            5. Boot vm, associate floating IP for vm
            6. Go to vm with ssh and check traffic

        Duration 5m

        """
        floating_quota = 50
        for num in xrange(floating_quota):
            floating_ip = self.nova.floating_ips.create()
            self.floating_ips.append(floating_ip)
        try:
            self.nova.floating_ips.create()
        except NovaClientException:
            logger.info('IP allocation over quota')
        for fip in self.floating_ips:
            common_functions.delete_floating_ip(self.nova, fip)
        self.assertNotIn(floating_ip.ip, [fip_info.ip for fip_info in
                                          self.nova.floating_ips.list()])
        net = self.os_conn.int_networks[0]['id']
        image_id = self.os_conn.nova.images.find(name='TestVM').id
        flavor_id = self.os_conn.nova.flavors.find(name='m1.micro').id
        floating_ip = self.nova.floating_ips.create()
        self.floating_ips.append(floating_ip)
        self.assertIn(floating_ip.ip, [fip_info.ip for fip_info in
                                       self.nova.floating_ips.list()])
        inst = common_functions.create_instance(self.nova, "inst_1696116",
                                                flavor_id, net,
                                                [self.sec_group.name],
                                                image_id=image_id,
                                                inst_list=self.instances)
        inst.add_floating_ip(floating_ip.ip)
        self.assertTrue(common_functions.check_ip(self.nova, inst.id,
                                                  floating_ip.ip))
        ping = common_functions.ping_command(floating_ip.ip)
        common_functions.delete_instance(self.nova, inst.id)
        self.assertTrue(ping, "Instance is not reachable")


@pytest.mark.undestructive
class TestBugVerification(TestBase):

    @pytest.yield_fixture
    def set_io_limits_to_flavor(self, os_conn):
        limit = 10240000
        logger.info('Setting I/O limits to flavor')
        flv = os_conn.nova.flavors.find(name='m1.tiny')
        flv.set_keys({'quota:disk_read_bytes_sec': '{0}'.format(limit)})
        flv.set_keys({'quota:disk_write_bytes_sec': '{0}'.format(limit)})
        yield limit
        logger.info('Removing I/O limits from flavor')
        flv.unset_keys({'quota:disk_read_bytes_sec': '{0}'.format(limit)})
        flv.unset_keys({'quota:disk_write_bytes_sec': '{0}'.format(limit)})

    @pytest.mark.testrail_id('1617024')
    @pytest.mark.check_env_('is_ephemeral_ceph_enabled')
    def test_disk_io_qos_settings_for_rbd_backend(self, os_conn,
                                                  set_io_limits_to_flavor):
        """Test checks that disk I/O QOS settings are set correctly in case of
        rbd backend is used (it covers bug #1507504).

        Steps:
        1. On controller node set I/O limits to m1.tiny flavor:
        'nova flavor-key m1.tiny set quota:disk_read_bytes_sec=10240000'
        'nova flavor-key m1.tiny set quota:disk_write_bytes_sec=10240000'
        2. Check that limits were applied to this flavor:
        'nova flavor-show m1.tiny | grep extra_specs'
        3. Create instance with this flavor
        4. On compute node (on which created instance is hosted) check instance
        xml file (located in /etc/libvirt/qemu). This file should contain
        section of rbd disk with I/O limits read_bytes_sec=10240000,
        write_bytes_sec=10240000
        5. In the output of command 'ps axu | grep qemu' should be present
        process with I/O limits: bps_rd=10240000, bps_wr=10240000.
        6. Delete instance and unset I/O limits to m1.tiny flavor. Check that
        limits were removed for m1.tiny flavor.
        """
        name = 'testVM_for_bug_1507504'
        limit = set_io_limits_to_flavor
        int_net_id = os_conn.nova.networks.find(label='admin_internal_net').id
        image_id = os_conn.nova.images.find(name='TestVM').id
        flv_id = os_conn.nova.flavors.find(name='m1.tiny').id

        sec_group_id = os_conn.nova.security_groups.find(name='default').id

        logger.info('Create instance using flavor with I/O limits')
        instance = common_functions.create_instance(os_conn.nova, name,
                                                    flv_id, int_net_id,
                                                    [sec_group_id], image_id)

        compute_hostname = getattr(instance, 'OS-EXT-SRV-ATTR:host')
        compute = self.env.find_node_by_fqdn(compute_hostname)
        inst_name = getattr(instance, 'OS-EXT-SRV-ATTR:instance_name')

        logger.info('Verify that I/O limits are applied for instance rbd disk')
        with compute.ssh() as remote:
            cmd = 'virsh dumpxml {0}'.format(inst_name)
            out = remote.check_call(cmd)
        root = ElementTree.fromstring(out.stdout_string)
        disk = root.find('devices').find('disk')
        err_msg = "Disk is not connected to instance through 'rbd'"
        assert disk.find('source').get('protocol') == 'rbd', err_msg
        iotune = disk.find('iotune')
        err_msg = "IO limits don't work correctly for instance"
        assert iotune.find('read_bytes_sec').text == str(limit), err_msg
        assert iotune.find('write_bytes_sec').text == str(limit), err_msg

        logger.info('Verify that I/O limits are working correctly')
        with compute.ssh() as remote:
            cmd = "ps axu | grep qemu | grep 'drive file=rbd'"
            out = remote.check_call(cmd).stdout_string
            assert 'bps_rd={0}'.format(limit) in out
            assert 'bps_wr={0}'.format(limit) in out

        common_functions.delete_instance(os_conn.nova, instance.id)
        assert instance not in os_conn.nova.servers.list()
