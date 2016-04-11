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

from mos_tests.functions.common import wait


@pytest.mark.parametrize('cluster', [{'initial_gateways': 1, 'max_gateways': 2,
                                     'initial_nodes': 2, 'max_nodes': 2}],
                         indirect=['cluster'])
@pytest.mark.testrail_id('836658')
def test_kub_node_down(environment, murano, session, cluster, grafana, influx):
    """Check ScaleNodesDown action for Kubernetes Cluster
    Scenario:
        1. Create Murano environment
        2. Add Kubernetes Cluster application to the environment: Set
        initial_gateways=1, max_gateways=2, initial_nodes=2, max_nodes=2
        3. Add Kubernetes Pod to the environment
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Execute ScaleNodesDown action
        8. Check deployment status and make sure that all nodes are active
        9. Delete Murano environment
    """
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instance(gateways_count=1, nodes_count=2)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083],
                         [cluster['name'], "minion-1", 4194],
                         [cluster['name'], "minion-2", 4194]
                         ],
                        kubernetes=True)

    action_id = murano.get_action_id(
        deployed_environment, 'scaleNodesDown', 0)
    deployed_environment = murano.run_action(deployed_environment, action_id)
    murano.check_instance(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.parametrize('cluster', [{'initial_gateways': 1, 'max_gateways': 2,
                                     'initial_nodes': 1, 'max_nodes': 2}],
                         indirect=['cluster'])
@pytest.mark.testrail_id('836657')
def test_kub_nodes_up(murano, environment, session, cluster, grafana, influx):
    """Check ScaleNodesUp action for Kubernetes Cluster
    Scenario:
        1. Create Murano environment
        2. Add Kubernetes Cluster application to the environment: Set
        initial_gateways=1, max_gateways=2, initial_nodes=1, max_nodes=2
        3. Add Kubernetes Pod to the environment
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Execute ScaleNodesUp action
        8. Check deployment status and make sure that all nodes are active
        9. Delete Murano environment
    """
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instance(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    action_id = murano.get_action_id(deployed_environment, 'scaleNodesUp', 0)
    deployed_environment = murano.run_action(deployed_environment, action_id)
    murano.check_instance(gateways_count=1, nodes_count=2)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083],
                         [cluster['name'], "minion-1", 4194],
                         [cluster['name'], "minion-2", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.parametrize('cluster', [{'initial_gateways': 2, 'max_gateways': 2,
                                     'initial_nodes': 1, 'max_nodes': 2}],
                         indirect=['cluster'])
@pytest.mark.testrail_id('836662')
def test_kub_gateway_down(murano, environment, session, cluster, grafana,
                          influx):
    """Check ScaleGatewaysDown action for Kubernetes Cluster
    Scenario:
        1. Create Murano environment
        2. Add Kubernetes Cluster application to the environment: Set
        initial_gateways=2, max_gateways=2, initial_nodes=1, max_nodes=2
        3. Add Kubernetes Pod to the environment
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Execute scaleGatewaysDown action
        8. Check deployment status and make sure that all nodes are active
        9. Delete Murano environment
    """
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instance(gateways_count=2, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083],
                         [cluster['name'], "gateway-2", 8083],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)

    action_id = murano.get_action_id(deployed_environment, 'scaleGatewaysDown',
                                     0)
    deployed_environment = murano.run_action(deployed_environment, action_id)
    murano.check_instance(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.parametrize('cluster', [{'initial_gateways': 1, 'max_gateways': 2,
                                     'initial_nodes': 1, 'max_nodes': 2}],
                         indirect=['cluster'])
@pytest.mark.testrail_id('836659')
def test_kub_gateway_up(murano, environment, session, cluster, grafana,
                        influx):
    """Check ScaleGatewaysUp action for Kubernetes Cluster
    Scenario:
        1. Create Murano environment
        2. Add Kubernetes Cluster application to the environment: Set
        initial_gateways=1, max_gateways=2, initial_nodes=1, max_nodes=2
        3. Add Kubernetes Pod to the environment
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Execute scaleGatewaysUp action
        8. Check deployment status and make sure that all nodes are active
        9. Delete Murano environment
    """
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instance(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    action_id = murano.get_action_id(deployed_environment, 'scaleGatewaysUp',
                                     0)
    deployed_environment = murano.run_action(deployed_environment, action_id)
    murano.check_instance(gateways_count=2, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083],
                         [cluster['name'], "gateway-2", 8083],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.testrail_id('836665')
def test_kub_nodes_up_if_limit_reached(murano, environment, session, cluster,
                                       grafana, influx):
    """Check ScaleNodesUp and scaleGatewaysUp actions for Kubernetes Cluster
    if maximum nodes limit is already reached
    Scenario:
        1. Create Murano environment
        2. Add Kubernetes Cluster application to the environment: Set
        initial_gateways=1, max_gateways=1, initial_nodes=1, max_nodes=1
        3. Add Kubernetes Pod to the environment
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Execute scaleNodesUp action
        8. Check error message
        9. Execute scaleGatewaysUp action
        10. Check error message
        11. Delete Murano environment
    """
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instance(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    action_id = murano.get_action_id(
        deployed_environment, 'scaleNodesUp', 0)
    deployed_environment = murano.run_action(deployed_environment, action_id)
    murano.check_instance(gateways_count=1, nodes_count=1)
    logs = murano.get_log(deployed_environment)
    assert 'Action scaleNodesUp is scheduled' in logs
    assert 'The maximum number of nodes has been reached' in logs
    murano.check_instance(gateways_count=1, nodes_count=1)
    action_id = murano.get_action_id(
        deployed_environment, 'scaleGatewaysUp', 0)
    deployed_environment = murano.run_action(deployed_environment, action_id)
    murano.check_instance(gateways_count=1, nodes_count=1)
    logs = murano.get_log(deployed_environment)
    assert 'Action scaleGatewaysUp is scheduled' in logs
    assert 'The maximum number of gateway nodes has been reached' in logs


@pytest.mark.parametrize('pod', '2', indirect=['pod'])
@pytest.mark.testrail_id('836661')
def test_pod_replication(env, os_conn, keypair, murano, environment, session,
                         cluster, pod, dockerhttpd):
    """Check that replication controller works correctly
    Scenario:
        1. Create Murano environment
        2. Add Kubernetes Cluster application to the environment: Set
        initial_gateways=1, max_gateways=1, initial_nodes=1, max_nodes=1
        3. Add Kubernetes Pod to the environment
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Go to minion node and check count of pod's replicas
        8. Kill one replica
        9. Wait for new pod's replica creation. Check that id of newly created
        replica differs from id of removed replica
        10. Remove environment
    """
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instance(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80],
                         [cluster['name'], "minion-1", 4194]], kubernetes=True)
    srv = [i for i in os_conn.nova.servers.list() if 'minion' in i.name][0]
    with os_conn.ssh_to_instance(env, srv, vm_keypair=keypair,
                                 username='ubuntu') as remote:
        def get_pods():
            return remote.check_call('sudo docker ps | grep httpd')['stdout']
        res = get_pods()
        assert len(res) == 2, "{0} replicas instead of {1}".format(len(res), 2)
        pod_id = [p.split(' ')[0] for p in res][0]
        remote.check_call('sudo docker kill {0}'.format(pod_id))
        wait(lambda: len(get_pods()) == 2, timeout_seconds=120,
             waiting_for="pod to be recreated")
        new_ids = [p.split(' ')[0] for p in get_pods()]
        assert new_ids.count(pod_id) == 0, \
            "No new pod's replica added, {0} still in the list".format(pod_id)


@pytest.mark.parametrize('pod', '2', indirect=['pod'])
@pytest.mark.testrail_id('836663', params={'action': 'Up'})
@pytest.mark.testrail_id('836664', params={'action': 'Down'})
@pytest.mark.parametrize('action', ['Up', 'Down'])
def test_pod_action_up_down(env, action, os_conn, keypair, murano, environment,
                            session, cluster, pod, dockerhttpd):
    """Check "scalePodUp" & "scalePodDown" actions
    Scenario:
        1. Create Murano environment
        2. Add Kubernetes Cluster application to the environment: Set
        initial_gateways=1, max_gateways=1, initial_nodes=1, max_nodes=1
        3. Add Kubernetes Pod to the environment with replica=2
        4. Add some application to the environment
        5. Deploy environment
        6. Check deployment status and make sure that all nodes are active
        7. Go to minion node and check count of pod's replicas (2 replicas are
        expected)
        8. Perform "scalePodUp" or "scalePodDown" action
        9. Check that count of replicas is correct (3 after "scalePodUp" and 1
        after "scalePodDown" action accordingly)
        10. Remove environment
    """
    deployed_environment = murano.deploy_environment(environment, session)
    murano.check_instance(gateways_count=1, nodes_count=1)
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80],
                         [cluster['name'], "minion-1", 4194]], kubernetes=True)

    srv = [i for i in os_conn.nova.servers.list() if 'minion' in i.name][0]
    with os_conn.ssh_to_instance(env, srv, vm_keypair=keypair,
                                 username='ubuntu') as remote:
        res = remote.check_call('sudo docker ps | grep httpd')['stdout']
        assert len(res) == 2, "{0} replicas instead of {1}".format(len(res), 2)

    action_id = murano.get_action_id(deployed_environment,
                                     'scalePod{0}'.format(action), 1)
    murano.run_action(deployed_environment, action_id)

    with os_conn.ssh_to_instance(env, srv, vm_keypair=keypair,
                                 username='ubuntu') as remote:
        res = remote.check_call('sudo docker ps | grep httpd')['stdout']
        if action == 'Up':
            assert len(res) == 3, "{0} replicas instead of {1}".format(
                len(res), 3)
        elif action == 'Down':
            assert len(res) == 1, "{0} replicas instead of {1}".format(
                len(res), 1)
