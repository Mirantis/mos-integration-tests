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

from ironicclient import client

from mos_tests.functions import common


class IronicActions(object):
    """Ironic-specific actions"""

    def __init__(self, os_conn):
        self.os_conn = os_conn
        self.client = client.get_client(api_version=1,
                                        session=os_conn.session,
                                        os_endpoint_type='public')

    def _get_image(self, name):
        return self.os_conn.nova.images.find(name=name)

    def all_nodes_provisioned(self):
        """Check if all ironic nodes provisioned"""
        ironic_hypervisors = self.os_conn.nova.hypervisors.findall(
            hypervisor_type='ironic')
        if len(ironic_hypervisors) == 0:
            return False
        for hypervisor in ironic_hypervisors:
            if hypervisor.vcpus + hypervisor.vcpus_used == 0:
                return False
            if hypervisor.memory_mb + hypervisor.memory_mb_used == 0:
                return False
            if hypervisor.local_gb + hypervisor.local_gb_used == 0:
                return False
        return True

    def boot_instance(self,
                      image,
                      flavor,
                      keypair,
                      name='ironic-server',
                      **kwargs):
        """Boot and return ironic instance

        :param os_conn: initialized `os_conn` fixture
        :type os_conn: mos_tests.environment.os_actions.OpenStackActions
        :param image: image to boot instance with it
        :type image: warlock.core.image
        :param flavor: baremetal flavor
        :type flavor: novaclient.v2.flavors.Flavor
        :param keypair: SSH keypair to instance
        :type keypair: novaclient.v2.keypairs.Keypair
        :return: created instance
        :rtype: novaclient.v2.servers.Server
        """
        common.wait(self.all_nodes_provisioned,
                    timeout_seconds=3 * 60,
                    sleep_seconds=15,
                    waiting_for='ironic nodes to be provisioned')
        baremetal_net = self.os_conn.nova.networks.find(label='baremetal')
        return self.os_conn.create_server(name,
                                          image_id=image.id,
                                          flavor=flavor.id,
                                          key_name=keypair.name,
                                          nics=[{'net-id': baremetal_net.id}],
                                          timeout=60 * 10,
                                          **kwargs)

    def create_node(self, driver, driver_info, node_properties, mac_address):
        """Create ironic node with port

        :param driver: driver name
        :type driver: str
        :param driver_info: driver parameters (like ssh_username or
            ipmi_password)
        :type driver_info: dict
        :param node_properties: node properties (cpu, ram, etc)
        :type node_properties: dict
        :param mac_address: MAC address to port assign
        :type mac_address: str
        :return: created ironic node object
        :rtype: ironicclient.v1.node.Node
        """

        driver_info.update({
            'deploy_kernel': self._get_image('ironic-deploy-linux').id,
            'deploy_ramdisk': self._get_image('ironic-deploy-initramfs').id,
            'deploy_squashfs': self._get_image('ironic-deploy-squashfs').id,
        })

        node = self.client.node.create(driver=driver,
                                       driver_info=driver_info,
                                       properties=node_properties)
        self.client.port.create(node_uuid=node.uuid, address=mac_address)
        return node

    def delete_node(self, node):
        """Deleting ironic baremetal node, instance on it, ports

        :param node: ironic node to delete
        :type node: ironicclient.v1.node.Node
        """
        node = self.client.node.get(node.uuid)
        if node.instance_uuid:
            self.os_conn.nova.servers.delete(node.instance_uuid)
            self.os_conn.wait_servers_deleted(node.instance_uuid)
        for port in self.client.node.list_ports(node.uuid):
            self.client.port.delete(port.uuid)
        if node.provision_state == 'error':
            self.client.node.set_provision_state(node.uuid, 'deleted')
        self.client.node.delete(node.uuid)
