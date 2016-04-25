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
from mos_tests.functions import os_cli
from mos_tests.glance.conftest import project  # noqa
from mos_tests.glance.conftest import user  # noqa
from mos_tests.ironic.conftest import make_devops_node

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.undestructive


@pytest.yield_fixture
def cleanup_ironic(ironic):
    exists_nodes = [x.uuid for x in ironic.client.node.list()]
    yield
    new_nodes = [x for x in ironic.client.node.list()
                 if x.uuid not in exists_nodes]  # yapf: disable
    for node in new_nodes:
        ironic.delete_node(node)


@pytest.yield_fixture
def chassis(ironic):
    chassis = ironic.client.chassis.create()
    yield chassis
    ironic.client.chassis.delete(chassis.uuid)


@pytest.fixture
def ironic_cli(controller_remote):
    return os_cli.Ironic(controller_remote)


@pytest.fixture
def config(ironic_drivers_params):
    config = ironic_drivers_params[0]
    if config['driver'] != 'fuel_libvirt':
        pytest.skip('Required config with `fuel_libvirt` driver for this test '
                    'actually {config} passed'.format(config))
    return config


@pytest.yield_fixture
def devops_node(devops_env, env, config):
    node = make_devops_node(config=config,
                            devops_env=devops_env,
                            fuel_env=env,
                            name='baremetal')
    yield node
    devops_env.del_node(node)


@pytest.mark.testrail_id('631901')
@pytest.mark.check_env_('has_ironic_conductor')
def test_crud_operations(config, devops_node, os_conn, ironic, cleanup_ironic,
                         chassis):
    """Test CRUD operations for ironic node

    Scenario:
        1. Create ironic node but mention fake driver instead of ssh one.
        2. Check that new node appears in ironic node-list.
        3. Check that nova hypervisor-list shows one new hypervisor with 0
            values for ram, cpu, disk.
        4. Validate new ironic node: ironic node-validate uuid
        5. Update node with real driver instead of fake one
        6. Check that node driver is updated
        7. Create port with correct MAC for this node
        8. Check that nova hypervisor-show uuid shows non-zero ram|cpu|disk
        9. Validate the node again
        10. Check that validation results is better, than last one
        11. Add/update chassis for node
        12. Delete node in Available state
        13. Check that node disappears from ironic node-list and
            nova hypervisor-list
    """
    fake_driver_info = {'A1': 'A1', 'B1': 'B1', 'B2': 'B2'}
    node_properties = config['node_properties']

    # Create node
    node = ironic.client.node.create(driver='fake',
                                     driver_info=fake_driver_info,
                                     properties=node_properties)

    assert node.uuid in [x.uuid for x in ironic.client.node.list()]

    def get_hypervisor():
        try:
            return os_conn.nova.hypervisors.find(hypervisor_hostname=node.uuid)
        except Exception as e:
            logger.info(e)

    hypervisor = common.wait(
        get_hypervisor,
        timeout_seconds=3 * 60,
        sleep_seconds=10,
        waiting_for='ironic node to appear in hypervisors list')

    assert hypervisor.vcpus == 0
    assert hypervisor.memory_mb == 0
    assert hypervisor.disk_available_least == 0

    validate_result = ironic.client.node.validate(node.uuid)
    for val in validate_result.to_dict().values():
        assert val == {'result': True}

    patch = [
        {'op': 'replace',
         'path': '/driver',
         'value': config['driver']}, {'op': 'replace',
                                      'path': '/driver_info',
                                      'value': config['driver_info']}
    ]

    # Update node driver
    node = ironic.client.node.update(node.uuid, patch=patch)
    assert node.driver == config['driver']

    # Create port
    ironic.client.port.create(node_uuid=node.uuid,
                              address=config['mac_address'])

    def updated_hypervisor():
        hypervisor = os_conn.nova.hypervisors.find(
            hypervisor_hostname=node.uuid)
        if hypervisor.vcpus > 0:
            return hypervisor

    hypervisor = common.wait(
        updated_hypervisor,
        timeout_seconds=3 * 60,
        sleep_seconds=10,
        waiting_for='ironic hypevisor to update CPU count')

    assert hypervisor.vcpus > 0
    assert hypervisor.memory_mb > 0
    assert hypervisor.disk_available_least > 0

    validate_result = ironic.client.node.validate(node.uuid)
    assert validate_result.boot['result'] is None
    assert validate_result.console['result'] is None
    assert validate_result.inspect['result'] is None
    assert validate_result.raid['result'] is None

    # Add node to chassis
    ironic.client.node.update(node.uuid, [{'op': 'replace',
                                           'path': '/chassis_uuid',
                                           'value': chassis.uuid}])

    assert len(ironic.client.chassis.list_nodes(chassis.uuid)) == 1

    # Delete node
    ironic.delete_node(node)

    assert node.uuid not in [x.uuid for x in ironic.client.node.list()]

    common.wait(
        lambda: not os_conn.nova.hypervisors.findall(
            hypervisor_hostname=node.uuid),  # yapf: disable
        timeout_seconds=2 * 60,
        sleep_seconds=10,
        waiting_for='ironic hypervisor to disappear in nova '
        'hypervisors list')


@pytest.mark.testrail_id('631902')  # noqa
@pytest.mark.check_env_('has_ironic_conductor')
def test_use_cli_with_not_admin_permissions(ironic_cli, project, user):
    """Try to use Ironic CLI with non-admin permissions

    Scenario:
        1. Create new user
        2. Run `ironic node-list` with this user credentials
        3. Check that 'Forbidden (HTTP 403)' in output
    """

    env = dict(OS_USERNAME=user['name'],
               OS_PASSWORD='password',
               OS_PROJECT_NAME=project['name'],
               OS_TENANT_NAME=project['name'])
    env_string = ' '.join(['{0}={1}'.format(*item) for item in env.items()])
    result = ironic_cli('node-list',
                        prefix='env {}'.format(env_string),
                        fail_ok=True,
                        merge_stderr=True)
    assert 'Forbidden (HTTP 403)' in result
