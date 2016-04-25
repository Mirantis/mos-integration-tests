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

import pytest


pytestmark = pytest.mark.undestructive


@pytest.mark.testrail_id('842486', param='-m image.size -p 100')
@pytest.mark.testrail_id('842487',
                         param='-m storage.containers.objects -p 100')
@pytest.mark.testrail_id(
    '842488',
    param='-m image -q project={project_id}; user={user_id}')
@pytest.mark.testrail_id(
    '842489',
    param='-m image.size -q project={project_id}; user={user_id}')
@pytest.mark.testrail_id(
    '842490',
    param=
    '-m storage.containers.objects -q project={project_id}; user={user_id}')
@pytest.mark.parametrize(
    'param',
    ['-m image.size -p 100',
     '-m storage.containers.objects -p 100',
     '-m image -q project={project_id}; user={user_id}',
     '-m image.size -q project={project_id}; user={user_id}',
     '-m storage.containers.objects -q project={project_id}; user={user_id}',
     ])
def test_statistic(ceilometer_client, param, os_conn):
    """Check that ceilometer statistics {params} return 0 exit code"""
    project_id = os_conn.session.get_project_id()
    user_id = os_conn.session.get_user_id()
    param = param.format(project_id=project_id, user_id=user_id)
    ceilometer_client('statistics {param}'.format(param=param))
