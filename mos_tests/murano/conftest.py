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
import subprocess

import pytest


@pytest.fixture(autouse=True, scope="session")
def prepare(set_openstack_environ):
    pass


def pytest_cmdline_preparse(args):
    base_dir = os.path.dirname(__file__)
    subprocess.check_call("{0}/pytest_adapter.sh {0}/client".format(base_dir),
                          shell=True, env=dict(os.environ))
    args[:] = args + ['--doctest-glob=""']
    os.environ['OS_MURANOCLIENT_EXEC_DIR'] = "{VENV_PATH}/bin".format(
        **os.environ)


def pytest_ignore_collect(path, config):
    # TODO(gdyuldin) make it py3 compatible
    p = unicode(path)
    if 'muranoclient/tests/' in p and 'muranoclient/tests/functional' not in p:
        return True
    return False


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.undestructive)
