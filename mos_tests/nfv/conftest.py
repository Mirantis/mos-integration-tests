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

import csv

import dpath.util
import pytest
import re

from mos_tests.functions import common
from mos_tests.functions import file_cache
from mos_tests.nfv.base import page_1gb
from mos_tests.nfv.base import page_2mb
from mos_tests.settings import UBUNTU_QCOW2_URL


@pytest.fixture
def nova_ceph(env):
    data = env.get_settings_data()
    if not dpath.util.get(data, '*/storage/**/ephemeral_ceph/value'):
        pytest.skip("Nova ceph is required")


@pytest.yield_fixture
def aggregate(os_conn):
    numa_computes = []
    for compute in os_conn.env.get_nodes_by_role('compute'):
        with compute.ssh() as remote:
            res = remote.check_call("lscpu -p=cpu,node | "
                                    "grep -v '#'")["stdout"]
            cmdline = remote.check_call("cat /proc/cmdline")["stdout"][0]
            cpu_pinning = True if 'isolcpus' in cmdline else False
        reader = csv.reader(res)
        numas = {int(numa[1]) for numa in reader}
        if len(numas) > 1 and cpu_pinning:
            numa_computes.append(compute)
    if len(numa_computes) < 2:
        pytest.skip("Insufficient count of compute with Numa Nodes")
    aggr = os_conn.nova.aggregates.create('performance', 'nova')
    os_conn.nova.aggregates.set_metadata(aggr, {'pinned': 'true'})
    for host in numa_computes:
        os_conn.nova.aggregates.add_host(aggr, host.data['fqdn'])
    yield aggr
    for host in numa_computes:
        os_conn.nova.aggregates.remove_host(aggr, host.data['fqdn'])
    os_conn.nova.aggregates.delete(aggr)


@pytest.yield_fixture()
def flavors(os_conn, request, cleanup):
    flvs = getattr(request.cls, 'flavors_to_create')
    created_flavors = []
    for flv in flvs:
        params = {'ram': 1024, 'vcpu': 2, 'disk': 20}
        params.update(flv.get('params', {}))
        flavor = os_conn.nova.flavors.create(flv['name'], params['ram'],
                                             params['vcpu'],
                                             params['disk'])
        flavor.set_keys(flv.get('keys', {}))
        created_flavors.append(flavor)
    yield created_flavors
    for flavor in created_flavors:
        os_conn.nova.flavors.delete(flavor.id)


@pytest.yield_fixture(scope="class")
def keypair(os_conn):
    key = os_conn.create_key(key_name='nfv_key')
    yield key
    os_conn.delete_key(key_name=key.name)


@pytest.yield_fixture(scope="class")
def security_group(os_conn):
    security_group = os_conn.create_sec_group_for_ssh()
    yield security_group
    os_conn.delete_security_groups()


@pytest.yield_fixture(scope="class")
def security_group_ipv6(os_conn):
    security_group = os_conn.create_sec_group_for_ssh_ipv6()
    yield security_group
    os_conn.delete_security_groups()


@pytest.yield_fixture(scope="class")
def networks(request, os_conn):
    router = os_conn.create_router(name="router01")['router']
    ext_net = os_conn.ext_network
    os_conn.router_gateway_add(router_id=router['id'],
                               network_id=ext_net['id'])
    subnet_params = getattr(request, 'param', {'ipv6_addr_mode': None,
                                               'ipv6_ra_mode': None,
                                               'version': 4})
    create_additional_subnet = False
    if subnet_params['version'] != 4 and subnet_params['version'] != 6:
        create_additional_subnet = True
        subnet_params['version'] = 4

    net01 = os_conn.add_net(router['id'], **subnet_params)
    net02 = os_conn.add_net(router['id'], **subnet_params)

    if create_additional_subnet:
        i = len(os_conn.neutron.list_networks()['networks'])
        subnet_params['version'] = 6
        os_conn.create_subnet_and_interface(router['id'], net01, i - 1,
                                            **subnet_params)
        os_conn.create_subnet_and_interface(router['id'], net02, i,
                                            **subnet_params)

    initial_floating_ips = os_conn.nova.floating_ips.list()
    yield [net01, net02]
    os_conn.delete_router(router['id'])
    os_conn.delete_network(net01)
    os_conn.delete_network(net02)
    for floating_ip in [x for x in os_conn.nova.floating_ips.list()
                        if x not in initial_floating_ips]:
        os_conn.delete_floating_ip(floating_ip)


@pytest.yield_fixture(scope="class")
def volume(os_conn):
    image_id = [image.id for image in os_conn.nova.images.list()
                if image.name == 'TestVM'][0]
    volume = common.create_volume(os_conn.cinder, image_id, name='nfv_volume')
    yield volume
    volume.delete()


@pytest.yield_fixture
def cleanup(os_conn):
    def instances_cleanup(os_conn):
        instances = os_conn.nova.servers.list()
        for instance in instances:
            instance.delete()
        common.wait(lambda: len(os_conn.nova.servers.list()) == 0,
                    timeout_seconds=10 * 60, waiting_for='instances cleanup')

    initial_images = os_conn.nova.images.list()
    instances_cleanup(os_conn)
    yield
    instances_cleanup(os_conn)

    images = [image for image in os_conn.nova.images.list() if
              image not in initial_images]
    for image in images:
        image.delete()
    common.wait(lambda: len(os_conn.nova.images.list()) == len(initial_images),
                timeout_seconds=10 * 60, waiting_for='images cleanup')

    for volume in os_conn.cinder.volumes.list():
        if volume.name != 'nfv_volume':
            volume.delete()
            common.wait(lambda: volume not in os_conn.cinder.volumes.list(),
                        timeout_seconds=10 * 60, waiting_for='volumes cleanup')


@pytest.yield_fixture
def flavor(os_conn, request):
    param = getattr(request, 'param', {"name": "old.flavor", "ram": 2048,
                                       "vcpu": 2, "disk": 20})
    flv = os_conn.nova.flavors.create(param['name'], param['ram'],
                                      param['vcpu'], param['disk'])
    yield flv
    os_conn.nova.flavors.delete(flv.id)


def computes_configuration(env):
    computes = env.get_nodes_by_role('compute')
    computes_def = {}

    def get_compute_def(host, size):
        with host.ssh() as remote:
            cmd = ("cat /sys/kernel/mm/hugepages/hugepages-"
                   "{size}kB/{type}_hugepages" " || echo 0")
            [free, total] = [
                remote.execute(cmd.format(size=size, type=t))['stdout'][0]
                for t in ['free', 'nr']]
            pages_count = {'total': int(total), 'free': int(free)}
        return pages_count

    for compute in computes:
        computes_def.update(
            {compute.data['fqdn']: {size: get_compute_def(compute, size)
                                    for size in [page_1gb, page_2mb]}})
    return computes_def


@pytest.fixture
def computes_without_hp(env, request):
    min_count = getattr(request, 'param', 0)
    computes = computes_configuration(env)
    computes_without_hp = [host for host, attr in computes.items() if
                           attr[page_1gb]['total'] == 0 and
                           attr[page_2mb]['total'] == 0]
    if len(computes_without_hp) < min_count:
        pytest.skip("Insufficient count of compute nodes without Huge Pages")
    return computes_without_hp


@pytest.fixture
def computes_with_hp_1gb(env, request):
    min_count = getattr(request, 'param', {'host_count': 1,
                                           'hp_count_per_host': 4})
    computes = computes_configuration(env)
    computes_with_1gb_hp = [
        host for host, attr in computes.items() if
        attr[page_1gb]['free'] >= min_count['hp_count_per_host']]
    if len(computes_with_1gb_hp) < min_count['host_count']:
        pytest.skip("Insufficient count of compute nodes with 1Gb huge pages")
    return computes_with_1gb_hp


@pytest.fixture
def computes_with_hp_2mb(env, request):
    min_count = getattr(request, 'param', {'host_count': 1,
                                           'hp_count_per_host': 1024})
    computes = computes_configuration(env)
    computes_with_2mb_hp = [
        host for host, attr in computes.items() if
        attr[page_2mb]['free'] >= min_count['hp_count_per_host']]
    if len(computes_with_2mb_hp) < min_count['host_count']:
        pytest.skip("Insufficient count of compute nodes with 2Mb huge pages")
    return computes_with_2mb_hp


@pytest.fixture
def computes_with_mixed_hp(env, request):
    min_count = getattr(request.cls, 'mixed_hp_computes')
    computes = computes_configuration(env)
    mixed_computes = [host for host, attr in computes.items()
                      if attr[page_2mb]['free'] >= min_count['count_2mb'] and
                      attr[page_1gb]['free'] >= min_count['count_1gb']]
    if len(mixed_computes) < min_count['host_count']:
        pytest.skip(
            "Insufficient count of compute nodes with 2Mb & 1Gb huge pages")
    return mixed_computes


@pytest.fixture
def computes_with_numa_nodes(env, request):
    min_count = getattr(request, 'param', {"hosts_count": 2,
                                           "numa_count": 2})
    cpus_distribution = get_cpu_distribition_per_numa_node(env)
    conf = {compute: cpus_distribution[compute]
            for compute in cpus_distribution.keys()
            if cpus_distribution[compute].keys() >= min_count["numa_count"]}
    if len(conf.keys()) < min_count["hosts_count"]:
        pytest.skip("Insufficient count of computes with required numa nodes")
    return conf


def get_numa_count(compute):
    with compute.ssh() as remote:
        res = remote.execute("lscpu | grep 'NUMA node(s)'")['stdout']
    count = int(re.findall('[\d]+', res[0])[0])
    return count


def get_cpu_distribition_per_numa_node(env):
    """Returns dictionary like below:
    {u'node-10.test.domain.local': {'numa0': [0, 1, 2, 3], 'numa1': [4, 5]},
    u'node-9.test.domain.local': {'numa0': [0, 1, 2, 3], 'numa1': [4, 5]}}
    Two settings are taken into account: vcpus per numa node and vcpus
    allocated for cpu pinning.
    """

    def convert_vcpu(s):
        result = []
        for item in s.split(','):
            bounds = item.split('-')
            if len(bounds) == 2:
                result.extend(range(int(bounds[0]), int(bounds[1]) + 1))
            else:
                result.append(int(bounds[0]))
        return result
    host_def = {}
    computes = env.get_nodes_by_role('compute')
    for host in computes:
        count = get_numa_count(host)
        with host.ssh() as remote:
            nodes = {}
            cpus = remote.execute('cat /proc/cmdline')['stdout'][0]
            if 'isolcpus' not in cpus:
                continue
            isolcpus = set(convert_vcpu({x[0]: x[2] for x in [y.partition('=')
                           for y in cpus.split()]}['isolcpus']))
            for i in range(count):
                cmd = "lscpu | grep 'NUMA node{0} CPU(s)'".format(i)
                res = remote.execute(cmd)['stdout'][0]
                vcpu_set = set(convert_vcpu(res.split(':')[1].strip()))
                vcpus = list(vcpu_set & isolcpus)
                nodes.update({'numa{0}'.format(i): vcpus})
            host_def.update({host.data['fqdn']: nodes})
    return host_def


def get_memory_distribition_per_numa_node(env):
    host_def = {}
    computes = env.get_nodes_by_role('compute')
    for host in computes:
        with host.ssh() as remote:
            res = remote.execute("lscpu -p=node | grep -v '#' | uniq")
            reader = csv.reader(res['stdout'])
            numas = [i[0] for i in reader]
            numa_nodes = {}
            for numa in numas:
                cmd = ("cat /sys/devices/system/node/node{0}/meminfo |"
                       "grep MemTotal")
                res = remote.execute(cmd.format(numa))['stdout']
                mem_kb = re.findall(r'MemTotal:.* (\d+)', res[0])
                numa_nodes.update({'numa{0}'.format(numa): float(mem_kb[0])})
        host_def.update({host.data['fqdn']: numa_nodes})
    return host_def


def get_hp_distribution_per_numa_node(env):
    computes = env.get_nodes_by_role('compute')

    def huge_pages_per_numa_node(host, node, size):
        with host.ssh() as remote:
            cmd = ("cat /sys/devices/system/node/node{0}/hugepages/hugepages-"
                   "{size}kB/{type}_hugepages" " || echo 0")
            [free, total] = [remote.execute(
                cmd.format(node, size=size, type=t))['stdout'][0]
                for t in ['free', 'nr']]
            pages_count = {'total': int(total), 'free': int(free)}
        return pages_count

    def huge_pages_per_compute(compute):
        node_def = {}
        numa_count = get_numa_count(compute)
        for node in range(numa_count):
            sizes = {size: huge_pages_per_numa_node(compute, node, size)
                     for size in [page_1gb, page_2mb]}
            node_def.update({'numa{0}'.format(node): sizes})
        return node_def

    computes_def = {compute.data['fqdn']: huge_pages_per_compute(compute)
                    for compute in computes}
    return computes_def


@pytest.fixture
def ubuntu_image_id(os_conn, cleanup):
    image = os_conn.glance.images.create(
        name="image_ubuntu", url=UBUNTU_QCOW2_URL, disk_format='qcow2',
        container_format='bare')
    with file_cache.get_file(UBUNTU_QCOW2_URL) as f:
        os_conn.glance.images.upload(image.id, f)
    return image.id


@pytest.fixture
def sriov_hosts(os_conn):
    computes_list = []
    for compute in os_conn.env.get_nodes_by_role('compute'):
        with compute.ssh() as remote:
            result = remote.execute(
                'lspci -vvv | grep -i "initial vf"')["stdout"]
        text = ''.join(result)
        vfs_number = re.findall('Number of VFs: (\d+)', text)
        if sum(map(int, vfs_number)) > 0:
            computes_list.append(compute)
    if len(computes_list) < 2:
        pytest.skip("Insufficient count of compute with SR-IOV")
    hosts = [compute.data['fqdn'] for compute in computes_list]
    return hosts


@pytest.fixture
def computes_with_dpdk_hp(env):
    """This fixture checks hosts for dpdk pages count if experimental features
    are in ON state. Otherwise test will be skipped.
    Minimal configuration: at least 2 computes
    """
    computes = env.get_nodes_by_role('compute')
    hosts = set([compute.data['fqdn'] for compute in computes
                 for interface in compute.get_attribute('interfaces') if
                 interface['attributes']['dpdk']['enabled']['value']])
    if len(hosts) < 2:
        pytest.skip("Insufficient count of compute with DPDK")
    return list(hosts)


@pytest.fixture
def experimental_features(fuel):
    return 'experimental' in fuel.version['feature_groups']


@pytest.fixture
def hosts_with_hyper_threading(os_conn):
    computes = os_conn.env.get_nodes_by_role('compute')
    hosts = []
    for compute in computes:
        with compute.ssh() as remote:
            res = remote.check_call("lscpu | grep 'Thread(s) per core'")
        threads_count = int(re.findall('[\d]+', res['stdout'][0])[0])
        if threads_count >= 2:
            hosts.append(compute.data['fqdn'])
    return hosts
