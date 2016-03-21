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


@pytest.fixture
def instance(os_conn, ubuntu_image, flavor, keypair):
    baremetal_net = os_conn.nova.networks.find(label='baremetal')
    instance = os_conn.create_server('ironic-server', image_id=ubuntu_image.id,
                                     flavor=flavor.id, key_name=keypair.name,
                                     nics=[{'net-id': baremetal_net.id}],
                                     timeout=60 * 10)
    return instance


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631916')
def test_instance_hard_reboot(env, ironic, os_conn, ironic_node, ubuntu_image,
                              flavor, keypair, instance):
    """Check instance state after hard reboot

    Scenario:
        1. Boot Ironic instance
        2. Hard reboot Ironic instance.
        3. Wait 2-3 minutes.
        4. Check that instance is back in ACTIVE status
    """
    os_conn.server_hard_reboot(instance)

    def is_instance_active():
        return os_conn.nova.servers.get(instance.id).status == 'ACTIVE'

    common.wait(
        is_instance_active, timeout_seconds=60 * 5, sleep_seconds=20,
        waiting_for="instance's state back to ACTIVE after hard reboot")
    assert os_conn.nova.servers.get(instance.id).status == 'ACTIVE'


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631917', params={'start_instance': False})
@pytest.mark.testrail_id('631918', params={'start_instance': True})
@pytest.mark.parametrize('start_instance', [True, False])
def test_instance_stop_start(env, ironic, os_conn, ironic_node, ubuntu_image,
                          flavor, keypair, instance, start_instance):
    """Check instance statuses during instance restart

    Scenario:
        1. Boot Ironic instance
        2. Shut down Ironic instance
        3. Check Ironic instance status
        4. Start Ironic instance (if 'start_instance')
        5. Check that instance is back in ACTIVE status (if 'start_instance')
    """

    os_conn.server_stop(instance)

    def is_instance_shutoff():
        return os_conn.nova.servers.get(instance.id).status == 'SHUTOFF'

    common.wait(is_instance_shutoff, timeout_seconds=60 * 5,
                sleep_seconds=20,
                waiting_for="instance's state is SHUTOFF after stop")

    assert getattr(os_conn.nova.servers.get(instance.id),
                   "OS-EXT-STS:vm_state") == 'stopped'

    if start_instance:
        os_conn.server_start(instance)

        def is_instance_active():
            return os_conn.nova.servers.get(instance.id).status == 'ACTIVE'

        common.wait(is_instance_active, timeout_seconds=60 * 5,
                    sleep_seconds=20,
                    waiting_for="instance's state is ACTIVE after start")

        assert getattr(os_conn.nova.servers.get(instance.id),
                       "OS-EXT-STS:vm_state") == 'active'


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.testrail_id('631920')
def test_instance_terminate(env, ironic, os_conn, ironic_node, ubuntu_image,
                            flavor, keypair, instance):
    """Check terminate instance

    Scenario:
        1. Boot Ironic instance
        2. Terminate Ironic instance
        3. Wait and check that instance not present in nova list
    """
    instance.delete()
    common.wait(lambda: not os_conn.nova.servers.list().count(instance),
                timeout_seconds=60, waiting_for="instance is terminated")


@pytest.mark.check_env_('has_ironic_conductor')
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
