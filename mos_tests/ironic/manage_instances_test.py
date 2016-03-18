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
def instance(os_conn, ubuntu_image, flavor, keypair):
    baremetal_net = os_conn.nova.networks.find(label='baremetal')
    instance = os_conn.create_server('ironic-server', image_id=ubuntu_image.id,
                                     flavor=flavor.id, key_name=keypair.name,
                                     nics=[{'net-id': baremetal_net.id}],
                                     timeout=60 * 10)
    yield instance
    instance.delete()


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631920')
def test_instance_terminate(env, ironic, os_conn, ironic_node, ubuntu_image,
                            flavor, keypair):
    """Check terminate instance

    Scenario:
        1. Boot Ironic instance
        2. Terminate Ironic instance
        3. Wait and check that instance not present in nova list
    """

    baremetal_net = os_conn.nova.networks.find(label='baremetal')
    instance = os_conn.create_server('ironic-server', image_id=ubuntu_image.id,
                                     flavor=flavor.id, key_name=keypair.name,
                                     nics=[{'net-id': baremetal_net.id}],
                                     timeout=60 * 10)

    instance.delete()
    common.wait(lambda: not os_conn.nova.servers.list().count(instance),
                timeout_seconds=60, waiting_for="instance is terminated")


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631919')
def test_instance_rebuild(env, ironic, os_conn, ironic_node, ubuntu_image,
                          flavor, keypair, instance):
    """Check rebuild instance

    Scenario:
        1. Boot Ironic instance
        2. Rebuild Ironic instance (nova rebuild <server> <image>)
        3. Check that instance status became REBUILD
        4. Wait until instance returns back to ACTIVE status.
    """
    server = os_conn.rebuild_server(instance, ubuntu_image.id)
    common.wait(lambda: os_conn.nova.servers.get(server).status == 'ACTIVE',
                timeout_seconds=60 * 10, waiting_for="instance is active")
