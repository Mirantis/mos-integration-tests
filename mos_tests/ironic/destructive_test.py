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

import time

import pytest

from mos_tests.functions import common
from mos_tests.functions import os_cli


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631921', params={'boot_instance_before': False})
@pytest.mark.testrail_id('631922', params={'boot_instance_before': True})
@pytest.mark.parametrize('boot_instance_before',
                         [True, False],
                         ids=['boot_instance_before', 'boot_instance_after'])
def test_reboot_conductor(env, ironic, os_conn, ironic_nodes, ubuntu_image,
                          flavors, keypair, devops_env, boot_instance_before):
    """Check ironic state after restart conductor node

    Scenario:
        1. Boot Ironic instance (if `boot_instance_before`)
        2. Reboot Ironic conductor.
        3. Wait 5-10 minutes.
        4. Run network verification.
        5. Run OSTF including Ironic tests.
        6. Verify that CLI ironicclient can list nodes, ports, chassis, drivers
        7. Boot new Ironic instance (if not `boot_instance_before`).
    """

    if boot_instance_before:
        instance = ironic.boot_instance(image=ubuntu_image,
                                        flavor=flavors[0],
                                        keypair=keypair)

    conductor = env.get_nodes_by_role('ironic')[0]

    devops_node = devops_env.get_node_by_fuel_node(conductor)
    devops_node.reset()

    time.sleep(10)

    common.wait(conductor.is_ssh_avaliable,
                timeout_seconds=60 * 10,
                sleep_seconds=20,
                waiting_for='ironic conductor node to reboot')

    def is_ironic_available():
        try:
            ironic.client.driver.list()
            return True
        except Exception:
            return False

    common.wait(is_ironic_available,
                timeout_seconds=60 * 5,
                sleep_seconds=20,
                waiting_for='ironic conductor service to start')

    result = env.wait_network_verification()
    assert result.status == 'ready', 'Result data:\n{0}'.format(result.data)

    common.wait(lambda: env.is_ostf_tests_pass('sanity'),
                timeout_seconds=60 * 5,
                waiting_for='OSTF sanity tests to pass')

    with env.get_nodes_by_role('controller')[0].ssh() as remote:
        ironic_cli = os_cli.Ironic(remote)
        for cmd in ['node-list', 'port-list', 'chassis-list', 'driver-list']:
            ironic_cli(cmd)

    if not boot_instance_before:
        instance = ironic.boot_instance(image=ubuntu_image,
                                        flavor=flavors[0],
                                        keypair=keypair)

    assert os_conn.nova.servers.get(instance.id).status == 'ACTIVE'


@pytest.mark.check_env_('has_2_or_more_ironic_conductors')
@pytest.mark.need_devops
@pytest.mark.testrail_id('638353')
def test_reboot_all_ironic_conductors(env, devops_env):
    """Check ironic state after restart all conductor nodes

    Scenario:
        1. Ensure ironic conductor service works correctly on each conductor
            node (e.g., ensure "ironic driver-list" returns correct list of
            drivers)
        2. Shutdown all ironic conductor nodes
        3. Turn on all ironic conductor nodes
        4. SSH to every conductor and ensure conductor service works fine.
    """

    controller = env.get_nodes_by_role('controller')[0]
    with controller.ssh() as remote:
        with remote.open('/root/openrc') as f:
            openrc = f.read()

    conductors = env.get_nodes_by_role('ironic')
    drivers = None
    for conductor in conductors:
        with conductor.ssh() as remote:
            with remote.open('/root/openrc', 'w') as f:
                f.write(openrc)
            drivers_data = os_cli.Ironic(remote)('driver-list').listing()
            assert len(drivers_data) > 0
            if drivers is None:
                drivers = drivers_data
            else:
                assert drivers == drivers_data

    devops_nodes = [devops_env.get_node_by_fuel_node(x) for x in conductors]

    for node in devops_nodes:
        node.destroy()

    for node in devops_nodes:
        node.start()

    common.wait(lambda: all(x.is_ssh_avaliable() for x in conductors),
                timeout_seconds=10 * 60,
                waiting_for='conductor nodes to boot')

    for conductor in conductors:
        with conductor.ssh() as remote:
            with remote.open('/root/openrc', 'w') as f:
                f.write(openrc)
            ironic_cli = os_cli.Ironic(remote)
            assert ironic_cli('driver-list').listing() == drivers


@pytest.mark.check_env_('has_2_or_more_ironic_conductors')
@pytest.mark.need_devops
@pytest.mark.testrail_id('675246')
def test_kill_conductor_service(env, os_conn, ironic_nodes, ubuntu_image,
                                flavors, keypair, env_name, ironic):
    """Kill ironic-conductor service with one bare-metal node

    Scenario:
        1. Launch baremetal instance
        2. Kill Ironic-conductor service for conductor node that had booted
            instance
        3. Wait some time
        4. Baremetal node must be reassigned to another Ironic-conductor
        5. Run OSTF including Ironic tests.
        6. Check that Ironic instance still ACTIVE and operable
    Info: https://bugs.launchpad.net/mos/+bug/1557464
    """
    flavor, ironic_node = zip(flavors, ironic_nodes)[0]

    def find_conductor_node(ironic_node_uuid, conductors):
        cmd = 'ls /var/log/remote/ironic/{0}/'.format(ironic_node_uuid)
        for conductor in conductors:
            with conductor.ssh() as remote:
                result = remote.execute(cmd)
                if result.is_ok:
                    return conductor

    def find_takeover_node(ironic_node_uuid, conductors):
        grep = 'grep "taking over node {inst_uid}" {log}'.format(
            inst_uid=ironic_node_uuid,
            log='/var/log/ironic/ironic-conductor.log')
        for conductor in conductors:
            with conductor.ssh() as remote:
                result = remote.execute(grep)
                if result.is_ok:
                    return conductor

    instance = ironic.boot_instance(image=ubuntu_image,
                                    flavor=flavor,
                                    keypair=keypair)

    conductors = env.get_nodes_by_role('ironic')
    conductor = find_conductor_node(ironic_node.uuid, conductors)
    if conductor is None:
        raise Exception("Can't find conductor node booted istance")

    with conductor.ssh() as remote:
        remote.check_call('service ironic-conductor stop')

    conductors.remove(conductor)
    common.wait(
        lambda: (find_takeover_node(ironic_node.uuid, conductors)
                 not in (conductor, None)),  # yapf: disable
        timeout_seconds=10 * 60,
        waiting_for='node to migrate to another conductor',
        sleep_seconds=60)

    assert os_conn.nova.servers.get(instance.id).status == 'ACTIVE'

    with os_conn.ssh_to_instance(env,
                                 instance,
                                 vm_keypair=keypair,
                                 username='ubuntu') as remote:
        remote.check_call('uname')
