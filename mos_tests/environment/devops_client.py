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
"""Virtual test env setup and so on."""
import logging

from devops.models import Environment

logger = logging.getLogger(__name__)


class DevopsClient(object):
    """Method to work with the virtual env over fuel-devops."""

    @classmethod
    def get_env(cls, env_name=''):
        """Find and return env by name.

        If name is empty will try to find the last created env.
        Will return None is failed to find any env at all.
        """
        env = None
        try:
            if env_name:
                env = Environment.get(name=env_name)
            else:
                env = Environment.objects.all().order_by('created').last()
        except Exception as e:
            logger.error('failed to find the last created enviroment{}'.
                         format(e))
            raise
        return env

    @classmethod
    def revert_snapshot(cls, env_name='', snapshot_name=''):
        """Resume the env and revert the snapshot.

        If the snapshot_name is empty
        than just find the last created snaphost
        Return True if the resume-revert is sucesfully done
        False othervise.
        """
        env = cls.get_env(env_name)
        not_interested = ['ready', 'empty']
        snapshots = []
        try:
            if not snapshot_name:
                for node in env.get_nodes():
                    for snapshot in node.get_snapshots():
                        if snapshot.name not in not_interested:
                            snapshots.append(snapshot.name)
                            not_interested.append(snapshot.name)
                snapshot_name = snapshots[-1]
            # TBD the calls below are non blocking once, need to add wait
            logger.info("Reverting snapshot {0}".format(snapshot_name))
            env.revert(snapshot_name, flag=False)
            env.resume(verbose=False)
            cls.sync_tyme(env)
        except Exception as e:
            logger.error('Can\'t revert snapshot due to error: {}'.
                         format(e))
            raise

    @classmethod
    def get_admin_node_ip(cls, env_name=''):
        """Return IP of admin node for given env_name as a string.

        Will return empty string if admin node was not found in env.
        """
        admin_ip = ''
        env = cls.get_env(env_name)
        if not env:
            logger.error('Can\'t find the env')
        else:
            master = env.get_nodes(role='fuel_master')[0]
            admin_ip = master.get_ip_address_by_network_name('admin')
        return admin_ip

    @classmethod
    def sync_tyme(cls, env):
        with env.get_admin_remote() as remote:
            slaves_count = len(env.nodes().all) - 1
            remote.execute('hwclock --hctosys')
            remote.execute('for i in {{1..{0}}}; do ssh node-$i '
                           '"hwclock --hctosys"; done'.format(slaves_count))

    @classmethod
    def get_node_by_mac(cls, env_name, mac):
        env = cls.get_env(env_name=env_name)
        for node in env.nodes().slaves:
            interfaces = node.interface_by_network_name('admin')
            mac_addresses = [x.mac_address for x in interfaces]
            if mac in mac_addresses:
                return node
