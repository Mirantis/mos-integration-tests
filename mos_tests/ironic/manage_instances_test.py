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

from mos_tests.environment.os_actions import OpenStackActions
from mos_tests.functions import common
from mos_tests import settings


@pytest.fixture
def instance(ubuntu_image, flavors, keypair, ironic_nodes, ironic):
    instance = ironic.boot_instance(image=ubuntu_image,
                                    flavor=flavors[0],
                                    keypair=keypair)
    return instance


@pytest.yield_fixture
def tenants(env, openstack_client):
    # os_conns = []
    os_conns = {}
    for i in range(2):
        user = 'ironic_user_{}'.format(i)
        password = 'ironic'
        project = 'ironic_project_{}'.format(i)
        openstack_client.project_create(project)
        openstack_client.user_create(user, password, project)
        os_conn = OpenStackActions(
            controller_ip=env.get_primary_controller_ip(),
            cert=env.certificate, env=env, user=user, password=password,
            tenant=project)
        keypair = os_conn.create_key(key_name='ironic-key')
        os_conns[i] = [os_conn, keypair]
    yield os_conns
    for i in range(2):
        user = 'ironic_user_{}'.format(i)
        project = 'ironic_project_{}'.format(i)
        openstack_client.user_delete(user)
        openstack_client.project_delete(project)


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
@pytest.mark.need_devops
@pytest.mark.testrail_id('631916')
def test_boot_instance_with_user_data(ubuntu_image, flavors, keypair,
                                      ironic, ironic_nodes, os_conn, env):
    """Boot Ubuntu14-based virtual-bare-metal instance with user-data

    Scenario:
        1. Boot ironic instance with user data file user_data.sh
        2. Check that user_data.sh is present on instance
        3. Ping 8.8.8.8 from instance
    """
    instance = ironic.boot_instance(image=ubuntu_image,
                                    flavor=flavors[0],
                                    keypair=keypair,
                                    userdata='touch /userdata_result')

    with os_conn.ssh_to_instance(env, instance, vm_keypair=keypair,
                                 username='ubuntu') as remote:
        remote.check_call('ls /userdata_result')
        remote.check_call('ping -c1 {}'.format(settings.PUBLIC_TEST_IP))


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631912')
@pytest.mark.parametrize('ironic_nodes', [2], indirect=['ironic_nodes'])
def test_boot_instances_on_different_tenants(env, os_conn, ubuntu_image,
                                             flavors, ironic_nodes, tenants,
                                             ironic, keypair):
    """Check instance statuses during instance restart

    Scenario:
        1. Boot 1st Ironic instance under 1st tenant
        2. Boot 2nd Ironic instance under 2nd tenant
        3. Check Ironic instances statuses
        4. Login via SSH to Ironic instances.
        5. Check that instances are accessible for each other in baremetal
        network
    """

    common.wait(ironic.get_provisioned_node, timeout_seconds=3 * 60,
                sleep_seconds=15, waiting_for='ironic node to be provisioned')
    instances = {}
    for i in range(2):
        tenant_conn = tenants[i][0]
        tenant_keypair = tenants[i][1]
        brm_net = tenant_conn.nova.networks.find(label='baremetal')
        instance = tenant_conn.create_server('ironic-server-{}'.format(i),
                                             image_id=ubuntu_image.id,
                                             flavor=flavors[i].id,
                                             key_name=tenant_keypair.name,
                                             nics=[{'net-id': brm_net.id}],
                                             timeout=60 * 10,
                                             wait_for_avaliable=False)
        instances[i] = [instance,
                        tenant_conn.get_nova_instance_ips(instance)['fixed']]

    for i in range(2):
        instance = instances[i][0]
        assert os_conn.is_server_ssh_ready(instance)
        for j in range(2):
            if j != i:
                instances[i].append(
                    os_conn.get_nova_instance_ips(instances[j][0])['fixed'])

    for i in range(2):
        instance = instances[i][0]
        tenant_keypair = tenants[i][1]
        ip_for_ping = instances[i][2]

        with os_conn.ssh_to_instance(env, instance, vm_keypair=tenant_keypair,
                                     username='ubuntu') as remote:
            result = remote.execute('ping -c 10 {}'.format(ip_for_ping))
            loss_packets = int(result['stdout'][-2].split()[5][:-1])
            assert loss_packets < 100

    def is_instance_deleted():
        return instance not in tenant_conn.nova.servers.list()

    for i in range(2):
        tenant_conn = tenants[i][0]
        instance = instances[i][0]
        instance.delete()
        common.wait(is_instance_deleted, timeout_seconds=60 * 5,
                    sleep_seconds=20, waiting_for="instance is deleted")
