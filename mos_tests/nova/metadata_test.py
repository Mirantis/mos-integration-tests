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

import pytest

from mos_tests.functions import common
from mos_tests.functions import file_cache
from mos_tests import settings

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.undestructive


@pytest.yield_fixture
def ubuntu_image_id(os_conn):
    logger.info('Creating ubuntu image')
    image = os_conn.glance.images.create(name="image_ubuntu",
                                         disk_format='qcow2',
                                         container_format='bare')
    with file_cache.get_file(settings.UBUNTU_QCOW2_URL) as f:
        os_conn.glance.images.upload(image.id, f)

    logger.info('Ubuntu image created')
    yield image.id
    os_conn.glance.images.delete(image.id)


@pytest.yield_fixture
def instances_cleanup(os_conn, security_group):
    old_instances = os_conn.nova.servers.list()
    yield
    for instance in os_conn.nova.servers.list():
        if instance not in old_instances:
            instance.delete()

    common.wait(lambda: len(os_conn.nova.servers.list()) == len(old_instances),
                timeout_seconds=2 * 60,
                waiting_for='instances to be deleted')


@pytest.mark.testrail_id('843871')
@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
def test_metadata_reach_all_booted_vm(os_conn, env, network, ubuntu_image_id,
                                      keypair, security_group,
                                      instances_cleanup):
    """[Bug #1545043] Check that metadata reach all booted VMs

    Scenario:
        1. Create a Glance image based on Ubuntu image
        2. Boot an instance based on previously created image
        3. Check that this instance is reachable via ssh connection
        4. Delete instance
        5. Repeat pp 2-4 100 times
    """
    flavor = os_conn.nova.flavors.find(name='m1.small')
    instances_count = 0
    # Determine available m1.small instances count
    for hypervisor in os_conn.nova.hypervisors.list():
        instances_count += min(hypervisor.disk_available_least / flavor.disk,
                               hypervisor.free_ram_mb / flavor.ram)
    iterations_count = 100 / instances_count
    for i in range(100 / instances_count):
        logger.info('Check metadata iteration {i} from {iterations_count}. '
                    'Boot {instances_count} instances'.format(
                        i=i,
                        iterations_count=iterations_count,
                        instances_count=instances_count))
        instances = []
        for j in range(instances_count):
            instance = os_conn.create_server(
                name='ubuntu_server_{:02d}'.format(j),
                availability_zone='nova',
                key_name=keypair.name,
                image_id=ubuntu_image_id,
                flavor=flavor,
                nics=[{'net-id': network['network']['id']}],
                security_groups=[security_group.id],
                wait_for_active=False,
                wait_for_avaliable=False)
            instances.append(instance)

        common.wait(
            lambda: all(os_conn.is_server_active(x) for x in instances),
            timeout_seconds=2 * 60,
            waiting_for='instances to became to ACTIVE status')
        common.wait(
            lambda: all(os_conn.is_server_ssh_ready(x) for x in instances),
            timeout_seconds=5 * 60,
            waiting_for='instances to be ssh available')

        for instance in instances:
            with os_conn.ssh_to_instance(env,
                                         instance,
                                         vm_keypair=keypair,
                                         username='ubuntu') as remote:
                remote.execute('uname')

        for instance in instances:
            instance.delete()

        common.wait(
            lambda: all(os_conn.is_server_deleted(x.id) for x in instances),
            timeout_seconds=2 * 60,
            waiting_for='instance to be deleted')
