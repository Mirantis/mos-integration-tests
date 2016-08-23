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

from fuelclient.objects import SnapshotTask
from fuelclient.client import APIClient
import pytest
import requests
import waiting

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption("--make-snapshots",
                     '-D',
                     action="store_true",
                     help="Generate fuel diagnostic snapshot on failues")


@pytest.yield_fixture(autouse=True)
def make_snapshot(request, fuel, env):
    """Make fuel diagnostic snapshot after failed tests"""
    yield

    try:
        skip_snapshot = not request.config.getoption("--make-snapshots")
        if skip_snapshot and os.environ.get('JOB_NAME') is None:
            return

        steps_rep = [getattr(request.node, 'rep_{}'.format(name), None)
                     for name in ("setup", "call", "teardown")]
        if not any(x for x in steps_rep if x is not None and x.failed):
            return

        test_name = request.node.nodeid
        logger.info('Making snapshot to test {}'.format(test_name))
        filename = unicode(re.sub('[^\w\s-]', '_', test_name).strip().lower())
        filename += '.tar.xz'
        path = os.path.join('snapshots', filename)

        config = SnapshotTask.get_default_config()
        task = SnapshotTask.start_snapshot_task(config)
        waiting.wait(lambda: task.is_finished,
                     timeout_seconds=10 * 60,
                     sleep_seconds=5,
                     waiting_for='dump to be finished')
        if task.status != 'ready':
            raise Exception(
                "Snapshot generating task ended with error. Task message: {0}"
                .format(task.data["message"]))

        url = 'http://{fuel.admin_ip}:8000{task.data[message]}'.format(
            fuel=fuel, task=task)
        response = requests.get(url,
                                stream=True,
                                headers={'x-auth-token': APIClient.auth_token})
        with open(path, 'wb') as f:
            for chunk in response.iter_content(65536):
                f.write(chunk)
    except Exception as e:
        logger.warning(e)
