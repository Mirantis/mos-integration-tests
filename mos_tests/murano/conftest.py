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

import functools
import pytest
import uuid


from mos_tests.functions import os_cli


flavor = 'm1.small'
linux_image = 'debian-8-m-agent.qcow2'
docker_image = 'debian-8-docker.qcow2'
kubernetes_image = 'ubuntu14.04-x64-kubernetes'
labels = "testkey=testvalue"


@pytest.yield_fixture
def controller_remote(env):
    with env.get_nodes_by_role('controller')[0].ssh() as remote:
        yield remote


@pytest.fixture
def openstack_client(controller_remote):
    return os_cli.OpenStack(controller_remote)


@pytest.yield_fixture
def environment(os_conn):
    environment = os_conn.murano.environments.create(
        {'name': os_conn.rand_name('MuranoEnv')})
    yield environment
    os_conn.murano.environments.delete(environment.id)


@pytest.yield_fixture
def session(os_conn, environment):
    session = os_conn.murano.sessions.configure(environment.id)
    yield session
    os_conn.murano.sessions.delete(environment.id, session.id)


@pytest.yield_fixture
def keypair(os_conn):
    keypair = os_conn.create_key(key_name='murano-key')
    yield keypair
    os_conn.delete_key(key_name=keypair.name)


@pytest.fixture
def murano_cli(controller_remote):
    return functools.partial(os_cli.Murano(controller_remote))


@pytest.fixture
def kubernetespod(murano_cli):
    fqn = 'io.murano.apps.docker.kubernetes.KubernetesPod'
    packages = murano_cli(
        'package-import',
        params='{0} --exists-action s'.format(fqn),
        flags='--murano-repo-url=http://storage.apps.openstack.org').listing()
    package = [x for x in packages if x['FQN'] == fqn][0]
    return package


@pytest.fixture
def grafana(murano_cli):
    fqn = 'io.murano.apps.docker.DockerGrafana'
    packages = murano_cli(
        'package-import',
        params='{0} --exists-action s'.format(fqn),
        flags='--murano-repo-url=http://storage.apps.openstack.org').listing()
    package = [x for x in packages if x['FQN'] == fqn][0]
    return package


@pytest.fixture
def docker_data(os_conn, keypair):
    body = {
        "instance": {
            "name": os_conn.rand_name("Docker"),
            "assignFloatingIp": True,
            "keyname": keypair.name,
            "flavor": flavor,
            "image": docker_image,
            "availabilityZone": 'nova',
            "?": {
                "type": "io.murano.resources.LinuxMuranoInstance",
                "id": str(uuid.uuid4())
            },
        },
        "name": "DockerVM",
        "?": {
            "_{id}".format(id=uuid.uuid4().hex): {
                "name": "Docker VM Service"
            },
            "type": "io.murano.apps.docker.DockerStandaloneHost",
            "id": str(uuid.uuid4())
        }
    }
    return body


@pytest.fixture
def cluster(os_conn, keypair, environment, session, request):
    initial_gateways, max_gateways, initial_nodes, max_nodes = \
        getattr(request, 'param', (1, 1, 1, 1))

    if max_gateways == 1:
        gateways_data = [
            {
                "instance": {
                    "name": "gateway-1",
                    "assignFloatingIp": True,
                    "keyname": keypair.name,
                    "flavor": flavor,
                    "image": kubernetes_image,
                    "availabilityZone": 'nova',
                    "?": {
                        "type": "io.murano.resources.LinuxMuranoInstance",
                        "id": str(uuid.uuid4())
                    }
                },
                "?": {
                    "type": "io.murano.apps.docker.kubernetes."
                            "KubernetesGatewayNode",
                    "id": str(uuid.uuid4())
                }
            }
        ]
    else:
        gateways_data = [
            {
                "instance": {
                    "name": "gateway-1",
                    "assignFloatingIp": True,
                    "keyname": keypair.name,
                    "flavor": flavor,
                    "image": kubernetes_image,
                    "availabilityZone": 'nova',
                    "?": {
                        "type": "io.murano.resources.LinuxMuranoInstance",
                        "id": str(uuid.uuid4())
                    }
                },
                "?": {
                    "type": "io.murano.apps.docker.kubernetes."
                            "KubernetesGatewayNode",
                    "id": str(uuid.uuid4())
                }
            },
            {
                "instance": {
                    "name": "gateway-2",
                    "assignFloatingIp": True,
                    "keyname": keypair.name,
                    "flavor": flavor,
                    "image": kubernetes_image,
                    "availabilityZone": 'nova',
                    "?": {
                        "type": "io.murano.resources.LinuxMuranoInstance",
                        "id": str(uuid.uuid4())
                    }
                },
                "?": {
                    "type": "io.murano.apps.docker.kubernetes."
                            "KubernetesGatewayNode",
                    "id": str(uuid.uuid4())
                }
            }
        ]
    if max_nodes == 1:
        nodes_data = [
            {
                "instance": {
                    "name": "minion-1",
                    "assignFloatingIp": True,
                    "keyname": keypair.name,
                    "flavor": flavor,
                    "image": kubernetes_image,
                    "availabilityZone": 'nova',
                    "?": {
                        "type": "io.murano.resources.LinuxMuranoInstance",
                        "id": str(uuid.uuid4())
                    }
                },
                "?": {
                    "type": "io.murano.apps.docker.kubernetes."
                            "KubernetesMinionNode",
                    "id": str(uuid.uuid4())
                },
                "exposeCAdvisor": True
            }
        ]
    else:
        nodes_data = [
            {
                "instance": {
                    "name": "minion-1",
                    "assignFloatingIp": True,
                    "keyname": keypair.name,
                    "flavor": flavor,
                    "image": kubernetes_image,
                    "availabilityZone": 'nova',
                    "?": {
                        "type": "io.murano.resources.LinuxMuranoInstance",
                        "id": str(uuid.uuid4())
                    }
                },
                "?": {
                    "type": "io.murano.apps.docker.kubernetes."
                            "KubernetesMinionNode",
                    "id": str(uuid.uuid4())
                },
                "exposeCAdvisor": True
            },
            {
                "instance": {
                    "name": "minion-2",
                    "assignFloatingIp": True,
                    "keyname": keypair.name,
                    "flavor": flavor,
                    "image": kubernetes_image,
                    "availabilityZone": 'nova',
                    "?": {
                        "type": "io.murano.resources.LinuxMuranoInstance",
                        "id": str(uuid.uuid4())
                    }
                },
                "?": {
                    "type": "io.murano.apps.docker.kubernetes."
                            "KubernetesMinionNode",
                    "id": str(uuid.uuid4())
                },
                "exposeCAdvisor": True
            }
        ]

    kub_data = {
        "gatewayCount": initial_gateways,
        "gatewayNodes": gateways_data,
        "?": {
            "_{id}".format(id=uuid.uuid4().hex): {
                "name": "Kubernetes Cluster"
            },
            "type": "io.murano.apps.docker.kubernetes.KubernetesCluster",
            "id": str(uuid.uuid4())
        },
        "nodeCount": initial_nodes,
        "dockerRegistry": "",
        "masterNode": {
            "instance": {
                "name": "master-1",
                "assignFloatingIp": True,
                "keyname": keypair.name,
                "flavor": flavor,
                "image": kubernetes_image,
                "availabilityZone": 'nova',
                "?": {
                    "type": "io.murano.resources.LinuxMuranoInstance",
                    "id": str(uuid.uuid4())
                }
            },
            "?": {
                "type": "io.murano.apps.docker.kubernetes."
                        "KubernetesMasterNode",
                "id": str(uuid.uuid4())
            }
        },
        "minionNodes": nodes_data,
        "name": "KubeClusterTest"
    }
    cluster = os_conn.create_service(environment, session, kub_data)
    return cluster


@pytest.fixture
def pod(os_conn, environment, session, cluster, request):
    replicas = getattr(request, 'param', 1)
    pod_data = {
        "kubernetesCluster": cluster,
        "labels": labels,
        "name": "testpod",
        "replicas": replicas,
        "?": {
            "_{id}".format(id=uuid.uuid4().hex): {
                "name": "Kubernetes Pod"
            },
            "type": "io.murano.apps.docker.kubernetes.KubernetesPod",
            "id": str(uuid.uuid4())
        }
    }
    pod = os_conn.create_service(environment, session, pod_data)
    return pod
