#    Copyright 2014 Mirantis, Inc.
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

from devops.models import Environment
from devops.models import Interface

logger = logging.getLogger(__name__)


class EnvProxy(object):
    """Devops environment proxy model with some helpful methods"""

    def __init__(self, env):
        self._env = env

    def __getattr__(self, name):
        return getattr(self._env, name)

    def add_node(self,
                 name,
                 memory=1024,
                 vcpu=1,
                 networks=None,
                 disks=(),
                 role='fuel_slave'):
        """Add new slave node to cluster

        :param name: name of node
        :param memory: memory in MB
        :param vcpu: CPU count
        :param networks: names of networks to assign to node. If None - will
            assign all networks
        :type networks: tuple or list or None
        :param disks: sizes of disk devices in GB to attach to node
        :param role: may be one of fuel_maste, fuel_slave, ironic_slave
        :return: created and started Node object
        :rtype: devops.models.node.Node
        """

        if self._env.node_set.filter(name=name).exists():
            node = self._env.get_node(name=name)
            node.erase()
        node = self._env.add_node(vcpu=vcpu,
                                  memory=memory,
                                  name=name,
                                  role=role)

        for i, size in enumerate(disks, 1):
            volume_name = '{name}_drive{i}'.format(name=name, i=i)
            if self._env.volume_set.filter(name=volume_name).exists():
                volume = self._env.get_volume(name=volume_name)
                volume.erase()

            volume = self._env.add_empty_volume(node, volume_name,
                                                size * (1024**3))
            volume.define()
        if networks is None:
            networks = self.get_networks().values_list('name', flat=True)
        node.attach_to_networks(networks)
        node.define()
        node.start()

        return node

    def del_node(self, node):
        """Add new slave node to cluster

        :param node: node object to destroy and delete
        :type node: devops.models.node.Node
        """
        node.destroy()
        for disk in node.disk_devices:
            disk.volume.erase()
            disk.delete()
        node.erase()

    def get_node_by_fuel_node(self, fuel_node):
        """Return devops node by fuel node

        :return: matched node
        :rtype: devops.models.node.Node
        """
        interfaces = fuel_node.data['meta']['interfaces']
        mac_addresses = [x['mac'] for x in interfaces]
        return self.node_set.distinct('uuid').get(
            interface__mac_address__in=mac_addresses)

    def get_interface_by_fuel_name(self, fuel_name, fuel_env):
        """Return devops network name for fuel network name

        :param fuel_name: fuel network name (like 'baremetal')
        :param fuel_env: Fuel environment object
        :type fuel_env: mos_tests.environment.fuel_client.Environment
        :return: devops network name
        """
        controller = fuel_env.get_nodes_by_role('controller')[0]
        fuel_networks = controller.data['network_data']
        node_devices = [x['dev'] for x in fuel_networks
                        if x['name'] == fuel_name]
        assert len(node_devices) == 1
        node_interfaces = [x
                           for x in controller.data['meta']['interfaces']
                           if x['name'] == node_devices[0]]
        assert len(node_interfaces) == 1
        interface_mac = node_interfaces[0]['mac']
        return Interface.objects.get(mac_address=interface_mac)

    def get_net_mac_addresses(self, net_name):
        net = self.get_network(name="private")
        return net.interfaces.values_list('mac_address', flat=True)

    def get_mac_net_mapping(self):
        result = {}
        for net in self.get_networks():
            addresses = net.interfaces.values_list('mac_address', flat=True)
            result.update(dict.fromkeys(addresses, net.name))
        return result

    def revert_snapshot(self, snapshot_name):
        try:
            logger.info("Reverting snapshot {0}".format(snapshot_name))
            self.revert(snapshot_name, flag=False)
            self.resume(verbose=False)
            self.sync_time()
        except Exception as e:
            logger.error('Can\'t revert snapshot due to error: {}'.format(e))
            raise

    def sync_time(self):
        with self.get_admin_remote() as remote:
            slaves_count = len(self.nodes().all) - 1
            logger.info("sync time on master")
            remote.execute('hwclock --hctosys')
            logger.info("sync time on {} slaves".format(slaves_count))
            remote.execute('for i in {{1..{0}}}; '
                           'do (ssh node-$i "hwclock --hctosys") done'.format(
                               slaves_count))


class DevopsClient(object):
    """Method to work with the virtual env over fuel-devops."""

    @classmethod
    def get_env(cls, env_name):
        """Find and return env by name."""
        try:
            return EnvProxy(Environment.get(name=env_name))
        except Exception as e:
            logger.error(
                'failed to find the last created environment{}'.format(e))
            raise

    @classmethod
    def revert_snapshot(cls, env_name, snapshot_name):
        """Resume the env and revert the snapshot."""
        env = cls.get_env(env_name)
        return env.revert_snapshot(snapshot_name)

    @classmethod
    def get_admin_node_ip(cls, env_name):
        """Return IP of admin node for given env_name as a string.

        Will return empty string if admin node was not found in env.
        """
        admin_ip = ''
        env = cls.get_env(env_name)
        if not env:
            logger.error('Can\'t find the env')
        else:
            master = env.get_nodes(role__in=('fuel_master', 'admin'))[0]
            admin_ip = master.get_ip_address_by_network_name('admin')
        return admin_ip

    @classmethod
    def get_devops_node(cls, node_name='', env_name=''):
        env = cls.get_env(env_name)
        for node in env.get_nodes():
            if node_name == node.name:
                return node
