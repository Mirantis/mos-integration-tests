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

from itertools import groupby
import logging
import os

from fuelclient import client
from fuelclient import fuelclient_settings
from fuelclient.objects import environment
from fuelclient.objects.node import Node as FuelNode
from fuelclient.objects import task as fuel_task
from paramiko import RSAKey
from paramiko import ssh_exception

from mos_tests.environment.ssh import SSHClient
from mos_tests.functions.common import gen_temp_file
from mos_tests.functions.common import wait


logger = logging.getLogger(__name__)


class NodeProxy(object):
    """Fuelclient Node proxy model with some helpful methods"""

    def __init__(self, orig_node, env):
        self._orig_node = orig_node
        self._env = env

    def __getattr__(self, name):
        return getattr(self._orig_node, name)

    def __eq__(self, other):
        if type(other) != type(self):
            return False
        return self.data['ip'] == other.data['ip']

    def __ne__(self, other):
        return not(self == other)

    def __repr__(self):
        return '<{name}({ip})>'.format(**self.data)

    @property
    def ip_list(self):
        """Returns node ip addresses list"""
        return [x['ip'].split('/')[0] for x in self.data['network_data']
                if 'ip' in x]

    def ssh(self):
        return SSHClient(
            host=self.data['ip'],
            username='root',
            private_keys=self._env.admin_ssh_keys
        )

    def is_ssh_avaliable(self):
        try:
            with self.ssh() as remote:
                remote.check_call('uname')
        except (ssh_exception.SSHException,
                ssh_exception.NoValidConnectionsError):
            return False
        else:
            return True


class Environment(environment.Environment):
    """Extended fuelclient Environment model with some helpful methods"""

    admin_ssh_keys = None
    _admin_ssh_keys_paths = None

    @property
    def admin_ssh_keys_paths(self):
        if self._admin_ssh_keys_paths is None:
            self._admin_ssh_keys_paths = []
            for key in self.admin_ssh_keys:
                keyfile = gen_temp_file(prefix="fuel_key_", suffix=".rsa")
                path = keyfile.name
                key.write_private_key_file(path)
                self._admin_ssh_keys_paths.append(path)
        return self._admin_ssh_keys_paths

    def get_all_nodes(self):
        nodes = super(Environment, self).get_all_nodes()
        return [NodeProxy(x, self) for x in nodes]

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

    def get_ssh_to_vm(self, ip, username=None, password=None,
                      private_keys=None, **kwargs):
        return SSHClient(
            host=ip, username=username, password=password,
            private_keys=private_keys, **kwargs)

    def get_nodes_by_role(self, role):
        """Returns nodes by assigned role"""
        return [x for x in self.get_all_nodes()
                if role in x.data['roles']]

    def is_ostf_tests_pass(self, *test_groups):
        """Check for OpenStack tests pass"""

        def test_is_done():
            res = self.get_state_of_tests()[0]
            if res['status'] == 'finished':
                return res

        if len(test_groups) == 0:
            test_groups = ('ha',)
        logger.info('[Re]start OSTF tests {}'.format(test_groups))
        self.run_test_sets(test_groups)
        result = wait(test_is_done, timeout_seconds=10 * 60,
                      waiting_for='OSTF tests to finish')

        for test in result['tests']:
            if test['status'] not in ('success', 'skipped'):
                logger.warning(
                    'Test "{name}" status is {status}; {message}'.format(
                        **test))
                return False
        return True

    def wait_for_ostf_pass(self):
        wait(self.is_ostf_tests_pass, timeout_seconds=20 * 60,
             sleep_seconds=20,
             waiting_for='OpenStack to pass OSTF tests')

    def wait_network_verification(self):
        data = self.verify_network()
        t = fuel_task.Task(data['id'])

        def is_ready():
            if t.is_finished:
                return t
        return wait(is_ready, timeout_seconds=3 * 60,
                    waiting_for='network verification to finish',
                    sleep_seconds=5)

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
            response = remote.check_call(
                'pcs status cluster | grep "Current DC:"')
        stdout = response.stdout_string
        for controller in controllers:
            if controller.data['fqdn'] in stdout:
                return controller

    @property
    def primary_controller(self):
        controllers = self.get_nodes_by_role('controller')
        for controller in controllers:
            with controller.ssh() as remote:
                response = remote.execute('hiera roles')
                stdout = ' '.join(response['stdout'])
                logger.debug('hiera roles for {} is {}'.format(
                    controller.data['fqdn'], stdout))
                if 'primary-controller' in stdout:
                    return controller
        else:
            raise Exception("Can't find primary controller")

    @property
    def non_primary_controllers(self):
        controllers = self.get_nodes_by_role('controller')
        primary_controller = self.primary_controller
        non_primary_controllers = [
            controller for controller in controllers
            if controller != primary_controller]
        non_primary_controllers.sort(key=lambda node: node.data['fqdn'])
        return non_primary_controllers

    def destroy_nodes(self, devops_nodes):
        node_ips = [node.get_ip_address_by_network_name('admin')
                    for node in devops_nodes]
        for node in devops_nodes:
            node.destroy()
        wait(lambda: self.check_nodes_get_offline_state(node_ips),
             timeout_seconds=10 * 60,
             waiting_for='the nodes get offline state')

        def keyfunc(node):
            return node.data['online']

        all_nodes = self.get_all_nodes()
        all_nodes.sort(key=keyfunc)
        for online, nodes in groupby(all_nodes, keyfunc):
            logger.info('online is {0} for nodes {1}'
                        .format(online, list(nodes)))

    def warm_shutdown_nodes(self, devops_nodes):
        for node in devops_nodes:
            node_ip = node.get_ip_address_by_network_name('admin')
            logger.info('Shutdown node {0} with ip {1}'
                        .format(node.name, node_ip))
            with self.get_ssh_to_node(node_ip) as remote:
                remote.check_call('/sbin/shutdown -Ph now')
        self.destroy_nodes(devops_nodes)

    def warm_start_nodes(self, devops_nodes):
        for node in devops_nodes:
            logger.info('Starting node {}'.format(node.name))
            node.create()
        wait(self.check_nodes_get_online_state, timeout_seconds=10 * 60)
        logger.info('wait until the nodes get online state')
        for node in self.get_all_nodes():
            logger.info('online state of node {0} now is {1}'
                        .format(node.data['name'], node.data['online']))

    def warm_restart_nodes(self, devops_nodes):
        logger.info('Reboot (warm restart) nodes %s',
                    [n.name for n in devops_nodes])
        self.warm_shutdown_nodes(devops_nodes)
        self.warm_start_nodes(devops_nodes)

    def check_nodes_get_offline_state(self, node_ips=()):
        nodes_states = [not x.data['online']
                        for x in self.get_all_nodes()
                        if x.data['ip'] in node_ips]
        return all(nodes_states)

    def check_nodes_get_online_state(self):
        return all([node.data['online'] for node in self.get_all_nodes()])

    def get_node_ip_by_host_name(self, hostname):
        controller_ip = ''
        for node in self.get_all_nodes():
            if node.data['fqdn'] == hostname:
                controller_ip = node.data['ip']
                break
        return controller_ip

    def get_node_by_devops_node(self, devops_node, interface='admin'):
        interfaces = devops_node.interface_by_network_name(interface)
        for interface in interfaces:
            for node in FuelNode.get_all():
                if node._data['mac'] == interface.mac_address:
                    return NodeProxy(node, self)


class FuelClient(object):
    """Fuel API client"""
    def __init__(self, ip, login, password, ssh_login, ssh_password):
        logger.debug('Init fuel client on {0}'.format(ip))
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
        """Returns Environment instance for latest deployed cluster"""
        env = Environment.get_all()[-1]
        env.admin_ssh_keys = self.admin_keys
        return env

    def ssh_admin(self):
        return SSHClient(host=self.admin_ip,
                         username=self.ssh_login,
                         password=self.ssh_password)

    @property
    def admin_keys(self):
        """Return list with private ssh keys from Fuel master node"""
        if self._admin_keys is None:
            self._admin_keys = []
            with self.ssh_admin() as remote:
                for path in ['/root/.ssh/id_rsa',
                             '/root/.ssh/bootstrap.rsa']:
                    with remote.open(path) as f:
                        self._admin_keys.append(RSAKey.from_private_key(f))
        return self._admin_keys
