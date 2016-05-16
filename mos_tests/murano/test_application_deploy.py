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


@pytest.mark.parametrize('package', [('databases.MySql',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836380')
def test_deploy_database_mysql(environment, murano, session, package, keypair):

    murano.create_service(environment, session, murano.mysql_app(keypair))
    murano.deploy_environment(environment, session)
    murano.deployment_success_check(environment, ports=[22, 3306])


@pytest.mark.parametrize('package', [('ApacheHttpServer',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836384')
def test_deploy_apache_http(environment, murano, session, package, keypair):

    murano.create_service(environment, session, murano.apache(keypair))
    murano.deploy_environment(environment, session)
    murano.deployment_success_check(environment, ports=[22, 80])


@pytest.mark.parametrize('package', [('apps.WordPress',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836381')
def test_deploy_apache_http_mysql_wordpress(environment, murano, session,
                                            package, keypair):

    mysql = murano.create_service(environment, session,
                                  murano.mysql_app(keypair))
    apache = murano.create_service(environment, session,
                                   murano.apache(keypair))
    murano.create_service(environment, session,
                          murano.wordpress(apache, mysql))
    murano.deploy_environment(environment, session)
    murano.status_check(environment, [[apache['instance']['name'], 22, 80],
                                      [mysql['instance']['name'], 22, 3306]])
    murano.check_path(environment, "wordpress", apache['instance']['name'])


@pytest.mark.parametrize('package', [('apps.apache.Tomcat',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836379')
def test_deploy_apache_tomcat(environment, murano, session, package, keypair):

    murano.create_service(environment, session, murano.tomcat_app(keypair))
    murano.deploy_environment(environment, session)
    murano.deployment_success_check(environment, ports=[22, 8080])


@pytest.mark.parametrize('package', [('databases.PostgreSql',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836385')
def test_deploy_database_postgres(environment, murano,
                                  session, package, keypair):

    murano.create_service(environment, session, murano.postgres_app(keypair))
    murano.deploy_environment(environment, session)
    murano.deployment_success_check(environment, ports=[22, 5432])


@pytest.mark.parametrize('package', [('apps.ZabbixServer',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836383')
def test_deploy_zabbix_server(environment, murano, session, package, keypair):

    murano.create_service(environment, session, murano.zabbix_server(keypair))
    murano.deploy_environment(environment, session)
    murano.deployment_success_check(environment, ports=[22, 80])
    murano.check_path(environment, "zabbix")


@pytest.mark.parametrize('package', [('apps.ZabbixAgent',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836382')
def test_deploy_zabbix_agent(environment, murano, session, package, keypair):

    zabbix_server = murano.create_service(environment, session,
                                          murano.zabbix_server(keypair))
    murano.create_service(environment, session,
                          murano.zabbix_agent(zabbix_server))
    murano.deploy_environment(environment, session)
    murano.deployment_success_check(environment, ports=[22, 80])
    murano.check_path(environment, "zabbix")
