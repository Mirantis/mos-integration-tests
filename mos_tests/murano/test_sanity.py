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
import multiprocessing
import os
import shutil
import SimpleHTTPServer
import SocketServer
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
from selenium.webdriver.common.keys import Keys
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


@pytest.fixture
def clean_packages(murano):
    for pkg in murano.murano.packages.list():
        if pkg.name != 'Core library':
            murano.murano.packages.delete(pkg.id)


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
@pytest.mark.usefixtures('screen', 'clean_packages')
@murano_test_patch
class TestImportPackageWithDepencies(base.PackageTestCase):

    @pytest.mark.testrail_id('836647')
    def test_import_package_by_url(self):
        """Test package importing via url."""
        self.navigate_to('Manage')
        self.go_to_submenu('Package')
        self.driver.find_element_by_id(c.UploadPackage).click()
        sel = self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        sel = ui.Select(sel)
        sel.select_by_value("by_url")

        el = self.driver.find_element_by_css_selector(
            "input[name='upload-url']")
        el.send_keys(settings.MURANO_PACKAGE_WITH_DEPS_URL)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

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
        self.go_to_submenu('Package')
        self.driver.find_element_by_id(c.UploadPackage).click()
        sel = self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        sel = ui.Select(sel)
        sel.select_by_value("by_name")

        el = self.driver.find_element_by_css_selector(
            "input[name='upload-repo_name']")
        el.send_keys(settings.MURANO_PACKAGE_WITH_DEPS_FQN)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_element_is_clickable(by.By.XPATH, c.InputSubmit)
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()

        for pkg_name in settings.MURANO_PACKAGE_DEPS_NAMES:
            self.check_element_on_page(
                by.By.XPATH, c.AppPackages.format(pkg_name))

    @pytest.mark.testrail_id('836649')
    def test_import_bundle_by_url(self):
        """Test bundle importing via url."""

        self.navigate_to('Manage')
        self.go_to_submenu('Packages')
        self.driver.find_element_by_id(c.ImportBundle).click()
        sel = self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        sel = ui.Select(sel)
        sel.select_by_value("by_url")

        el = self.driver.find_element_by_css_selector(
            "input[name='upload-url']")
        el.send_keys(settings.MURANO_BUNDLE_URL)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()

        for pkg_name in settings.MURANO_PACKAGE_BUNDLE_NAMES:
            self.check_element_on_page(
                by.By.XPATH, c.AppPackages.format(pkg_name))

    @pytest.mark.testrail_id('836650')
    def test_import_bundle_from_repo(self):
        """Test bundle importing via repository."""
        self.navigate_to('Manage')
        self.go_to_submenu('Packages')
        self.driver.find_element_by_id(c.ImportBundle).click()
        sel = self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        sel = ui.Select(sel)
        sel.select_by_value("by_name")

        el = self.driver.find_element_by_css_selector(
            "input[name='upload-name']")
        el.send_keys(settings.MURANO_BUNDLE_NAME)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()

        for pkg_name in settings.MURANO_PACKAGE_BUNDLE_NAMES:
            self.check_element_on_page(
                by.By.XPATH, c.AppPackages.format(pkg_name))


@pytest.mark.requires_('firefox', 'xvfb-run')
@pytest.mark.undestructive
@pytest.mark.usefixtures('screen')
@murano_test_patch
@pytest.mark.incremental
class TestCategoryManagement(base.PackageTestCase):

    """Test application category adds and deletes successfully
    Scenario:
        1. Navigate to 'Categories' page
        2. Click on 'Add Category' button
        3. Create new category and check it's browsed in the table
        4. Delete new category and check it's not browsed anymore
    """

    @pytest.mark.testrail_id('836684')
    def test_add_category(self):
        self.navigate_to('Manage')
        self.go_to_submenu('Categories')
        self.driver.find_element_by_id(c.AddCategory).click()
        self.fill_field(by.By.XPATH, "//input[@id='id_name']", 'TEST_CATEGORY')
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.wait_for_alert_message()

    @pytest.mark.testrail_id('836685')
    def test_delete_category(self):
        self.navigate_to('Manage')
        self.go_to_submenu('Categories')
        delete_new_category_btn = c.DeleteCategory.format('TEST_CATEGORY')
        self.driver.find_element_by_xpath(delete_new_category_btn).click()
        self.driver.find_element_by_xpath(c.ConfirmDeletion).click()
        self.wait_for_alert_message()
        self.check_element_not_on_page(by.By.XPATH, delete_new_category_btn)

    @pytest.mark.testrail_id('836692')
    def test_add_existing_category(self):
        """Add category with name of already existing category

        Scenario:
            1. Log into OpenStack Horizon dashboard as admin user
            2. Navigate to 'Categories' page
            3. Add new category
            4. Check that new category has appeared in category list
            5. Try to add category with the same name
            6. Check that appropriate user friendly error message has
                appeared.
        """
        category_name = self.murano_client.categories.list()[0].name

        self.navigate_to('Manage')
        self.go_to_submenu('Categories')
        self.driver.find_element_by_id(c.AddCategory).click()
        self.fill_field(by.By.XPATH, "//input[@id='id_name']", category_name)
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        error_message = ("Error: Requested operation conflicts "
                         "with an existing object.")
        self.check_alert_message(error_message)


@pytest.mark.requires_('firefox', 'xvfb-run')
@pytest.mark.undestructive
@pytest.mark.usefixtures('screen')
@murano_test_patch
class TestSuitePackageCategory(base.PackageTestCase):
    def _log_in(self, username, password):
        self.log_in(username, password)
        elm = self.driver.find_element_by_tag_name('html')
        elm.send_keys(Keys.HOME)
        self.navigate_to('Manage')
        self.go_to_submenu('Packages')

    def _import_package_with_category(self, package_archive, category):
        self.navigate_to('Manage')
        self.go_to_submenu('Packages')
        self.driver.find_element_by_id(c.UploadPackage).click()

        el = self.driver.find_element_by_css_selector(
            "input[name='upload-package']")
        el.send_keys(package_archive)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.driver.find_element_by_xpath(c.InputSubmit).click()
        # choose the required category
        self.driver.find_element_by_xpath(
            c.PackageCategory.format(category)).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()

        # To wait till the focus is swithced
        # from modal dialog back to the window.
        self.wait_for_sidebar_is_loaded()

    def _create_new_user_in_new_project(self):
        new_project = str(uuid.uuid4())[::4]
        project_id = self.create_project(new_project)
        user_name = 'test{}'.format(new_project)
        password = 'Test'
        self.create_user(name=user_name, password=password,
                         email='{}@example.com'.format(user_name),
                         tenant_id=project_id)
        return user_name, password

    @classmethod
    def setUpClass(cls):
        super(TestSuitePackageCategory, cls).setUpClass()
        suffix = str(uuid.uuid4())[:6]
        cls.testuser_name = 'test_{}'.format(suffix)
        cls.testuser_password = 'test'
        email = '{}@example.com'.format(cls.testuser_name)
        cls.create_user(name=cls.testuser_name,
                        password=cls.testuser_password,
                        email=email)

    @classmethod
    def tearDownClass(cls):
        cls.delete_user(cls.testuser_name)
        super(TestSuitePackageCategory, cls).tearDownClass()

    def setUp(self):
        super(TestSuitePackageCategory, self).setUp()
        self.categories_list = set(category.id for category in
                                   self.murano_client.categories.list())

        # add new category
        self.category = 'Test' + str(uuid.uuid4())[:6]
        self.murano_client.categories.add({"name": self.category})

    def tearDown(self):
        super(TestSuitePackageCategory, self).tearDown()

        # delete created category
        new_categories_list = set(category.id for category in
                                  self.murano_client.categories.list())
        categories_for_delete = new_categories_list - self.categories_list
        for category_id in categories_for_delete:
            self.murano_client.categories.delete(category_id)

    @pytest.mark.testrail_id('836683')
    def test_list_of_existing_categories(self):
        """Checks that list of categories is available
        Scenario:
            1. Navigate to 'Categories' page
            2. Check that list of categories available and basic categories
                ("Web", "Databases") are present in the list
        """
        self.navigate_to('Manage')
        self.go_to_submenu("Categories")
        categories_table_locator = (by.By.CSS_SELECTOR, "table#categories")
        self.check_element_on_page(*categories_table_locator)
        for category in ("Databases", "Web"):
            category_locator = (by.By.XPATH,
                                "//tr[@data-display='{}']".format(category))
        self.check_element_on_page(*category_locator)

    @pytest.mark.testrail_id('836691')
    def test_category_pagination(self):
        """Test categories pagination in case of many categories created """
        self.navigate_to('Manage')
        self.go_to_submenu('Categories')

        categories_list = [elem.name for elem in
                           self.murano_client.categories.list()]
        # Murano client lists the categories in order of creation
        # starting from the last created. So need to reverse it to align with
        # the table in UI form. Where categories are listed starting from the
        # first created to the last one.
        categories_list.reverse()

        categories_per_page = cfg.common.items_per_page
        pages_itself = [categories_list[i:i + categories_per_page] for i in
                        range(0, len(categories_list), categories_per_page)]
        for i, names in enumerate(pages_itself, 1):
            for name in names:
                self.check_element_on_page(by.By.XPATH, c.Status.format(name))
            if i != len(pages_itself):
                self.driver.find_element_by_xpath(c.NextBtn).click()
        # Wait till the Next button disappear
        # Otherwise 'Prev' button from the previous page might be used
        self.check_element_not_on_page(by.By.XPATH, c.NextBtn)
        pages_itself.reverse()
        for i, names in enumerate(pages_itself, 1):
            for name in names:
                self.check_element_on_page(by.By.XPATH, c.Status.format(name))
            if i != len(pages_itself):
                self.driver.find_element_by_xpath(c.PrevBtn).click()

    @pytest.mark.usefixtures('clean_packages')
    @pytest.mark.testrail_id('836687')
    def test_add_delete_package_to_category(self):
        """Test package importing with new category and deleting the package
        from the category.

        Scenario:
            1. Log into OpenStack Horizon dashboard as admin user
            2. Navigate to 'Categories' page
            3. Click on 'Add Category' button
            4. Create new category and check it's browsed in the table
            5. Navigate to 'Packages' page
            6. Click on 'Import Package' button
            7. Import package and select created 'test' category for it
            8. Navigate to "Categories" page
            9. Check that package count = 1 for created category
            10. Navigate to 'Packages' page
            11. Modify imported earlier package, by changing its category
            12. Navigate to 'Categories' page
            13. Check that package count = 0 for created category
        """
        # add new package to the created category
        self._import_package_with_category(self.archive, self.category)
        # Modify imported earlier package by changing its category
        self.go_to_submenu('Packages')
        package = self.driver.find_element_by_xpath(c.AppPackages.format(
            self.archive_name))
        pkg_id = package.get_attribute("data-object-id")

        self.select_action_for_package(pkg_id, 'modify_package')
        sel = self.driver.find_element_by_xpath(
            "//select[contains(@name, 'categories')]")
        sel = ui.Select(sel)
        sel.deselect_all()
        sel.select_by_value('Web')
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()

    @pytest.mark.usefixtures('clean_packages')
    @pytest.mark.testrail_id('836693')
    def test_delete_category_with_package(self):
        """Deletion of category with package in it

        Scenario:
            1. Log into OpenStack Horizon dashboard as admin user
            2. Navigate to 'Categories' page
            3. Add new category
            4. Navigate to 'Packages' page
            5. Import package and select created category for it
            6. Navigate to "Categories" page
            7. Check that package count = 1 for created category
            8. Check that there is no 'Delete Category' button for the category
        """
        # add new package to the created category
        self._import_package_with_category(self.archive, self.category)

        # Check that package count = 1 for created category
        self.navigate_to('Manage')
        self.go_to_submenu('Categories')
        delete_category_btn = c.DeleteCategory.format(self.category)
        self.driver.find_element_by_xpath(delete_category_btn).click()
        self.driver.find_element_by_xpath(c.ConfirmDeletion).click()
        self.wait_for_alert_message()
        self.check_element_not_on_page(by.By.XPATH, delete_category_btn)

    @pytest.mark.usefixtures('clean_packages')
    @pytest.mark.testrail_id('836688')
    def test_filter_by_new_category(self):
        """Filter by new category from Applications page

        Scenario:
            1. Log into OpenStack Horizon dashboard as admin user
            2. Navigate to 'Categories' page
            2. Click on 'Add Category' button
            3. Create new category and check it's browsed in the table
            4. Navigate to 'Packages' page
            5. Click on 'Import Package' button
            6. Import package and select created 'test' category for it
            7. Navigate to "Applications" page
            8. Select new category in "App category" dropdown list
        """
        self._import_package_with_category(self.archive, self.category)
        self.navigate_to('Catalog')
        self.go_to_submenu('Browse')

        self.driver.find_element_by_xpath(
            c.CategorySelector.format('All')).click()
        self.driver.find_element_by_partial_link_text(self.category).click()

        self.check_element_on_page(by.By.XPATH,
                                   c.App.format(self.archive_name))

    @pytest.mark.usefixtures('clean_packages')
    @pytest.mark.testrail_id('836689')
    def test_filter_by_category_from_env_components(self):
        """Filter by new category from Environment Components page

        Scenario:
            1. Log into OpenStack Horizon dashboard as admin user
            2. Navigate to 'Categories' page
            2. Click on 'Add Category' button
            3. Create new category and check it's browsed in the table
            4. Navigate to 'Packages' page
            5. Click on 'Import Package' button
            6. Import package and select created 'test' category for it
            7. Navigate to 'Environments' page
            8. Create environment
            9. Select new category in 'App category' dropdown list
            10. Check that imported package is displayed
            11. Select 'Web' category in 'App category' dropdown list
            12. Check that imported package is not displayed
        """
        self._import_package_with_category(self.archive, self.category)

        # create environment
        env_name = str(uuid.uuid4())

        self.navigate_to('Catalog')
        self.go_to_submenu('Environments')
        self.create_environment(env_name)
        self.go_to_submenu('Environments')
        self.check_element_on_page(by.By.LINK_TEXT, env_name)

        # filter by new category
        self.select_action_for_environment(env_name, 'show')
        self.driver.find_element_by_xpath(c.EnvAppsCategorySelector).click()
        self.driver.find_element_by_partial_link_text(self.category).click()

        # check that imported package is displayed
        self.check_element_on_page(
            by.By.XPATH, c.EnvAppsCategory.format(self.archive_name))

        # filter by 'Web' category
        self.driver.find_element_by_xpath(c.EnvAppsCategorySelector).click()
        self.driver.find_element_by_partial_link_text('Web').click()

        # check that imported package is not displayed
        self.check_element_not_on_page(
            by.By.XPATH, c.EnvAppsCategory.format(self.archive_name))

    @pytest.mark.usefixtures('clean_packages')
    @pytest.mark.testrail_id('836690')
    def test_add_pkg_to_category_non_admin(self):
        """Test package addition to category as non admin user

        Scenario:
            1. Log into OpenStack Horizon dashboard as non-admin user
            2. Navigate to 'Packages' page
            3. Modify any package by changing its category from
                'category 1' to 'category 2'
            4. Log out
            5. Log into OpenStack Horizon dashboard as admin user
            6. Navigate to 'Categories' page
            7. Check that 'category 2' has one more package
        """
        # create categories and package
        new_category = self.murano_client.categories.add(
            {"name": 'New' + self.category})
        self._import_package_with_category(self.archive, self.category)

        self.navigate_to('Manage')
        self.go_to_submenu('Categories')
        self.check_element_on_page(by.By.XPATH, c.DeleteCategory.format(
            self.category))
        self.check_element_on_page(by.By.XPATH, c.DeleteCategory.format(
            new_category.name))

        # relogin as test user
        self.log_out()
        self._log_in(self.testuser_name, self.testuser_password)

        # change category for package
        package = self.driver.find_element_by_xpath(c.AppPackages.format(
            self.archive_name))
        pkg_id = package.get_attribute("data-object-id")

        self.select_action_for_package(pkg_id, 'modify_package')
        sel = self.driver.find_element_by_xpath(
            "//select[contains(@name, 'categories')]")
        sel = ui.Select(sel)
        sel.deselect_all()
        sel.select_by_value(new_category.name)
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.wait_for_alert_message()
        self.log_out()

    @pytest.mark.usefixtures('clean_packages')
    @pytest.mark.testrail_id('836640')
    def test_check_toggle_non_public_package(self):
        """Test check ability to make package non public

        Scenario:
            1. Add new package
            2. Make the package non 'Public' and inactive
            3. Verify, that package is unavailable for other users
        """
        self._import_package_with_category(self.archive, self.category)

        # create new user in new project
        user_name, password = self._create_new_user_in_new_project()

        # make package inactive and non-public
        self.navigate_to('Manage')
        self.go_to_submenu('Packages')
        package = self.driver.find_element_by_xpath(c.AppPackages.format(
            self.archive_name))
        pkg_id = package.get_attribute("data-object-id")
        try:
            self.check_package_parameter_by_id(pkg_id, 'Public', 'False')
        except Exception:
            self.select_action_for_package(pkg_id, 'more')
            self.select_action_for_package(pkg_id, 'toggle_public_enabled')

        try:
            self.check_package_parameter_by_id(pkg_id, 'Active', 'False')
        except Exception:
            self.select_action_for_package(pkg_id, 'more')
            self.select_action_for_package(pkg_id, 'toggle_enabled')
        self.check_element_on_page(by.By.XPATH, c.AppPackages.format(
            self.archive_name))

        # re-login as test user
        self.log_out()
        self._log_in(user_name, password)

        # check that package is unavailable
        self.check_element_not_on_page(by.By.XPATH, c.AppPackages.format(
            self.archive_name))

        # re-login as admin user
        self.log_out()
        self.log_in()
        self.navigate_to('Manage')
        self.go_to_submenu('Packages')
        self.select_action_for_package(pkg_id, 'more')
        self.select_action_for_package(pkg_id, 'toggle_enabled')
        self.delete_user(user_name)

    @pytest.mark.usefixtures('clean_packages')
    @pytest.mark.testrail_id('836675')
    def test_package_share(self):
        """Test that admin is able to share Murano Apps

        Scenario:
            1. Add new package
            2. Make the package 'Public'
            3. Verify, that package is available for other users
        """
        self._import_package_with_category(self.archive, self.category)

        # create new user in new project
        user_name, password = self._create_new_user_in_new_project()
        self.navigate_to('Manage')
        self.go_to_submenu('Packages')
        package = self.driver.find_element_by_xpath(c.AppPackages.format(
            self.archive_name))
        pkg_id = package.get_attribute("data-object-id")

        # make package public
        try:
            self.check_package_parameter_by_id(pkg_id, 'Public', 'True')
        except Exception:
            self.select_action_for_package(pkg_id, 'more')
            self.select_action_for_package(pkg_id, 'toggle_public_enabled')

        self.check_element_on_page(by.By.XPATH, c.AppPackages.format(
            self.archive_name))

        # re-login as test user
        self.log_out()
        self._log_in(user_name, password)

        # check that package is available
        self.check_element_on_page(by.By.XPATH, c.AppPackages.format(
            self.archive_name))
        self.delete_user(user_name)

    @pytest.mark.usefixtures('clean_packages')
    @pytest.mark.testrail_id('836679')
    def test_sharing_app_without_permission(self):
        """Tests sharing Murano App without permission

        Scenario:
            1) Create 2 new users
            2) Add new non-public package by first user
            3) Login to Horizon as second user
            4) Verify, that package is unavailable for the user
            5) Login to Horizon as first user
            6) Change package to public
            7) Login to Horizon as second user
            8) Verify, that package is available for the user
            9) Try to change the package
            10) Check error message
        """
        # create new users in new projects
        user_name_1, password_1 = self._create_new_user_in_new_project()
        user_name_2, password_2 = self._create_new_user_in_new_project()

        # login as first new user
        self.log_out()
        self._log_in(user_name_1, password_1)

        # Import package
        self.driver.find_element_by_id(c.UploadPackage).click()
        el = self.driver.find_element_by_css_selector(
            "input[name='upload-package']")
        el.send_keys(self.archive)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        # Public = OFF; Active = ON.
        public_checkbox = self.driver.find_element_by_id('id_modify-is_public')
        active_checkbox = self.driver.find_element_by_id('id_modify-enabled')
        if public_checkbox.is_selected():
            public_checkbox.click()
        if not active_checkbox.is_selected():
            active_checkbox.click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.wait_for_alert_message()
        self.check_element_on_page(
            by.By.XPATH, c.AppPackages.format(self.archive_name))

        # login as second new user
        self.log_out()
        self._log_in(user_name_2, password_2)

        # check that package is unavailable
        self.check_element_not_on_page(by.By.XPATH, c.AppPackages.format(
            self.archive_name))

        # login as first new user
        self.log_out()
        self._log_in(user_name_1, password_1)

        # Modify Package to set Public = ON
        package = self.driver.find_element_by_xpath(
            c.AppPackages.format(self.archive_name))
        pkg_id = package.get_attribute("data-object-id")
        self.select_action_for_package(pkg_id, 'modify_package')
        label = self.driver.find_element_by_css_selector(
            "label[for=id_is_public]")
        label.click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.wait_for_alert_message()
        self.check_element_on_page(by.By.XPATH, c.AppPackages.format(
            self.archive_name))

        # login as second new user
        self.log_out()
        self._log_in(user_name_2, password_2)

        # check that package is available
        self.check_element_on_page(by.By.XPATH, c.AppPackages.format(
            self.archive_name))
        # Modify Package to set Public = OFF
        package = self.driver.find_element_by_xpath(
            c.AppPackages.format(self.archive_name))
        pkg_id = package.get_attribute("data-object-id")
        self.select_action_for_package(pkg_id, 'modify_package')
        label = self.driver.find_element_by_css_selector(
            "label[for=id_is_public]")
        label.click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        # Check Error
        err_msg = self.wait_for_error_message()
        self.assertIn('You are not allowed to perform this operation', err_msg)

        self.delete_user(user_name_1)
        self.delete_user(user_name_2)


@pytest.mark.requires_('firefox', 'xvfb-run')
@pytest.mark.undestructive
@pytest.mark.usefixtures('screen', 'clean_packages')
@murano_test_patch
class TestPackageSizeLimit(base.PackageTestCase):
    """Test package size limit."""

    def setUp(self):
        super(TestPackageSizeLimit, self).setUp()
        self.zips = prepare_zips()

    def tearDown(self):
        shutil.rmtree((os.path.split(self.zips[0])[0]), ignore_errors=True)
        super(TestPackageSizeLimit, self).tearDown()

    @pytest.mark.skip(reason="Disabled for Murano+Glare configuration")
    @pytest.mark.testrail_id('836646')
    @pytest.mark.usefixtures('package_size_limit')
    def test_package_size_limit(self):
        self.navigate_to('Manage')
        self.go_to_submenu('Package')

        # Upload package with allowed size
        self.driver.find_element_by_id(c.UploadPackage).click()
        el = self.driver.find_element_by_css_selector(
            "input[name='upload-package']")
        el.send_keys(self.zips[0])
        self.driver.find_element_by_xpath(c.InputSubmit).click()
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
        net_names = [x['name']
                     for x in self.os_conn.neutron.list_networks()['networks']]

        self._prepare(cidr='192.168.1.0/24')

        yield

        self.os_conn.cleanup_network(networks_to_skip=net_names)

    @pytest.yield_fixture
    def prepare_30(self, os_conn_for_unittests):
        net_names = [x['name']
                     for x in self.os_conn.neutron.list_networks()['networks']]

        self._prepare(cidr='192.168.1.0/30')

        yield

        self.os_conn.cleanup_network(networks_to_skip=net_names)

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
    def apache_package(self, apache_image, murano):
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
        package = murano.murano.packages.create(data, files)
        self.apache_id = package.id

        yield

        murano.murano.packages.delete(package.id)

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
        self.navigate_to('Catalog')
        self.go_to_submenu('Browse')
        self.driver.find_element_by_xpath(
            ".//a[contains(@href, '/murano/catalog/add/"
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

        self.assertEqual(self.murano_client.environments.get(
            env_id).status, 'ready')
        open_stack_id = self.murano_client.environments.get(
            env_id).services[0]['instance']['openstackId']
        instance = self.os_conn.nova.servers.get(open_stack_id)
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
    @pytest.mark.usefixtures('init', 'clean_packages', 'apache_package',
                             'prepare_24')
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
                                 net_name=self.net_name)

        # add application to env
        self.add_component_with_changed_net(env_id, net['network']['id'])

        # deploy env
        self.deploy_env(env_id)
        self.assertEqual(self.murano_client.environments.get(
            env_id).status, 'ready')

        # check that application was deployed in the second network
        open_stack_id = self.murano_client.environments.get(
            env_id).services[0]['instance']['openstackId']
        instance = self.os_conn.nova.servers.get(open_stack_id)
        self.assertIn(net_name, instance.addresses.keys())
        self.assertNotIn(self.net_name, instance.addresses.keys())


@pytest.mark.requires_('firefox', 'xvfb-run')
@pytest.mark.undestructive
@pytest.mark.usefixtures('screen')
@murano_test_patch
class TestPackageRepository(base.PackageTestCase):
    _apps_to_delete = set()

    def _compose_app(self, name, require=None):
        package_dir = os.path.join(self.serve_dir, 'apps/', name)
        shutil.copytree(c.PackageDir, package_dir)

        app_name = utils.compose_package(
            name,
            os.path.join(package_dir, 'manifest.yaml'),
            package_dir,
            require=require,
            archive_dir=os.path.join(self.serve_dir, 'apps/'),
        )
        self._apps_to_delete.add(name)
        return app_name

    def _compose_bundle(self, name, app_names):
        bundles_dir = os.path.join(self.serve_dir, 'bundles/')
        shutil.os.mkdir(bundles_dir)
        utils.compose_bundle(os.path.join(bundles_dir, name + '.bundle'),
                             app_names)

    def _make_pkg_zip_regular_file(self, name):
        file_name = os.path.join(self.serve_dir, 'apps', name + '.zip')
        with open(file_name, 'w') as f:
            f.write("I'm not an application. I'm not a zip file at all")
        return file_name

    def _make_non_murano_zip_in_pkg(self, name):
        file_name = os.path.join(self.serve_dir, 'apps', 'manifest.yaml')
        with open(file_name, 'w') as f:
            f.write("Description: I'm not a murano package at all")
        zip_name = os.path.join(self.serve_dir, 'apps', name + '.zip')
        with zipfile.ZipFile(zip_name, 'w') as archive:
            archive.write(file_name)
        return zip_name

    def _make_big_zip_pkg(self, name, size):
        file_name = os.path.join(self.serve_dir, 'apps', 'images.lst')
        self._compose_app(name)

        # create file with size 10 mb
        with open(file_name, 'wb') as f:
            f.seek(size - 1)
            f.write('\0')

        # add created file to archive
        zip_name = os.path.join(self.serve_dir, 'apps', name + '.zip')
        with zipfile.ZipFile(zip_name, 'a') as archive:
            archive.write(file_name)
        return zip_name

    def setUp(self):
        super(TestPackageRepository, self).setUp()
        self.serve_dir = tempfile.mkdtemp(suffix="repo")

        def serve_function():
            class Handler(SimpleHTTPServer.SimpleHTTPRequestHandler):
                pass
            os.chdir(self.serve_dir)
            httpd = SocketServer.TCPServer(
                ("0.0.0.0", 8099),
                Handler, bind_and_activate=False)
            httpd.allow_reuse_address = True
            httpd.server_bind()
            httpd.server_activate()
            httpd.serve_forever()

        self.p = multiprocessing.Process(target=serve_function)
        self.p.start()

    def tearDown(self):
        super(TestPackageRepository, self).tearDown()
        self.p.terminate()
        for package in self.murano_client.packages.list(include_disabled=True):
            if package.name in self._apps_to_delete:
                self.murano_client.packages.delete(package.id)
                self._apps_to_delete.remove(package.name)
        shutil.rmtree(self.serve_dir)

    @pytest.mark.testrail_id('836655')
    def test_import_unexciting_package_from_repository(self):
        """Negative test when unexciting package is imported from repository"""
        pkg_name = self.gen_random_resource_name('pkg')

        self.navigate_to('Manage')
        self.go_to_submenu('Packages')

        self.driver.find_element_by_id(c.UploadPackage).click()
        sel = self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        sel = ui.Select(sel)
        sel.select_by_value("by_name")
        el = self.driver.find_element_by_css_selector(
            "input[name='upload-repo_name']")
        el.send_keys("io.murano.apps.{0}.zip".format(pkg_name))
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        error_message = ("Error: Package creation failed.Reason: "
                         "Can't find Package name from repository.")
        self.check_alert_message(error_message)

        self.check_element_not_on_page(
            by.By.XPATH, c.AppPackages.format(pkg_name))

    @pytest.mark.testrail_id('836656')
    def test_import_package_by_invalid_url(self):
        """Negative test when package is imported by invalid url."""
        pkg_name = self.gen_random_resource_name('pkg')

        self.navigate_to('Manage')
        self.go_to_submenu('Packages')

        self.driver.find_element_by_id(c.UploadPackage).click()
        sel = self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        sel = ui.Select(sel)
        sel.select_by_value("by_url")
        el = self.driver.find_element_by_css_selector(
            "input[name='upload-url']")
        el.send_keys("http://storage.apps.openstack.org/apps/"
                     "io.murano.apps.{0}.zip".format(pkg_name))
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        error_message = ("Error: Package creation failed.Reason: "
                         "Can't find Package name from repository.")
        self.check_alert_message(error_message)

        self.check_element_not_on_page(
            by.By.XPATH, c.AppPackages.format(pkg_name))

    @pytest.mark.testrail_id('836652')
    def test_import_non_zip_file(self):
        """"Negative test import regualr file instead of zip package."""
        # Create dummy package with zip file replaced by text one
        pkg_name = self.gen_random_resource_name('pkg')
        self._compose_app(pkg_name)
        pkg_path = self._make_pkg_zip_regular_file(pkg_name)

        self.navigate_to('Manage')
        self.go_to_submenu('Packages')
        self.driver.find_element_by_id(c.UploadPackage).click()
        self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        el = self.driver.find_element_by_css_selector(
            "input[name='upload-package']")
        el.send_keys(pkg_path)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        err_msg = self.wait_for_error_message()
        self.assertIn('File is not a zip file', err_msg)

        self.check_element_not_on_page(
            by.By.XPATH, c.AppPackages.format(pkg_name))

    @pytest.mark.testrail_id('836653')
    def test_import_invalid_zip_file(self):
        """"Negative test import zip file which is not a murano package."""
        # At first create dummy package with zip file replaced by text one
        pkg_name = self.gen_random_resource_name('pkg')
        self._compose_app(pkg_name)
        pkg_path = self._make_non_murano_zip_in_pkg(pkg_name)

        self.navigate_to('Manage')
        self.go_to_submenu('Packages')
        self.driver.find_element_by_id(c.UploadPackage).click()
        self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        el = self.driver.find_element_by_css_selector(
            "input[name='upload-package']")
        el.send_keys(pkg_path)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        err_msg = self.wait_for_error_message()
        self.assertIn("There is no item named 'manifest.yaml' in the archive",
                      err_msg)

        self.check_element_not_on_page(
            by.By.XPATH, c.AppPackages.format(pkg_name))

    @pytest.mark.testrail_id('836654')
    def test_import_big_zip_file(self):
        """Import very big zip archive.

        Scenario:
            1. Log in Horizon with admin credentials
            2. Navigate to 'Packages' page
            3. Click 'Import Package' and select 'File' as a package source
            4. Choose very big zip file
            5. Click on 'Next' button
            6. Check that error message that user can't upload file more than
                5 MB is displayed
        """
        pkg_name = self.gen_random_resource_name('pkg')
        pkg_path = self._make_big_zip_pkg(name=pkg_name, size=10 * 1024 * 1024)

        # import package and choose big zip file for it
        self.navigate_to('Manage')
        self.go_to_submenu('Packages')
        self.driver.find_element_by_id(c.UploadPackage).click()
        self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        el = self.driver.find_element_by_css_selector(
            "input[name='upload-package']")
        el.send_keys(pkg_path)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        # check that error message appeared
        error_message = 'It is forbidden to upload files larger than 5 MB.'
        self.driver.find_element_by_xpath(
            c.ErrorMessage.format(error_message))
