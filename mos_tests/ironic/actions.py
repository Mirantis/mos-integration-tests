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
        token = os_conn.keystone.auth_token
        ironic_endpoint = os_conn.keystone.service_catalog.url_for(
            service_type='baremetal',
            endpoint_type='publicURL')
        self.client = client.get_client(api_version=1,
                                        os_auth_token=token,
                                        ironic_url=ironic_endpoint)

    def _get_image(self, name):
        return self.os_conn.nova.images.find(name=name)

    def get_provisioned_node(self):
        """Return ironic node wich have non zero vcpu in hypervisor

        Raises exception, if not ironic node registered

        :rtype: ironicclient.v1.node.Node
        :return: provisioned ironic node
        """
        nodes = self.client.node.list()
        if len(nodes) == 0:
            raise Exception("No ironic node registered")
        for node in nodes:
            try:
                hypervisor = self.os_conn.nova.hypervisors.find(
                    hypervisor_hostname=node.uuid)
            except Exception:
                continue
            if hypervisor.vcpus > 0:
                return node

    def boot_instance(self, image, flavor, keypair, **kwargs):
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
        common.wait(self.get_provisioned_node,
                    timeout_seconds=3 * 60,
                    sleep_seconds=15,
                    waiting_for='ironic node to be provisioned')
        baremetal_net = self.os_conn.nova.networks.find(label='baremetal')
        return self.os_conn.create_server('ironic-server',
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

        node = self.client.node.create(driver='fuel_ssh',
                                       driver_info=driver_info,
                                       properties=node_properties)
        self.client.port.create(node_uuid=node.uuid, address=mac_address)
        return node

    def delete_node(self, node):
        """Deleting ironic baremetal node, instance on it, ports

        :param node: ironic node to delete
        :type node: ironicclient.v1.node.Node
        """
        instance_uuid = self.client.node.get(node.uuid).instance_uuid
        if instance_uuid:
            self.os_conn.nova.servers.delete(instance_uuid)
            common.wait(
                lambda: len(self.os_conn.nova.servers.findall(
                    id=instance_uuid)) == 0,  # yapf: disable
                timeout_seconds=60,
                waiting_for='instance to be deleted')
        for port in self.client.node.list_ports(node.uuid):
            self.client.port.delete(port.uuid)
        self.client.node.delete(node.uuid)
