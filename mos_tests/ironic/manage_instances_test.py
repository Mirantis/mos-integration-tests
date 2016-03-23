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
def instance(ubuntu_image, flavors, keypair, ironic_nodes, ironic, request):
    instance_count = getattr(request, 'param', 1)
    kwargs = {'min_count': instance_count}
    instance = ironic.boot_instance(image=ubuntu_image,
                                    flavor=flavors[0],
                                    keypair=keypair,
                                    **kwargs)
    return instance


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631916')
def test_instance_hard_reboot(os_conn, instance):
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
def test_instance_stop_start(os_conn, instance, start_instance):
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


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.parametrize('ironic_nodes', [2], indirect=['ironic_nodes'])
@pytest.mark.parametrize('instance', [2], indirect=['instance'])
@pytest.mark.testrail_id('631915')
def test_boot_nodes_concurrently(env, keypair, os_conn, instance):
    """Check boot several bare-metal nodes concurrently

    Scenario:
        1. Boot several baremetal instances at the same time
        2. Check that instances statuses are ACTIVE
        3. Check that both baremetal instances are available via ssh
    """
    servers = filter(lambda srv: srv.name.startswith('ironic-server-'),
                     os_conn.nova.servers.list())
    for server in servers:
        with os_conn.ssh_to_instance(env, server, vm_keypair=keypair,
                                     username='ubuntu') as remote:
            remote.check_call('uname')


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.parametrize('ironic_nodes', [2], indirect=['ironic_nodes'])
@pytest.mark.testrail_id('631913')
def test_boot_nodes_consequently(env, os_conn, ubuntu_image, flavors, keypair,
                                 instance):
    """Check boot several bare-metal nodes consequently

    Scenario:
        1. Boot 1st baremetal instance
        2. Check that 1st instance is in ACTIVE status
        3. Boot 2nd baremetal instance
        4. Check that 2nd instance is in ACTIVE status
        5. Check that both baremetal instances are available via ssh
    """
    baremetal_net = os_conn.nova.networks.find(label='baremetal')
    srv2 = os_conn.create_server('ironic-server-2', image_id=ubuntu_image.id,
                                 flavor=flavors[0].id, key_name=keypair.name,
                                 nics=[{'net-id': baremetal_net.id}],
                                 timeout=60 * 10)
    for server in [srv2, instance]:
        with os_conn.ssh_to_instance(env, server, vm_keypair=keypair,
                                     username='ubuntu') as remote:
            remote.check_call('uname')
