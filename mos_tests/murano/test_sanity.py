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

from keystoneclient.v2_0 import client as ksclient
from muranoclient import client as mclient
from muranodashboard.tests.functional import base
from muranodashboard.tests.functional.config import config as cfg
from muranodashboard.tests.functional import consts as c
import pytest
from selenium.webdriver.common import by
from selenium.webdriver.support import ui
from six.moves.urllib import parse as urlparse
from xvfbwrapper import Xvfb

from mos_tests import settings

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module", autouse=True)
def set_config(credentials):
    cfg.common.horizon_url = 'http://{0.controller_ip}/horizon'.format(
        credentials)
    cfg.common.user = credentials.username
    cfg.common.password = credentials.password
    cfg.common.tenant = credentials.project
    cfg.common.keystone_url = credentials.keystone_url
    cfg.common.murano_url = 'http://{0.controller_ip}:8082/'.format(
        credentials)
    cfg.common.ca_cert = credentials.cert
    TestImportPackageWithDepencies.set_up_class()


@pytest.yield_fixture(scope='class')
def screen():
    vdisplay = Xvfb()
    vdisplay.start()
    yield
    vdisplay.stop()


@pytest.mark.requires_('firefox', 'xvfb-run')
@pytest.mark.undestructive
@pytest.mark.usefixtures('screen')
class TestImportPackageWithDepencies(base.PackageTestCase):

    @classmethod
    def setUpClass(cls):
        """Disable original method to prevent early setup with undefined cfg"""
        pass

    @classmethod
    def set_up_class(cls):
        """Real setup class method"""
        super(TestImportPackageWithDepencies, cls).setUpClass()
        cls.keystone_client = ksclient.Client(username=cfg.common.user,
                                              password=cfg.common.password,
                                              tenant_name=cfg.common.tenant,
                                              auth_url=cfg.common.keystone_url,
                                              cacert=cfg.common.ca_cert)
        cls.murano_client = mclient.Client(
            '1', endpoint=cfg.common.murano_url,
            token=cls.keystone_client.auth_token)
        cls.url_prefix = urlparse.urlparse(cfg.common.horizon_url).path or ''
        if cls.url_prefix.endswith('/'):
            cls.url_prefix = cls.url_prefix[:-1]

    def tearDown(self):
        for pkg in self.murano_client.packages.list():
            if pkg.name in settings.MURANO_PACKAGE_DEPS_NAMES:
                self.murano_client.packages.delete(pkg.id)
        super(TestImportPackageWithDepencies, self).tearDown()

    def switch_to_project(self, name):
        pass

    def test_import_package_by_url(self):
        """Test package importing via url."""

        self.navigate_to('Manage')
        self.go_to_submenu('Package Definitions')
        self.driver.find_element_by_id(c.UploadPackage).click()
        sel = self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        sel = ui.Select(sel)
        sel.select_by_value("by_url")

        el = self.driver.find_element_by_css_selector(
            "input[name='upload-url']")
        el.send_keys(settings.MURANO_PACKAGE_WITH_DEPS_URL)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        for el in self.driver.find_elements_by_class_name('alert'):
            el.find_element_by_class_name('close').click()

        # No application data modification is needed
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()
        for pkg_name in settings.MURANO_PACKAGE_DEPS_NAMES:
            self.check_element_on_page(
                by.By.XPATH, c.AppPackages.format(pkg_name))

    def test_import_package_from_repo(self):
        """Test package importing via fqn from repo with dependent apps."""

        self.navigate_to('Manage')
        self.go_to_submenu('Package Definitions')
        self.driver.find_element_by_id(c.UploadPackage).click()
        sel = self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        sel = ui.Select(sel)
        sel.select_by_value("by_name")

        el = self.driver.find_element_by_css_selector(
            "input[name='upload-repo_name']")
        el.send_keys(settings.MURANO_PACKAGE_WITH_DEPS_FQN)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        for el in self.driver.find_elements_by_class_name('alert'):
            el.find_element_by_class_name('close').click()

        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()

        for pkg_name in settings.MURANO_PACKAGE_DEPS_NAMES:
            self.check_element_on_page(
                by.By.XPATH, c.AppPackages.format(pkg_name))
