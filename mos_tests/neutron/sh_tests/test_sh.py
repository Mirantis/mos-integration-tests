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

import logging
import os
import re

import pytest

logger = logging.getLogger(__name__)


def get_tests(base_dir):
    tests = []
    expr = re.compile(r'^test_(?P<name>.+)_(?P<id>\d+)\.sh$')
    for name in os.listdir(base_dir):
        result = expr.search(name)
        if result is None:
            continue
        test_name, id = result.groups()
        tests.append({
            'name': os.path.join(base_dir, name),
            'id': '{} ({})'.format(test_name.replace('_', ' '), id)
        })
    return tests

base_dir = os.path.dirname(__file__)

compute_tests = get_tests(os.path.join(base_dir, 'compute'))
controller_tests = get_tests(os.path.join(base_dir, 'controller'))


def run_test(path, node):
    filename = os.path.basename(path)
    with node.ssh() as remote:
        logger.info('Executing {}'.format(filename))
        remote.upload(path, filename)
        remote.check_call('chmod a+x {}'.format(filename))
        result = remote.execute('./{} 2>&1'.format(filename))
        logger.info('Stdout:')
        logger.info(''.join(result['stdout']))
        assert result['exit_code'] == 0


@pytest.mark.undestructive
@pytest.mark.shell
@pytest.mark.check_env_('is_dvr')
@pytest.mark.parametrize('filename', [x['name'] for x in compute_tests],
                        ids=[x['id'] for x in compute_tests])
def test_sh_compute(filename, env):
    node = env.get_nodes_by_role('compute')[0]
    run_test(filename, node)


@pytest.mark.undestructive
@pytest.mark.shell
@pytest.mark.parametrize('filename', [x['name'] for x in controller_tests],
                        ids=[x['id'] for x in controller_tests])
def test_sh_controller(filename, env):
    node = env.get_nodes_by_role('controller')[0]
    run_test(filename, node)
