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
import os
import time

import pytest

from mos_tests.functions import common
from mos_tests import settings

logger = logging.getLogger(__name__)


@pytest.mark.undestructive
class TestWindowCompatibility(object):
    """Basic automated tests for OpenStack Windows Compatibility verification.
    """

    video_ram_mb = 16

    @pytest.fixture(autouse=True)
    def variables(self, env, os_conn):
        self.env = env
        self.os_conn = os_conn

    def is_instance_ready(self, instance):
        """Determine instance is ready by mean brightness of screenshot

        Minimal registered level for booted machne was 33, so 25 is used as
        threshold value.
        """
        hypervisor_hostname = getattr(instance,
                                      'OS-EXT-SRV-ATTR:hypervisor_hostname')
        instance_name = getattr(instance, 'OS-EXT-SRV-ATTR:instance_name')
        compute_node = self.env.find_node_by_fqdn(hypervisor_hostname)
        screenshot_path = '/tmp/instance_screenshot.ppm'
        with compute_node.ssh() as remote:
            remote.check_call(
                'virsh send-key {name} --codeset win32 VK_TAB'.format(
                    name=instance_name))
            remote.check_call('virsh screenshot {name} --file {path}'.format(
                name=instance_name,
                path=screenshot_path),
                              verbose=False)
            with remote.open(screenshot_path, 'rb') as f:
                data = f.read()
        with open('temp/{name}_{time:.0f}.ppm'.format(name=self.test_name,
                                                      time=int(time.time())),
                  'wb') as f:
            f.write(data)
        return sum(ord(x) for x in data) / len(data) > 25

    def wait_to_boot(self, instance):
        common.wait(
            lambda: self.is_instance_ready(instance),
            timeout_seconds=60 * 60,
            sleep_seconds=60,
            waiting_for='windows instance to boot')

    @pytest.yield_fixture(scope='class')
    def image(self, os_conn):
        image_path = os.path.join(settings.TEST_IMAGE_PATH,
                                  settings.WIN_SERVER_QCOW2)
        video_ram = str(self.video_ram_mb)
        image = os_conn.glance.images.create(name='win_server_2012_r2',
                                             disk_format='qcow2',
                                             container_format='bare',
                                             cpu_arch='x86_64',
                                             os_distro='windows',
                                             hw_video_model='vga',
                                             hw_video_ram=video_ram)
        with open(image_path, 'rb') as f:
            os_conn.glance.images.upload(image.id, f)
        yield image
        os_conn.glance.images.delete(image.id)

    @pytest.yield_fixture(scope='class')
    def sec_group(self, os_conn):
        sec_group = os_conn.create_sec_group_for_ssh()
        yield sec_group
        os_conn.delete_security_group(name=sec_group.name)

    @pytest.yield_fixture(scope='class')
    def floating_ip(self, os_conn):
        pool_name = os_conn.nova.floating_ip_pools.list()[0].name
        ip = os_conn.nova.floating_ips.create(pool_name)
        yield ip
        os_conn.nova.floating_ips.delete(ip)

    @pytest.yield_fixture(scope='class')
    def flavor(self, os_conn):
        flavor = os_conn.nova.flavors.create('win_flavor',
                                             ram=4096,
                                             vcpus=1,
                                             disk=25)
        flavor.set_keys({"hw_video:ram_max_mb": self.video_ram_mb})
        yield flavor
        flavor.delete()

    @pytest.yield_fixture
    def instance(self, request, os_conn, image, sec_group, floating_ip,
                 flavor):
        func_name = request.node.function.func_name
        self.test_name = func_name.split('test_')[-1]

        int_networks = os_conn.neutron.list_networks(
            **{'router:external': False,
               'status': 'ACTIVE'})['networks']
        network_id = int_networks[0]['id']

        instance = os_conn.create_server(name="win_server_2012_r2",
                                         image_id=image.id,
                                         flavor=flavor.id,
                                         nics=[{'net-id': network_id}],
                                         security_groups=[sec_group.name],
                                         timeout=10 * 60,
                                         wait_for_avaliable=False)

        instance.add_floating_ip(floating_ip)

        self.wait_to_boot(instance)

        yield instance

        instance.remove_floating_ip(floating_ip)
        instance.delete()
        common.wait(lambda: os_conn.is_server_deleted(instance),
                    timeout_seconds=3 * 60,
                    waiting_for='instance to be deleted')

    @pytest.mark.testrail_id('634680')
    def test_create_instance_with_windows_image(self, request, floating_ip):
        """This test checks that instance with Windows image could be created

        Steps:
        1. Upload Windows 2012 Server image to Glance
        2. Create VM with this Windows image
        3. Assign floating IP to this VM
        4. Ping this VM and verify that we can ping it
        """
        request.getfuncargvalue("instance")
        ping_result = common.ping_command(floating_ip.ip)
        assert ping_result, "Instance is not reachable"

    @pytest.mark.testrail_id('634681')
    def test_pause_and_unpause_instance_with_windows_image(self, instance,
                                                           floating_ip):
        """This test checks that instance with Windows image could be paused
        and unpaused

        Steps:
        1. Upload Windows 2012 Server image to Glance
        2. Create VM with this Windows image
        3. Assign floating IP to this VM
        4. Ping this VM and verify that we can ping it
        5. Pause this VM
        6. Verify that we can't ping it
        7. Unpause it and verify that we can ping it again
        8. Reboot VM
        9. Verify that we can ping this VM after reboot.
        :return: Nothing
        """
        # Initial check
        ping_result = common.ping_command(floating_ip.ip)
        assert ping_result, "Instance is not reachable"
        # Paused state check
        instance.pause()
        # Make sure that the VM in 'Paused' state
        ping_result = common.ping_command(floating_ip.ip,
                                          should_be_available=False)
        assert ping_result, "Instance is reachable"
        # Unpaused state check
        instance.unpause()
        # Make sure that the VM in 'Unpaused' state
        ping_result = common.ping_command(floating_ip.ip)
        assert ping_result, "Instance is not reachable"

        # Reboot the VM and make sure that we can ping it
        instance.reboot(reboot_type='HARD')
        instance_status = common.check_inst_status(
            self.os_conn.nova,
            instance.id,
            'ACTIVE')
        instance = self.os_conn.nova.servers.get(instance.id)
        if not instance_status:
            raise AssertionError(
                "Instance status is '{0}' instead of 'ACTIVE".format(
                    instance.status))

        self.wait_to_boot(instance)

        # Waiting for up-and-run of Virtual Machine after reboot
        ping_result = common.ping_command(floating_ip.ip)
        assert ping_result, "Instance is not reachable"

    @pytest.mark.testrail_id('638381')
    def test_suspend_and_resume_instance_with_windows_image(self, instance,
                                                            floating_ip):
        """This test checks that instance with Windows image can be suspended
        and resumed

        Steps:
        1. Upload Windows 2012 Server image to Glance
        2. Create VM with this Windows image
        3. Assign floating IP to this VM
        4. Ping this VM and verify that we can ping it
        5. Suspend VM
        6. Verify that we can't ping it
        7. Resume and verify that we can ping it again.
        8. Reboot VM
        9. Verify that we can ping this VM after reboot.
        :return: Nothing
        """
        # Initial check
        ping_result = common.ping_command(floating_ip.ip)
        assert ping_result, "Instance is not reachable"
        # Suspend state check
        instance.suspend()
        # Make sure that the VM in 'Suspended' state
        ping_result = common.ping_command(
            floating_ip.ip,
            should_be_available=False
        )
        assert ping_result, "Instance is reachable"
        # Resume state check
        instance.resume()
        # Make sure that the VM in 'Resume' state
        ping_result = common.ping_command(floating_ip.ip)
        assert ping_result, "Instance is not reachable"

        # Reboot the VM and make sure that we can ping it
        instance.reboot(reboot_type='HARD')
        instance_status = common.check_inst_status(
            self.os_conn.nova,
            instance.id,
            'ACTIVE')
        instance = self.os_conn.nova.servers.get(instance.id)
        if not instance_status:
            raise AssertionError(
                "Instance status is '{0}' instead of 'ACTIVE".format(
                    instance.status))

        self.wait_to_boot(instance)

        # Waiting for up-and-run of Virtual Machine after reboot
        ping_result = common.ping_command(floating_ip.ip)
        assert ping_result, "Instance is not reachable"

    @pytest.mark.testrail_id('634682')
    def test_live_migration_for_windows_instance(self, instance, floating_ip):
        """This test checks that instance with Windows Image could be
        migrated without any issues

        Steps:
        1. Upload Windows 2012 Server image to Glance
        2. Create VM with this Windows image
        3. Assign floating IP to this VM
        4. Ping this VM and verify that we can ping it
        5. Migrate this VM to another compute node
        6. Verify that live Migration works fine for Windows VMs
        and we can successfully ping this VM
        7. Reboot VM and verify that
        we can successfully ping this VM after reboot.

        :return: Nothing
        """
        # 1. 2. 3. -> Into setUp function
        # 4. Ping this VM and verify that we can ping it
        hypervisor_hostname_attribute = "OS-EXT-SRV-ATTR:hypervisor_hostname"
        ping_result = common.ping_command(floating_ip.ip)
        assert ping_result, "Instance is not reachable"
        hypervisors = {h.hypervisor_hostname: h for h
                       in self.os_conn.nova.hypervisors.list()}
        old_hyper = getattr(instance,
                            hypervisor_hostname_attribute)
        logger.info("Old hypervisor is: {}".format(old_hyper))
        new_hyper = [h for h in hypervisors.keys() if h != old_hyper][0]
        logger.info("New hypervisor is: {}".format(new_hyper))
        # Execute the live migrate
        instance.live_migrate(new_hyper, block_migration=True)

        instance = self.os_conn.nova.servers.get(instance.id)
        end_time = time.time() + 60 * 10
        debug_string = "Waiting for changes."
        while getattr(instance,
                      hypervisor_hostname_attribute) != new_hyper:
            if time.time() > end_time:
                # it can fail because of this issue
                # https://bugs.launchpad.net/mos/+bug/1544564
                logger.info(debug_string)
                raise AssertionError(
                    "Hypervisor is not changed after live migration")
            time.sleep(30)
            debug_string += "."
            instance = self.os_conn.nova.servers.get(instance.id)
        logger.info(debug_string)
        assert self.instance.status == 'ACTIVE'
        # Ping the Virtual Machine
        ping_result = common.ping_command(floating_ip.ip)
        assert ping_result, "Instance is not reachable"

        # Reboot the VM and make sure that we can ping it
        instance.reboot(reboot_type='HARD')
        instance_status = common.check_inst_status(
            self.os_conn.nova,
            instance.id,
            'ACTIVE')
        instance = self.os_conn.nova.servers.get(instance.id)
        if not instance_status:
            raise AssertionError(
                "Instance status is '{0}' instead of 'ACTIVE".format(
                    instance.status))

        self.wait_to_boot(instance)

        # Waiting for up-and-run of Virtual Machine after reboot
        ping_result = common.ping_command(floating_ip.ip)
        assert ping_result, "Instance is not reachable"
