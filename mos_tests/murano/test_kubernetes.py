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
import uuid


@pytest.mark.parametrize('cluster', [(1, 2, 1, 2)], indirect=['cluster'])
@pytest.mark.testrail_id('543014')
def test_kub_scale_up(os_conn, environment, session, grafana, cluster, pod):
    """Check ScaleNodesUp action for Kubernetes Cluster
    Scenario:
        1. Create environment
        2. Add Kubernetes Cluster application to the environment
        3. Add Kubernetes Pod to the environment
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Execute ScaleNodesUp action
        8. Check deployment status and make sure that all nodes are active
    """
    post_body = {
        "host": pod,
        "name": "Influx",
        "preCreateDB": 'db1;db2',
        "publish": True,
        "?": {
            "_{id}".format(id=uuid.uuid4().hex): {
                "name": "Docker InfluxDB"
            },
            "type": "io.murano.apps.docker.DockerInfluxDB",
            "id": str(uuid.uuid4())
        }
    }
    os_conn.create_service(environment, session, post_body)
    deployed_environment = os_conn.deploy_environment(environment, session)
    instance_list = os_conn.nova.servers.list()
    os_conn.check_instance(instance_list, gateways_count=1, nodes_count=1)
    os_conn.status_check(deployed_environment,
                         [[cluster['name'], "master-1", 8080],
                          [cluster['name'], "gateway-1", 8083],
                          [cluster['name'], "minion-1", 4194]
                          ],
                         kubernetes=True)
    action_id = os_conn.get_action_id(deployed_environment, 'scaleNodesUp', 0)
    deployed_environment = os_conn.run_action(deployed_environment, action_id)
    instance_list = os_conn.nova.servers.list()
    os_conn.check_instance(instance_list, gateways_count=1, nodes_count=2)
    os_conn.status_check(deployed_environment,
                         [[cluster['name'], "master-1", 8080],
                          [cluster['name'], "gateway-1", 8083],
                          [cluster['name'], "minion-1", 4194],
                          [cluster['name'], "minion-2", 4194]
                          ],
                         kubernetes=True)


@pytest.mark.parametrize('cluster', [(1, 2, 2, 2)], indirect=['cluster'])
@pytest.mark.testrail_id('543015')
def test_kub_scale_down(os_conn, environment, session, grafana, cluster, pod):
    """Check ScaleNodesDown action for Kubernetes Cluster
    Scenario:
        1. Create environment
        2. Add Kubernetes Cluster application to the environment
        3. Add Kubernetes Pod to the environment
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Execute ScaleNodesDown action
        8. Check deployment status and make sure that all nodes are active
    """
    post_body = {
        "host": pod,
        "name": "Influx",
        "preCreateDB": 'db1;db2',
        "publish": True,
        "?": {
            "_{id}".format(id=uuid.uuid4().hex): {
                "name": "Docker InfluxDB"
            },
            "type": "io.murano.apps.docker.DockerInfluxDB",
            "id": str(uuid.uuid4())
        }
    }
    os_conn.create_service(environment, session, post_body)
    deployed_environment = os_conn.deploy_environment(environment, session)
    instance_list = os_conn.nova.servers.list()
    os_conn.check_instance(instance_list, gateways_count=1, nodes_count=2)
    os_conn.status_check(deployed_environment,
                         [[cluster['name'], "master-1", 8080],
                          [cluster['name'], "gateway-1", 8083],
                          [cluster['name'], "minion-1", 4194],
                          [cluster['name'], "minion-2", 4194]
                          ],
                         kubernetes=True)

    action_id = os_conn.get_action_id(
        deployed_environment, 'scaleNodesDown', 0)
    deployed_environment = os_conn.run_action(deployed_environment, action_id)
    instance_list = os_conn.nova.servers.list()
    os_conn.check_instance(instance_list, gateways_count=1, nodes_count=1)
    os_conn.status_check(deployed_environment,
                         [[cluster['name'], "master-1", 8080],
                          [cluster['name'], "gateway-1", 8083],
                          [cluster['name'], "minion-1", 4194]
                          ],
                         kubernetes=True)


@pytest.mark.parametrize('cluster', [(1, 2, 1, 2)], indirect=['cluster'])
@pytest.mark.testrail_id('543016')
def test_kub_gateway_up(os_conn, environment, session, grafana, cluster, pod):
    """Check ScaleGatewaysUp action for Kubernetes Cluster
    Scenario:
        1. Create environment
        2. Add Kubernetes Cluster application to the environment
        3. Add Kubernetes Pod to the environment
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Execute scaleGatewaysUp action
        8. Check deployment status and make sure that all nodes are active
    """
    post_body = {
        "host": pod,
        "name": "Influx",
        "preCreateDB": 'db1;db2',
        "publish": True,
        "?": {
            "_{id}".format(id=uuid.uuid4().hex): {
                "name": "Docker InfluxDB"
            },
            "type": "io.murano.apps.docker.DockerInfluxDB",
            "id": str(uuid.uuid4())
        }
    }
    os_conn.create_service(environment, session, post_body)
    deployed_environment = os_conn.deploy_environment(environment, session)
    instance_list = os_conn.nova.servers.list()
    os_conn.check_instance(instance_list, gateways_count=1, nodes_count=1)
    os_conn.status_check(deployed_environment,
                         [[cluster['name'], "master-1", 8080],
                          [cluster['name'], "gateway-1", 8083],
                          [cluster['name'], "minion-1", 4194]
                          ],
                         kubernetes=True)
    action_id = os_conn.get_action_id(deployed_environment, 'scaleGatewaysUp',
                                      0)
    deployed_environment = os_conn.run_action(deployed_environment, action_id)
    instance_list = os_conn.nova.servers.list()
    os_conn.check_instance(instance_list, gateways_count=2, nodes_count=1)
    os_conn.status_check(deployed_environment,
                         [[cluster['name'], "master-1", 8080],
                          [cluster['name'], "gateway-1", 8083],
                          [cluster['name'], "gateway-2", 8083],
                          [cluster['name'], "minion-1", 4194]
                          ],
                         kubernetes=True)


@pytest.mark.parametrize('cluster', [(2, 2, 1, 2)], indirect=['cluster'])
@pytest.mark.testrail_id('638363')
def test_kub_gateway_down(os_conn, environment, session, grafana, cluster,
                          pod):
    """Check ScaleGatewaysDown action for Kubernetes Cluster
    Scenario:
        1. Create environment
        2. Add Kubernetes Cluster application to the environment
        3. Add Kubernetes Pod to the environment
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Execute scaleGatewaysDown action
        8. Check deployment status and make sure that all nodes are active
    """
    post_body = {
        "host": pod,
        "name": "Influx",
        "preCreateDB": 'db1;db2',
        "publish": True,
        "?": {
            "_{id}".format(id=uuid.uuid4().hex): {
                "name": "Docker InfluxDB"
            },
            "type": "io.murano.apps.docker.DockerInfluxDB",
            "id": str(uuid.uuid4())
        }
    }
    os_conn.create_service(environment, session, post_body)
    deployed_environment = os_conn.deploy_environment(environment, session)
    instance_list = os_conn.nova.servers.list()
    os_conn.check_instance(instance_list, gateways_count=2, nodes_count=1)
    os_conn.status_check(deployed_environment,
                         [[cluster['name'], "master-1", 8080],
                          [cluster['name'], "gateway-1", 8083],
                          [cluster['name'], "gateway-2", 8083],
                          [cluster['name'], "minion-1", 4194]
                          ],
                         kubernetes=True)

    action_id = os_conn.get_action_id(
        deployed_environment, 'scaleGatewaysDown', 0)
    deployed_environment = os_conn.run_action(deployed_environment, action_id)
    instance_list = os_conn.nova.servers.list()
    os_conn.check_instance(instance_list, gateways_count=1, nodes_count=1)
    os_conn.status_check(deployed_environment,
                         [[cluster['name'], "master-1", 8080],
                          [cluster['name'], "gateway-1", 8083],
                          [cluster['name'], "minion-1", 4194]
                          ],
                         kubernetes=True)
