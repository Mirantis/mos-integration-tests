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

from distutils.spawn import find_executable
import pytest
import six

from mos_tests.environment.devops_client import DevopsClient


@pytest.fixture(autouse=True)
def devops_requirements(request, env_name):
    if request.node.get_marker('need_devops'):
        try:
            DevopsClient.get_env(env_name=env_name)
        except Exception:
            pytest.skip('requires devops env to be defined')


@pytest.fixture(autouse=True)
def tshark_requirements(request, env_name):
    if request.node.get_marker('need_tshark'):
        path = find_executable('tshark')
        if path is None:
            pytest.skip('requires tshark executable')


def pytest_configure(config):
    config.addinivalue_line("markers",
        "name_suffix(suffix, cond=condition): add suffix to test if condition "
        "is True. Condition may be value, expression, or string (in such case "
        "it will eval)")


@pytest.fixture(autouse=True)
def name_suffix(request, env):
    """Add suffix_smth mark to testcases"""
    markers = request.node.get_marker('name_suffix') or []
    suffixes = []
    for marker in markers:
        suffix = marker.args[0]
        condition = marker.kwargs['cond']
        if isinstance(condition, six.string_types):
            condition = eval(condition)
        if condition:
            suffixes.append(suffix)
    suffixes = reversed(suffixes)
    suffixes_string = ''.join('[{}]'.format(x) for x in suffixes)
    request.node.add_marker('suffixes_{}'.format(suffixes_string))


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_logreport(report):
    """Collect suffix_ prefixed marks and add it to testid in report"""
    suffixes = [x.lstrip('suffixes_') for x in report.keywords.keys()
                if x.startswith('suffixes_')]
    if len(suffixes) > 0:
        report.nodeid += suffixes[0]
    yield
