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
@pytest.mark.testrail_id('836463')
def test_deploy_k8s_influxdb(environment, murano, session, cluster, pod):

    murano.create_service(environment, session, murano.influxdb(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083, 8086],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.testrail_id('836471')
def test_deploy_k8s_grafana(environment, murano, session, cluster, pod):

    influx_service = murano.create_service(environment, session,
                                           murano.influxdb(pod))
    murano.create_service(environment, session,
                          murano.grafana(pod, influx_service))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083, 8086, 80],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerMongoDB',)], indirect=['package'])
@pytest.mark.testrail_id('836467')
def test_deploy_k8s_mongodb(environment, murano, session, cluster, pod,
                               package):

    murano.create_service(environment, session, murano.mongodb(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 27017],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerNginx',)], indirect=['package'])
@pytest.mark.testrail_id('836468')
def test_deploy_k8s_nginx(environment, murano, session, cluster, pod, package):

    murano.create_service(environment, session, murano.nginx(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerGlassFish',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836461')
def test_deploy_k8s_glassfish(environment, murano, session, cluster, pod,
                              package):

    murano.create_service(environment, session, murano.glassfish(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 4848, 8080],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerMariaDB',)], indirect=['package'])
@pytest.mark.testrail_id('836466')
def test_deploy_k8s_mariadb(environment, murano, session, cluster, pod,
                            package):

    murano.create_service(environment, session, murano.mariadb(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 3306],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerMySQL',)], indirect=['package'])
@pytest.mark.testrail_id('836460')
def test_deploy_k8s_mysql(environment, murano, session, cluster, pod, package):

    murano.create_service(environment, session, murano.mysql(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 3306],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerJenkins',)], indirect=['package'])
@pytest.mark.testrail_id('836464')
def test_deploy_k8s_jenkins(environment, murano, session, cluster, pod,
                            package):

    murano.create_service(environment, session, murano.jenkins(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8080],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerPostgreSQL',)],
                         indirect=['package'])
@pytest.mark.testrail_id('836469')
def test_deploy_k8s_postgresql(environment, murano, session, cluster, pod,
                               package):

    murano.create_service(environment, session, murano.postgres(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 5432],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerCrate',)], indirect=['package'])
@pytest.mark.testrail_id('836459')
def test_deploy_k8s_crate(environment, murano, session, cluster, pod, package):

    murano.create_service(environment, session, murano.crate(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 4200],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerRedis',)], indirect=['package'])
@pytest.mark.testrail_id('836470')
def test_deploy_k8s_redis(environment, murano, session, cluster, pod, package):

    murano.create_service(environment, session, murano.redis(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 6379],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerTomcat',)], indirect=['package'])
@pytest.mark.testrail_id('836465')
def test_deploy_k8s_tomcat(environment, murano, session, cluster, pod,
                           package):

    murano.create_service(environment, session, murano.tomcat(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8080],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerHTTPd',)], indirect=['package'])
@pytest.mark.testrail_id('836462')
def test_deploy_k8s_httpd(environment, murano, session, cluster, pod, package):

    murano.create_service(environment, session, murano.httpd(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerHTTPdSite',)],
                         indirect=['package'])
@pytest.mark.testrail_id('843445')
def test_deploy_k8s_httpd_site(environment, murano, session, cluster, pod,
                               package):

    murano.create_service(environment, session, murano.httpd_site(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerNginxSite',)],
                         indirect=['package'])
@pytest.mark.testrail_id('843446')
def test_deploy_k8s_nginx_site(environment, murano, session, cluster, pod,
                               package):

    murano.create_service(environment, session, murano.nginx_site(pod))
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instances(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
