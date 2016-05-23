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
import shutil
import tempfile
import types
import uuid
import zipfile

from muranodashboard.tests.functional import base
from muranodashboard.tests.functional.config import config as cfg
from muranodashboard.tests.functional import consts as c
from muranodashboard.tests.functional import utils
import pytest
from selenium.webdriver.common import by
from selenium.webdriver.support import expected_conditions as EC  # noqa
from selenium.webdriver.support import ui
from six.moves import configparser
from six.moves.urllib import request
from xvfbwrapper import Xvfb

from mos_tests.functions import common
from mos_tests import settings

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.undestructive

apps_names = ['app_small', 'app_big']


@pytest.yield_fixture(scope='class')
def screen():
    vdisplay = Xvfb(width=1280, height=720)
    vdisplay.start()
    yield
    vdisplay.stop()


@pytest.yield_fixture
def package_size_limit(env):
    def set_package_size_limit(node):
        with node.ssh() as remote:
            remote.check_call('service murano-api stop')
            remote.check_call('mv /etc/murano/murano.conf '
                              '/etc/murano/murano.conf.orig')
            with remote.open('/etc/murano/murano.conf.orig') as f:
                parser = configparser.RawConfigParser()
                parser.readfp(f)
                try:
                    parser.set('packages_opts', 'package_size_limit', 2)
                except configparser.NoSectionError:
                    parser.add_section('packages_opts')
                    parser.set('packages_opts', 'package_size_limit', 2)
                with remote.open('/etc/murano/murano.conf', 'w') as new_f:
                    parser.write(new_f)
            remote.check_call('service murano-api start')

    def reset_package_size_limit(node):
        with node.ssh() as remote:
            remote.check_call('service murano-api stop')
            remote.check_call('mv /etc/murano/murano.conf.orig '
                              '/etc/murano/murano.conf')
            remote.check_call('service murano-api start')

    controllers = env.get_nodes_by_role('controller')
    for controller in controllers:
        set_package_size_limit(controller)
    yield
    for controller in controllers:
        reset_package_size_limit(controller)


def prepare_zips():
    def change_archive_size(archive_name, size):
        file_name = os.path.join(os.path.split(archive_name)[0], 'file')
        initial_size = os.path.getsize(archive_name)
        with open(file_name, 'wb') as f:
            f.seek(size * 1024 * 1024 - initial_size - 1)
            f.write('\0')
        with zipfile.ZipFile(archive_name, 'a') as archive:
            archive.write(file_name)
    tmp_dir = tempfile.mkdtemp()
    manifest = os.path.join(c.PackageDir, 'manifest.yaml')
    app_small = utils.compose_package(
        apps_names[0], manifest, c.PackageDir, archive_dir=tmp_dir)
    app_big = utils.compose_package(
        apps_names[1], manifest, c.PackageDir, archive_dir=tmp_dir)
    change_archive_size(app_small, 1.99)
    change_archive_size(app_big, 2.01)
    return [app_small, app_big]


def murano_test_patch(cls):
    """Class decorator to make setUpClass method lazy"""

    def lazySetUpClass(cls):  # noqa
        return super(cls, cls).setUpClass()

    def setUpClass(cls):
        pass

    @pytest.fixture(scope="class", autouse=True)
    def set_config(self, credentials):
        cfg.common.horizon_url = 'http://{0.controller_ip}/horizon'.format(
            credentials)
        cfg.common.user = credentials.username
        cfg.common.password = credentials.password
        cfg.common.tenant = credentials.project
        cfg.common.keystone_url = credentials.keystone_url
        cfg.common.murano_url = 'http://{0.controller_ip}:8082/'.format(
            credentials)
        cfg.common.ca_cert = credentials.cert
        self.lazySetUpClass()

    def switch_to_project(self, name):
        pass

    if 'setUpClass' in cls.__dict__:
        method = cls.setUpClass
    else:
        method = types.MethodType(lazySetUpClass, cls, cls)
    setattr(cls, 'lazySetUpClass', method)
    setattr(cls, 'setUpClass', types.MethodType(setUpClass, cls, cls))
    setattr(cls, 'set_config', set_config)
    setattr(cls, 'switch_to_project', switch_to_project)

    return cls


@pytest.mark.requires_('firefox', 'xvfb-run')
@pytest.mark.undestructive
@pytest.mark.usefixtures('screen')
@murano_test_patch
class TestImportPackageWithDepencies(base.PackageTestCase):

    def tearDown(self):
        for pkg in self.murano_client.packages.list():
            if pkg.name in settings.MURANO_PACKAGE_DEPS_NAMES:
                self.murano_client.packages.delete(pkg.id)
        super(TestImportPackageWithDepencies, self).tearDown()

    @pytest.mark.testrail_id('836647')
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
        self.wait_element_is_clickable(by.By.XPATH, c.InputSubmit)
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()
        for pkg_name in settings.MURANO_PACKAGE_DEPS_NAMES:
            self.check_element_on_page(
                by.By.XPATH, c.AppPackages.format(pkg_name))

    @pytest.mark.testrail_id('836648')
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

        self.wait_element_is_clickable(by.By.XPATH, c.InputSubmit)
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()

        for pkg_name in settings.MURANO_PACKAGE_DEPS_NAMES:
            self.check_element_on_page(
                by.By.XPATH, c.AppPackages.format(pkg_name))


@pytest.mark.requires_('firefox', 'xvfb-run')
@pytest.mark.usefixtures('screen')
@murano_test_patch
class TestPackageSizeLimit(base.PackageTestCase):
    """Test package size limit."""

    def setUp(self):
        super(TestPackageSizeLimit, self).setUp()
        self.zips = prepare_zips()

    def tearDown(self):
        for pkg in self.murano_client.packages.list():
            if pkg.name in apps_names:
                self.murano_client.packages.delete(pkg.id)
        shutil.rmtree((os.path.split(self.zips[0])[0]), ignore_errors=True)
        super(TestPackageSizeLimit, self).tearDown()

    @pytest.mark.testrail_id('836646')
    @pytest.mark.usefixtures('package_size_limit')
    def test_package_size_limit(self):
        self.navigate_to('Manage')
        self.go_to_submenu('Package Definitions')

        # Upload package with allowed size
        self.driver.find_element_by_id(c.UploadPackage).click()
        el = self.driver.find_element_by_css_selector(
            "input[name='upload-package']")
        el.send_keys(self.zips[0])
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        for el in self.driver.find_elements_by_class_name('alert'):
            el.find_element_by_class_name('close').click()
        self.wait_element_is_clickable(by.By.XPATH, c.InputSubmit)
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.wait_for_alert_message()
        self.check_element_on_page(by.By.XPATH,
                                   c.AppPackages.format(apps_names[0]))

        # Upload package with not allowed size
        self.driver.find_element_by_id(c.UploadPackage).click()
        el = self.driver.find_element_by_css_selector(
            "input[name='upload-package']")
        el.send_keys(self.zips[1])
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        error_message = ("Error: 400 Bad Request: Uploading file is too "
                         "large. The limit is 2 Mb")
        self.check_alert_message(error_message)
        for el in self.driver.find_elements_by_class_name('alert'):
            el.find_element_by_class_name('close').click()
        self.check_element_not_on_page(by.By.XPATH,
                                       c.AppPackages.format(apps_names[1]))


@pytest.mark.requires_('firefox', 'xvfb-run')
@pytest.mark.undestructive
@pytest.mark.usefixtures('screen')
@murano_test_patch
class TestDeployEnvInNetwork(base.ApplicationTestCase):

    @classmethod
    def _create_network_with_subnet(cls, net_name, subnet_name,
                                    cidr=None):
        """Create network with subnet."""
        if cidr is None:
            cidr = '192.168.1.0/24'

        network = cls.os_conn.create_network(name=net_name)
        subnet = cls.os_conn.create_subnet(
            network_id=network['network']['id'],
            name=subnet_name,
            cidr=cidr,
            dns_nameservers=['8.8.8.8'])
        return network, subnet

    @classmethod
    def _create_router_between_nets(cls, router_name, ext_net, subnet):
        """Create router between external network and sub network."""
        router = cls.os_conn.create_router(name=router_name)
        cls.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=ext_net['id'])

        cls.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])
        return router

    @staticmethod
    def gen_random_resource_name(prefix=None, reduce_by=None):
        random_name = str(uuid.uuid4()).replace('-', '')[::reduce_by]
        if prefix:
            random_name = prefix + '_' + random_name
        return random_name

    def _prepare(self, cidr):
        self.net_name = self.gen_random_resource_name(prefix='net')
        self.subnet_name = self.gen_random_resource_name(prefix='subnet')
        self.router_name = self.gen_random_resource_name(prefix='router')

        _, subnet = self._create_network_with_subnet(
            net_name=self.net_name,
            subnet_name=self.subnet_name,
            cidr=cidr)

        self._create_router_between_nets(
            router_name=self.router_name,
            ext_net=self.os_conn.ext_network,
            subnet=subnet)

    @pytest.yield_fixture
    def prepare_24(self, os_conn_for_unittests):
        self._prepare(cidr='192.168.1.0/24')

        yield

        self.os_conn.cleanup_network()

    @pytest.yield_fixture
    def prepare_30(self, os_conn_for_unittests):
        self._prepare(cidr='192.168.1.0/30')

        yield

        self.os_conn.cleanup_network()

    @classmethod
    @pytest.yield_fixture(scope='class')
    def apache_image(cls):
        image_properties = {
            'murano_image_info': '{"type": "linux", "title": "testDeploy"}'
        }
        image = cls.glance.images.create(name="testDeploy",
                                         disk_format='qcow2',
                                         container_format='bare',
                                         properties=image_properties)

        image.update(data=request.urlopen(settings.MURANO_IMAGE_URL))
        cls.apache_image_id = image.id

        yield

        cls.glance.images.delete(image.id)

    @pytest.yield_fixture
    def apache_package(self, apache_image):
        app_name = 'ApacheHTTPServer'
        data = {"categories": ["Web"], "tags": ["tag"]}
        tmp_dir = tempfile.mkdtemp()

        archive_path = os.path.join(tmp_dir, app_name)
        package_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                   'packages', app_name)

        with zipfile.ZipFile(archive_path, 'w') as zip_file:
            for root, dirs, files in os.walk(package_dir):
                for f in files:
                    zip_file.write(
                        os.path.join(root, f),
                        arcname=os.path.join(
                            os.path.relpath(root, package_dir), f)
                    )

        files = {app_name: open(archive_path, 'rb')}
        package = self.murano_client.packages.create(data, files)
        self.apache_id = package.id

        yield

        self.murano_client.packages.delete(package.id)

    @pytest.fixture
    def init(self):
        self.env_name = self.gen_random_resource_name(prefix='env',
                                                      reduce_by=4)
        self.app_name = self.gen_random_resource_name(prefix='app',
                                                      reduce_by=4)

    def select_net(self, net_name):
        locator = (by.By.XPATH,
                   "//select[@name='net_config']"
                   "/option[contains(text(),'{0}')]".format(net_name))
        el = ui.WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(locator))
        el.click()

    def create_env(self, env_name, net_name=None, submenu='Environments'):
        if submenu == 'Environments':
            create_env_locator = (by.By.ID, c.ConfirmCreateEnvironment)
        elif submenu == 'Applications':
            create_env_locator = (by.By.XPATH, c.InputSubmit)
        else:
            raise ValueError("Submenu can be 'Environments' or "
                             "'Applications'.")

        self.go_to_submenu(submenu)
        self.driver.find_element_by_xpath(
            "//a[contains(@href, 'murano/create_environment')]").click()
        self.fill_field(by.By.ID, 'id_name', env_name)
        if net_name:
            self.select_net(net_name=net_name)

        self.driver.find_element(*create_env_locator).click()
        self.wait_for_alert_message()

        return self.murano_client.environments.find(name=env_name).id

    def add_component(self, app_id, env_id):
        self.go_to_submenu('Environments')
        self.driver.find_element_by_id(
            "environments__row_{0}__action_show".format(env_id)).click()

        self.driver.find_element_by_xpath(
            "//a[@id='services__action_AddApplication']").click()
        self.driver.find_element_by_xpath(
            ".//a[contains(@href, 'murano/catalog/add/"
            "{app_id}/{env_id}')]".format(app_id=app_id, env_id=env_id)
        ).click()
        self.driver.find_element_by_xpath(c.ButtonSubmit).click()

        self.select_from_list('flavor', 'm1.small')
        self.select_from_list('osImage', self.apache_image_id)
        self.fill_field(by.By.NAME, '1-unitNamingPattern', value=self.env_name)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.wait_for_alert_message()

    def add_component_with_changed_net(self, env_id, net_id):
        self.go_to_submenu('Applications')
        self.driver.find_element_by_xpath(
            ".//a[contains(@href, 'murano/catalog/add/"
            "{app_id}/{env_id}')]".format(app_id=self.apache_id, env_id=env_id)
        ).click()
        self.driver.find_element_by_xpath(c.ButtonSubmit).click()

        self.select_from_list('flavor', 'm1.small')
        self.select_from_list('osImage', self.apache_image_id)
        self.fill_field(by.By.NAME, '1-unitNamingPattern', value=self.env_name)

        locator = (by.By.XPATH,
                   "//select[contains(@name, 'network')]"
                   "/option[contains(@value, '{0}')]".format(net_id))
        el = ui.WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(locator))
        el.click()

        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.wait_for_alert_message()

    def deploy_env(self, env_id):
        self.go_to_submenu('Environments')
        self.driver.find_element_by_id(
            "environments__row_{0}__action_show".format(env_id)).click()

        self.driver.find_element_by_xpath(
            "//button[@id='services__action_deploy_env']").click()

        self.wait_for_alert_message()

        common.wait(
            lambda: self.murano_client.environments.get(
                env_id).status != 'deploying',
            timeout_seconds=10 * 60,
            waiting_for='environment deployed')

    @pytest.mark.testrail_id('836680')
    @pytest.mark.usefixtures('init', 'apache_package', 'prepare_24')
    def test_particular_network(self):
        """Deploy Murano environment in particular network"""
        env_id = self.create_env(env_name=self.env_name,
                                 net_name=self.net_name)
        self.add_component(app_id=self.apache_id, env_id=env_id)
        self.deploy_env(env_id)

        self.assertEqual(self.murano_client.environments.get(env_id).status,
                         'ready')

        instance = [x for x in self.os_conn.nova.servers.findall()
                    if self.env_name in x.name][0]
        self.assertIn(self.net_name, instance.addresses.keys())

    @pytest.mark.testrail_id('836682')
    @pytest.mark.usefixtures('init', 'apache_package', 'prepare_30')
    def test_particular_network_no_free_ip(self):
        """Deploy Murano environment in network with empty ip"""
        app_name = 'Apache HTTP Server'
        env_id = self.create_env(env_name=self.env_name,
                                 net_name=self.net_name)
        self.add_component(app_id=self.apache_id, env_id=env_id)
        self.deploy_env(env_id)

        self.driver.refresh()

        status_el = self.driver.find_element_by_xpath(
            "//table[@id='services']//tr//td[contains(text(), '{0}')]"
            "/following-sibling::td[contains(@class, 'status_down')]".format(
                app_name))

        self.assertEqual(status_el.text, 'Deploy FAILURE')

    @pytest.mark.testrail_id('836681')
    @pytest.mark.usefixtures('init', 'apache_package', 'prepare_24')
    def test_change_network_for_app_from_app_page(self):
        """Change network for Murano application"""
        # create net, subnet and router
        net_name = self.gen_random_resource_name(prefix='net')
        subnet_name = self.gen_random_resource_name(prefix='subnet')
        router_name = self.gen_random_resource_name(prefix='router')

        net, subnet = self._create_network_with_subnet(
            net_name=net_name,
            subnet_name=subnet_name,
            cidr='192.168.2.0/24')

        self._create_router_between_nets(
            router_name=router_name,
            ext_net=self.os_conn.ext_network,
            subnet=subnet)

        # create new env
        env_id = self.create_env(env_name=self.env_name,
                                 net_name=self.net_name,
                                 submenu='Applications')

        # add application to env
        self.add_component_with_changed_net(env_id, net['network']['id'])

        # deploy env
        self.deploy_env(env_id)
        self.assertEqual(self.murano_client.environments.get(env_id).status,
                         'ready')

        # check that application was deployed in the second network
        instance = [x for x in self.os_conn.nova.servers.findall()
                    if self.env_name in x.name][0]
        self.assertIn(net_name, instance.addresses.keys())
        self.assertNotIn(self.net_name, instance.addresses.keys())
