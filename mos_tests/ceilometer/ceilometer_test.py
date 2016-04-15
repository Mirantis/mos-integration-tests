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

from tempest.lib.cli import output_parser as parser


def scripts_dir_path():
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'scripts/')


@pytest.mark.testrail_id('631854')
def test_limits_feature(env):
    """Test case for Ceilometer mandatory limits feature. (QA-2039)
    Actions:
    1. Generate data in MongoDB with a help of 'mongo-generator.py';
    2. Run 'ceilometer meter-list' and check that number of items == 100;
    3. Run 'ceilometer sample-list' and check that number of items == 100;
    4. Run 'ceilometer resource-list' and check that number of items == 100;
    5. Run 'ceilometer event-list --no-traits' and check that number
        of items == 100;
    """
    script_name = 'mongo-generator.py'
    script_path = scripts_dir_path() + script_name

    set_env = 'source /root/openrc && '
    ceil_meter_list = set_env + 'ceilometer meter-list'
    ceil_sample_list = set_env + 'ceilometer sample-list'
    ceil_res_list = set_env + 'ceilometer resource-list'
    ceil_event_list = set_env + 'ceilometer event-list --no-traits'

    with env.get_nodes_by_role('controller')[0].ssh() as remote:
        remote.upload(script_path, '/root/{0}'.format(script_name))
        cmd = ('python /root/{0} --users 1 --projects 1 '
               '--resources_per_user_project 200 '
               '--samples_per_user_project 1000').format(script_name)
        remote.check_call(cmd)
        ceil_meter_list_out = remote.check_call(ceil_meter_list)['stdout']
        ceil_sample_list_out = remote.check_call(ceil_sample_list)['stdout']
        ceil_res_list_out = remote.check_call(ceil_res_list)['stdout']
        ceil_event_list_out = remote.check_call(ceil_event_list)['stdout']

    ceil_meter_list_out = parser.listing(ceil_meter_list_out)
    ceil_sample_list_out = parser.listing(ceil_sample_list_out)
    ceil_res_list_out = parser.listing(ceil_res_list_out)
    ceil_event_list_out = parser.listing(ceil_event_list_out)

    assert all(i == 100
               for i in (
                   len(ceil_meter_list_out),
                   len(ceil_sample_list_out),
                   len(ceil_res_list_out),
                   len(ceil_event_list_out)))
