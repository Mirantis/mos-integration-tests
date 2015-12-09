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


class VrtualEnviroment(object):
    """Method to work with the virtual env over fuel-devops."""

    @staticmethod
    def revert_snapshot(env_name, snapshot_name=''):
        """Resume the env and revert the snapshot."""
        # TBD checl the exception here
        env = Environment.get(name=env_name)
        not_interested = ['ready', 'empty']
        snapshots = []
        # If the snapshot_name is empty
        # than just find the last created snaphost
        if not snapshot_name:
            for node in env.get_nodes():
                for snapshot in node.get_snapshots():
                    if snapshot.name not in not_interested:
                        snapshots.append(snapshot.name)
                        not_interested.append(snapshot.name)
            snapshot_name = snapshots[-1]
        env.resume(verbose=False)
        # TBD check the exception here
        env.revert(snapshot_name, flag=False)
