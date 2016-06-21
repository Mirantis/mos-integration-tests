# -*- coding: utf-8 -*-
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


import hashlib
import tempfile
import json

import pytest
from tempest.lib.cli import output_parser as parser

from mos_tests.functions.common import wait
from mos_tests import settings
import requests

from base import TestBase

pytestmark = pytest.mark.undestructive


class TestArtifact(TestBase):

    @pytest.mark.testrail_id('1295437')
    def test_list_any_artifacts(self):
        url1 = '/myartifact/drafts'
        art = self._create_artifact()
        artifacts = self._check_artifact_get(url=url1)
        assert len(artifacts['artifacts']) == 1

        url2 = '/myartifact/v2.0/{id}'.format(id=art['id'])
        self._check_artifact_delete(url=url2)
        artifacts = self._check_artifact_get(url=url1)
        assert len(artifacts['artifacts']) == 0

    @pytest.mark.testrail_id('1295437')
    def test_list_last_version(self):
        """/artifacts/endoint == /artifacts/endpoint/all-versions"""
        url1 = '/myartifact/v2.0/drafts'
        art = self._create_artifact()
        artifacts = self._check_artifact_get(url=url1)['artifacts']
        assert len(artifacts) == 1

        url1 = '/myartifact/drafts'
        artifacts_precise = self._check_artifact_get(url=url1)['artifacts']
        assert artifacts == artifacts_precise

        url = '/myartifact/v2.0/{id}'.format(id=art['id'])
        self._check_artifact_delete(url=url)
        artifacts = self._check_artifact_get(url=url1)
        assert len(artifacts['artifacts']) == 0