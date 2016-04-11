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


@pytest.mark.parametrize('package', [('DockerCrate', 'DockerNginxSite',
                                      'DockerGlassFish')],
                         indirect=['package'])
@pytest.mark.testrail_id('836387')
def test_deploy_docker_crate_nginxsite_glassfish(environment, murano, session,
                                                 docker, package):
    murano.create_service(environment, session, murano.crate(docker))
    murano.create_service(environment, session, murano.nginx_site(docker))
    murano.create_service(environment, session, murano.glassfish(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 4200, 4300, 80,
                                                        4848, 8080, 8181])


@pytest.mark.parametrize('package', [('DockerCrate', 'DockerNginx',
                                      'DockerMongoDB')], indirect=['package'])
@pytest.mark.testrail_id('836386')
def test_deploy_docker_crate_nginx_mongodb(environment, murano, session,
                                           docker, package):
    murano.create_service(environment, session, murano.crate(docker))
    murano.create_service(environment, session, murano.nginx(docker))
    murano.create_service(environment, session, murano.mongodb(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 4200, 4300, 80,
                                                        27017])


@pytest.mark.parametrize('package', [('DockerMariaDB', 'DockerPostgreSQL',
                                      'DockerMongoDB')], indirect=['package'])
@pytest.mark.testrail_id('836389')
def test_deploy_docker_mariadb_postgresql_mongodb(environment, murano, session,
                                                  docker, package):

    murano.create_service(environment, session, murano.mariadb(docker))
    murano.create_service(environment, session, murano.postgres(docker))
    murano.create_service(environment, session, murano.mongodb(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 3306, 5432, 27017])


@pytest.mark.parametrize('package', [('DockerRedis', 'DockerTomcat',
                                      'DockerInfluxDB')], indirect=['package'])
@pytest.mark.testrail_id('836396')
def test_deploy_docker_redis_tomcat_influxdb(environment, murano, session,
                                             docker, package):

    murano.create_service(environment, session, murano.redis(docker))
    murano.create_service(environment, session, murano.tomcat(docker))
    murano.create_service(environment, session, murano.influxdb(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 6379, 8080, 8083,
                                                        8086])


@pytest.mark.parametrize('package', [('DockerNginxSite', 'DockerMySQL',
                                      'DockerRedis')], indirect=['package'])
@pytest.mark.testrail_id('836391')
def test_deploy_docker_mysql_nginxsite_redis(environment, murano, session,
                                             docker, package):

    murano.create_service(environment, session, murano.nginx_site(docker))
    murano.create_service(environment, session, murano.mysql(docker))
    murano.create_service(environment, session, murano.redis(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 3306, 80, 6379])


@pytest.mark.parametrize('package', [('DockerNginx', 'DockerHTTPd')],
                         indirect=['package'])
@pytest.mark.testrail_id('836394')
def test_deploy_docker_nginx_wait_deploy_httpd(environment, murano, session,
                                               docker, package):

    murano.create_service(environment, session, murano.nginx(docker))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 80])
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.httpd(docker))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 80, 1025])


@pytest.mark.parametrize('package', [('DockerMySQL', 'DockerTomcat')],
                         indirect=['package'])
@pytest.mark.testrail_id('836392')
def test_deploy_docker_mysql_wait_deploy_tomcat(environment, murano, session,
                                                docker, package):

    murano.create_service(environment, session, murano.mysql(docker))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 3306])
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.tomcat(docker))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 3306, 8080])


@pytest.mark.parametrize('package', [('DockerMariaDB', 'DockerTomcat')],
                         indirect=['package'])
@pytest.mark.testrail_id('836397')
def test_deploy_docker_tomcat_wait_deploy_mariadb(environment, murano, session,
                                                  docker, package):

    murano.create_service(environment, session, murano.tomcat(docker))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 8080])
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.mariadb(docker))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 8080, 3306])


@pytest.mark.parametrize('package', [('DockerGlassFish', 'DockerJenkins')],
                         indirect=['package'])
@pytest.mark.testrail_id('836388')
def test_deploy_docker_glassfish_wait_deploy_jenkins(environment, murano,
                                                     session, docker, package):

    murano.create_service(environment, session, murano.glassfish(docker))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 4848, 8080, 8181])
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.jenkins(docker))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 4848, 8080, 8181,
                                                        1025])


@pytest.mark.parametrize('package', [('DockerNginxSite', 'DockerCrate')],
                         indirect=['package'])
@pytest.mark.testrail_id('836393')
def test_deploy_docker_nginx_wait_deploy_crate(environment, murano, session,
                                               docker, package):

    murano.create_service(environment, session, murano.nginx_site(docker))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 80])
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.crate(docker))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 80, 4200, 4300])


@pytest.mark.parametrize('package', [('DockerPostgreSQL', 'DockerInfluxDB')],
                         indirect=['package'])
@pytest.mark.testrail_id('836395')
def test_deploy_docker_postgresql_wait_deploy_influxdb(murano, session, docker,
                                                       environment, package):

    murano.create_service(environment, session, murano.postgres(docker))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 5432])
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.influxdb(docker))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 5432, 8083, 8086])


@pytest.mark.parametrize('package', [('DockerMongoDB', 'DockerNginx')],
                         indirect=['package'])
@pytest.mark.testrail_id('836390')
def test_deploy_docker_mongodb_wait_deploy_nginx(environment, murano, session,
                                                 docker, package):

    murano.create_service(environment, session, murano.mongodb(docker))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 27017])
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.nginx(docker))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 27017, 80])
