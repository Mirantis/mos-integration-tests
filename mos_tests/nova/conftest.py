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


@pytest.yield_fixture
def network(os_conn, request):
    network = os_conn.create_network(name='net01')
    subnet = os_conn.create_subnet(network_id=network['network']['id'],
                                   name='net01__subnet',
                                   cidr='192.168.1.0/24')
    yield network
    if 'undestructive' in request.node.keywords:
        os_conn.delete_subnet(subnet['subnet']['id'])
        os_conn.delete_network(network['network']['id'])


@pytest.yield_fixture
def keypair(os_conn, request):
    keypair = os_conn.create_key(key_name='instancekey')
    yield keypair
    if 'undestructive' in request.node.keywords:
        os_conn.delete_key(key_name=keypair.name)


@pytest.yield_fixture
def security_group(os_conn, request):
    sec_group = os_conn.create_sec_group_for_ssh()
    yield sec_group
    if 'undestructive' in request.node.keywords:
        os_conn.delete_security_group(name=sec_group.name)
