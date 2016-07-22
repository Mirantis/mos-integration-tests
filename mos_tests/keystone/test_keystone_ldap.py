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
import re
import time

from keystoneauth1.identity import v3
from keystoneauth1 import session
from keystoneclient.v3 import Client as KeystoneClientV3
from six.moves import configparser

from mos_tests.functions import common


@pytest.yield_fixture
def domain_projects(os_conn):
    # Get current projects for all domains
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domains = [d for d in keystone_v3.domains.list()]
    old_projects = {}
    for domain in domains:
        old_projects[domain.name] = []
        for project in keystone_v3.projects.list(domain=domain):
            old_projects[domain.name].append(project.name)
    yield old_projects
    # Delete projects created during test execution
    # (it's supposed that domains are not created/deleted/renamed)
    for domain in domains:
        for project in keystone_v3.projects.list(domain=domain):
            if project.name not in old_projects[domain.name]:
                keystone_v3.projects.delete(project=project)


@pytest.yield_fixture
def slapd_running(os_conn):
    provide_slapd_state(os_conn.env, "running")
    yield
    provide_slapd_state(os_conn.env, "running")


@pytest.yield_fixture
def controllers(env):
    controllers = env.get_nodes_by_role('controller')
    for controller in controllers:
        move_cert(controller, to_original=True)
    yield controllers
    for controller in controllers:
        move_cert(controller, to_original=True)


@pytest.yield_fixture
def keystone_conf(env):
    controllers = env.get_nodes_by_role('controller')
    cmd = 'cp /etc/keystone/keystone.conf /etc/keystone/keystone.conf.bk'
    for controller in controllers:
        with controller.ssh() as remote:
            remote.check_call(cmd)
    yield
    cmd = 'cp /etc/keystone/keystone.conf.bk /etc/keystone/keystone.conf'
    for controller in controllers:
        with controller.ssh() as remote:
            remote.check_call(cmd)
            remote.check_call('service apache2 restart')
            remote.check_call('rm /etc/keystone/keystone.conf.bk ')


def restart_slapd(controller):
    with controller.ssh() as remote:
        remote.check_call('service slapd restart')
        common.wait(
            lambda: 'start/running' in remote.check_call(
                'service slapd status').stdout_string,
            timeout_seconds=60,
            waiting_for='status is start/running')


def move_cert(controller, to_original=True):
    cert = 'ca-certificates.crt'
    tmp_dir = '/tmp'
    orig_dir = '/etc/ssl/certs'
    if to_original:
        dir_1, dir_2 = tmp_dir, orig_dir
    else:
        dir_1, dir_2 = orig_dir, tmp_dir

    cmd = "mv {0}/{1} {2}".format(dir_1, cert, dir_2)
    check_cmd = 'ls {}/ |grep {}'

    with controller.ssh() as remote:
        if cert in remote.execute(check_cmd.format(dir_1, cert)).stdout_string:
            remote.check_call(cmd)
            assert cert not in remote.execute(check_cmd.format(
                dir_1, cert)).stdout_string
            assert cert in remote.execute(check_cmd.format(
                dir_2, cert)).stdout_string


def provide_slapd_state(env, status):
    """check/start/stop the slapd service on all controllers"""

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


@pytest.mark.undestructive
@pytest.mark.testrail_id('1295439')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
def test_ldap_basic_functions(os_conn):
    """Test to cover basic functionality for multi domain

    Steps to reproduce:
    1. Check that LDAP plugin is installed
    2. Login as admin/admin, domain: default
    4. Find LDAP domain(s)
    5. For each domain, checks lists of users and groups
    """

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    ldap_domains = [domain for domain in keystone_v3.domains.list() if
                    re.search("^(openldap|AD)", domain.name)]
    # Limitation: only domains like openldap1, openldap.tld, AD2 are checked
    assert len(ldap_domains) > 0, "no LDAP test domains are found"
    for ldap_domain in ldap_domains:
        users = keystone_v3.users.list(domain=ldap_domain)
        assert len(users) > 0, "no users in domain {0}".\
            format(ldap_domain.name)
        groups = keystone_v3.groups.list(domain=ldap_domain)
        assert len(groups) > 0, "no groups in domain {0}".\
            format(ldap_domain.name)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1616778')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed")
def test_create_project_by_user(os_conn, domain_projects):
    """Create a project by LDAP user

    Steps to reproduce:
    1. Check that LDAP plugin is installed
    2. Login as admin/admin, domain: default
    3. Set role 'admin' to 'user01' in domain openldap1
    4. Relogin as user01/1111, domain: openldap1
    5. Create a new project
    """

    test_domain_name = "openldap1"
    test_user_name = 'user01'
    test_user_pass = '1111'

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    test_domain = [d for d in keystone_v3.domains.list() if
                   d.name == test_domain_name][0]
    users = keystone_v3.users.list(domain=test_domain)
    test_user = [u for u in users if u.name == test_user_name][0]

    roles = keystone_v3.roles.list(domain=test_domain)
    role_admin = [r for r in roles if r.name == "admin"][0]

    keystone_v3.roles.grant(role=role_admin, user=test_user,
                            domain=test_domain)

    role_assignments = keystone_v3.role_assignments.list(domain=test_domain)
    domain_users_ids = [du.user["id"] for du in role_assignments]
    assert test_user.id in domain_users_ids

    controller_ip = os_conn.env.get_primary_controller_ip()
    auth_url = 'http://{0}:5000/v3'.format(controller_ip)
    auth = v3.Password(auth_url=auth_url,
                       username=test_user_name,
                       password=test_user_pass,
                       domain_name=test_domain_name,
                       user_domain_name=test_domain_name)
    sess = session.Session(auth=auth)
    keystone_v3 = KeystoneClientV3(session=sess)

    new_project_name = "project_1616778"
    keystone_v3.projects.create(name=new_project_name, domain=test_domain,
                                description="New project")

    projects = keystone_v3.projects.list(domain=test_domain)
    projects_names = [p.name for p in projects]
    assert new_project_name in projects_names, \
        "Project {0} is not created".format(new_project_name)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1618359')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed", "is_ldap_proxy",
                        "has_3_or_more_controllers")
def test_support_ldap_proxy(os_conn, slapd_running):
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
        assert len(keystone_v3.users.list(domain=domain)) > 0

    provide_slapd_state(os_conn.env, "stopped")
    exp_mess_1 = "An unexpected error prevented the server from fulfilling " \
                 "your request"
    exp_mess_2 = 'Gateway Timeout'

    for domain in domains:
        try:
            users = keystone_v3.users.list(domain=domain)
            assert domain.name == domain_without_LDAP_proxy
            assert len(users) > 0
        except Exception as e:
            assert domain.name == domain_with_LDAP_proxy
            assert exp_mess_1 in e.message or exp_mess_2 in e.message

    provide_slapd_state(os_conn.env, "running")
    time.sleep(1)

    for domain in domains:
        assert len(keystone_v3.users.list(domain=domain)) > 0


@pytest.mark.undestructive
@pytest.mark.testrail_id('1663412')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed", "is_tls_use",
                        "is_ldap_proxy", "has_3_or_more_controllers")
def test_check_tls_option(os_conn, controllers, env):
    """Check that tls option works correctly

    Steps to reproduce:
    1. Check lists of users for domains openldap1 and openldap2 (no errors)
    2. Move ca-certificates.crt to tmp directory on 1 controller
    3. Check lists of users for domains openldap1 and openldap2 (no errors)
    4. Move ca-certificates.crt to tmp directory on all controllers
    5. Restart slapd service on all controllers
    6. Check lists of users for domains openldap1 and openldap2
       (exception for openldap1)
    7. Move ca-certificates.crt in the original directory on all controllers
    8. Check lists of users for domains openldap1 and openldap2 (no errors)
    """

    domain_with_tls = "openldap1"
    domain_without_tls = "openldap2"

    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domains = [d for d in keystone_v3.domains.list() if 'openldap' in d.name]
    assert len(domains) == 2

    for domain in domains:
        assert len(keystone_v3.users.list(domain=domain)) > 0
    controller_1 = controllers[0]
    move_cert(controller_1, to_original=False)
    restart_slapd(controller_1)

    for domain in domains:
        assert len(keystone_v3.users.list(domain=domain)) > 0

    for controller in controllers:
        move_cert(controller, to_original=False)
        restart_slapd(controller)

    exp_mess = "An unexpected error prevented the server from fulfilling " \
               "your request"

    for domain in domains:
        try:
            users = keystone_v3.users.list(domain=domain)
            assert domain.name == domain_without_tls
            assert len(users) > 0
        except Exception as e:
            assert domain.name == domain_with_tls
            assert exp_mess in e.message

    for controller in controllers:
        move_cert(controller)

    for domain in domains:
        assert len(keystone_v3.users.list(domain=domain)) > 0


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
            remote.check_call('service apache2 restart')

    controllers = env.get_nodes_by_role('controller')
    for controller in controllers:
        change_limit(controller, limit)


@pytest.mark.undestructive
@pytest.mark.testrail_id('1640557')
@pytest.mark.ldap
@pytest.mark.check_env_("is_ldap_plugin_installed",
                        "has_3_or_more_controllers")
def test_check_list_limit(os_conn, env, keystone_conf):
    """Check that list_limit option works correctly

    Steps to reproduce:
    1. Check values of list users for domains openldap1 and openldap2
    2. Change /etc/keystone/keystone.conf [DEFAULT] list_limit to 100 on all
    controllers
    3. Restart apache2 service on all controllers
    4. Check values of list users for domains openldap1 and openldap2 again
    5. Compare values of list users before and after change limit
    """
    list_limit = 100
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    domains = [d for d in keystone_v3.domains.list() if 'openldap' in d.name]
    users_before = {}
    for domain in domains:
        users_before[domain.name] = len(keystone_v3.users.list(domain=domain))

    change_list_limit(env, list_limit)
    users_after = {}
    for domain in domains:
        users_after[domain.name] = len(keystone_v3.users.list(domain=domain))
    for domain in users_before:
        assert users_before[domain] >= users_after[domain]
        assert users_after[domain] <= list_limit
