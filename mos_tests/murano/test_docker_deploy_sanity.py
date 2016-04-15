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


@pytest.mark.testrail_id('836410')
def test_deploy_docker_influx(environment, murano, session, docker):

    murano.create_service(environment, session, murano.influxdb(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 8083, 8086])


@pytest.mark.testrail_id('836437')
def test_deploy_docker_grafana(environment, murano, session, docker):

    influx_service = murano.create_service(environment, session,
                                           murano.influxdb(docker))
    murano.create_service(environment, session,
                          murano.grafana(docker, influx_service))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 8083, 8086, 80])


@pytest.mark.parametrize('package', [('DockerMongoDB',)], indirect=['package'])
@pytest.mark.testrail_id('836419')
def test_deploy_docker_mongodb(environment, murano, session, docker, package):

    murano.create_service(environment, session, murano.mongodb(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 27017])


@pytest.mark.parametrize('package', [('DockerNginx',)], indirect=['package'])
@pytest.mark.testrail_id('836422')
def test_deploy_docker_nginx(environment, murano, session, docker, package):

    murano.create_service(environment, session, murano.nginx(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 80])


@pytest.mark.parametrize('package', [('DockerGlassFish',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836404')
def test_deploy_docker_glassfish(environment, murano, session, docker,
                                 package):

    murano.create_service(environment, session, murano.glassfish(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 4848, 8080, 8181])


@pytest.mark.parametrize('package', [('DockerMariaDB',)], indirect=['package'])
@pytest.mark.testrail_id('836416')
def test_deploy_docker_mariadb(environment, murano, session, docker, package):

    murano.create_service(environment, session, murano.mariadb(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 3306])


@pytest.mark.parametrize('package', [('DockerMySQL',)], indirect=['package'])
@pytest.mark.testrail_id('836401')
def test_deploy_docker_mysql(environment, murano, session, docker, package):

    murano.create_service(environment, session, murano.mysql(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 3306])


@pytest.mark.parametrize('package', [('DockerJenkins',)], indirect=['package'])
@pytest.mark.testrail_id('836413')
def test_deploy_docker_jenkins(environment, murano, session, docker, package):

    murano.create_service(environment, session, murano.jenkins(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 8080])


@pytest.mark.parametrize('package', [('DockerPostgreSQL',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836428')
def test_deploy_docker_postgres(environment, murano, session, docker, package):

    murano.create_service(environment, session, murano.postgres(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 5432])


@pytest.mark.parametrize('package', [('DockerCrate',)], indirect=['package'])
@pytest.mark.testrail_id('836398')
def test_deploy_docker_crate(environment, murano, session, docker, package):

    murano.create_service(environment, session, murano.crate(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 4200, 4300])


@pytest.mark.parametrize('package', [('DockerRedis',)], indirect=['package'])
@pytest.mark.testrail_id('836431')
def test_deploy_docker_redis(environment, murano, session, docker, package):

    murano.create_service(environment, session, murano.redis(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 6379])


@pytest.mark.parametrize('package', [('DockerTomcat',)], indirect=['package'])
@pytest.mark.testrail_id('836434')
def test_deploy_docker_tomcat(environment, murano, session, docker, package):

    murano.create_service(environment, session, murano.tomcat(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 8080])


@pytest.mark.parametrize('package', [('DockerHTTPd',)], indirect=['package'])
@pytest.mark.testrail_id('836407')
def test_deploy_docker_httpd(environment, murano, session, docker, package):

    murano.create_service(environment, session, murano.httpd(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 80])


@pytest.mark.parametrize('package', [('DockerHTTPdSite',)],
                         indirect=['package'])
@pytest.mark.testrail_id('843444')
def test_deploy_docker_httpd_site(environment, murano, session, docker,
                                  package):

    murano.create_service(environment, session, murano.httpd_site(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 80])


@pytest.mark.parametrize('package', [('DockerNginxSite',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836425')
def test_deploy_docker_nginx_site(environment, murano, session, docker,
                                  package):

    murano.create_service(environment, session, murano.nginx_site(docker))
    murano.deploy_environment(environment, session)
    murano.check_instances(docker_count=1)
    murano.deployment_success_check(environment, ports=[22, 80])
