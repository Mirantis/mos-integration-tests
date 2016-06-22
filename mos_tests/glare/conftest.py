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

from muranoclient.glance.client import Client as GlanceClient
import pytest


@pytest.fixture
def glare_client(os_conn):
    type_name = 'myartifact'
    type_version = '2.0'
    endpoint = os_conn.session.get_endpoint(service_type='artifact',
                                            interface="internalURL")
    token = os_conn.session.get_auth_headers()['X-Auth-Token']
    glanceclient = GlanceClient(endpoint=endpoint,
                                type_name=type_name,
                                type_version=type_version,
                                token=token)
    return glanceclient.artifacts
