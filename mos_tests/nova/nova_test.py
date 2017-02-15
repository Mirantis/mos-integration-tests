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
import re
import subprocess
from time import sleep
from time import time
import xml.etree.ElementTree as ElementTree

from novaclient.exceptions import BadRequest
import paramiko
import pytest
import six
from six.moves import configparser

from mos_tests.environment.ssh import SSHClient
from mos_tests.functions.base import OpenStackTestCase
from mos_tests.functions import common as common_functions
from mos_tests.functions import file_cache
from mos_tests.functions import network_checks
from mos_tests.functions import service
from mos_tests.neutron.python_tests.base import TestBase
from mos_tests import settings


logger = logging.getLogger(__name__)


@pytest.yield_fixture
def set_recl_inst_interv(env, request):
    interv_sec = request.param  # reclaim_instance_interval
    config = [('DEFAULT', 'reclaim_instance_interval', interv_sec)]
    for step in service.nova_patch(env, config):
        yield step


@pytest.mark.undestructive
@pytest.mark.check_env_("is_flavor_exist")
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

        self.sec_group = self.nova.security_groups.create(
            'security_nova_NovaIntegrationTests',
            'Security group, created for Nova automatic tests')
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
            self.os_conn.delete_volume(volume)
        self.volumes = []
        for flavor in self.flavors:
            common_functions.delete_flavor(self.nova, flavor.id)
        self.flavors = []
        for key in self.keys:
            common_functions.delete_keys(self.nova, key.name)
        self.keys = []
        self.os_conn.delete_security_group(self.sec_group)

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
        net = self.get_admin_int_net_id()
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
                                                    [self.sec_group.id],
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
        net = self.get_admin_int_net_id()
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
                                                    [self.sec_group.id],
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
        net = self.get_admin_int_net_id()
        flavor_list = {f.name: f.id for f in self.nova.flavors.list()}
        initial_flavor = flavor_list['m1.small']
        resize_flavor = flavor_list['m1.tiny']
        bdm = {'vda': volume.id}
        instance = common_functions.create_instance(self.nova,
                                                    name, initial_flavor, net,
                                                    [self.sec_group.id],
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
        self.floating_ips.append(floating_ip)
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
        for num in range(volume_count):
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
        net_internal_id = self.get_admin_int_net_id()

        self.floating_ips = [self.nova.floating_ips.create()
                             for _ in range(count)]
        fip_new = [fip_info.ip for fip_info in self.floating_ips]
        fip_all = [fip_info.ip for fip_info in self.nova.floating_ips.list()]
        for fip in fip_new:
            self.assertIn(fip, fip_all)

        self.nova.servers.create(primary_name, image_id, flavor_id,
                                 max_count=count,
                                 security_groups=[self.sec_group.id],
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
        net_internal_id = self.get_admin_int_net_id()

        initial_volumes = self.cinder.volumes.list()
        for i in range(count):
            common_functions.create_volume(self.cinder, image_id, size=1)
        self.volumes = [volume for volume in self.cinder.volumes.list()
                        if volume not in initial_volumes]
        msg = "Count of created volumes is incorrect!"
        self.assertEqual(len(self.volumes), 10, msg)

        self.floating_ips = [self.nova.floating_ips.create()
                             for _ in range(count)]
        fip_new = [fip_info.ip for fip_info in self.floating_ips]
        fip_all = [fip_info.ip for fip_info in self.nova.floating_ips.list()]
        for fip in fip_new:
            self.assertIn(fip, fip_all)

        for volume in self.volumes:
            bdm = {'vda': volume.id}
            self.nova.servers.create(primary_name, '', flavor_id,
                                     security_groups=[self.sec_group.id],
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
        net = self.get_admin_int_net_id()
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
                                                [self.sec_group.id],
                                                image_id=image_id,
                                                inst_list=self.instances)
        self.instances.append(inst.id)
        inst.add_floating_ip(floating_ip.ip)
        ping = common_functions.ping_command(floating_ip.ip)
        self.assertTrue(ping, "Instance is not reachable")

        self.live_migration(inst, floating_ip.ip)

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
        net = self.get_admin_int_net_id()
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
                                                [self.sec_group.id],
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

        self.live_migration(inst, floating_ip.ip)

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

    def live_migration(self, instance, ip_to_ping, timeout=20):
        hypervisors = {h.hypervisor_hostname: h for h in
                       self.nova.hypervisors.list()}
        old_hyper = getattr(instance, "OS-EXT-SRV-ATTR:hypervisor_hostname")
        new_hyper = [h for h in hypervisors.keys() if h != old_hyper][0]
        # Start ping of the vm in background
        ping = subprocess.Popen(["/bin/ping", "-c20", "-i1", ip_to_ping],
                                stdout=subprocess.PIPE)
        # Then run the migration
        try:
            instance.live_migrate(new_hyper,
                                  block_migration=True,
                                  disk_over_commit=False)
        except BadRequest:
            instance.live_migrate(new_hyper,
                                  block_migration=False,
                                  disk_over_commit=False)

        # Check that migration is over, usually it takes about 10-15 seconds
        def instance_hypervisor():
            instance.get()
            return getattr(instance, "OS-EXT-SRV-ATTR:hypervisor_hostname")

        common_functions.wait(lambda: instance_hypervisor() == new_hyper,
                              timeout_seconds=timeout * 60,
                              waiting_for='instance hypervisor to be changed')
        self.assertEqual(instance.status, 'ACTIVE')

        # Now wait till background ping is over
        ping.wait()
        # And check that vm was reachable during migration
        output = re.search(r'(\d+)% packet loss', ping.stdout.read())
        loss = int(output.group(1))
        if loss > 90:
            msg = "Packets loss during migration {}% exceeds the 90% limit"
            raise AssertionError(msg.format(loss))

        # And now sure that vm is stable after the migration
        ping = subprocess.Popen(["/bin/ping", "-c300", "-i0.4",
                                ip_to_ping], stdout=subprocess.PIPE)
        ping.wait()
        output = re.search('([0-9]+)% packet loss', ping.stdout.read())
        loss = int(output.group(1))
        if loss > 10:
            msg = "Packets loss during stability {}% exceeds the 10% limit"
            raise AssertionError(msg.format(loss))

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
        image_id = [image.id for image in self.nova.images.list() if
                    image.name == 'TestVM'][0]

        volume = common_functions.create_volume(self.cinder, image_id,
                                                size=2, timeout=60)
        self.volumes.append(volume)

        # 2. Create router, network, subnet, connect them to external network
        exist_networks = self.os_conn.list_networks()['networks']
        ext_network = [x for x in exist_networks
                       if x.get('router:external')][0]
        self.router = self.os_conn.create_router(name="router01")['router']
        self.os_conn.router_gateway_add(router_id=self.router['id'],
                                        network_id=ext_network['id'])
        net_id = self.os_conn.add_net(self.router['id'])

        # 3. Create instance from newly created volume, associate floating_ip
        name = 'TestVM_1517671_instance'
        flavor_list = {f.name: f.id for f in self.nova.flavors.list()}
        initial_flavor_id = flavor_list['m1.tiny']
        bdm = {'vda': volume.id}
        instance = common_functions.create_instance(self.nova, name,
                                                    initial_flavor_id, net_id,
                                                    [self.sec_group.id],
                                                    block_device_mapping=bdm,
                                                    inst_list=self.instances)
        self.instances.append(instance.id)

        # Assert for attached volumes
        attached_volumes = self.nova.servers.get(instance).to_dict()[
            'os-extended-volumes:volumes_attached']
        self.assertIn({'id': volume.id}, attached_volumes)

        # Assert to flavor size
        self.assertEqual(self.nova.servers.get(instance).flavor['id'],
                         initial_flavor_id,
                         "Unexpected instance flavor after creation")

        floating_ip = self.nova.floating_ips.create()
        self.floating_ips.append(floating_ip)
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


@pytest.mark.undestructive
class TestNovaDeferredDelete(TestBase):
    """Nova Deferred Delete test cases"""
    recl_interv_long = 24 * 60 * 60  # seconds
    recl_interv_short = 30           # seconds

    @classmethod
    @pytest.yield_fixture
    def volumes(cls, os_conn):
        """Volumes cleanUp"""
        volumes = []
        yield volumes
        for volume in volumes:
            os_conn.delete_volume(volume)

    @pytest.mark.testrail_id('842493')
    @pytest.mark.parametrize(
        'set_recl_inst_interv', [recl_interv_long], indirect=True)
    def test_restore_deleted_instance(
            self, set_recl_inst_interv, instances, volumes):
        """Restore previously deleted instance.
        Actions:
        1. Update '/etc/nova/nova.conf' with 'reclaim_instance_interval=86400'
        and restart Nova on all nodes;
        2. Create net and subnet;
        3. Create and run two instances (vm1, vm2) inside same net;
        4. Check that ping are successful between vms;
        5. Create a volume and attach it to an instance vm1;
        6. Delete instance vm1 and check that it's in 'SOFT_DELETE' state;
        7. Restore vm1 instance and check that it's in 'ACTIVE' state;
        8. Check that ping are successful between vms;
        """
        timeout = 60  # (sec) timeout to wait instance for status change

        # Create two vms
        vm1, vm2 = instances

        # Ping one vm from another
        vm1_ip = self.os_conn.get_nova_instance_ips(vm1).values()[0]
        vm2_ip = self.os_conn.get_nova_instance_ips(vm2).values()[0]
        network_checks.check_ping_from_vm(
            self.env, self.os_conn, vm1, ip_to_ping=vm2_ip, timeout=60)

        # Create a volume and attach it to an instance vm1
        volume = common_functions.create_volume(
            self.os_conn.cinder, image_id=None)
        self.os_conn.nova.volumes.create_server_volume(
            server_id=vm1.id, volume_id=volume.id, device='/dev/vdb')
        volumes.append(volume)

        # Delete instance vm1 and check that it's in "SOFT_DELETED" state
        common_functions.delete_instance(self.os_conn.nova, vm1.id)
        assert vm1 not in self.os_conn.get_servers()
        common_functions.wait(
            lambda: self.os_conn.server_status_is(vm1, 'SOFT_DELETED'),
            timeout_seconds=timeout, sleep_seconds=5,
            waiting_for='instance {0} changes status to SOFT_DELETED'.format(
                vm1.name))

        # Restore vm1 instance and check that it's in "ACTIVE" state now
        resp = self.os_conn.nova.servers.restore(vm1.id)
        assert resp[0].ok
        common_functions.wait(
            lambda: self.os_conn.is_server_active(vm1.id),
            timeout_seconds=timeout, sleep_seconds=5,
            waiting_for='instance {0} changes status to ACTIVE'.format(
                vm1.name))

        # Ping one vm from another
        network_checks.check_ping_from_vm(
            self.env, self.os_conn, vm2, ip_to_ping=vm1_ip, timeout=60)

    @pytest.mark.testrail_id('842494')
    @pytest.mark.parametrize(
        'set_recl_inst_interv', [recl_interv_short], indirect=True)
    def test_inst_deleted_reclaim_interval_timeout(
            self, set_recl_inst_interv, instances, volumes):
        """Check that softly-deleted instance is totally deleted after
        reclaim interval timeout.
        Actions:
        1. Update '/etc/nova/nova.conf' with short 'reclaim_instance_interval'
        and restart Nova on all nodes;
        2. Create net and subnet;
        3. Create and run two instances (vm1, vm2) inside same net;
        4. Create a volume and attach it to an instance vm1;
        5. Delete instance vm1 and check that it's in 'SOFT_DELETE' state;
        6. Wait for the reclaim instance interval to expire and make sure
        the vm1 is deleted;
        7. Check that volume is released now and has an Available state;
        8. Attach the volume to vm2 instance to ensure that the volume's reuse
        doesn't call any errors.

        ~! BUG !~
        https://bugs.launchpad.net/cinder/+bug/1463856
        Cinder volume isn't available after instance soft-deleted timer
        expired while volume is still attached.
        """
        timeout = 60  # (sec) timeout to wait instance for status change

        # Create two vms
        vm1, vm2 = instances

        # Create a volume and attach it to an instance vm1
        volume = common_functions.create_volume(
            self.os_conn.cinder, image_id=None)
        self.os_conn.nova.volumes.create_server_volume(
            server_id=vm1.id, volume_id=volume.id, device='/dev/vdb')
        volumes.append(volume)

        # Delete instance vm1 and check that it's in "SOFT_DELETED" state
        common_functions.delete_instance(self.os_conn.nova, vm1.id)
        assert vm1 not in self.os_conn.get_servers()
        common_functions.wait(
            lambda: self.os_conn.server_status_is(vm1, 'SOFT_DELETED'),
            timeout_seconds=timeout, sleep_seconds=5,
            waiting_for='instance {0} changes status to SOFT_DELETED'.format(
                vm1.name))

        # Wait interval and check that instance is not present
        time_to_sleep = 2.5 * self.recl_interv_short
        logger.debug(('Sleep to wait for 2.5 reclaim_instance_interval ({0})'
                      ).format(time_to_sleep))
        sleep(time_to_sleep)
        try:
            self.os_conn.get_instance_detail(vm1.id)
        except Exception as e:
            assert e.code == 404
        else:
            raise Exception(('Instance {0} not deleted after '
                             '"reclaim_interval_timeout"').format(vm1.name))

        # Update volume information
        volume = self.os_conn.cinder.volumes.get(volume.id)

        # ~! BUG !~: https://bugs.launchpad.net/cinder/+bug/1463856
        # Check that volume is released now and has an Available state
        assert volume.status == 'available'
        # Check volume is not attached
        assert volume.attachments == []

        # Attach the volume to vm2 instance
        self.os_conn.nova.volumes.create_server_volume(
            server_id=vm2.id, volume_id=volume.id, device='/dev/vdb')

        # Check volume status after re-attach
        assert self.os_conn.cinder.volumes.get(volume.id).status == 'in-use'

    @pytest.mark.testrail_id('842495')
    @pytest.mark.parametrize(
        'set_recl_inst_interv', [recl_interv_long], indirect=True)
    def test_force_delete_inst_before_deferred_cleanup(
            self, set_recl_inst_interv, instances, volumes):
        """Force delete of instance before deferred cleanup
        Actions:
        1. Update '/etc/nova/nova.conf' with long 'reclaim_instance_interval'
        and restart Nova on all nodes;
        2. Create net and subnet;
        3. Create and run two instances (vm1, vm2) inside same net;
        4. Create a volume and attach it to an instance vm1;
        5. Delete instance vm1 and check that it's in 'SOFT_DELETE' state;
        6. Delete instance vm1 with 'force' option and check that it's not
        present.
        7. Check that volume is released now and has an Available state;
        8. Attach the volume to vm2 instance to ensure that the volume's reuse
        doesn't call any errors.
        """
        timeout = 60  # (sec) timeout to wait instance for status change

        # Create two vms
        vm1, vm2 = instances

        # Create a volume and attach it to an instance vm1
        volume = common_functions.create_volume(
            self.os_conn.cinder, image_id=None)
        self.os_conn.nova.volumes.create_server_volume(
            server_id=vm1.id, volume_id=volume.id, device='/dev/vdb')
        volumes.append(volume)

        # Delete instance vm1 and check that it's in "SOFT_DELETED" state
        common_functions.delete_instance(self.os_conn.nova, vm1.id)
        assert vm1 not in self.os_conn.get_servers()
        common_functions.wait(
            lambda: self.os_conn.server_status_is(vm1, 'SOFT_DELETED'),
            timeout_seconds=timeout, sleep_seconds=5,
            waiting_for='instance {0} changes status to SOFT_DELETED'.format(
                vm1.name))

        # Force delete and check vm1 not present
        common_functions.delete_instance(self.os_conn.nova, vm1.id, force=True)
        common_functions.wait(
            lambda: self.os_conn.is_server_deleted(vm1.id),
            timeout_seconds=timeout, sleep_seconds=5,
            waiting_for='instance {0} to be forced deleted'.format(vm1.name))

        # Check that volume is released now and has an Available state
        assert common_functions.check_volume_status(
            self.os_conn.cinder, volume.id, 'available', 1)

        # Check volume is not attached
        assert self.os_conn.cinder.volumes.get(volume.id).attachments == []

        # Attach the volume to vm2 instance
        self.os_conn.nova.volumes.create_server_volume(
            server_id=vm2.id, volume_id=volume.id, device='/dev/vdb')
        # Check volume status is 'in-use' after re-attach
        assert common_functions.check_volume_status(
            self.os_conn.cinder, volume.id, 'in-use', 1)
        # Check that volume has correct server id
        volume = self.os_conn.cinder.volumes.get(volume.id)
        assert volume.attachments[0]['server_id'] == vm2.id


@pytest.mark.undestructive
class TestBugVerification(TestBase):

    @pytest.yield_fixture
    def ubuntu_image_id(self, os_conn):
        logger.info('Creating ubuntu image')
        image = os_conn.glance.images.create(name="image_ubuntu",
                                             disk_format='qcow2',
                                             container_format='bare')
        with file_cache.get_file(settings.UBUNTU_QCOW2_URL) as f:
            os_conn.glance.images.upload(image.id, f)
        os_conn.wait_images_active([image])
        logger.info('Ubuntu image created')
        yield image.id
        os_conn.glance.images.delete(image.id)

    @pytest.yield_fixture
    def flavors(self, os_conn):
        # create 2 flavors
        flavors = []
        flavor_little = self.os_conn.nova.flavors.create(
            name='test-eph',
            ram=1024, vcpus=1, disk=5, ephemeral=1)
        flavor_large = self.os_conn.nova.flavors.create(
            name='test-eph-large',
            ram=2048, vcpus=1, disk=5, ephemeral=1)
        flavors.extend((flavor_little, flavor_large))
        yield flavors
        for flavor in flavors:
            os_conn.nova.flavors.delete(flavor)

    @pytest.fixture
    def instance(self, request, os_conn, keypair, ubuntu_image_id, flavors,
                 security_group):
        zone = os_conn.nova.availability_zones.find(zoneName="nova")
        compute_fqdn = zone.hosts.keys()[0]
        network = os_conn.int_networks[0]

        boot_marker = "nova_856599_boot_done"

        userdata = '\n'.join([
            '#!/bin/bash -v',
            'apt-get install -y qemu-utils',
            'echo {marker}'
        ]).format(marker=boot_marker)

        # create instance
        instance = os_conn.create_server(
            name='server-test-ubuntu',
            availability_zone='nova:{}'.format(compute_fqdn),
            key_name=keypair.name,
            image_id=ubuntu_image_id,
            flavor=flavors[0].id,
            userdata=userdata,
            nics=[{'net-id': network['id']}],
            security_groups=[security_group.id],
            wait_for_active=False,
            wait_for_avaliable=False)

        request.addfinalizer(
            lambda: common_functions.delete_instance(os_conn.nova,
                                                     instance.id,
                                                     True))

        os_conn.wait_servers_active([instance])
        os_conn.wait_marker_in_servers_log([instance], boot_marker)
        instance.get()
        return instance

    @pytest.yield_fixture
    def nova_upd_cfg_on_computes(self):
        """Set 'use_cow_images'=False in nova cfg file.
        Then restart nova service
        """
        def wait_nova_alive():
            common_functions.wait(
                self.os_conn.is_nova_ready,
                timeout_seconds=60 * 3,
                expected_exceptions=Exception,
                waiting_for="Nova services to be alive")

        # change nova config on all computes and restart nova service
        nova_cfg_path = '/etc/nova/nova.conf'
        restart_cmd = 'service nova-compute restart'

        logger.debug("Set 'use_cow_images=False' in %s" % nova_cfg_path)
        computes = self.os_conn.env.get_nodes_by_role('compute')
        for node in computes:
            with node.ssh() as remote:
                remote.check_call('cp {0} {0}.bak'.format(nova_cfg_path))
                parser = configparser.RawConfigParser()
                with remote.open(nova_cfg_path) as f:
                    parser.readfp(f)
                parser.set('DEFAULT', 'use_cow_images', False)
                with remote.open(nova_cfg_path, 'w') as f:
                    parser.write(f)
                remote.check_call(restart_cmd)
        wait_nova_alive()
        yield
        # restore configs
        logger.debug("Revert changes in %s" % nova_cfg_path)
        for node in computes:
            with node.ssh() as remote:
                result = remote.execute('cp {0}.bak {0}'.format(nova_cfg_path))
                if result.is_ok:
                    remote.check_call(restart_cmd)
        wait_nova_alive()

    def get_block_device_by_mount(self, remote, path):
        """Returns block device which is mounted at specified path

        Returns looks like "/dev/sda1"
        Raises an exception if there is no mounts on specified path
        """
        result = remote.check_call('cat /proc/mounts')
        for row in result['stdout']:
            cells = row.split()
            dev, mount_point = cells[:2]
            if mount_point == path and dev.startswith('/dev'):
                return dev
        else:
            raise Exception("Can't find block device "
                            "mounted at {}".format(path))

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

    @pytest.mark.testrail_id('856599')
    @pytest.mark.usefixtures('nova_upd_cfg_on_computes')
    def test_image_access_host_device_when_resizing(self, instance, keypair,
                                                    flavors):
        """Test to cover bugs #1552683 and #1548450 (CVE-2016-2140)

        1. Check use_cow_images=0 value in nova config on all computes
        2. Start instance with ephemeral disk
        3. umount /mnt in instance
        4. On instance create qcow2 image with baking_file
            linked to target host device in ephemeral block device
            something like: qemu-img create -f qcow2
            -o backing_file=/dev/sda3,backing_fmt=raw /dev/vdb 20G
        5. Change flavor or migrate instance
        6. Check that /vdb is not linked to host device

        Duration: 2-5 minutes
        """
        compute_fqdn = getattr(instance, 'OS-EXT-SRV-ATTR:host')
        compute = self.env.find_node_by_fqdn(compute_fqdn)
        with compute.ssh() as remote:
            root_dev = self.get_block_device_by_mount(remote, '/')

        instance_ssh = self.os_conn.ssh_to_instance(self.env,
                                                    instance,
                                                    vm_keypair=keypair,
                                                    username='ubuntu')

        # validate + umount /mnt and create qcow image
        with instance_ssh as remote:
            eph_dev = self.get_block_device_by_mount(remote, '/mnt')
            remote.check_call('sudo umount /mnt')
            remote.check_call('sudo qemu-img create -f qcow2'
                              ' -o backing_file={host_dev},backing_fmt=raw '
                              '{eph_dev} 20G'.format(eph_dev=eph_dev,
                                                     host_dev=root_dev))

        # resize instance
        instance.resize(flavors[1].id)
        common_functions.wait(
            lambda: self.os_conn.server_status_is(instance, 'VERIFY_RESIZE'),
            timeout_seconds=2 * 60,
            waiting_for='instance became to VERIFY_RESIZE status')
        # confirm resize
        instance.get()
        instance.confirm_resize()
        common_functions.wait(
            lambda: self.os_conn.is_server_ssh_ready(instance),
            timeout_seconds=2 * 60,
            waiting_for="Instance to be accessed via ssh")

        # validate /mnt is not contains files
        with instance_ssh as remote:
            cmd_result = remote.check_call('ls /mnt')
            assert cmd_result.stdout_string == ''

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


class TestServicesRestart(TestBase):

    test_message = 'Some test message for test'  # message to write in files

    @pytest.yield_fixture
    def volume(self, os_conn):
        logger.info('Create volume')
        image = os_conn.nova.images.find(name='TestVM')
        volume = common_functions.create_volume(os_conn.cinder, image.id, 1)
        yield volume

    def restart_nova_services(self, nodes):
        """Restart all active nova services on all controllers
        and/or computes.
        """
        get_alive_services = ("initctl list | grep running | grep nova | "
                              "awk '{ print $1 }'")
        logger.debug('Restart nova services on {0}'.format(nodes))
        for node in nodes:
            with node.ssh() as remote:
                # get alive services
                out = remote.check_call(get_alive_services).stdout_string
                alive_services = out.split()
                # restart alive services one-by-one
                for nova_service in alive_services:
                    remote.check_call(
                        'restart {0}'.format(nova_service),
                        verbose=False)

    def ping_public_ip_from_vms(self, vms, key, username='cirros'):
        for vm in vms:
            network_checks.check_ping_from_vm(
                self.env, self.os_conn, vm, key, vm_login=username)

    def mount_and_create_file_on_volume(self, vm, volume, vm_keypair):
        # Attach volume to vm
        self.os_conn.nova.volumes.create_server_volume(
            vm.id, volume.id)
        # Make attached volume usable inside VM
        with self.os_conn.ssh_to_instance(
                self.env, vm, vm_keypair=vm_keypair,
                username='ubuntu') as remote:
            # Create FS on mounted volume
            res = remote.check_call(                 # find exact mount point
                'lsblk -rdn -o NAME | tail -n1').stdout_string.strip()
            cmd_1 = 'sudo mkfs -t ext3 /dev/{}'.format(res)
            cmd_2 = 'sudo mkdir /mnt/{}'.format(res)
            cmd_3 = 'sudo mount /dev/{0} /mnt/{0}'.format(res)
            remote.check_call(cmd_1)
            remote.check_call(cmd_2)
            remote.check_call(cmd_3)
            filename = '/mnt/{0}/file1.txt'.format(res)
            tmp_filename = '/tmp/file1.txt'
            # Write message to tmp file
            with remote.open(tmp_filename, 'w') as f:
                f.write(self.test_message)
            # Put tmp file to mounted volume
            remote.check_call('sudo mv {0} {1}'.format(tmp_filename, filename))
            return filename

    def control_cindervolume_service(self, action='start'):
        """Performs start/stop/.. 'cinder-volume' service on all controllers"""
        controllers = self.env.get_nodes_by_role('controller')
        for controller in controllers:
            with controller.ssh() as remote:
                remote.check_call('service cinder-volume %s' % action)

    def control_novacompute_service(self, action='start'):
        """Performs start/stop/.. 'nova-compute' service on all computes"""
        computes = self.env.get_nodes_by_role('compute')
        for compute in computes:
            with compute.ssh() as remote:
                remote.check_call('service nova-compute %s' % action)

    @pytest.mark.testrail_id('1295467')
    def test_restart_all_nova_services(
            self, os_conn, keypair, security_group):
        """Nova: restart all Nova services.

        Actions:
        1. Boot first VM and verify that we can ping this VM and login to this
        VM via SSH;
        2. Restart all running nova services on all controllers;
        3. Boot second VM and verify that we can ping this VM and login to this
        VM via SSH and can login to first VM;
        4. Restart all running nova services on all computes;
        5. Boot third VM and verify that we can ping this VM and login to this
        VM via SSH and can login to rest two as well;
        6. Restart all running nova services on all controllers and computes;
        7. Delete all VMs and verify that we can successfully delete VMs after
        the restart of all Nova services;
        """
        int_net_id = os_conn.nova.networks.find(label='admin_internal_net').id
        controllers = self.env.get_nodes_by_role('controller')
        computes = self.env.get_nodes_by_role('compute')

        # Create and check connection for the first VM
        vm1 = os_conn.create_server(
            name='server01',
            key_name=keypair.id,
            nics=[{'net-id': int_net_id}],
            security_groups=[security_group.id])
        self.ping_public_ip_from_vms([vm1], keypair)

        # Restart nova services on all controllers
        self.restart_nova_services(controllers)

        # Create second WM
        vm2 = os_conn.create_server(
            name='server02',
            key_name=keypair.id,
            nics=[{'net-id': int_net_id}],
            security_groups=[security_group.id])
        self.ping_public_ip_from_vms([vm1, vm2], keypair)

        # Restart nova services on all computes
        self.restart_nova_services(computes)

        # Check two VMs' connection
        os_conn.wait_servers_ssh_ready([vm1, vm2])
        self.ping_public_ip_from_vms([vm1, vm2], keypair)

        # Create third WM
        vm3 = os_conn.create_server(
            name='server03',
            key_name=keypair.id,
            nics=[{'net-id': int_net_id}],
            security_groups=[security_group.id])

        # Restart nova services on all computes+controllers
        self.restart_nova_services(controllers + computes)

        # Check all three VMs' connection
        os_conn.wait_servers_ssh_ready([vm1, vm2, vm3])
        self.ping_public_ip_from_vms([vm1, vm2, vm3], keypair)

        # After services restart instances should be deleted with no errors
        for vm in [vm1, vm2, vm3]:
            vm.delete()
        os_conn.wait_servers_deleted([vm1, vm2, vm3])

    @pytest.mark.check_env_('is_ceph_enabled')
    @pytest.mark.testrail_id('1295483')
    def test_stop_cinder_nova(
            self, os_conn, keypair, security_group, volume, ubuntu_image_id):
        """Nova: Cinder+Nova. Boot vm, attach volume,
        stop cinder-volume and nova-compute.

        Actions:
        1) Boot VM with Ubuntu and verify that we can ping this VM and login
        to this VM via SSH;
        2) Create volume and attach it to "test1" VM, mount this volume on VM
        and create file(test1.txt with text) on the volume;
        3) Stop service cinder-volume on all controllers;
        4) Stop service nova-compute on compute nodes;
        5) Login to this VM via SSH and create file(test2.txt with same
        content as in test1.txt);
        6) Read text from test2.txt, test1.txt and compare it;
        7) Start nova-compute service on compute nodes;
        8) Start cinder-volume on all controllers;
        9) Detach and delete volume, delete VM.
        """
        int_net_id = os_conn.nova.networks.find(label='admin_internal_net').id
        flavor = os_conn.nova.flavors.find(name='m1.small')

        # Create and check connection for the first VM
        vm1 = os_conn.create_server(
            name='server01',
            image_id=ubuntu_image_id,
            flavor=flavor.id,
            key_name=keypair.id,
            nics=[{'net-id': int_net_id}],
            security_groups=[security_group.id])
        self.ping_public_ip_from_vms([vm1], keypair, username='ubuntu')

        # Mount volume to vm and create file on it
        filename_on_vl = self.mount_and_create_file_on_volume(
            vm1, volume, keypair)

        # Stop cinder-volume and nova-compute service on nodes
        self.control_cindervolume_service('stop')
        self.control_novacompute_service('stop')

        # Write new file on vm
        filename_on_vm = '/tmp/file2.txt'
        with os_conn.ssh_to_instance(
                self.env, vm1, vm_keypair=keypair,
                username='ubuntu') as remote:
            # Write message to a new file on VM
            with remote.open(filename_on_vm, 'w') as f:
                f.write(self.test_message)
            # Compare file on VM and file on volume attache to VM
            remote.check_call('cmp {0} {1}'.format(
                filename_on_vl, filename_on_vm))

        # Start services back
        self.control_cindervolume_service('start')
        self.control_novacompute_service('start')

        # Detach, delete volume and VM
        os_conn.nova.volumes.delete_server_volume(vm1.id, volume.id)
        common_functions.wait(
            lambda: (os_conn.cinder.volumes.get(volume.id)
                     .status == 'available'),
            timeout_seconds=60 * 2,
            sleep_seconds=10,
            waiting_for='volume to became available')
        volume.delete()
        vm1.delete()
