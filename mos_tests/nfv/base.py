#    Copyright 2016 Mirantis, Inc.
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
import xml.etree.ElementTree as ElementTree

from mos_tests.functions import common


class TestBaseNFV(object):

    def check_pages(self, os_conn, host, total_pages, free_pages):
        compute = os_conn.env.find_node_by_fqdn(host)
        with compute.ssh() as remote:
            total = remote.execute(
                "grep HugePages_Total /proc/meminfo")['stdout']
            assert str(total_pages) in total[0], "Unexpected HugePages_Total"
            free = remote.execute(
                "grep HugePages_Free /proc/meminfo")['stdout']
            assert str(free_pages) in free[0], "Unexpected HugePages_Free"

    def check_instance_page_size(self, os_conn, vm, size):
        name = getattr(os_conn.nova.servers.get(vm),
                       "OS-EXT-SRV-ATTR:instance_name")
        host = os_conn.env.find_node_by_fqdn(
            getattr(os_conn.nova.servers.get(vm), "OS-EXT-SRV-ATTR:host"))
        with host.ssh() as remote:
            cmd = "virsh dumpxml {0}".format(name)
            res = remote.execute(cmd)
        root = ElementTree.fromstring(res.stdout_string)
        page_size = root.find('memoryBacking').find('hugepages').find('page')\
            .get('size')
        assert str(size) == page_size, "Unexpected package size"

    def live_migrate(self, os_conn, vm, host, block_migration=True,
                     disk_over_commit=False):

        os_conn.nova.servers.live_migrate(
            vm, host, block_migration=block_migration,
            disk_over_commit=disk_over_commit)
        common.wait(lambda: os_conn.is_server_active(vm),
                    timeout_seconds=10 * 60,
                    waiting_for='instance {} changes status to ACTIVE after '
                                'live migration'.format(vm.name))

    def create_volume_from_vm(self, os_conn, vm):
        image = os_conn.nova.servers.create_image(vm, image_name="image_vm2")
        common.wait(lambda: os_conn.nova.images.get(image).status == 'ACTIVE',
                    timeout_seconds=10 * 60,
                    waiting_for='image changes status to ACTIVE')
        volume = common.create_volume(os_conn.cinder, image,
                                      volume_type='volumes_lvm')
        return volume.id

    def migrate(self, os_conn, vm):
        os_conn.nova.servers.migrate(vm)
        common.wait(
            lambda: os_conn.nova.servers.get(vm).status == 'VERIFY_RESIZE',
            timeout_seconds=3 * 60,
            waiting_for='instance {} changes status to VERIFY_RESIZE during '
                        'migration'.format(vm.name))
        os_conn.nova.servers.confirm_resize(vm)
        common.wait(lambda: os_conn.is_server_active(vm),
                    timeout_seconds=5 * 60,
                    waiting_for='instance {} changes status to ACTIVE after '
                                'migration'.format(vm.name))
        return os_conn.nova.servers.get(vm)
