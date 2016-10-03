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
import contextlib
import re
import xml.etree.ElementTree as ElementTree

from mos_tests.environment.os_actions import InstanceError
from mos_tests.functions import common
from mos_tests.functions import network_checks

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

    def get_instance_page_size(self, os_conn, vm):
        root = self.get_vm_dump(os_conn, vm)
        if root.find('memoryBacking'):
            page_size = root.find('memoryBacking').find('hugepages').find(
                'page').get('size')
            return int(page_size)
        else:
            return None

    def live_migrate(self, os_conn, vm, host, block_migration=True,
                     disk_over_commit=False):

        os_conn.nova.servers.live_migrate(vm, host,
                                          block_migration=block_migration,
                                          disk_over_commit=disk_over_commit)
        common.wait(lambda: os_conn.is_server_active(vm),
                    timeout_seconds=10 * 60,
                    waiting_for='instance {} changes status to ACTIVE after '
                                'live migration'.format(vm.name))
        common.wait(lambda: getattr(os_conn.nova.servers.get(vm),
                                    'OS-EXT-SRV-ATTR:host') == host,
                    timeout_seconds=10 * 60,
                    waiting_for='new vm {0} host after migration'.format(vm))

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

    def check_cpu_for_vm(self, os_conn, vm, numa_count, host_conf,
                         exp_vcpupin=None):
        """Checks vcpus allocation for vm. Vcpus should be on the same numa
        node if flavor metadata 'hw:numa_nodes':1. In case of
        'hw:numa_nodes':2 vcpus from the different numa nodes are used.

        :param os_conn: os_conn
        :param vm: vm to check cpu
        :param numa_count: count of numa nodes for vm (depends on flavor)
        :param host_conf: (dictionary) host configuration, vcpu's distribution
        per numa node. It can be calculated by method
        get_cpu_distribition_per_numa_node(env) from conftest.py
        :param exp_vcpupin: vcpu distribution per numa node. Example:
        {'numa0': [1, 3, 4], 'numa1': [2]}
        :return:
        """
        root = self.get_vm_dump(os_conn, vm)
        actual_numa = root.find('numatune').findall('memnode')
        assert len(actual_numa) == numa_count

        vm_vcpupins = [
            {'id': int(v.get('vcpu')), 'set_id': int(v.get('cpuset'))}
            for v in root.find('cputune').findall('vcpupin')]
        vm_vcpus_sets = [vcpupin['set_id'] for vcpupin in vm_vcpupins]
        cnt_of_used_numa = 0
        for host in host_conf.values():
            if set(host) & set(vm_vcpus_sets):
                cnt_of_used_numa += 1
        assert cnt_of_used_numa == numa_count, (
            "Unexpected count of numa nodes in use: {0} instead of {1}".
            format(cnt_of_used_numa, numa_count))

        if exp_vcpupin is not None:
            act_vcpupin = {}
            for numa, ids in host_conf.items():
                pins = [p['id'] for p in vm_vcpupins if p['set_id'] in ids]
                act_vcpupin.update({numa: pins})
            assert act_vcpupin == exp_vcpupin, "Unexpected cpu's allocation"

    def get_nodesets_for_vm(self, os_conn, vm):
        root = self.get_vm_dump(os_conn, vm)
        nodesets = [numa.get('nodeset') for numa in
                    root.find('numatune').findall('memnode')]
        return nodesets

    def compute_change_state(self, os_conn, devops_env, host, state):
        def is_compute_state():
            hypervisor = [i for i in os_conn.nova.hypervisors.list()
                          if i.hypervisor_hostname == host][0]
            return hypervisor.state == state

        compute = os_conn.env.find_node_by_fqdn(host)
        devops_node = devops_env.get_node_by_fuel_node(compute)
        if state == 'down':
            devops_node.destroy()
        else:
            devops_node.start()
        common.wait(is_compute_state,
                    timeout_seconds=20 * 60,
                    waiting_for='compute is {}'.format(state))

    @contextlib.contextmanager
    def change_compute_state_to_down(self, os_conn, devops_env, host):
        try:
            self.compute_change_state(os_conn, devops_env, host, state='down')
            yield
        finally:
            self.compute_change_state(os_conn, devops_env, host, state='up')

    def evacuate(self, os_conn, devops_env, vm, host=None,
                 on_shared_storage=False):
        os_conn.nova.servers.evacuate(vm, host=host,
                                      on_shared_storage=on_shared_storage)
        try:
            common.wait(
                lambda: os_conn.is_server_active(vm), timeout_seconds=10 * 60,
                waiting_for='instance {} changes status to ACTIVE after '
                            'evacuation'.format(vm.name))
        except InstanceError:
            host = getattr(vm, "OS-EXT-SRV-ATTR:host")
            self.compute_change_state(os_conn, devops_env, host, state='up')
            raise

        new_vm = os_conn.nova.servers.get(vm)
        if host is not None:
            assert host == getattr(new_vm, "OS-EXT-SRV-ATTR:host"), (
                "Wrong host found for {0} after evacuation. "
                "Expected host is {1}").format(new_vm, host)
        return new_vm

    def cpu_load(self, env, os_conn, vm, vm_keypair=None, vm_login='ubuntu',
                 vm_password='ubuntu', action='start'):
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

    def get_instance_ips(self, os_conn, vm):
        ip_addrs = []
        vm.get()
        for x in vm.addresses.values():
            for l in x:
                ip_addrs.append(l['addr'])
        return ip_addrs

    def get_port_ips(self, os_conn, port_id):
        port_ips = []
        port_info = os_conn.neutron.show_port(port_id)
        for ip in port_info['port']['fixed_ips']:
            port_ips.append(ip['ip_address'])
        return port_ips

    def check_vm_connectivity_ubuntu(
            self, env, os_conn, keypair, vms, inactive_ips=()):
        vm_ips = {}
        for vm in vms:
            ips = [ip for ip in self.get_instance_ips(os_conn, vm) if
                   ip not in inactive_ips]
            vm_ips[vm] = ips
        for vm in vms:
            ips = ['8.8.8.8']
            for vm_1 in vms:
                if vm != vm_1:
                    ips.extend(vm_ips[vm_1])

            network_checks.check_ping_from_vm(
                env, os_conn, vm, vm_keypair=keypair, ip_to_ping=ips,
                vm_login='ubuntu', vm_password='ubuntu', vm_ip=vm_ips[vm][0])

    def check_vif_type_for_vm(self, vm, os_conn):
        vm_ports = os_conn.neutron.list_ports(device_id=vm.id)['ports']
        vhost_ports = [port for port in vm_ports if
                       port['binding:vif_type'] == 'vhostuser']
        assert vhost_ports, ("Vm should have at least one port with "
                             "binding:vif_type = vhostuser")

    def get_ovs_agents(self, env, os_conn):
        ovs_agts = os_conn.neutron.list_agents(
            binary='neutron-openvswitch-agent')['agents']
        ovs_agent_ids = [agt['id'] for agt in ovs_agts]
        controllers = [node.data['fqdn']
                       for node in env.get_nodes_by_role('controller')]
        ovs_conroller_agents = [agt['id'] for agt in ovs_agts
                                if agt['host'] in controllers]
        return [ovs_agent_ids, ovs_conroller_agents]

    def get_memory_allocation_per_numa(self, os_conn, vm, numa_count):
        """This method returns memory allocation per numa set for vm.

        :param os_conn: os_conn
        :param vm: vm to check
        :param numa_count: count of numa nodes for vm (depends on flavor)
        :param expected_allocation: dictionary like {'0': 512, '1': 1536} where
        key is numa_cpu, value is allocated memory in Mb
        :return: actual allocation {'0': 512, '1': 1536} where key is numa_cpu,
         value is allocated memory in Mb
        """
        root = self.get_vm_dump(os_conn, vm)
        numa_cells = root.find('cpu').find('numa').findall('cell')
        assert len(numa_cells) == numa_count, "Unexpected count of numa nodes"
        memory_allocation = {cell.get('id'): int(cell.get('memory')) / 1024
                             for cell in numa_cells}
        return memory_allocation

    def get_vm_dump(self, os_conn, vm):
        vm.get()
        name = getattr(vm, "OS-EXT-SRV-ATTR:instance_name")
        host = os_conn.env.find_node_by_fqdn(
            getattr(vm, "OS-EXT-SRV-ATTR:host"))
        with host.ssh() as remote:
            dump = remote.execute("virsh dumpxml {0}".format(name))
        return ElementTree.fromstring(dump.stdout_string)

    def get_instances(self, os_conn, host):
        host = os_conn.env.find_node_by_fqdn(host)
        with host.ssh() as remote:
            instances = remote.check_call('virsh list --name').stdout_string
        return instances.splitlines()

    def get_thread_siblings_lists(self, os_conn, host, numanode):
        """This method returns list of thread_siblings_list for numanode. Only
        cpus isolated for cpu_pinning are taken into account

        :param os_conn: os_conn
        :param host: fqdn hostname
        :param numanode: id from numa node
        :return: list of thread_siblings_list
        """
        compute = os_conn.env.find_node_by_fqdn(host)
        with compute.ssh() as remote:
            # Get all thread_siblings_list
            cmd = ("cat /sys/bus/node/devices/node{0}/cpu*/topology/"
                   "thread_siblings_list".format(numanode))
            res = remote.check_call(cmd).stdout_string.splitlines()
            all_ts = [re.split('-|,', item) for item in res]

            # Get cpus for cpu pinning usage
            cpus = remote.check_call("cat /proc/cmdline")["stdout"][0]
            isolcpus = {x[0]: x[2] for x in [y.partition('=')
                        for y in cpus.split()]}['isolcpus'].split(',')
        return [tuple(i) for i in all_ts if set(i).issubset(set(isolcpus))]

    def get_vm_thread_siblings_lists(self, os_conn, vm):
        """This method returns thread_siblings_lists used by vm"""
        vm.get()
        host = getattr(vm, "OS-EXT-SRV-ATTR:host")
        dump = self.get_vm_dump(os_conn, vm)
        numa = dump.find('numatune').find('memnode').get('cellid')
        ts_lsts = self.get_thread_siblings_lists(os_conn, host, numa)
        vcpus = [vcpupin.get('cpuset') for vcpupin in
                 dump.find('cputune').findall('vcpupin')]
        used_ts = set([ts for ts in ts_lsts for vcpu in vcpus if vcpu in ts])
        return used_ts
