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
from mos_tests import settings


logger = logging.getLogger(__name__)
pytestmark = pytest.mark.undestructive


@pytest.yield_fixture
def cleanup_ironic(ironic):
    exists_nodes = set([x.uuid for x in ironic.node.list()])
    yield
    for node_uuid in set([x.uuid for x in ironic.node.list()]) - exists_nodes:
        for port in ironic.node.list_ports():
            ironic.port.delete(port.uuid)
        ironic.node.delete(node_uuid)


@pytest.yield_fixture
def chassis(ironic):
    chassis = ironic.chassis.create()
    yield chassis
    ironic.chassis.delete(chassis.uuid)


@pytest.mark.testrail_id('631901')
def test_crud_operations(server_ssh_credentials, baremetal_node, os_conn,
                         ironic, cleanup_ironic, chassis):
    """Test CRUD operations for ironic node

    Scenario:
        1. Create ironic node but mention fake driver instead of ssh one.
        2. Check that new node appears in ironic node-list.
        3. Check that nova hypervisor-list shows one new hypervisor with 0
            values for ram, cpu, disk.
        4. Validate new ironic node: ironic node-validate uuid
        5. Update node with ssh driver instead of fake one
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
    fake_driver_info = {
        'A1': 'A1',
        'B1': 'B1',
        'B2': 'B2',
    }
    node_properties = {
        'cpus': baremetal_node.vcpu,
        'memory_mb': baremetal_node.memory,
        'local_gb': settings.IRONIC_DISK_GB,
        'cpu_arch': 'x86_64',
    }

    # Create node
    node = ironic.node.create(driver='fake', driver_info=fake_driver_info,
                              properties=node_properties)

    assert node.uuid in [x.uuid for x in ironic.node.list()]

    def get_hypervisor():
        try:
            return os_conn.nova.hypervisors.find(
                hypervisor_hostname=node.uuid)
        except Exception as e:
            logger.info(e)

    hypervisor = common.wait(
        get_hypervisor, timeout_seconds=2 * 60, sleep_seconds=10,
        waiting_for='ironic node to appear in hypervisors list')

    assert hypervisor.vcpus == 0
    assert hypervisor.memory_mb == 0
    assert hypervisor.disk_available_least == 0

    validate_result = ironic.node.validate(node.uuid)
    for val in validate_result.to_dict().values():
        assert val == {'result': True}

    def get_image(name):
        return os_conn.nova.images.find(name=name)

    driver_info = {
        'ssh_address': server_ssh_credentials['ip'],
        'ssh_username': server_ssh_credentials['username'],
        'ssh_key_contents': server_ssh_credentials['key'],
        'ssh_virt_type': 'virsh',
        'deploy_kernel': get_image('ironic-deploy-linux').id,
        'deploy_ramdisk': get_image('ironic-deploy-initramfs').id,
        'deploy_squashfs': get_image('ironic-deploy-squashfs').id,
    }
    patch = [
        {'op': 'replace', 'path': '/driver', 'value': 'fuel_ssh'},
        {'op': 'replace', 'path': '/driver_info', 'value': driver_info}
    ]

    # Update node driver
    node = ironic.node.update(node.uuid, patch=patch)
    assert node.driver == 'fuel_ssh'

    mac = baremetal_node.interface_by_network_name('baremetal')[0].mac_address
    ironic.port.create(node_uuid=node.uuid, address=mac)

    def updated_hypervisor():
        hypervisor = os_conn.nova.hypervisors.find(
            hypervisor_hostname=node.uuid)
        if hypervisor.vcpus > 0:
            return hypervisor

    hypervisor = common.wait(
        updated_hypervisor, timeout_seconds=2 * 60, sleep_seconds=10,
        waiting_for='ironic hypevisor to update CPU count')

    assert hypervisor.vcpus > 0
    assert hypervisor.memory_mb > 0
    assert hypervisor.disk_available_least > 0

    validate_result = ironic.node.validate(node.uuid)
    assert validate_result.boot['result'] is None
    assert validate_result.console['result'] is None
    assert validate_result.inspect['result'] is None
    assert validate_result.raid['result'] is None

    # Add node to chassis
    ironic.node.update(node.uuid, [{'op': 'replace',
                                    'path': '/chassis_uuid',
                                    'value': chassis.uuid}])

    assert len(ironic.chassis.list_nodes(chassis.uuid)) == 1

    # Delete node
    ironic.node.delete(node.uuid)

    assert node.uuid not in [x.uuid for x in ironic.node.list()]

    common.wait(lambda: not os_conn.nova.hypervisors.findall(
                    hypervisor_hostname=node.uuid),
                timeout_seconds=2 * 60, sleep_seconds=10,
                waiting_for='ironic hypervisor to disappear in nova '
                            'hypervisors list')
