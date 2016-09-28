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
import unittest

import pytest

from mos_tests.environment.devops_client import DevopsClient

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption("--env",
                     '-E',
                     action="store",
                     help="Fuel devops env name")
    parser.addoption("--snapshot",
                     '-S',
                     action="store",
                     help="Fuel devops snapshot name")


def pytest_configure(config):
    # register an additional marker
    config.addinivalue_line("markers",
                            "need_devops: mark test wich need devops to run")
    config.addinivalue_line("markers",
                            "undestructive: mark test wich has teardown")
    config.addinivalue_line("markers",
                            "force_revert_cleanup: run revert after executing "
                            "test(s) in function/class/module")


@pytest.fixture(scope="session")
def env_name(request):
    return request.config.getoption("--env")


@pytest.fixture(scope="session")
def snapshot_name(request):
    return request.config.getoption("--snapshot")


@pytest.fixture(autouse=True)
def devops_requirements(request, env_name):
    if request.node.get_marker('need_devops'):
        try:
            DevopsClient.get_env(env_name=env_name)
        except Exception:
            pytest.skip('requires devops env to be defined')


def revert_snapshot(env_name, snapshot_name):
    DevopsClient.revert_snapshot(env_name=env_name,
                                 snapshot_name=snapshot_name)


def clean_finalizers(request, finalizers):
    for finalizer in finalizers:
        try:
            fixturedef = finalizer.im_self
        except:
            continue
        if not hasattr(fixturedef, 'cached_result'):
            continue
        if fixturedef.scope == 'session':
            continue
        logger.info("Cleaning %s fixture", fixturedef.argname)
        fixturedef._finalizer = []
        if hasattr(fixturedef, "cached_result"):
            del fixturedef.cached_result


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    """Count failed tests to detect fail"""

    failed_count_before = item.session.testsfailed
    setattr(item, 'failed_count_before', failed_count_before)

    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Revert devops environment after destruclive and failed tests
        (if possible)"""

    outcome = yield

    # No revert after last test
    if nextitem is None or item.session.shouldstop:
        return

    # No revert on KeyboardInterrupt
    if outcome.excinfo is not None and outcome.excinfo[0] is KeyboardInterrupt:
        return

    reverted = False

    # Test fail or teardown fail
    failed = (item.failed_count_before != item.session.testsfailed or
              outcome.excinfo is not None)

    destructive = 'undestructive' not in item.keywords
    env_name = item.config.getoption("--env")
    snapshot_name = item.config.getoption("--snapshot")
    if destructive or failed:
        if all([env_name, snapshot_name]):
            revert_snapshot(env_name, snapshot_name)

            finalizers = [
                x
                for y in item.session._setupstate._finalizers.values()
                for x in y if hasattr(x, 'im_self')
            ]
            clean_finalizers(item._request, finalizers)

            parent = item
            while parent != item.session:
                if parent in item.session._setupstate._finalizers:
                    del item.session._setupstate._finalizers[parent]
                if parent.cls and issubclass(parent.cls, unittest.TestCase):
                    parent.setup()
                parent = parent.parent
            if item in item.session._setupstate._finalizers:
                del item.session._setupstate._finalizers[item]
            reverted = True

    setattr(nextitem._request.session, 'reverted', reverted)
