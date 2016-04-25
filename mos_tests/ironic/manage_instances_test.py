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

import json
import logging
import tarfile

import ipaddress
import pytest

from mos_tests.environment.os_actions import OpenStackActions
from mos_tests.functions import common
from mos_tests.functions import file_cache
from mos_tests.ironic import actions
from mos_tests.ironic import conftest
from mos_tests import settings

logger = logging.getLogger(__name__)


@pytest.fixture
def instance(ubuntu_image, flavors, keypair, ironic_nodes, ironic, request):
    instance_count = getattr(request, 'param', 1)
    instance = ironic.boot_instance(image=ubuntu_image,
                                    flavor=flavors[0],
                                    keypair=keypair,
                                    min_count=instance_count)
    return instance


@pytest.yield_fixture
def tenants_clients(env, openstack_client):
    os_conns = []
    for i in range(2):
        user = 'ironic_user_{}'.format(i)
        password = 'ironic'
        project = 'ironic_project_{}'.format(i)
        openstack_client.project_create(project)
        openstack_client.user_create(user, password, project)
        os_conn = OpenStackActions(
            controller_ip=env.get_primary_controller_ip(),
            cert=env.certificate,
            env=env,
            user=user,
            password=password,
            tenant=project)
        os_conns.append(os_conn)
    yield os_conns
    for i in range(2):
        user = 'ironic_user_{}'.format(i)
        project = 'ironic_project_{}'.format(i)
        openstack_client.user_delete(user)
        openstack_client.project_delete(project)


@pytest.fixture
def env2(request, fuel, env, env_name, devops_env):
    def get_baremetal_cidr(env):
        network_data = env.get_network_data()
        baremetal_net = [x
                         for x in network_data['networks']
                         if x['name'] == 'baremetal'][0]
        return baremetal_net['cidr']

    def get_baremetal_hosts_list(env):
        network_data = env.get_network_data()
        hosts = set()
        baremetal_net = [x
                         for x in network_data['networks']
                         if x['name'] == 'baremetal'][0]
        for start, end in baremetal_net['ip_ranges']:
            start = ipaddress.ip_address(start)
            end = ipaddress.ip_address(end)
            for subnet in ipaddress.summarize_address_range(start, end):
                for host in subnet:
                    hosts.add(host)
        start, end = network_data['networking_parameters']['baremetal_range']
        start = ipaddress.ip_address(start)
        end = ipaddress.ip_address(end)
        for subnet in ipaddress.summarize_address_range(start, end):
            for host in subnet:
                hosts.add(host)
        hosts.add(ipaddress.ip_address(network_data['networking_parameters'][
            'baremetal_gateway']))
        return hosts

    names = request.config.getoption('--cluster')
    if not names:
        envs = fuel.get_all_cluster()
    else:
        envs = fuel.get_clustres_by_names(names)
    if len(envs) < 2:
        pytest.skip("This test requires 2 deployed Fuel environments")

    env2 = [x for x in envs if x.id != env.id][0]

    if get_baremetal_cidr(env) != get_baremetal_cidr(env2):
        pytest.skip("This test requires identical CIDR for baremetal "
                    "network for both environments")

    env_hosts = get_baremetal_hosts_list(env)
    env2_hosts = get_baremetal_hosts_list(env2)
    if len(env_hosts & env2_hosts) > 0:
        pytest.skip("Test requires that baremetal IP ranges doesn't overlap "
                    "in environments")

    return env2


@pytest.fixture
def env2_ironic(env2):
    return actions.IronicActions(env2.os_conn)


@pytest.fixture
def env2_ironic_drivers_params(ironic_drivers_params):
    return ironic_drivers_params[1:]


@pytest.yield_fixture
def env2_ironic_node(env2, env2_ironic, env2_ironic_drivers_params,
                     devops_env):
    config = env2_ironic_drivers_params[0]
    name = 'baremetal2_0'
    devops_node, node = conftest.make_ironic_node(config=config,
                                                  devops_env=devops_env,
                                                  ironic=env2_ironic,
                                                  name=name,
                                                  fuel_env=env2)
    yield node

    env2_ironic.delete_node(node)

    if devops_node is not None:
        devops_env.del_node(devops_node)


@pytest.yield_fixture
def env2_keypair(env2):
    keypair = env2.os_conn.create_key(key_name='ironic-key')
    yield keypair
    env2.os_conn.delete_key(key_name=keypair.name)


@pytest.yield_fixture
def env2_flavors(env2_ironic_drivers_params, env2):
    flavors = []
    for i, config in enumerate(env2_ironic_drivers_params):
        flavor = env2.os_conn.nova.flavors.create(
            name='baremetal_{}'.format(i),
            ram=config['node_properties']['memory_mb'],
            vcpus=config['node_properties']['cpus'],
            disk=config['node_properties']['local_gb'])
        flavors.append(flavor)

    yield flavors

    for flavor in flavors:
        flavor.delete()


@pytest.yield_fixture
def env2_ubuntu_image(env2, image_file):
    image_name = 'ironic_trusty'

    logger.info('Creating ubuntu image')
    image = env2.os_conn.glance.images.create(
        name=image_name,
        disk_format='raw',
        container_format='bare',
        hypervisor_type='baremetal',
        visibility='public',
        cpu_arch='x86_64',
        fuel_disk_info=json.dumps(settings.IRONIC_GLANCE_DISK_INFO))

    with file_cache.get_file(settings.IRONIC_IMAGE_URL) as src:
        with tarfile.open(fileobj=src, mode='r|gz') as tar:
            img = tar.extractfile(tar.firstmember)
            env2.os_conn.glance.images.upload(image.id, img)

    logger.info('Creating ubuntu image ... done')

    yield image

    env2.os_conn.glance.images.delete(image.id)


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
        is_instance_active,
        timeout_seconds=60 * 5,
        sleep_seconds=20,
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

    common.wait(is_instance_shutoff,
                timeout_seconds=60 * 5,
                sleep_seconds=20,
                waiting_for="instance's state is SHUTOFF after stop")

    assert getattr(
        os_conn.nova.servers.get(instance.id),
        "OS-EXT-STS:vm_state") == 'stopped'

    if start_instance:
        os_conn.server_start(instance)

        def is_instance_active():
            return os_conn.nova.servers.get(instance.id).status == 'ACTIVE'

        common.wait(is_instance_active,
                    timeout_seconds=60 * 5,
                    sleep_seconds=20,
                    waiting_for="instance's state is ACTIVE after start")

        assert getattr(
            os_conn.nova.servers.get(instance.id),
            "OS-EXT-STS:vm_state") == 'active'


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.testrail_id('631920')
def test_instance_terminate(env, ironic, os_conn, ironic_nodes, ubuntu_image,
                            flavors, keypair, instance):
    """Check terminate instance

    Scenario:
        1. Boot Ironic instance
        2. Terminate Ironic instance
        3. Wait and check that instance not present in nova list
    """
    instance.delete()
    common.wait(lambda: os_conn.is_server_deleted(instance.id),
                timeout_seconds=60,
                waiting_for="instance is terminated")


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.testrail_id('631919')
def test_instance_rebuild(env, ironic, os_conn, ironic_nodes, ubuntu_image,
                          flavors, keypair, instance):
    """Check rebuild instance

    Scenario:
        1. Boot Ironic instance
        2. Rebuild Ironic instance (nova rebuild <server> <image>)
        3. Check that instance status became REBUILD
        4. Wait until instance returns back to ACTIVE status.
    """
    server = os_conn.rebuild_server(instance, ubuntu_image.id)
    common.wait(lambda: os_conn.nova.servers.get(server).status == 'ACTIVE',
                timeout_seconds=60 * 10,
                waiting_for="instance is active")


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631910')
def test_boot_instance_with_user_data(ubuntu_image, flavors, keypair, ironic,
                                      ironic_nodes, os_conn, env):
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

    with os_conn.ssh_to_instance(env,
                                 instance,
                                 vm_keypair=keypair,
                                 username='ubuntu') as remote:
        remote.check_call('ls /userdata_result')
        remote.check_call('ping -c1 {}'.format(settings.PUBLIC_TEST_IP))


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631912')
@pytest.mark.parametrize('ironic_nodes', [2], indirect=['ironic_nodes'])
def test_boot_instances_on_different_tenants(env, os_conn, ubuntu_image,
                                             ironic_nodes, ironic, flavors,
                                             tenants_clients):
    """Check instance statuses during instance restart

    Scenario:
        1. Boot 1st Ironic instance under 1st tenant
        2. Boot 2nd Ironic instance under 2nd tenant
        3. Check Ironic instances statuses
        4. Login via SSH to Ironic instances.
        5. Check that instances are accessible for each other in baremetal
        network
    """

    common.wait(ironic.get_provisioned_node,
                timeout_seconds=3 * 60,
                sleep_seconds=15,
                waiting_for='ironic node to be provisioned')
    instances, keypairs, ips = [], [], []

    for flavor, tenant_conn in zip(flavors, tenants_clients):
        tenant_keypair = tenant_conn.create_key(key_name='ironic-key')
        brm_net = tenant_conn.nova.networks.find(label='baremetal')
        instance = tenant_conn.create_server('ironic-server',
                                             image_id=ubuntu_image.id,
                                             flavor=flavor.id,
                                             key_name=tenant_keypair.name,
                                             nics=[{'net-id': brm_net.id}],
                                             timeout=60 * 10,
                                             wait_for_avaliable=False)

        keypairs.append(tenant_keypair)
        instances.append(instance)
        ips.append(tenant_conn.get_nova_instance_ips(instance)['fixed'])

    for instance, tenant_keypair, ip in zip(instances, keypairs, ips[::-1]):
        with os_conn.ssh_to_instance(env,
                                     instance,
                                     vm_keypair=tenant_keypair,
                                     username='ubuntu') as remote:
            result = remote.execute('ping -c 10 {}'.format(ip))
            received_packets = int(result['stdout'][-2].split()[3])
            assert received_packets > 0

    for instance, tenant_conn in zip(instances, tenants_clients):
        instance.delete()
        common.wait(tenant_conn.is_server_deleted(instance.id),
                    timeout_seconds=60 * 5,
                    sleep_seconds=20,
                    waiting_for="instance is deleted")


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
    servers = [x
               for x in os_conn.nova.servers.list()
               if x.name.startswith('ironic-server-')]
    assert len(servers) == 2
    for server in servers:
        with os_conn.ssh_to_instance(env,
                                     server,
                                     vm_keypair=keypair,
                                     username='ubuntu') as remote:
            remote.check_call('uname')


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.parametrize('ironic_nodes', [2], indirect=['ironic_nodes'])
@pytest.mark.testrail_id('631913')
def test_boot_nodes_consequently(env, os_conn, ironic, ubuntu_image, flavors,
                                 keypair, instance):
    """Check boot several bare-metal nodes consequently

    Scenario:
        1. Boot 1st baremetal instance
        2. Check that 1st instance is in ACTIVE status
        3. Boot 2nd baremetal instance
        4. Check that 2nd instance is in ACTIVE status
        5. Check that both baremetal instances are available via ssh
    """
    instance2 = ironic.boot_instance(image=ubuntu_image,
                                     flavor=flavors[0],
                                     keypair=keypair)
    for server in [instance, instance2]:
        with os_conn.ssh_to_instance(env,
                                     server,
                                     vm_keypair=keypair,
                                     username='ubuntu') as remote:
            remote.check_call('uname')


@pytest.mark.testrail_id('631914')
@pytest.mark.parametrize('ironic_nodes', [1], indirect=['ironic_nodes'])
@pytest.mark.usefixtures('ironic_nodes', 'env2_ironic_node')
def test_deploy_baremetal_nodes_on_2_envs(
        env, ironic, ubuntu_image, flavors, keypair, env2, env2_ironic,
        env2_ubuntu_image, env2_flavors, env2_keypair):
    """Check deploy bare-metal nodes on two environments concurrently

    Scenario:
        1. Launch baremetal instance from env1
        2. Launch baremetal instance from env2
        3. Verify that "Provisioning State" became "available" on baremetal
            nodes in both Envs.
        4. Check that baremetal instances ase SSH available
    """
    instance1 = ironic.boot_instance(image=ubuntu_image,
                                     flavor=flavors[0],
                                     keypair=keypair,
                                     wait_for_active=False,
                                     wait_for_avaliable=False)

    instance2 = env2_ironic.boot_instance(image=env2_ubuntu_image,
                                          flavor=env2_flavors[0],
                                          keypair=env2_keypair,
                                          wait_for_active=False,
                                          wait_for_avaliable=False)

    def is_instances_active():
        return (env.os_conn.is_server_active(instance1) and
                env2.os_conn.is_server_active(instance2))

    common.wait(is_instances_active,
                timeout_seconds=10 * 60,
                waiting_for='instances became active state')

    def is_ssh_ready():
        return (env.os_conn.is_server_ssh_ready(instance1) and
                env2.os_conn.is_server_ssh_ready(instance2))

    common.wait(is_ssh_ready,
                timeout_seconds=5 * 60,
                waiting_for='instances to be available via SSH')

    with env.os_conn.ssh_to_instance(env,
                                     instance1,
                                     vm_keypair=keypair,
                                     username='ubuntu') as remote:
        remote.check_call('uname')

    with env2.os_conn.ssh_to_instance(env2,
                                      instance2,
                                      vm_keypair=env2_keypair,
                                      username='ubuntu') as remote:
        remote.check_call('uname')
