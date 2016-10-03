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
import random
import re

import ldap
import ldap.modlist as modlist
import pytest
from six.moves import configparser
from six.moves.html_parser import HTMLParser
from six.moves.urllib.request import urlopen

from fuelclient.objects import Plugins as FuelPlugins
from keystoneauth1.exceptions.base import ClientException as KeyStoneException
from keystoneauth1.exceptions.http import GatewayTimeout
from keystoneauth1.exceptions.http import InternalServerError
from keystoneauth1.identity import v3
from keystoneauth1 import session
from keystoneclient.v3 import Client as KeystoneClientV3
from muranoclient.glance import client as glare_client
from muranoclient.v1.client import Client as MuranoClient
from neutronclient.common.exceptions import NeutronClientException

from mos_tests import conftest
from mos_tests.environment.os_actions import OpenStackActions
from mos_tests.functions import common


logger = logging.getLogger(__name__)

AUTH_DATA = {
    'openldap1': ('user01', '1111'),
    'openldap2': ('user1', '1111'),
    'AD2': ('user01', 'qwerty123!')
}

MAIN_PLUGIN_URL = ("https://www.mirantis.com/validated-solution-integrations/"
                   "fuel-plugins/")
STACKLIGHT_PLUGIN_NAMES = ['influxdb_grafana',
                           'lma_collector',
                           'lma_infrastructure_alerting',
                           'elasticsearch_kibana']


@pytest.yield_fixture
def admin_remote(fuel):
    with fuel.ssh_admin() as remote:
        yield remote


@pytest.yield_fixture
def domain_projects(os_conn, env):
    # Get current projects for all domains
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domains = [d for d in keystone_v3.domains.list()]
    old_projects = {}
    for domain in domains:
        old_projects[domain.name] = []
        for project in keystone_v3.projects.list(domain=domain):
            old_projects[domain.name].append(project.name)
    yield
    # Delete projects created during test execution
    for domain in domains:
        for project in keystone_v3.projects.list(domain=domain):
            if project.name not in old_projects[domain.name]:
                clear_project(env, domain, project)
                keystone_v3.projects.delete(project=project)


@pytest.yield_fixture
def slapd_running(env):
    """Check/start the slapd service on all controllers"""
    provide_slapd_state(env, "running")
    yield
    provide_slapd_state(env, "running")


@pytest.yield_fixture
def controllers(env):
    """Move certificate files on all controllers and restart slapd/apache2"""
    proxy = get_plugin_config_value(env, 'ldap', 'ldap_proxy')
    service_name = 'slapd' if proxy else 'apache2'

    controllers = env.get_nodes_by_role('controller')
    for controller in controllers:
        if move_cert(controller, to_original=True):
            restart_service(controller, service_name)
    yield controllers
    for controller in controllers:
        if move_cert(controller, to_original=True):
            restart_service(controller, service_name)


@pytest.yield_fixture
def keystone_conf(env):
    """Copy/restore keystone.conf before and after test execution"""
    # NOTE: similar to short_lifetime_keystone in glance/conftest.py
    controllers = env.get_nodes_by_role('controller')
    cmd = 'cp /etc/keystone/keystone.conf /etc/keystone/keystone.conf.orig'
    for controller in controllers:
        with controller.ssh() as remote:
            remote.check_call(cmd)
    yield
    cmd = 'cp /etc/keystone/keystone.conf.orig /etc/keystone/keystone.conf'
    for controller in controllers:
        with controller.ssh() as remote:
            remote.check_call(cmd)
            remote.check_call('service apache2 reload')
            remote.check_call('rm /etc/keystone/keystone.conf.orig')
    wait_keystone_alive(env)


@pytest.yield_fixture
def ldap_server(env):
    """Connect to LDAP server"""

    # Get LDAP data
    data = env.get_settings_data()['editable']
    ldap_data = data['ldap']['metadata']['versions'][0]
    ldap_domain_name = ldap_data['domain']['value']
    ldap_url = ldap_data['url']['value']
    ldap_cacert = ldap_data['ca_chain']['value']
    ldap_user = ldap_data['user']['value']
    ldap_password = ldap_data['password']['value']
    ldap_user_tree_dn = ldap_data['user_tree_dn']['value']
    ldap_name_attr = ldap_data['user_name_attribute']['value']

    if ldap_cacert:
        cacert_file = "/tmp/cert.pem"
        with open(cacert_file, 'w') as f:
            f.write(ldap_cacert)
        ldap.set_option(ldap.OPT_X_TLS_CACERTFILE, cacert_file)

    logger.info("Connecting to LDAP server {} ({})".
                format(ldap_domain_name, ldap_url))
    ld = ldap.initialize(ldap_url)
    ld.start_tls_s()
    ld.simple_bind_s(ldap_user, ldap_password)

    ldap_server = (ld, ldap_domain_name, ldap_user_tree_dn, ldap_name_attr)

    yield ldap_server

    ld.unbind_s()


@pytest.yield_fixture
def new_ldap_user(ldap_server):
    """Create a user on LDAP server"""

    ld, ldap_domain_name, ldap_user_tree_dn, ldap_name_attr = ldap_server

    logger.debug("Getting list of users for domain {0} from LDAP server".
                 format(ldap_domain_name))
    search_filter = "{0}=*".format(ldap_name_attr)  # sn=*
    search_attrs = ['{0}'.format(ldap_name_attr)]
    ldap_results = ld.search_s(ldap_user_tree_dn, ldap.SCOPE_SUBTREE,
                               search_filter, search_attrs)
    dn, res = ldap_results[0]
    # ex: 'sn=user01,ou=Users,dc=openldap1,dc=tld', {'sn': ['user01']}
    old_user_name = res[ldap_name_attr][0]
    new_user_name = "test-" + old_user_name
    new_user_dn = dn.replace(old_user_name, new_user_name)
    # ex: 'sn=test-user01,ou=Users,dc=openldap1,dc=tld'

    logger.debug("Getting data for user {0} from LDAP server".
                 format(old_user_name))
    search_filter = "{0}={1}".format(ldap_name_attr, old_user_name)
    ldap_result = ld.search_s(ldap_user_tree_dn, ldap.SCOPE_SUBTREE,
                              search_filter)[0][1]
    # ex:
    # {'cn': ['user01'],
    #  'description': ['description for user01'],
    #  'mail': ['user01@gmail.com'],
    #  'objectClass': ['inetOrgPerson'],
    #  'sn': ['user01'],
    #  'title': ['title01'],
    #  'userPassword': ['1111']}

    logger.info("Adding new user {0} on LDAP server".format(new_user_name))
    # data are copied from old user except some fields
    attrs = {}
    for key in ldap_result:
        if key in ["cn", "sn"]:
            attrs[key] = [new_user_name]
        else:
            attrs[key] = ldap_result[key]
    ldif = modlist.addModlist(attrs)
    ld.add_s(new_user_dn, ldif)

    new_ldap_user = (new_user_name, new_user_dn)

    yield new_ldap_user

    # Delete test user(s) if still exist
    search_filter = "{0}=test*".format(ldap_name_attr)  # sn=test**
    ldap_results = ld.search_s(ldap_user_tree_dn, ldap.SCOPE_SUBTREE,
                               search_filter)
    for dn, res in ldap_results:
        ld.delete_s(dn)


@pytest.fixture(scope='module')
def get_plugin_url():
    """Finds URL of plugins in Mirantis repository"""
    logger.info("Parsing {0}".format(MAIN_PLUGIN_URL))
    parser = PluginHtmlParser()
    parser.feed(urlopen(MAIN_PLUGIN_URL).read())

    def _get_url(plugin_name):
        return parser.get_url(plugin_name)

    return _get_url


@pytest.fixture
def no_murano_plugin(env, admin_remote):
    """Check/uninstall the Murano plugin"""
    if "detach-murano" in env.get_plugins():
        uninstall_plugin(env, admin_remote, "detach-murano")


@pytest.fixture
def no_stacklight_plugins(env, admin_remote):
    """Check/uninstall the StackLight plugins"""
    for plugin_name in STACKLIGHT_PLUGIN_NAMES:
        if plugin_name in env.get_plugins():
            uninstall_plugin(env, admin_remote, plugin_name)


def clear_project(env, domain, project):
    """Delete instances, keypairs, security groups, networks in a project"""
    controller_ip = env.get_primary_controller_ip()
    user_name, user_pass = AUTH_DATA[domain.name]
    try:
        os_conn_v3 = OpenStackActions(controller_ip,
                                      keystone_version=3,
                                      domain=domain.name,
                                      user=user_name,
                                      password=user_pass,
                                      tenant=project.name,
                                      env=env)
        vms = os_conn_v3.get_servers()
    except KeyStoneException:
        # ex: user is not a member of this project
        logger.info("cannot connect to project {0} under {1}".
                    format(project.name, user_name))
        return
    if not vms:
        return
    for vm in vms:
        os_conn_v3.nova.servers.delete(vm)
        common.wait(lambda: os_conn_v3.is_server_deleted(vm.id),
                    timeout_seconds=60,
                    waiting_for='instances to be deleted')
    os_conn_v3.delete_keypairs()
    os_conn_v3.delete_security_groups()
    for network in [net for net in
                    os_conn_v3.neutron.list_networks()['networks']]:
        if network['name'].startswith('admin'):
            continue
        try:
            os_conn_v3.delete_net_subnet_smart(network['id'])
        except NeutronClientException:
            logger.info('the net {} is not deletable'.
                        format(network['name']))
        # see similar examples in os_actions.py


def restart_service(controller, service_name):
    """Restart slapd/apache2 service on a controller"""
    with controller.ssh() as remote:
        remote.check_call('service {0} restart'.format(service_name))
        status = "start/running" if service_name == "slapd" else "is running"
        common.wait(
            lambda: status in remote.check_call(
                "service {0} status".format(service_name)).stdout_string,
            timeout_seconds=60,
            waiting_for="status is '{0}'".format(status))


def move_cert(controller, to_original=True):
    """Move certificate file from /etc/ssl/certs to /tmp or restore back"""
    cert = 'ca-certificates.crt'
    tmp_dir = '/tmp'
    orig_dir = '/etc/ssl/certs'
    if to_original:
        dir_1, dir_2 = tmp_dir, orig_dir
    else:
        dir_1, dir_2 = orig_dir, tmp_dir

    cmd = "mv {0}/{1} {2}".format(dir_1, cert, dir_2)
    check_cmd = 'ls {}/ | grep {}'

    is_moved = False
    with controller.ssh() as remote:
        if cert in remote.execute(check_cmd.format(dir_1, cert)).stdout_string:
            remote.check_call(cmd)
            assert cert not in remote.execute(check_cmd.format(
                dir_1, cert)).stdout_string
            assert cert in remote.execute(check_cmd.format(
                dir_2, cert)).stdout_string
            is_moved = True
    return is_moved


def change_list_limit(env, limit=100):
    """Change list_limit in keystone.conf"""

    config_keystone = '/etc/keystone/keystone.conf'

    def change_limit(node, limit):
        with node.ssh() as remote:
            with remote.open(config_keystone) as f:
                parser = configparser.RawConfigParser()
                parser.readfp(f)
            parser.set('DEFAULT', 'list_limit', limit)
            with remote.open(config_keystone, 'w') as f:
                parser.write(f)
            remote.check_call('service apache2 reload')

    controllers = env.get_nodes_by_role('controller')
    for controller in controllers:
        change_limit(controller, limit)
    wait_keystone_alive(env)


def wait_keystone_alive(env):
    """Wait until keystone is up"""
    session = env.os_conn.session
    common.wait(lambda: session.get(session.auth.auth_url).ok,
                timeout_seconds=60 * 3,
                waiting_for='keystone available',
                expected_exceptions=Exception)


def provide_slapd_state(env, status):
    """Check/start/stop the slapd service on all controllers"""

    status_commands = {
        "stopped": ['start/running', 'service slapd stop', 'stop/waiting'],
        "running": ['stop/waiting', 'service slapd start', 'start/running']}

    check_command = 'service slapd status'

    for node in env.get_nodes_by_role('controller'):
        with node.ssh() as remote:
            out = remote.check_call(check_command).stdout_string
            # ex: slapd start/running, process 16161
            if status_commands[status][0] in out:
                remote.check_call(status_commands[status][1])

            common.wait(
                lambda: status_commands[status][2] in remote.check_call(
                    check_command).stdout_string,
                timeout_seconds=60,
                waiting_for='status is {}'.format(status_commands[status][2]))


def map_interfaces(devops_env, fuel_node):
    """Return pairs of fuel_node interfaces and devops interfaces"""
    pairs = []
    devops_node = devops_env.get_node_by_fuel_node(fuel_node)
    for fuel_interface in fuel_node.get_attribute('interfaces'):
        for devops_interface in devops_node.interfaces:
            if fuel_interface['mac'] == devops_interface.mac_address:
                pairs.append((fuel_interface, devops_interface))
                continue
    return pairs


def map_devops_to_fuel_net(env, devops_env, fuel_node):
    """Make devops network.id -> fuel networks mapping"""
    interfaces_map = {}
    for fuel_if, devop_if in map_interfaces(devops_env,
                                            env.primary_controller):
        interfaces_map[devop_if.network_id] = fuel_if['assigned_networks']

    # Assign fuel networks to corresponding interfaces
    interfaces = []
    for fuel_if, devop_if in map_interfaces(devops_env, fuel_node):
        fuel_if['assigned_networks'] = interfaces_map[devop_if.network_id]
        interfaces.append(fuel_if)
    return interfaces


# TODO(ssokolov) remove later
def check_504_error(keystone_v3):
    # This function is used for investigation of error 504 (Gateway Timeout)
    proxy_domain = [d for d in keystone_v3.domains.list()
                    if d.name == 'openldap1'][0]

    def no_504_error():
        try:
            keystone_v3.users.list(domain=proxy_domain)
        except GatewayTimeout:
            return False
        except InternalServerError:
            # ignore
            pass
        return True

    for i in range(5):
        if no_504_error():
            break
        # gateway timeout = 1 min, no need to sleep
    if i > 0:
        logger.debug("check_504_error, errors: {0}".format(i))


def basic_check(keystone_v3, domain_name=None):
    """Check list of users and groups for LDAP domains"""

    # TODO(ssokolov) remove later
    check_504_error(keystone_v3)

    if domain_name:
        ldap_domains = [keystone_v3.domains.find(name=domain_name)]
    else:
        ldap_domains = [domain for domain in keystone_v3.domains.list() if
                        re.search("^(openldap|AD)", domain.name)]
        assert len(ldap_domains) > 0, "no LDAP domains are found"

    for ldap_domain in ldap_domains:
        logger.info("Checking users of domain {0}".format(ldap_domain.name))
        users = keystone_v3.users.list(domain=ldap_domain)
        assert len(users) > 0, ("no users in domain {0}".
                                format(ldap_domain.name))
        logger.info("Checking groups of domain {0}".format(ldap_domain.name))
        groups = keystone_v3.groups.list(domain=ldap_domain)
        assert len(groups) > 0, ("no groups in domain {0}".
                                 format(ldap_domain.name))


def install_plugin(admin_remote, url):
    """Plugin installation"""
    logger.info("Downloading the RPM file")
    rpm_file = re.sub("^.*/", "", url)
    admin_remote.check_call("wget -O {0} {1}".format(rpm_file, url))

    logger.info("Installing the plugin {0}".format(rpm_file))
    output = admin_remote.check_call("fuel plugins --install {0}".
                                     format(rpm_file)).stdout_string
    # NOTE: cannot use FuelPlugins.install because it executes the rpm command
    # on local machine instead of master node
    exp_msg = "Plugin {0} was successfully installed".format(rpm_file)
    assert exp_msg in output


def uninstall_plugin(env, admin_remote, plugin_name):
    """Plugin uninstallation"""
    logger.info("Uninstalling the plugin {0}".format(plugin_name))
    configure_plugin(env, plugin_name, enabled=False)
    plugin_version = get_plugin_version(env, plugin_name)
    admin_remote.execute("fuel plugins --remove {0}=={1}".
                         format(plugin_name, plugin_version))
    # NOTE: cannot use FuelPlugins.remove because it executes the rpm command
    # on local machine instead of master node


def configure_plugin(env, plugin_name, enabled):
    """Disable/enable a plugin and configure some values (if necesary)"""
    if enabled:
        logger.info("Enable plugin {0}".format(plugin_name))
    else:
        logger.info("Disable plugin {0}".format(plugin_name))
    data = env.get_settings_data()
    data['editable'][plugin_name]['metadata']['enabled'] = enabled
    if enabled and plugin_name == 'lma_infrastructure_alerting':
        # cannot use set_plugin_config_value because all data must be set
        # by one command env.set_settings_data(data)
        metadata = data['editable'][plugin_name]['metadata']
        metadata['versions'][0]['send_from']['value'] = 'nagios@localhost'
        metadata['versions'][0]['send_to']['value'] = 'root@localhost'
        data['editable'][plugin_name]['metadata'] = metadata
    env.set_settings_data(data)


def get_plugin_config_value(env, plugin_name, attr):
    """Get value of plugin config data"""
    data = env.get_settings_data()
    plugin_data = data['editable'][plugin_name]['metadata']['versions'][0]
    return plugin_data[attr]['value']


def set_plugin_config_value(env, plugin_name, attr, value):
    """Set value of plugin config data"""
    data = env.get_settings_data()
    plugin_data = data['editable'][plugin_name]['metadata']['versions'][0]
    plugin_data[attr]['value'] = value
    data['editable'][plugin_name]['metadata']['versions'][0] = plugin_data
    logger.debug("Plugin {0}: {1} = {2}".format(plugin_name, attr, value))
    env.set_settings_data(data)


def get_plugin_version(env, plugin_name):
    """Get plugin version"""
    data = env.get_settings_data()
    plugin_data = data['editable'][plugin_name]['metadata']['versions'][0]
    return plugin_data['metadata']['plugin_version']


class PluginHtmlParser(HTMLParser):
    """Parser of Mirantis plugin main page to find plugin URLs"""

    is_parsed = False
    rpm_urls = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            # ex: attrs = [('class', 'plugin-file-download'),
            # ('id', 'fuel-plugin-nsxv-3.0-3.0.0-1.noarch.rpm'),
            # ('href', 'http://plugins.mirantis.com/repository/f/u/
            # fuel-plugin-nsxv/fuel-plugin-nsxv-3.0-3.0.0-1.noarch.rpm')]
            attrs_dict = dict(attrs)
            if attrs_dict.get('href', '').endswith('rpm'):
                PluginHtmlParser.rpm_urls.append(attrs_dict['href'])

    def get_url(self, plugin_name):
        return next(url for url in PluginHtmlParser.rpm_urls
                    if ("/" + plugin_name) in url)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1295439', with_proxy=True)
@pytest.mark.testrail_id('1681468', with_proxy=False)
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
@pytest.mark.parametrize('with_proxy', [True, False])
def test_ldap_basic_functions(os_conn, env, with_proxy):
    """Test to cover basic functionality for multi domain

    Steps to reproduce:
    1. Check that LDAP plugin is installed
    2. Login as admin/admin, domain: default
    3. Find LDAP domains
    4. For each domain, checks lists of users and groups
    """

    if with_proxy != conftest.is_ldap_proxy(env):
        enabled_or_disabled = 'enabled' if with_proxy else 'disabled'
        pytest.skip("LDAP proxy is not {}".format(enabled_or_disabled))

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1665419', domain_name='AD2')
@pytest.mark.testrail_id('1680675', domain_name='openldap2')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
@pytest.mark.parametrize('domain_name', ['AD2', 'openldap2'])
def test_ldap_get_group_members(os_conn, domain_name):
    """Test to check user list for a group

    Steps to reproduce:
    1. Check that LDAP plugin is installed
    2. Login as admin/admin, domain: default
    3. Checks list of users for domain AD2 and group Administrators
       (similar for openldap2/group01)
    """
    if domain_name == 'AD2':
        group_name = 'Administrators'
    else:
        group_name = 'group01'
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domain = keystone_v3.domains.find(name=domain_name)
    try:
        group = keystone_v3.groups.find(domain=domain, name=group_name)
    except KeyStoneException:
        pytest.skip("Group {0} is not found in domain {1}".
                    format(group_name, domain_name))
    users = keystone_v3.users.list(domain=domain)
    assert len(users) > 0, ("no users in domain {0}".format(domain_name))
    users = keystone_v3.users.list(domain=domain, group=group)
    assert len(users) > 0, ("no users in domain {0} and group {1}".
                            format(domain_name, group_name))


@pytest.mark.undestructive
@pytest.mark.testrail_id('1616778', with_proxy=True)
@pytest.mark.testrail_id('1617216', with_proxy=False)
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
@pytest.mark.parametrize('with_proxy', [True, False])
def test_create_project_by_user(os_conn, env, domain_projects, with_proxy):
    """Create a project by LDAP user

    Steps to reproduce:
    1. Check that LDAP plugin is installed
    2. Login as admin/admin, domain: default
    3. Set role 'admin' to 'user01' in domain openldap1
    4. Relogin as user01/1111, domain: openldap1
    5. Create a new project
    """

    if with_proxy != conftest.is_ldap_proxy(env):
        enabled_or_disabled = 'enabled' if with_proxy else 'disabled'
        pytest.skip("LDAP proxy is not {}".format(enabled_or_disabled))

    domain_name = "openldap1"
    user_name, user_pass = AUTH_DATA[domain_name]

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domain = keystone_v3.domains.find(name=domain_name)
    user = keystone_v3.users.find(domain=domain, name=user_name)

    role_admin = keystone_v3.roles.find(name="admin")
    logger.info("Setting role 'admin' to user {0}".format(user_name))
    keystone_v3.roles.grant(role=role_admin, user=user, domain=domain)

    role_assignments = keystone_v3.role_assignments.list(domain=domain)
    domain_users_ids = [du.user["id"] for du in role_assignments]
    assert user.id in domain_users_ids

    controller_ip = env.get_primary_controller_ip()
    auth_url = 'http://{0}:5000/v3'.format(controller_ip)
    auth = v3.Password(auth_url=auth_url,
                       username=user_name,
                       password=user_pass,
                       domain_name=domain_name,
                       user_domain_name=domain_name)
    sess = session.Session(auth=auth)
    keystone_v3 = KeystoneClientV3(session=sess)

    new_project_name = "project_1616778"
    logger.info("Creating project {0} in domain {1}".
                format(new_project_name, domain_name))
    keystone_v3.projects.create(name=new_project_name, domain=domain,
                                description="New project")

    projects = keystone_v3.projects.list(domain=domain)
    projects_names = [p.name for p in projects]
    assert new_project_name in projects_names, ("Project {0} is not created".
                                                format(new_project_name))


@pytest.mark.undestructive
@pytest.mark.testrail_id('1618359')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed", "is_ha", "is_ldap_proxy")
def test_support_ldap_proxy(os_conn, env, slapd_running):
    """Check that getUsers results for domains configured with LDAP proxy
    depend on slapd state (stopped or running)

    Steps to reproduce:
    1. Check that LDAP plugin is installed
    2. Check that slapd service is running on all controllers
    3. Login as admin/admin, domain: default
    4. Check lists of users for domains openldap1 and openldap2 (no errors)
    5. Stop the slapd service on all controllers
    6. Check lists of users for domains openldap1 and openldap2
       (exception for openldap1)
    7. Start the slapd service on all controllers
    8. Check lists of users for domains openldap1 and openldap2 (no errors)
    """
    domain_with_LDAP_proxy = "openldap1"
    domain_without_LDAP_proxy = "openldap2"

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domains = [d for d in keystone_v3.domains.list() if 'openldap' in d.name]
    assert len(domains) == 2
    for domain in domains:
        logger.debug("Checking users for domain {0}".format(domain.name))
        assert len(keystone_v3.users.list(domain=domain)) > 0

    logger.info("Stopping slapd service on all controllers")
    provide_slapd_state(env, "stopped")

    for domain in domains:
        logger.debug("Checking users for domain {0}".format(domain.name))
        try:
            users = keystone_v3.users.list(domain=domain)
            assert domain.name == domain_without_LDAP_proxy
            assert len(users) > 0
            logger.debug("domain {0} (without LDAP proxy), users list: OK".
                         format(domain.name))
        except (GatewayTimeout, InternalServerError) as e:
            assert domain.name == domain_with_LDAP_proxy
            logger.debug("domain {0} (with LDAP proxy), get users list: {1}".
                         format(domain.name, e.message))

    def is_proxy_up():
        proxy_domain = [d for d in domains if d.name == 'openldap1'][0]
        try:
            keystone_v3.users.list(domain=proxy_domain)
            return True
        except Exception:
            return False

    logger.info("Starting slapd service on all controllers")
    provide_slapd_state(env, "running")
    common.wait(is_proxy_up, timeout_seconds=180, sleep_seconds=10,
                waiting_for='proxy is up')

    for domain in domains:
        logger.debug("Checking users for domain {0}".format(domain.name))
        assert len(keystone_v3.users.list(domain=domain)) > 0


@pytest.mark.undestructive
@pytest.mark.testrail_id('1663412', with_proxy=True)
@pytest.mark.testrail_id('1682426', with_proxy=False)
@pytest.mark.ldap
@pytest.mark.parametrize('with_proxy', [True, False])
@pytest.mark.check_env_("is_ldap_plugin_installed", "is_ha", "is_tls_use")
def test_check_tls_option(os_conn, env, controllers, with_proxy):
    """Check that tls option works correctly

    Steps to reproduce:
    1. Check lists of users for domains openldap1 and openldap2 (no errors)
    2. Move ca-certificates.crt to tmp directory on all controllers
    3. Restart slapd/apache2 service on all controllers
    4. Check lists of users for domains openldap1 and openldap2
       (exception for openldap1)
    5. Move ca-certificates.crt in the original directory on all controllers
    6. Restart slapd/apache2 service on all controllers
    7. Check lists of users for domains openldap1 and openldap2 (no errors)

    """

    if with_proxy != conftest.is_ldap_proxy(env):
        enabled_or_disabled = 'enabled' if with_proxy else 'disabled'
        pytest.skip("LDAP proxy is not {}".format(enabled_or_disabled))

    domain_with_tls = "openldap1"
    domain_without_tls = "openldap2"
    service_name = "slapd" if with_proxy else "apache2"

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domains = [d for d in keystone_v3.domains.list() if 'openldap' in d.name]
    assert len(domains) == 2

    for domain in domains:
        logger.debug("Checking users for domain {0}".format(domain.name))
        assert len(keystone_v3.users.list(domain=domain)) > 0

    logger.info("Moving certificates and restarting {0} service on all "
                "controllers".format(service_name))
    for controller in controllers:
        move_cert(controller, to_original=False)
        restart_service(controller, service_name)
    check_504_error(keystone_v3)

    for domain in domains:
        logger.debug("Checking users for domain {0}".format(domain.name))
        try:
            users = keystone_v3.users.list(domain=domain)
            assert domain.name == domain_without_tls
            assert len(users) > 0
            logger.debug("domain {0} (without LDAP proxy), users list: OK".
                         format(domain.name))
        except InternalServerError as e:
            # 500: An unexpected error prevented the server ...
            assert domain.name == domain_with_tls
            logger.debug("domain {0} (with LDAP proxy), get users list: {1}".
                         format(domain.name, e.message))

    if with_proxy:
        logger.info("Restoring certificates and restarting slapd service "
                    "on all controllers")
    else:
        logger.info("Restoring certificates on all controllers")
    for controller in controllers:
        move_cert(controller)
        if service_name == "slapd":
            restart_service(controller, service_name)
    check_504_error(keystone_v3)

    for domain in domains:
        logger.debug("Checking users for domain {0}".format(domain.name))
        assert len(keystone_v3.users.list(domain=domain)) > 0


@pytest.mark.undestructive
@pytest.mark.testrail_id('1640557')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed", "is_ha")
def test_check_list_limit(os_conn, env, keystone_conf):
    """Check that list_limit option works correctly

    Steps to reproduce:
    1. Check values of list users for domains openldap1 and openldap2
    2. Change /etc/keystone/keystone.conf [DEFAULT] list_limit to 4 on all
    controllers
    3. Restart apache2 service on all controllers
    4. Check values of list users for domains openldap1 and openldap2 again
    5. Compare values of list users before and after change limit
    """
    list_limit = 4
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domains = [d for d in keystone_v3.domains.list() if 'openldap' in d.name]
    users_before = {}
    for domain in domains:
        users_before[domain.name] = len(keystone_v3.users.list(domain=domain))
        logger.debug("domain {0}, number of users: {1}".
                     format(domain.name, users_before[domain.name]))

    logger.info("Changing list limit to {0} on all controllers".
                format(list_limit))
    change_list_limit(env, list_limit)
    users_after = {}
    for domain in domains:
        users_after[domain.name] = len(keystone_v3.users.list(domain=domain))
        logger.debug("domain {0}, number of users: {1}".
                     format(domain.name, users_after[domain.name]))
    for domain in users_before:
        assert users_before[domain] >= users_after[domain]
        assert users_after[domain] <= list_limit


@pytest.mark.undestructive
@pytest.mark.testrail_id('1618360')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
def test_check_support_active_directory(os_conn):
    """Check support active directory

    Steps to reproduce:
    1. Check that some LDAP domains have Active Directory(AD in domain name).
    2. Check list of users for domains with active directory
    3. Check list of groups for domains with active directory
    """
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domains = [d for d in keystone_v3.domains.list() if 'AD' in d.name]
    if len(domains) == 0:
        pytest.skip('Domain with active directory is required')
    basic_check(keystone_v3, domain_name=domains[0].name)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1668066', with_proxy=True)
@pytest.mark.testrail_id('1681494', with_proxy=False)
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed", "has_1_or_more_computes")
@pytest.mark.parametrize('with_proxy', [True, False])
def test_create_instance_by_user(os_conn, env, domain_projects, with_proxy):
    """Launch an instance by LDAP user

    Steps to reproduce:
    1. Check that LDAP plugin is installed
    2. Login as admin/admin, domain: default
    3. Create a new project
    4. Set role 'admin' to 'user01' in domain openldap1 and project
    5. Relogin as user01/1111, domain: openldap1
    6. Create a network and subnetwork for the new project
    7. Create an instance
    8. Repeat steps 2-7 for domain AD2
    """

    if with_proxy != conftest.is_ldap_proxy(env):
        enabled_or_disabled = 'enabled' if with_proxy else 'disabled'
        pytest.skip("LDAP proxy is not {}".format(enabled_or_disabled))

    for domain_name in ['openldap1', 'AD2']:

        user_name, user_pass = AUTH_DATA[domain_name]
        id = random.randint(1, 10000)

        keystone_v3 = KeystoneClientV3(session=os_conn.session)
        domain = keystone_v3.domains.find(name=domain_name)
        new_project_name = "project-{}".format(id)
        logger.info("Creating project {0} in domain {1}".
                    format(new_project_name, domain_name))
        new_project = keystone_v3.projects.create(name=new_project_name,
                                                  domain=domain,
                                                  description="New project")

        logger.info("Setting role 'admin' to user {0}".format(user_name))
        user = keystone_v3.users.find(domain=domain, name=user_name)
        role_admin = keystone_v3.roles.find(name="admin")
        keystone_v3.roles.grant(role=role_admin, user=user, domain=domain)
        keystone_v3.roles.grant(role=role_admin, user=user,
                                project=new_project)

        controller_ip = env.get_primary_controller_ip()

        os_conn_v3 = OpenStackActions(controller_ip,
                                      keystone_version=3,
                                      domain=domain_name,
                                      user=user_name,
                                      password=user_pass,
                                      tenant=new_project_name,
                                      env=env)

        logger.info("Creating network, subnetwork, keypair and "
                    "security_group in project {0}".format(new_project_name))
        network_name = "net-{}".format(id)
        network = os_conn_v3.create_network(name=network_name,
                                            tenant_id=new_project.id)
        subnet_name = "subnet-{}".format(id)
        os_conn_v3.create_subnet(network_id=network['network']['id'],
                                 name=subnet_name,
                                 cidr="192.168.2.0/24",
                                 tenant_id=new_project.id)
        keypair_name = "key-{}".format(id)
        instance_keypair = os_conn_v3.create_key(key_name=keypair_name)
        security_group = os_conn_v3.create_sec_group_for_ssh()

        new_instance_name = "inst-{}".format(id)
        logger.info("Creating instance {0}".format(new_instance_name))
        vm = os_conn_v3.create_server(name=new_instance_name,
                                      availability_zone='nova',
                                      key_name=instance_keypair.name,
                                      nics=[{
                                          'net-id': network['network']['id']
                                      }],
                                      security_groups=[security_group.id],
                                      wait_for_avaliable=False)

        assert os_conn_v3.server_status_is(vm, 'ACTIVE')


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681394')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
def test_mapping_user_parameters(os_conn, ldap_server, new_ldap_user):
    """Test to check mapping between LDAP server and keystone

    Steps to reproduce:
    1. Create a new user on LDAP server
    2. Check that this user is shown on keystone and its description and mail
       are equal to LDAP values
    3. Change description and mail on LDAP servers
    4. Check that new values are equal on LDAP and keystone sides
    5. Delete the user on LDAP server
    6. Check that the user is not present on keystone
    """

    ld, ldap_domain_name, ldap_user_tree_dn, ldap_name_attr = ldap_server
    user_name, user_dn = new_ldap_user

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domain = keystone_v3.domains.find(name=ldap_domain_name)

    def get_user_data():
        logger.debug("Getting data for user {0} from LDAP server".
                     format(user_name))
        search_filter = "{0}={1}".format(ldap_name_attr, user_name)
        # ex: sn=test-user01
        search_attrs = ["description", "mail"]
        ldap_result = ld.search_s(ldap_user_tree_dn, ldap.SCOPE_SUBTREE,
                                  search_filter, search_attrs)[0][1]
        ldap_descr = ldap_result['description'][0]
        ldap_email = ldap_result['mail'][0]
        return ldap_descr, ldap_email

    ldap_descr, ldap_email = get_user_data()

    logger.debug("Getting data for user {0} from keystone".format(user_name))
    user = keystone_v3.users.find(domain=domain, name=user_name)

    assert user.description == ldap_descr
    assert user.email == ldap_email

    logger.info("Updating data for user {0}".format(user_name))
    old = {'description': ldap_descr, 'mail': ldap_email}
    new = {'description': 'titi', 'mail': 'toto-' + ldap_email}
    ldif = modlist.modifyModlist(old, new)
    ld.modify_s(user_dn, ldif)

    ldap_descr, ldap_email = get_user_data()

    logger.info("Getting data for user {0} from keystone".format(user_name))
    user = keystone_v3.users.find(domain=domain, name=user_name)

    assert user.description == ldap_descr
    assert user.email == ldap_email

    logger.info("Deleting user {0} on LDAP server".format(user_name))
    ld.delete_s(user_dn)

    with pytest.raises(KeyStoneException):
        keystone_v3.users.find(domain=domain, name=user_name)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1681395')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed", "is_ha")
def test_check_admin_privileges(os_conn, env):
    """Check the admin privileges for a domain user

    Steps to reproduce:
    1. Login as admin/admin, domain: default
    2. Set role 'admin' to 'user1' in domain openldap2
    3. Relogin as user1/1111, domain: openldap2
    4. Check list of users in domain openldap1
    """

    domain_name = "openldap2"
    user_name, user_pass = AUTH_DATA[domain_name]

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domain = keystone_v3.domains.find(name=domain_name)
    user = keystone_v3.users.find(domain=domain, name=user_name)

    logger.info("Setting role 'admin' to user {0}".format(user_name))
    role_admin = keystone_v3.roles.find(name="admin")
    keystone_v3.roles.grant(role=role_admin, user=user, domain=domain)

    role_assignments = keystone_v3.role_assignments.list(domain=domain)
    domain_users_ids = [du.user["id"] for du in role_assignments]
    assert user.id in domain_users_ids

    logger.info("Login as {0}".format(user_name))
    controller_ip = env.get_primary_controller_ip()
    auth_url = 'http://{0}:5000/v3'.format(controller_ip)
    auth = v3.Password(auth_url=auth_url,
                       username=user_name,
                       password=user_pass,
                       domain_name=domain_name,
                       user_domain_name=domain_name)
    sess = session.Session(auth=auth)
    keystone_v3 = KeystoneClientV3(session=sess)

    basic_check(keystone_v3, domain_name="openldap1")


@pytest.mark.undestructive
@pytest.mark.testrail_id('1680670')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
def test_plugin_uninstall_for_deployed_env(env, admin_remote):
    """Check that the LDAP plugin cannot be uninstalled in the deployed
    environment

    Steps to reproduce:
    1. Execute the command to remove LDAP plugin
    2. Check that this command is failed with expected error message
    """

    plugin_version = get_plugin_version(env, 'ldap')
    result = admin_remote.execute("fuel plugins --remove ldap=={0}".
                                  format(plugin_version))
    exp_msg = "Can't delete plugin which is enabled for some environment"
    assert exp_msg in result['stderr'][0]


# destructive
@pytest.mark.testrail_id('1680671')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
def test_plugin_uninstall_for_non_deployed_env(env, admin_remote):
    """Check uninstallation of the LDAP plugin when an environment is
    non-deployed and the plugin is disabled for it

    Steps to reproduce:
    1. Reset environment
    2. Disable the LDAP plugin
    3. Execute the command to remove LDAP plugin
    4. Check that this command is finished successfully
    """

    logger.info("Reset environment")
    env.reset()
    common.wait(lambda: env.status == 'new',
                timeout_seconds=120,
                sleep_seconds=20,
                waiting_for="Env reset finish")

    # Disable plugin
    configure_plugin(env, 'ldap', enabled=False)

    logger.info("Uninstall the LDAP plugin")
    plugin_version = get_plugin_version(env, 'ldap')
    result = admin_remote.execute("fuel plugins --remove ldap=={0}".
                                  format(plugin_version))
    exp_msg = "Plugin ldap=={0} was successfully removed".\
        format(plugin_version)
    assert exp_msg in result['stdout'][-1]


# destructive
@pytest.mark.testrail_id('1680674')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
def test_plugin_update(os_conn, env, admin_remote):
    """Check update of the LDAP plugin in the deployed environment

    Steps to reproduce:
    1. Check list of users and groups for LDAP domains
    2. Get the current plugin version
    3. Download file for new version of the LDAP plugin
    4. Update the plugin
    5. Check that plugin version is changed
    6. Reset and re-deploy env
    7. Checks users and groups for LDAP domains

    Duration ~ 1 hour

    NOTE: RPM file for new plugin version must be available via
    http://<ip_addr>/ldap.rpm
    """

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)

    old_plugin_version = next(p['version'] for p in FuelPlugins.get_all_data()
                              if p['name'] == 'ldap')

    logger.info("Download the RPM file")
    # RPM file is located on the LDAP server
    ldap_url = get_plugin_config_value(env, 'ldap', 'url')
    # ldap://176.74.22.8 -> http://176.74.22.8:8080/ldap.rpm
    rpm_file = "ldap.rpm"
    url = ldap_url.replace("ldap", "http") + ":8080/" + rpm_file
    admin_remote.check_call("wget {}".format(url))

    logger.info("Update the LDAP plugin")
    # NOTE: cannot use FuelPlugins.update because it executes the rpm command
    # on local machine (which is not installed)
    result = admin_remote.execute("fuel plugins --update {0}".
                                  format(rpm_file))
    exp_msg = "Plugin {0} was successfully updated".format(rpm_file)
    assert exp_msg in result['stdout'][-1]

    new_plugin_version = next(p['version'] for p in FuelPlugins.get_all_data()
                              if p['name'] == 'ldap')
    assert new_plugin_version != old_plugin_version

    logger.info("Reset environment")
    env.reset()
    common.wait(lambda: env.status == 'new',
                timeout_seconds=120,
                sleep_seconds=20,
                waiting_for="Env reset finish")

    logger.info("Deploy changes")
    deploy_task = env.deploy_changes()
    common.wait(lambda: common.is_task_ready(deploy_task),
                timeout_seconds=60 * 120,
                sleep_seconds=60,
                waiting_for="changes to be deployed")

    assert env.status == 'operational'
    env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)


# destructive
@pytest.mark.testrail_id('1680673')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed", "is_ha")
def test_recovery_after_controller_shutdown(os_conn, env, devops_env):
    """Check recovery after shutdown of a controller

    Steps to reproduce:
    1. Check list of users and groups for LDAP domains
    2. Shutdown the primary controller
    3. Check list of users and groups for LDAP domains
    """
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)

    primary_controller = \
        devops_env.get_node_by_fuel_node(env.primary_controller)
    env.warm_shutdown_nodes([primary_controller])

    basic_check(keystone_v3)


# destructive
@pytest.mark.testrail_id('1663416', node_role='controller')
@pytest.mark.testrail_id('1663415', node_role='compute')
@pytest.mark.ldap
@pytest.mark.parametrize('node_role', ['controller', 'compute'])
@pytest.mark.check_env_("is_ldap_plugin_installed", "is_ha",
                        "has_1_or_more_computes")
def test_remove_add_node_to_env(os_conn, env, devops_env, node_role):
    """Check basic LDAP functionalities after removing/adding the primary
    controller or compute

    Steps to reproduce:
    1. Check list of users and groups for LDAP domains
    2. Delete the primary controller/compute
    3. Deploy the environment
    4. Check that env is OK
    5. Check list of users and groups for LDAP domains
    6. Add the controller/compute deleted before
    7. Deploy the environment
    8. Check that env is OK
    9. Check list of users and groups for LDAP domains

    Duration ~ 90 minutes for every node

    See similar test_remove_add_compute_controller_nodes_to_env
    in rabbitmq_oslo/test_detached_rabbit
    """

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)

    if node_role == 'controller':
        node = env.primary_controller
    else:
        node = env.get_nodes_by_role('compute')[0]
    node_dev = devops_env.get_node_by_fuel_node(node)
    node_name = node.data['name']
    node_roles = node.data['roles']

    logger.info("Unassign node {0} ({1})".format(node_name, node_roles))
    env.unassign([node.id])

    logger.debug("Run network verification")
    assert env.wait_network_verification().status == 'ready'

    logger.info("Deploy changes")
    deploy_task = env.deploy_changes()
    common.wait(lambda: common.is_task_ready(deploy_task),
                timeout_seconds=60 * 120,
                sleep_seconds=60,
                waiting_for="changes to be deployed")

    assert env.status == 'operational'
    env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)

    logger.info("Assign back node {0} ({1})".format(node_name, node_roles))
    node = env.get_node_by_devops_node(node_dev)
    node.set({'name': node_name + '_new'})
    env.assign([node], node_roles)

    logger.debug("Restore network interfaces")
    interfaces = map_devops_to_fuel_net(env, devops_env, node)
    node.upload_node_attribute('interfaces', interfaces)

    logger.debug("Run network verification")
    assert env.wait_network_verification().status == 'ready'

    logger.info("Reset environment")
    env.reset()
    common.wait(lambda: env.status == 'new',
                timeout_seconds=120,
                sleep_seconds=20,
                waiting_for="Env reset finish")

    logger.info("Deploy environment")
    deploy_task = env.deploy_changes()
    common.wait(lambda: common.is_task_ready(deploy_task),
                timeout_seconds=60 * 120,
                sleep_seconds=60,
                waiting_for="changes to be deployed")

    assert env.status == 'operational'
    env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)


# destructive
@pytest.mark.skip(reason="Skip because of Murano plugin problems for 9.1")
@pytest.mark.testrail_id('1680672')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
def test_plugin_interoperability_murano(os_conn, env, devops_env, admin_remote,
                                        no_murano_plugin, get_plugin_url):
    """Check the LDAP plugin together with Murano plugin

    Steps to reproduce:
    1. Checks users and groups for LDAP domains
    2. Download and install Murano plugin
    3. Reset and re-deploy env
    4. Check list of Murano packages
    5. Checks users and groups for LDAP domains

    Duration ~ 90 minutes
    """

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)

    # Download and install Murano plugin
    url = get_plugin_url('detach-murano')
    install_plugin(admin_remote, url)

    # Enable plugin
    configure_plugin(env, 'detach-murano', enabled=True)

    # Node for Murano roles
    node = env.non_primary_controllers[0]
    node_name = node.data['name']
    interfaces = map_devops_to_fuel_net(env, devops_env, node)

    logger.info("Reset environment")
    env.reset()
    common.wait(lambda: env.status == 'new',
                timeout_seconds=120,
                sleep_seconds=20,
                waiting_for="Env reset finish")

    logger.info("Assign Murano roles to a non-primary controller")
    # this is done via node recreation (cannot find more easily way)
    env.unassign([node.id])
    node.set({'name': node_name + '-murano'})
    env.assign([node], ['murano-node'])
    node.upload_node_attribute('interfaces', interfaces)

    logger.info("Deploy changes")
    deploy_task = env.deploy_changes()
    common.wait(lambda: common.is_task_ready(deploy_task),
                timeout_seconds=60 * 120,
                sleep_seconds=60,
                waiting_for="changes to be deployed")

    assert env.status == 'operational'
    env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)

    logger.info("Getting Murano package list")
    # See MuranoActions in murano.actions.py
    # Murano is installed with Glare (Enable glance artifact repository)
    murano_endpoint = os_conn.session.get_endpoint(
        service_type='application-catalog', endpoint_type='publicURL')
    token = os_conn.session.get_auth_headers()['X-Auth-Token']
    glare_endpoint = os_conn.session.get_endpoint(
        service_type='artifact', endpoint_type='publicURL')
    glare = glare_client.Client(endpoint=glare_endpoint,
                                token=token,
                                cacert=os_conn.path_to_cert,
                                type_name='murano',
                                type_version=1)
    murano = MuranoClient(endpoint=murano_endpoint,
                          token=token,
                          cacert=os_conn.path_to_cert,
                          artifacts_client=glare)

    package_names = [p.name for p in murano.packages.list()]
    assert "Core library" in package_names

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)


# destructive
@pytest.mark.testrail_id('1682427')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
def test_plugin_interoperability_stacklight(os_conn, env, devops_env,
                                            admin_remote,
                                            no_stacklight_plugins,
                                            get_plugin_url):
    """Check the LDAP plugin together with StackLight plugins

    Steps to reproduce:
    1. Checks users and groups for LDAP domains
    2. Download and install StackLight plugins
    3. Reset and re-deploy env
    4. Execute diagnostic command
    5. Checks users and groups for LDAP domains

    Duration ~ 90 minutes
    """

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)

    # Install plugins
    for plugin_name in STACKLIGHT_PLUGIN_NAMES:
        url = get_plugin_url(plugin_name)
        install_plugin(admin_remote, url)

    # Enable plugins and set some values
    for plugin_name in STACKLIGHT_PLUGIN_NAMES:
        configure_plugin(env, plugin_name, enabled=True)

    # Node for StackLite roles
    node = env.non_primary_controllers[0]
    node_name = node.data['name']
    interfaces = map_devops_to_fuel_net(env, devops_env, node)

    logger.info("Reset environment")
    env.reset()
    common.wait(lambda: env.status == 'new',
                timeout_seconds=120,
                sleep_seconds=20,
                waiting_for="Env reset finish")

    logger.info("Assign StackLight roles to a non-primary controller")
    # this is done via node recreation (cannot find more easily way)
    env.unassign([node.id])
    node.set({'name': node_name + '-stacklight'})
    stacklight_roles = ['infrastructure_alerting', 'elasticsearch_kibana',
                        'influxdb_grafana']
    env.assign([node], stacklight_roles)
    node.upload_node_attribute('interfaces', interfaces)

    logger.info("Deploy changes")
    deploy_task = env.deploy_changes()
    common.wait(lambda: common.is_task_ready(deploy_task),
                timeout_seconds=60 * 120,
                sleep_seconds=60,
                waiting_for="changes to be deployed")

    assert env.status == 'operational'
    env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)

    logger.info("Launch diagnostic tool")
    node = env.primary_controller
    with node.ssh() as remote:
        output = remote.check_call("lma_diagnostics").stdout_string
        assert "ERROR" not in output

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)


# destructive
@pytest.mark.testrail_id('1682247')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
def test_wrong_ldap_server(os_conn, env):
    """Check the LDAP plugin when IP address of LDAP server is wrong

    Steps to reproduce:
    1. Checks users and groups for LDAP domains
    2. Set wrong IP address of LDAP server
    3. Redeploy
    4. Check domains (OK)
    5. Checks users and groups for LDAP domains (NOK)

    Duration ~ 90 minutes
    """

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)

    logger.info("Set wrong address of LDAP server")
    node = env.get_nodes_by_role('compute')[0]
    ip_address = node.ip_list[0]
    set_plugin_config_value(env, 'ldap', 'url',
                            "ldap://{0}".format(ip_address))

    logger.info("Reset environment")
    env.reset()
    common.wait(lambda: env.status == 'new',
                timeout_seconds=120,
                sleep_seconds=20,
                waiting_for="Env reset finish")

    logger.info("Deploy changes")
    deploy_task = env.deploy_changes()
    common.wait(lambda: common.is_task_ready(deploy_task),
                timeout_seconds=60 * 120,
                sleep_seconds=60,
                waiting_for="changes to be deployed")

    assert env.status == 'operational'
    env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    logger.info("Checking domains")
    main_domain = [d for d in keystone_v3.domains.list()
                   if d.name == 'openldap1'][0]
    logger.info("Checking users of domain {0}".format(main_domain.name))
    with pytest.raises(KeyStoneException):
        keystone_v3.users.list(domain=main_domain)
    logger.info("Checking groups of domain {0}".format(main_domain.name))
    with pytest.raises(KeyStoneException):
        keystone_v3.groups.list(domain=main_domain)


# destructive
@pytest.mark.testrail_id('1683946')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed", "not is_ldap_proxy")
def test_check_anonymous_user(os_conn, env):
    """Check the LDAP plugin when IP address of LDAP server is wrong

    Steps to reproduce:
    1. Checks users and groups for LDAP domains
    2. Configure LDAP plugin with empty LDAP user
    3. Redeploy
    4. Login as admin/admin, domain: default
    5. Create the new user u123/1111 and set its role=admin
    6. Login as u123/1111, domain: default
    5. Checks users and groups for LDAP domains

    Duration ~ 90 minutes
    """

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    basic_check(keystone_v3)

    logger.info("Configure LDAP plugin with empty LDAP user")
    set_plugin_config_value(env, 'ldap', 'user', '')
    set_plugin_config_value(env, 'ldap', 'password', '1111')

    logger.info("Reset environment")
    env.reset()
    common.wait(lambda: env.status == 'new',
                timeout_seconds=120,
                sleep_seconds=20,
                waiting_for="Env reset finish")

    logger.info("Deploy changes")
    deploy_task = env.deploy_changes()
    common.wait(lambda: common.is_task_ready(deploy_task),
                timeout_seconds=60 * 120,
                sleep_seconds=60,
                waiting_for="changes to be deployed")

    assert env.status == 'operational'
    env.wait_for_ostf_pass(['sanity'], timeout_seconds=60 * 5)

    logger.info("Creating new user with role 'admin'")
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    user_name = 'u123'
    user_pass = '1111'
    domain_name = 'default'
    domain = keystone_v3.domains.find(name=domain_name)
    user = keystone_v3.users.create(name=user_name, domain=domain,
                                    password=user_pass)
    role_admin = keystone_v3.roles.find(name='admin')
    keystone_v3.roles.grant(role=role_admin, user=user, domain=domain)

    logger.info("Relogin as new user")
    controller_ip = env.get_primary_controller_ip()
    auth_url = 'http://{0}:5000/v3'.format(controller_ip)
    auth = v3.Password(auth_url=auth_url,
                       username=user_name,
                       password=user_pass,
                       domain_name=domain_name,
                       user_domain_name=domain_name)
    sess = session.Session(auth=auth)
    keystone_v3 = KeystoneClientV3(session=sess)

    basic_check(keystone_v3)
