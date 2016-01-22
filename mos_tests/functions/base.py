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


import pytest
import unittest

from mos_tests.conftest import get_os_conn


@pytest.mark.usefixtures("os_conn_for_unittests")
class OpenStackTestCase(unittest.TestCase):
    """Base TestCase class with initialized clients"""

    def __getattr__(self, item):
        return getattr(self.os_conn, item)

    def setUp(self):
        self.os_conn = get_os_conn(self.env)
