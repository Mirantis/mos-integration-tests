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

import logging
import warnings

import paramiko
import pytest
import six
import json
import requests

from mos_tests.functions.common import wait
from mos_tests.functions import network_checks
from mos_tests import settings
pytestmark = pytest.mark.undestructive

logger = logging.getLogger(__name__)


class TestBase(object):
    """Class contains common methods for GlARe tests"""

    @pytest.fixture(autouse=True)
    def init(self, fuel, env, os_conn, devops_env):
        self.fuel = fuel
        self.env = env
        self.os_conn = os_conn
        self.devops_env = devops_env
        self.cirros_creds = {'username': 'cirros',
                             'password': 'cubswin:)'}

    def _url(self, url='/myartifact/v2.0/drafts'):
        endpoint = self.os_conn.session.get_endpoint(service_type='artifact', interface="internalURL")
        return "{endpoint}/v0.1/artifacts{url}".format(endpoint=endpoint, url=url)

    def _check_artifact_get(self, url, status=200):
        return self._check_artifact_methods(method="get", url=url, status=200)

    def _check_artifact_methods(self, url, method, data=None, status=200, headers=None):
        token_id = self.os_conn.session.get_token()
        if headers is None:
           headers = {"Content-Type": "application/json",
                      "X-Auth-Token": token_id}

        data = json.dumps(data)
        response = getattr(requests, method)(url=self._url(url=url), headers=headers, data=data)
        assert status == response.status_code
        if status >= 400:
            return response.text
        if "application/json" in response.headers["content-type"]:
            return json.loads(response.text)
        return response.text

    def _create_artifact(self, data=None, type_version='2.0', status=201):
        artifact_data = data or {"name":"new_name", "version":"20"}
        return self._check_artifact_post(url='/myartifact/v{vers}/drafts'.format(vers=type_version), data=artifact_data)


    def _headers(self):
        token_id = self.os_conn.session.get_token()
        headers = {'Content-Type': 'application/json', "X-Auth-Token": token_id}
        return headers

    def _check_artifact_delete(self, url, status=204):
        response = requests.delete(self._url(url), headers=self._headers())


    def _check_artifact_post(self, url, data, status=201, headers=None):
        token_id = self.os_conn.session.get_token()
        if headers is None:
            headers = {'Content-Type': 'application/json', "X-Auth-Token": token_id}
        return self._check_artifact_methods(url=url, method="post", data=data, status=status, headers=headers)
