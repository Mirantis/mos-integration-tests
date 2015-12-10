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
from devops.models import Environment
# TBD: replace the logger
from tools.settings import logger


class VirtualEnviroment(object):
    """Method to work with the virtual env over fuel-devops."""

    @staticmethod
    def get_env(env_name=''):
        """Find and return env by name.

        If name is empty will try to find the last created env.
        Will return None is failed to find any env at all.
        """
        env = None
        try:
            if env_name:
                env = Environment.get(name=env_name)
            else:
                # The call below returns QuerySet not a list
                envs = Environment.list_all().order_by('created')
                # QuerySet doesn't support the Negative indexing
                # So just reverse it and get the first element
                # which due to the order method above
                # shoud be the last created env
                env = envs.reverse()[0]
        except Exception as e:
            logger.error('failed to find the last created enviroment{}'.
                         format(e))
        return env

    @staticmethod
    def revert_snapshot(env_name='', snapshot_name=''):
        """Resume the env and revert the snapshot.

        If the snapshot_name is empty
        than just find the last created snaphost
        Return True if the resume-revert is sucesfully done
        False othervise.
        """
        env = VirtualEnviroment.get_env(env_name)
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
            env.resume(verbose=False)
            env.revert(snapshot_name, flag=False)
        except Exception as e:
            logger.error('Can\'t revert snapshot due to error: {}'.
                         format(e))
            return False
        return True

    @staticmethod
    def get_admin_node_ip(env_name=''):
        """Return IP of admin node for given env_name as a string.

        Will return empty string if admin node was not found in env.
        """
        admin_ip = ''
        env = VirtualEnviroment.get_env(env_name)
        if not env:
            logger.error('Can\'t find the env')
        else:
            for node in env.get_nodes():
                if node.is_admin:
                    admin_ip = node.get_ip_address_by_network_name('admin')
        return admin_ip
