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

from mos_tests.environment.os_actions import InstanceError
from mos_tests.functions import common

page_1gb = 1048576
page_2mb = 2048


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
        if size is None:
            assert not root.find('memoryBacking'), "Huge pages are unexpected"
        else:
            page_size = root.find('memoryBacking').find('hugepages').find(
                'page').get('size')
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

    def create_volume_from_vm(self, os_conn, vm, size=1):
        image = os_conn.nova.servers.create_image(vm, image_name="image_vm2")
        common.wait(lambda: os_conn.nova.images.get(image).status == 'ACTIVE',
                    timeout_seconds=10 * 60,
                    waiting_for='image changes status to ACTIVE')
        volume = common.create_volume(os_conn.cinder, image, size=size)
        return volume.id

    def migrate(self, os_conn, vm):
        os_conn.nova.servers.migrate(vm)
        common.wait(
            lambda: os_conn.server_status_is(vm, 'VERIFY_RESIZE'),
            timeout_seconds=3 * 60,
            waiting_for='instance {} changes status to VERIFY_RESIZE during '
                        'migration'.format(vm.name))
        os_conn.nova.servers.confirm_resize(vm)
        common.wait(lambda: os_conn.is_server_active(vm),
                    timeout_seconds=5 * 60,
                    waiting_for='instance {} changes status to ACTIVE after '
                                'migration'.format(vm.name))
        return os_conn.nova.servers.get(vm)

    def resize(self, os_conn, vm, flavor_to_resize):
        os_conn.nova.servers.resize(vm, flavor_to_resize)
        common.wait(
            lambda: os_conn.server_status_is(vm, 'VERIFY_RESIZE'),
            timeout_seconds=3 * 60,
            waiting_for='instance {} changes status to VERIFY_RESIZE during '
                        'resizing'.format(vm.name))
        os_conn.nova.servers.confirm_resize(vm)
        common.wait(lambda: os_conn.is_server_active(vm),
                    timeout_seconds=5 * 60,
                    waiting_for='instance {} changes status to ACTIVE after '
                                'resizing'.format(vm.name))
        return os_conn.nova.servers.get(vm)

    def check_cpu_for_vm(self, os_conn, vm, numa_count, host_conf):
        """Checks vcpus allocation for vm. Vcpus should be on the same numa
        node if flavor metadata 'hw:numa_nodes':1. In case of
        'hw:numa_nodes':2 vcpus from the different numa nodes are used.

        :param os_conn: os_conn
        :param vm: vm to check cpu
        :param numa_count: count of numa nodes for vm (depends on flavor)
        :param host_conf: (dictionary) host configuration, vcpu's distribution
        per numa node. It can be calculated by method
        get_cpu_distribition_per_numa_node(env) from conftest.py
        :return:
        """
        name = getattr(os_conn.nova.servers.get(vm),
                       "OS-EXT-SRV-ATTR:instance_name")
        host = os_conn.env.find_node_by_fqdn(
            getattr(os_conn.nova.servers.get(vm), "OS-EXT-SRV-ATTR:host"))
        with host.ssh() as remote:
            cmd = "virsh dumpxml {0}".format(name)
            dump = remote.execute(cmd)
        root = ElementTree.fromstring(dump.stdout_string)
        actual_numa = root.find('numatune').findall('memnode')
        assert len(actual_numa) == numa_count
        vcpus = [int(v.get('cpuset'))
                 for v in root.find('cputune').findall('vcpupin')]
        cnt_of_used_numa = 0
        for host in host_conf.values():
            if set(host) & set(vcpus):
                cnt_of_used_numa += 1
        assert cnt_of_used_numa == numa_count, (
            "Unexpected count of numa nodes in use: {0} instead of {1}".
            format(cnt_of_used_numa, numa_count))

    def compute_change_state(self, os_conn, devops_env, host, state):
        def is_compute_state():
            hypervisor = [i for i in os_conn.nova.hypervisors.list()
                          if i.hypervisor_hostname == host][0]
            return hypervisor.state == state

        compute = os_conn.env.find_node_by_fqdn(host)
        devops_node = devops_env.get_node_by_fuel_node(compute)
        if state == 'down':
            devops_node.suspend()
        else:
            devops_node.resume()
        common.wait(is_compute_state,
                    timeout_seconds=20 * 60,
                    waiting_for='compute is {}'.format(state))

    def evacuate(self, os_conn, devops_env, vm, on_shared_storage=True,
                 password=None):
        os_conn.nova.servers.evacuate(vm, on_shared_storage=on_shared_storage)
        try:
            common.wait(
                lambda: os_conn.is_server_active(vm), timeout_seconds=5 * 60,
                waiting_for='instance {} changes status to ACTIVE after '
                            'evacuation'.format(vm.name))
            return os_conn.nova.servers.get(vm)
        except InstanceError:
            host = getattr(vm, "OS-EXT-SRV-ATTR:host")
            self.compute_change_state(os_conn, devops_env, host, state='up')
            raise

    def cpu_load(self, env, os_conn, vm, vm_keypair=None, vm_login=None,
                 vm_password=None, action='start'):
        if action == 'start':
            cmd = 'cpulimit -l 50 -- gzip -9 < /dev/urandom > /dev/null'
            with os_conn.ssh_to_instance(env, vm, vm_keypair=vm_keypair,
                                         username=vm_login) as vm_remote:
                vm_remote.check_call(cmd)
        if action == 'stop':
            cmd = "ps -aux | grep cpulimit | awk '{print $2}'"
            with os_conn.ssh_to_instance(env, vm, vm_keypair=vm_keypair,
                                         username=vm_login) as vm_remote:
                result = vm_remote.check_call(cmd)
                pid = result['stdout'][0]
                result = vm_remote.execute('kill -9 {}'.format(pid))
                assert not result['exit_code'], "kill failed {}".format(result)

    def delete_servers(self, os_conn):
        os_conn.delete_servers()
        common.wait(
            lambda: len(os_conn.nova.servers.list()) == 0,
            timeout_seconds=3 * 60,
            waiting_for='instances are deleted')
