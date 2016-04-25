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
def nfv_flavor(os_conn, cleanup, request):
    flavors = getattr(
        request, 'param', [[['m1.small.hpgs', 512, 1, 1],
                           [{'hw:mem_page_size': 2048}, ]], ])
    created_flavors = []

    for flavor_params, flavor_keys in flavors:
        flavor = os_conn.nova.flavors.create(*flavor_params)
        for flavor_key in flavor_keys:
            flavor.set_keys(flavor_key)
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
