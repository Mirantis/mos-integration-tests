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

import os

import pytest
import yaml


@pytest.fixture
def ironic_drivers_params(ironic_drivers_params, libvirt_proxy_ip):
    ipmi_configs = [x for x in ironic_drivers_params
                    if x['driver'] == 'fuel_ipmitool']
    if len(ipmi_configs) == 0:
        pytest.skip('This test requires at leat one ipmi driver powered node')

    base_dir = os.path.dirname(__file__)
    with open(os.path.join(base_dir, 'ironic_nodes.yaml')) as f:
        libvirt_config = yaml.load(f)
    for node in libvirt_config:
        driver_info = node['driver_info']
        if driver_info['libvirt_uri'] is None:
            driver_info['libvirt_uri'] = 'qemu+tcp://{ip}/system'.format(
                ip=libvirt_proxy_ip)
    nodes_config = [libvirt_config[0], ipmi_configs[0]]
    return nodes_config


@pytest.mark.undestructive
@pytest.mark.check_env_('has_ironic_conductor')
@pytest.mark.parametrize('ironic_nodes', [2], indirect=True)
@pytest.mark.testrail_id('1664190')
def test_boot_instances_with_different_drivers(
        env, os_conn, ironic, make_image, flavors, keypair, ironic_nodes):
    """Check boot several ironic nodes using different drivers

    Scenario:
        1. Enroll 1st virtual ironic node using fuel_ipmitool driver
        2. Enroll 2nd virtual ironic node using fuel_libvirt driver
        3. Boot both 1st and 2nd baremetal instances
        4. Verify that "Provisioning State" became "active" on both nodes
        5. Check that both baremetal instances are available via ssh
    """
    image1 = make_image(node_driver=ironic_nodes[0].driver)
    image2 = make_image(node_driver=ironic_nodes[1].driver)
    instance1 = ironic.boot_instance(name="ironic_libvirt",
                                     image=image1,
                                     flavor=flavors[0],
                                     keypair=keypair,
                                     wait_for_active=False,
                                     wait_for_avaliable=False)
    instance2 = ironic.boot_instance(name="ironic_ipmi",
                                     image=image2,
                                     flavor=flavors[1],
                                     keypair=keypair,
                                     wait_for_active=False,
                                     wait_for_avaliable=False)

    os_conn.wait_servers_active([instance1, instance2])

    for node in ironic_nodes:
        node = ironic.client.node.get(node.uuid)
        assert node.provision_state == 'active'

    os_conn.wait_servers_ssh_ready([instance1, instance2])

    for server in [instance1, instance2]:
        with os_conn.ssh_to_instance(env,
                                     server,
                                     vm_keypair=keypair,
                                     username='ubuntu') as remote:
            remote.check_call('uname')
