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

import logging
from multiprocessing.dummy import Pool

import dpath.util
from novaclient import exceptions as nova_exceptions
import pytest
from six.moves import configparser

from mos_tests.functions import common

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.undestructive


def delete_instances(os_conn, instances, force=False):
    for instance in instances:
        if force:
            delete = instance.force_delete
        else:
            delete = instance.delete
        try:
            delete()
        except nova_exceptions.NotFound:
            pass
    common.wait(
        lambda: all(os_conn.is_server_deleted(x.id) for x in instances),
        timeout_seconds=2 * 60,
        waiting_for='instances to be deleted')


def is_migrated(os_conn, instances, target=None, source=None):
    assert any([source, target]), 'One of target or source is required'
    for instance in instances:
        instance.get()
        host = getattr(instance, 'OS-EXT-SRV-ATTR:host')
        if not os_conn.is_server_active(instance):
            return False
        if target and host != target:
            return False
        if source and host == source:
            return False
    return True


@pytest.yield_fixture
def unlimited_live_migrations(env):
    nova_config_path = '/etc/nova/nova.conf'

    nodes = (
        env.get_nodes_by_role('controller') + env.get_nodes_by_role('compute'))
    for node in nodes:
        if 'controller' in node.data['roles']:
            restart_cmd = 'service nova-api restart'
        else:
            restart_cmd = 'service nova-compute restart'
        with node.ssh() as remote:
            remote.check_call('cp {0} {0}.bak'.format(nova_config_path))

            parser = configparser.RawConfigParser()
            with remote.open(nova_config_path) as f:
                parser.readfp(f)
            parser.set('DEFAULT', 'max_concurrent_live_migrations', 0)
            with remote.open(nova_config_path, 'w') as f:
                parser.write(f)
            remote.check_call(restart_cmd)

    common.wait(env.os_conn.is_nova_ready,
                timeout_seconds=60 * 5,
                expected_exceptions=Exception,
                waiting_for="Nova services to be alive")

    yield
    for node in nodes:
        if 'controller' in node.data['roles']:
            restart_cmd = 'service nova-api restart'
        else:
            restart_cmd = 'service nova-compute restart'
        with node.ssh() as remote:
            result = remote.execute('mv {0}.bak {0}'.format(nova_config_path))
            if result.is_ok:
                remote.check_call(restart_cmd)

    common.wait(env.os_conn.is_nova_ready,
                timeout_seconds=60 * 5,
                expected_exceptions=Exception,
                waiting_for="Nova services to be alive")


@pytest.fixture
def big_hypervisors(os_conn):
    hypervisors = os_conn.nova.hypervisors.list()
    for flavor in os_conn.nova.flavors.list():
        suitable_hypervisors = []
        for hypervisor in hypervisors:
            if os_conn.get_hypervisor_capacity(hypervisor, flavor) > 0:
                suitable_hypervisors.append(hypervisor)
        hypervisors = suitable_hypervisors
    if len(hypervisors) < 2:
        pytest.skip('This test requires minimum 2 hypervisors '
                    'suitable for max flavor')
    return hypervisors[:2]


@pytest.yield_fixture
def instances(os_conn):
    instances = []
    yield instances
    delete_instances(os_conn, instances, force=True)


@pytest.yield_fixture
def big_port_quota(os_conn):
    tenant = os_conn.neutron.get_quotas_tenant()
    tenant_id = tenant['tenant']['tenant_id']
    orig_quota = os_conn.neutron.show_quota(tenant_id)
    new_quota = orig_quota.copy()
    # update quota for class C net
    new_quota['quota']['port'] = 256
    os_conn.neutron.update_quota(tenant_id, new_quota)
    yield
    os_conn.neutron.update_quota(tenant_id, orig_quota)


@pytest.fixture(scope='session')
def block_migration(env, request):
    value = request.param
    data = env.get_settings_data()
    if dpath.util.get(data, '*/storage/**/ephemeral_ceph/value') and value:
        pytest.skip('Block migration requires Nova Ceph RBD to be disabled')
    if not dpath.util.get(data,
                          '*/storage/**/ephemeral_ceph/value') and not value:
        pytest.skip('True live migration requires Nova Ceph RBD')
    return value


@pytest.mark.testrail_id('838028', block_migration=True)
@pytest.mark.testrail_id('838257', block_migration=False)
@pytest.mark.parametrize('block_migration',
                         [True, False],
                         ids=['block LM', 'true LM'],
                         indirect=True)
def test_live_migration_max_instances_with_all_flavors(
        os_conn, big_hypervisors, network, keypair, security_group, instances,
        env, block_migration, unlimited_live_migrations, big_port_quota):
    """LM of maximum allowed amount of instances created with all available
        flavors

    Scenario:
        1. Allow unlimited concurrent live migrations
        2. Restart nova-api services on controllers and
            nova-compute services on computes
        3. Create maximum allowed number of instances on a single compute node
        4. Initiate serial block LM of previously created instances
            to another compute node and estimate total time elapsed
        5. Check that all live-migrated instances are hosted on target host
            and are in Active state:
        6. Send pings between pairs of VMs to check that network connectivity
            between these hosts is still alive
        7. Initiate concurrent block LM of previously created instances
            to another compute node and estimate total time elapsed
        8. Check that all live-migrated instances are hosted on target host
            and are in Active state
        9. Send pings between pairs of VMs to check that network connectivity
            between these hosts is alive
        10. Repeat pp.3-9 for every available flavor
    """
    zone = os_conn.nova.availability_zones.find(zoneName="nova")
    hypervisor1, hypervisor2 = big_hypervisors
    flavors = sorted(os_conn.nova.flavors.list(), key=lambda x: -x.ram)
    for flavor in flavors:
        # Skip small flavors
        if flavor.ram < 512:
            continue
        instances_count = min(
            os_conn.get_hypervisor_capacity(hypervisor1, flavor),
            os_conn.get_hypervisor_capacity(hypervisor2, flavor))
        instances[:] = []
        logger.info('Start with flavor {0.name}, '
                    'creates {1} instances'.format(flavor, instances_count))
        for i in range(instances_count):
            instance = os_conn.create_server(
                name='server%02d' % i,
                flavor=flavor,
                availability_zone='{}:{}'.format(
                    zone.zoneName, hypervisor1.hypervisor_hostname),
                key_name=keypair.name,
                nics=[{'net-id': network['network']['id']}],
                security_groups=[security_group.id],
                wait_for_active=False,
                wait_for_avaliable=False)
            instances.append(instance)
        common.wait(
            lambda: all(os_conn.is_server_active(x) for x in instances),
            timeout_seconds=3 * 60,
            waiting_for='instances to became to ACTIVE status')
        common.wait(
            lambda: all(os_conn.is_server_ssh_ready(x) for x in instances),
            timeout_seconds=3 * 60,
            waiting_for='instances to be ssh available')

        # Successive migrations
        logger.info('Start successive migrations')
        for instance in instances:
            instance.live_migrate(block_migration=block_migration)

        common.wait(
            lambda: is_migrated(os_conn, instances,
                                source=hypervisor1.hypervisor_hostname),
            timeout_seconds=5 * 60,
            waiting_for='instances to migrate from '
                        '{0.hypervisor_hostname}'.format(hypervisor1))

        common.wait(
            lambda: all(os_conn.is_server_ssh_ready(x) for x in instances),
            timeout_seconds=3 * 60,
            waiting_for='instances to be ssh available')

        hyp1_id = hypervisor1.id
        common.wait(
            lambda: os_conn.nova.hypervisors.get(hyp1_id).running_vms == 0,
            timeout_seconds=2 * 60,
            waiting_for='hypervisor info be updated')

        pool = Pool(instances_count)
        logger.info('Start concurrent migrations')
        try:
            pool.map(
                lambda x: x.live_migrate(host=hypervisor1.hypervisor_hostname,
                                         block_migration=block_migration),
                instances)
        finally:
            pool.terminate()

        common.wait(
            lambda: is_migrated(os_conn, instances,
                                target=hypervisor1.hypervisor_hostname),
            timeout_seconds=5 * 60,
            waiting_for='instances to migrate to '
                        '{0.hypervisor_hostname}'.format(hypervisor1))

        common.wait(
            lambda: all(os_conn.is_server_ssh_ready(x) for x in instances),
            timeout_seconds=3 * 60,
            waiting_for='instances to be ssh available')

        delete_instances(os_conn, instances)
