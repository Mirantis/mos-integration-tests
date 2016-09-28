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


@pytest.fixture(autouse=True)
def set_fuel_ip(request, fuel):
    setattr(request.node, 'fuel_ip', fuel.admin_ip)


def pytest_runtest_makereport(item, call):
    config = item.session.config

    fuel_ip = getattr(item, 'fuel_ip', None)
    if fuel_ip is None:
        return

    make_snapshot = config.getoption("--make-snapshots")
    is_ci = os.environ.get('JOB_NAME') is not None
    test_failed = call.excinfo is not None
    if test_failed and (make_snapshot or is_ci):
        try:
            task = SnapshotTask.start_snapshot_task({})
            waiting.wait(lambda: task.is_finished,
                         timeout_seconds=10 * 60,
                         sleep_seconds=5,
                         waiting_for='dump to be finished')
            if task.status != 'ready':
                raise Exception("Snapshot generating task ended with error. "
                                "Task message: {message}".format(**task.data))

            url = 'http://{fuel_ip}:8000{task.data[message]}'.format(
                fuel_ip=fuel_ip, task=task)
            response = requests.get(
                url,
                stream=True,
                headers={'x-auth-token': APIClient.auth_token})

            test_name = item.nodeid
            logger.info('Making snapshot to test {}'.format(test_name))
            filename = re.sub('[^\w\s-]', '_', test_name).strip().lower()
            _, ext = os.path.splitext(task.data['message'])
            ext = ext or '.tar'
            path = os.path.join('snapshots', filename + ext)

            with open(path, 'wb') as f:
                for chunk in response.iter_content(65536):
                    f.write(chunk)
        except Exception as e:
            logger.warning(e)
