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


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerCrate', 'DockerNginxSite',
                                      'DockerGlassFish')],
                         indirect=['package'])
@pytest.mark.testrail_id('836440')
def test_k8s_deploy_crate_nginxsite_glassfish(environment, murano, session,
                                              cluster, pod, package):
    murano.create_service(environment, session, murano.crate(pod))
    murano.create_service(environment, session, murano.nginx_site(pod))
    murano.create_service(environment, session, murano.glassfish(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 4200, 80, 4848, 8080],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerCrate', 'DockerNginx',
                                      'DockerMongoDB')], indirect=['package'])
@pytest.mark.testrail_id('836441')
def test_k8s_deploy_crate_nginx_mongodb(environment, murano, session, cluster,
                                        pod, package):
    murano.create_service(environment, session, murano.crate(pod))
    murano.create_service(environment, session, murano.nginx(pod))
    murano.create_service(environment, session, murano.mongodb(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 4200, 4300, 80, 27017],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerMariaDB', 'DockerPostgreSQL',
                                      'DockerMongoDB')], indirect=['package'])
@pytest.mark.testrail_id('836442')
def test_k8s_deploy_mariadb_postgresql_mongodb(environment, murano, session,
                                               cluster, pod, package):
    murano.create_service(environment, session, murano.mariadb(pod))
    murano.create_service(environment, session, murano.postgres(pod))
    murano.create_service(environment, session, murano.mongodb(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 3306, 5432, 27017],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerRedis', 'DockerTomcat',
                                      'DockerInfluxDB')], indirect=['package'])
@pytest.mark.testrail_id('836444')
def test_k8s_deploy_redis_tomcat_influxdb(environment, murano, session,
                                          cluster, pod, package):
    murano.create_service(environment, session, murano.redis(pod))
    murano.create_service(environment, session, murano.tomcat(pod))
    murano.create_service(environment, session, murano.influxdb(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 6379, 8080, 8083,
                          8086],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerNginxSite', 'DockerMySQL',
                                      'DockerRedis')], indirect=['package'])
@pytest.mark.testrail_id('836445')
def test_k8s_deploy_mysql_nginxsite_redis(environment, murano, session,
                                          cluster, pod, package):
    murano.create_service(environment, session, murano.nginx_site(pod))
    murano.create_service(environment, session, murano.mysql(pod))
    murano.create_service(environment, session, murano.redis(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 3306, 80, 6379],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerMySQL', 'DockerTomcat')],
                         indirect=['package'])
@pytest.mark.testrail_id('836447')
def test_k8s_deploy_mysql_wait_deploy_tomcat(environment, murano, session,
                                             cluster, pod, package):

    murano.create_service(environment, session, murano.mysql(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 3306],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.tomcat(pod))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 3306, 8080],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerMariaDB', 'DockerTomcat')],
                         indirect=['package'])
@pytest.mark.testrail_id('836449')
def test_k8s_deploy_tomcat_wait_deploy_mariadb(environment, murano, session,
                                               cluster, pod, package):

    murano.create_service(environment, session, murano.tomcat(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8080],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.mariadb(pod))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 3306, 8080],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerNginx', 'DockerCrate')],
                         indirect=['package'])
@pytest.mark.testrail_id('836451')
def test_k8s_deploy_nginx_wait_deploy_crate(environment, murano, session,
                                            cluster, pod, package):
    murano.create_service(environment, session, murano.nginx(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.crate(pod))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80, 4200],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerPostgreSQL', 'DockerInfluxDB')],
                         indirect=['package'])
@pytest.mark.testrail_id('836452')
def test_k8s_deploy_postgresql_wait_deploy_influxdb(environment, murano, pod,
                                                    cluster, session, package):
    murano.create_service(environment, session, murano.postgres(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 5432],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.influxdb(pod))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 5432, 8083, 8086],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerMongoDB', 'DockerNginx')],
                         indirect=['package'])
@pytest.mark.testrail_id('836453')
def test_k8s_deploy_mongodb_wait_deploy_nginx(environment, murano, pod,
                                                  cluster, session, package):
    murano.create_service(environment, session, murano.mongodb(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 27017],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    session = murano.create_session(deployed_environment)

    murano.create_service(environment, session, murano.nginx(pod))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80, 27017],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerNginx', 'DockerHTTPd')],
                         indirect=['package'])
@pytest.mark.testrail_id('836446')
def test_k8s_deploy_nginx_wait_deploy_httpd_multipod(
        environment, murano, session, cluster, pod, package):
    murano.create_service(environment, session, murano.nginx(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    session = murano.create_session(deployed_environment)
    pod_2 = murano.create_service(environment, session, murano.pod(cluster, 1))
    murano.create_service(environment, session, murano.httpd(pod_2))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80, 1025],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerGlassFish', 'DockerJenkins')],
                         indirect=['package'])
@pytest.mark.testrail_id('836450')
def test_k8s_deploy_glassfish_wait_deploy_jenkins_multipod(
        environment, murano, session, cluster, pod, package):
    murano.create_service(environment, session, murano.glassfish(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 4848, 8080],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    session = murano.create_session(deployed_environment)
    pod_2 = murano.create_service(environment, session, murano.pod(cluster, 1))
    murano.create_service(environment, session, murano.jenkins(pod_2))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 4848, 8080, 1025],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerNginx', 'DockerCrate')],
                         indirect=['package'])
@pytest.mark.testrail_id('836454')
def test_k8s_deploy_crate_after_nginx_removal(environment, murano, session,
                                              cluster, pod, package):
    nginx = murano.create_service(environment, session, murano.nginx(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    session = murano.create_session(deployed_environment)
    murano.delete_service(environment, session, nginx)

    murano.create_service(environment, session, murano.crate(pod))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 4200],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "gateway-1", 80]],
                        kubernetes=True, negative=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.testrail_id('836455')
def test_k8s_redeploy_influxdb_with_another_parameters(
        environment, murano, session, cluster, pod, package):
    influx = murano.create_service(environment, session, murano.influxdb(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083, 8086],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    session = murano.create_session(deployed_environment)
    murano.delete_service(environment, session, influx)
    murano.create_service(environment, session, murano.influxdb(
        pod, name='InfluxNew', db='db_1;db_2'))
    murano.deploy_environment(deployed_environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083, 8086],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
