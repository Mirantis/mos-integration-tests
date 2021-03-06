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

from collections import defaultdict
import time

import pytest

from mos_tests.functions import common
from mos_tests.functions import os_cli


@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.need_devops
@pytest.mark.testrail_id('631921', params={'boot_instance_before': False})
@pytest.mark.testrail_id('631922', params={'boot_instance_before': True})
@pytest.mark.parametrize('boot_instance_before', [True, False],
                         ids=['boot_instance_before', 'boot_instance_after'])
def test_reboot_conductor(env, ironic, os_conn, ironic_nodes, make_image,
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
    flavor, ironic_node = zip(flavors, ironic_nodes)[0]
    image = make_image(node_driver=ironic_node.driver)
    if boot_instance_before:
        instance = ironic.boot_instance(image=image,
                                        flavor=flavor,
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

    env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)

    with env.get_nodes_by_role('controller')[0].ssh() as remote:
        ironic_cli = os_cli.Ironic(remote)
        for cmd in ['node-list', 'port-list', 'chassis-list', 'driver-list']:
            ironic_cli(cmd)

    if not boot_instance_before:
        instance = ironic.boot_instance(image=image,
                                        flavor=flavor,
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
        4. SSH to controller and ensure that "ironic driver-list" return same
            result as for step 1
    """
    controller = env.get_nodes_by_role('controller')[0]
    with controller.ssh() as remote:
        driver_hosts = os_cli.Ironic(remote).get_driver_hosts()

    conductors = env.get_nodes_by_role('ironic')
    conductor_hosts = set(node.data['fqdn'] for node in conductors)

    assert conductor_hosts == driver_hosts
    devops_nodes = [devops_env.get_node_by_fuel_node(x) for x in conductors]

    for node in devops_nodes:
        node.destroy()

    for node in devops_nodes:
        node.start()

    common.wait(lambda: all(x.is_ssh_avaliable() for x in conductors),
                timeout_seconds=10 * 60,
                waiting_for='conductor nodes to boot')

    with controller.ssh() as remote:
        ironic_cli = os_cli.Ironic(remote)
        common.wait(lambda: ironic_cli.get_driver_hosts() == conductor_hosts,
                    timeout_seconds=60 * 2,
                    waiting_for="ironic conductor to register their drivers")


@pytest.mark.check_env_('has_2_or_more_ironic_conductors')
@pytest.mark.need_devops
@pytest.mark.testrail_id('675246')
def test_kill_conductor_service(env, os_conn, ironic_nodes, make_image,
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
    image = make_image(node_driver=ironic_node.driver)

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

    instance = ironic.boot_instance(image=image,
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
                 not in (conductor, None)),
        timeout_seconds=10 * 60,
        waiting_for='node to migrate to another conductor',
        sleep_seconds=60)

    assert os_conn.nova.servers.get(instance.id).status == 'ACTIVE'

    with os_conn.ssh_to_instance(env,
                                 instance,
                                 vm_keypair=keypair,
                                 username='ubuntu') as remote:
        remote.check_call('uname')


@pytest.mark.testrail_id('1295473')
@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.parametrize('ironic_nodes', [2], indirect=True)
@pytest.mark.need_devops
def test_restart_all_ironic_services(env, os_conn, ironic_nodes, ironic,
                                     make_image, flavors, keypair):
    """Test ironic after restarting all ironic services

    Scenario:
        1. Launch baremetal instance 'test1'
        2. Check that 'test1' instance ACTIVE and operable
        3. Stop all ironic-<name> services on each controllers and ironic
            nodes:
            service ironic-<name of service> restart
        4. Check that 'test1' instance are accesible with SSH
        5. Launch all ironic services
        6. Launch baremetal instance 'test2'
        7. Check that 'test1' instance ACTIVE and operable
        8. Delete created instances
    """
    image = make_image(node_driver=ironic_nodes[0].driver)

    instance1 = ironic.boot_instance(name='test1',
                                     image=image,
                                     flavor=flavors[0],
                                     keypair=keypair)

    nodes = (set(env.get_nodes_by_role('controller')) |
             set(env.get_nodes_by_role('ironic')))
    ironic_services_cmd = ("service --status-all 2>&1 | grep '+' | "
                           "grep ironic | awk '{ print $4 }'")

    stopped_services = defaultdict(set)
    for node in nodes:
        with node.ssh() as remote:
            output = remote.check_call(ironic_services_cmd).stdout_string
            for service in output.splitlines():
                remote.check_call('service {0} stop'.format(service))
                stopped_services[node].add(service)

    assert os_conn.is_server_ssh_ready(instance1)

    for node, services in stopped_services.items():
        with node.ssh() as remote:
            for service in services:
                remote.check_call('service {0} start'.format(service))

    instance2 = ironic.boot_instance(name='test2',
                                     image=image,
                                     flavor=flavors[1],
                                     keypair=keypair)

    instance1.delete()
    instance2.delete()

    os_conn.wait_servers_deleted([instance1, instance2])
