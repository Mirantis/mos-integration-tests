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

import pytest

from mos_tests.functions import common
from mos_tests.nfv.base import page_1gb
from mos_tests.nfv.base import page_2mb


@pytest.yield_fixture
def aggregate(os_conn):
    hp_computes = []
    for compute in os_conn.env.get_nodes_by_role('compute'):
        with compute.ssh() as remote:
            res = remote.execute(
                'grep HugePages_Total /proc/meminfo')['stdout']
        if res:
            if res[0].split(':')[1].strip() != '0':
                hp_computes.append(compute)
    if len(hp_computes) < 2:
        pytest.skip("Insufficient count of compute nodes with Huge Pages")
    aggr = os_conn.nova.aggregates.create('hpgs-aggr', 'nova')
    os_conn.nova.aggregates.set_metadata(aggr, {'hpgs': 'true'})
    for host in hp_computes:
        os_conn.nova.aggregates.add_host(aggr, host.data['fqdn'])
    yield aggr
    for host in hp_computes:
        os_conn.nova.aggregates.remove_host(aggr, host.data['fqdn'])
    os_conn.nova.aggregates.delete(aggr)


@pytest.yield_fixture()
def small_nfv_flavor(os_conn, cleanup, request):
    flv = os_conn.nova.flavors.create("m1.small.hpgs", 512, 1, 1)
    flv.set_keys({'hw:mem_page_size': page_2mb})
    yield flv
    os_conn.nova.flavors.delete(flv.id)


@pytest.yield_fixture()
def medium_nfv_flavor(os_conn, cleanup, request):
    flv = os_conn.nova.flavors.create("m1.medium.hpgs", 2048, 2, 20)
    flv.set_keys({'hw:mem_page_size': page_1gb})
    yield flv
    os_conn.nova.flavors.delete(flv.id)


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
def networks(os_conn):
    router = os_conn.create_router(name="router01")['router']
    ext_net = os_conn.ext_network
    os_conn.router_gateway_add(router_id=router['id'],
                               network_id=ext_net['id'])
    net01 = os_conn.add_net(router['id'])
    net02 = os_conn.add_net(router['id'])
    yield [net01, net02]

    os_conn.delete_router(router['id'])
    os_conn.delete_network(net01)
    os_conn.delete_network(net02)


@pytest.yield_fixture(scope="class")
def volume(os_conn):
    image_id = [image.id for image in os_conn.nova.images.list()
                if image.name == 'TestVM'][0]
    volume = common.create_volume(os_conn.cinder, image_id,
                                  name='nfv_volume',
                                  volume_type='volumes_lvm')
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
            cmd = "cat /sys/kernel/mm/hugepages/hugepages-" \
                  "{size}kB/{type}_hugepages" " || echo 0"
            [free, total] = [remote.execute(
                cmd.format(size=size, type=t))['stdout'][0]
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
    computes_with_1gb_hp = [host for host, attr in computes.items() if
                            attr[page_1gb]['total'] != 0]
    if len(computes_with_1gb_hp) < min_count['host_count']:
        pytest.skip("Insufficient count of compute nodes with 1Gb huge pages")
    for host in computes_with_1gb_hp:
        if computes[host][page_1gb]['total'] < min_count['hp_count_per_host']:
            pytest.skip("Insufficient count of 1Gb huge pages for host")
    return computes_with_1gb_hp


@pytest.fixture
def computes_with_hp_2mb(env, request):
    min_count = getattr(request, 'param', {'host_count': 1,
                                           'hp_count_per_host': 1024})
    computes = computes_configuration(env)
    computes_with_2mb_hp = [host for host, attr in computes.items() if
                            attr[page_2mb]['total'] != 0]
    if len(computes_with_2mb_hp) < min_count['host_count']:
        pytest.skip("Insufficient count of compute nodes with 2Mb huge pages")
    for host in computes_with_2mb_hp:
        if computes[host][page_2mb]['total'] < min_count['hp_count_per_host']:
            pytest.skip("Insufficient count of 2Mb huge pages for host")
    return computes_with_2mb_hp


@pytest.fixture
def computes_with_mixed_hp(env, request):
    min_count = getattr(request, 'param', {'host_count': 1,
                                           'count_2mb': 1024,
                                           'count_1gb': 4})
    computes = computes_configuration(env)
    mixed_computes = [host for host, attr in computes.items()
                      if attr[page_2mb]['total'] != 0 and
                      attr[page_1gb]['total'] != 0]
    if len(mixed_computes) < min_count['host_count']:
        pytest.skip(
            "Insufficient count of compute nodes with 2Mb & 1Gb huge pages")
    for host in mixed_computes:
        counts = [(computes[host][page_1gb]['total'], min_count['count_1gb']),
                  (computes[host][page_2mb]['total'], min_count['count_2mb'])]
        for (act, minimum) in counts:
            if act < minimum:
                pytest.skip("Insufficient count huge pages for host")
    return mixed_computes
