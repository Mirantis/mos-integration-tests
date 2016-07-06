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
from saharaclient import client as saharaclient
from swiftclient import client as swiftclient

from mos_tests.functions.common import gen_random_resource_name

pytest_plugins = ('mos_tests.sahara.fixture_sahara_cluster',
                  'mos_tests.sahara.fixture_pig_job')


@pytest.fixture
def swift(os_conn):
    return swiftclient.Connection(authurl=os_conn.session.auth.auth_url,
                                  user=os_conn.session.auth.username,
                                  key=os_conn.session.auth.password,
                                  tenant_name=os_conn.session.auth.tenant_name,
                                  auth_version='2.0')


@pytest.fixture
def sahara(os_conn):
    return saharaclient.Client(version='1.1', session=os_conn.session)


@pytest.yield_fixture
def keypair(os_conn):
    key = os_conn.create_key(gen_random_resource_name(prefix='sahara_key'))
    yield key
    os_conn.delete_key(key_name=key.name)
