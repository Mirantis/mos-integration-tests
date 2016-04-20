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

__doc__ = """This module allow to run incremental tests.

An example below:

@pytest.mark.incremental
class TestSmth(object):
    def test_a(self):
        self.__class__.item = 'foo'          # < set some value to class
        assert True

    def test_b(self):
        assert self.__class__.item == 'foo'  # < get value, which was setted in
                                             # previous test
        assert False                         # < here test will fail

    def test_c(self):
        assert True                          # < this test will mark as xfailed
"""


def gen_key(item):
    if not hasattr(item, 'callspec'):
        return None
    else:
        return str(item.callspec.params)


def pytest_runtest_makereport(item, call):
    if "incremental" in item.keywords:
        if call.excinfo is not None:
            parent = item.parent
            parent._previousfailed = {gen_key(item): item}


def pytest_runtest_setup(item):
    if "incremental" in item.keywords:
        previousfailed_info = getattr(item.parent, "_previousfailed", {})
        previousfailed = previousfailed_info.get(gen_key(item))
        if previousfailed is not None:
            pytest.xfail("previous test failed ({0.name})".format(
                previousfailed))
