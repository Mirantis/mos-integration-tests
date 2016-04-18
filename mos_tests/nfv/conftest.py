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


@pytest.yield_fixture()
def nfv_flavor(os_conn, request):
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
    yield key.name

    os_conn.delete_key(key_name='nfv_key')


@pytest.yield_fixture(scope="class")
def networks(os_conn):
    router = os_conn.create_router(name="router01")['router']
    ext_net = [x for x in os_conn.list_networks()['networks']
               if x.get('router:external')][0]
    os_conn.router_gateway_add(router_id=router['id'],
                               network_id=ext_net['id'])
    net01 = os_conn.add_net(router['id'])
    net02 = os_conn.add_net(router['id'])
    yield [net01, net02]

    os_conn.delete_router(router['id'])
    os_conn.delete_network(net01)
    os_conn.delete_network(net02)



