#    Copyright 2015 Mirantis, Inc.
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
from paramiko import RSAKey

from devops.helpers.helpers import SSHClient
from fuelclient import fuelclient_settings
from fuelclient.objects.environment import Environment as EnvironmentBase
from fuelclient import client


class Environment(EnvironmentBase):
    """Extended fuelclient Environment model with some helpful methods"""

    admin_ssh_keys = None

    def get_primary_controller_ip(self):
        """Return public ip of primary controller"""
        return self.get_network_data()['public_vip']

    def find_node_by_fqdn(self, fqdn):
        """Returns list of fuelclient.objects.Node instances for cluster"""
        for node in self.get_all_nodes():
            if node.data['fqdn'] == fqdn:
                return node
        raise Exception("Node doesn't found")

    def get_ssh_to_node(self, ip):
        return SSHClient(
            host=ip,
            username='root',
            private_keys=self.admin_ssh_keys
        )

    def get_nodes_by_role(self, role):
        """Returns nodes by assigned role"""
        return [x for x in self.get_all_nodes()
                if role in x.data['roles']]

    @property
    def is_operational(self):
        return self.status == 'operational'

    @property
    def is_ha(self):
        return self.data['mode'] == 'ha_compact'

    @property
    def network_segmentation_type(self):
        return self.get_network_data()[
            'networking_parameters']['segmentation_type']

    @property
    def certificate(self):
        ssl = self.get_settings_data()['editable']['public_ssl']
        if ssl['services']['value']:
            return ssl['cert_data']['value']['content']

    @property
    def leader_controller(self):
        controllers = self.get_nodes_by_role('controller')
        controller_ip = controllers[0].data['ip']
        with self.get_ssh_to_node(controller_ip) as remote:
            response = remote.execute('pcs status cluster')
        stdout = ' '.join(response['stdout'])
        for controller in controllers:
            if controller.data['fqdn'] in stdout:
                return controller


class FuelClient(object):
    """Fuel API client"""
    def __init__(self, ip, login, password, ssh_login, ssh_password):
        self.reconfigure_fuelclient(ip, login, password)
        self.admin_ip = ip
        self.ssh_login = ssh_login
        self.ssh_password = ssh_password
        self._admin_keys = None

    @staticmethod
    def reconfigure_fuelclient(ip, login, password):
        """There is ugly way to reconfigure fuelclient APIClient singleton"""
        os.environ.update({
            'SERVER_ADDRESS': ip,
            'KEYSTONE_USER': login,
            'KEYSTONE_PASS': password,
        })
        fuelclient_settings._SETTINGS = None
        client.APIClient.__init__()

    def get_last_created_cluster(self):
        """Returns Environment instance for laset deployed cluster"""
        env = Environment.get_all()[-1]
        env.admin_ssh_keys = self.admin_keys
        return env

    @property
    def admin_keys(self):
        """Return list with private ssh keys from Fuel master node"""
        if self._admin_keys is None:
            self._admin_keys = []
            with SSHClient(host=self.admin_ip,
                           username=self.ssh_login,
                           password=self.ssh_password) as remote:
                for path in ['/root/.ssh/id_rsa',
                             '/root/.ssh/bootstrap.rsa']:
                    with remote.open(path) as f:
                        self._admin_keys.append(RSAKey.from_private_key(f))
        return self._admin_keys
