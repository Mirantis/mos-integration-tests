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
import yaml
import json
import time
import functools
import pytest
from mos_tests.functions import os_cli


from mos_tests.functions import common
from mos_tests import settings

flavor = 'm1.medium'
linux_image = 'debian-8-m-agent.qcow2'
docker_image = 'debian-8-docker.qcow2'
kubernetes_image = 'ubuntu14.04-x64-kubernetes'
labels = "testkey=testvalue"


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
def dockerhttpd(murano_cli):
    fqn = 'io.murano.apps.docker.DockerHTTPd'
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
def cluster(os_conn, keypair, environment, session):
    kub_data = {
        "gatewayCount": 1,
        "gatewayNodes": [
            {
                "instance": {
                    "name": os_conn.rand_name("gateway-1"),
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
                    "type": "io.murano.apps.docker.kubernetes.KubernetesGatewayNode",
                    "id": str(uuid.uuid4())
                }
            }
        ],
        "?": {
            "_{id}".format(id=uuid.uuid4().hex): {
                "name": "Kubernetes Cluster"
            },
            "type": "io.murano.apps.docker.kubernetes.KubernetesCluster",
            "id": str(uuid.uuid4())
        },
        "nodeCount": 1,
        "dockerRegistry": "",
        "masterNode": {
            "instance": {
                "name": os_conn.rand_name("master-1"),
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
                "type": "io.murano.apps.docker.kubernetes.KubernetesMasterNode",
                "id": str(uuid.uuid4())
            }
        },
        "minionNodes": [
            {
                "instance": {
                    "name": os_conn.rand_name("minion-1"),
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
                    "type": "io.murano.apps.docker.kubernetes.KubernetesMinionNode",
                    "id": str(uuid.uuid4())
                },
                "exposeCAdvisor": True
            }
        ],
        "name": os_conn.rand_name("KubeCluster")
    }
    cluster = os_conn.create_service(environment, session, kub_data)
    return cluster


@pytest.fixture
def pod(os_conn, environment, session, cluster):
    pod_data = {
        "kubernetesCluster": cluster,
        "labels": labels,
        "name": "testpod",
        "replicas": 2,
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


@pytest.mark.testrail_id('111111')
def test_kube(env, keypair,os_conn, environment, session, pod, kubernetespod, dockerhttpd):
    """
    Scenario:
        1.
        2.
        3.
        4.
    """
    post_body = {
        "host": pod,
        "image": 'httpd',
        "name": "HTTPd",
        "port": 80,
        "publish": True,
        "?": {
            "_{id}".format(id=uuid.uuid4().hex): {
                "name": "Docker HTTPd"
            },
            "type": "io.murano.apps.docker.DockerHTTPd",
            "id": str(uuid.uuid4())
        }
    }
    os_conn.create_service(environment, session, post_body)
    os_conn.deploy_environment(environment, session)

    # sec_group = [group for group in os_conn.nova.security_groups.list()
    #         if group.name == "default"][0]
    # self.os_conn.nova.security_group_rules.create(
    #     default_sec_group.id,
    #     ip_protocol='tcp',
    #     from_port=22,
    #     to_port=22,
    #     cidr='0.0.0.0/0')
    # self.os_conn.nova.security_group_rules.create(
    #     default_sec_group.id,
    #     ip_protocol='icmp',
    #     from_port=-1,
    #     to_port=-1,
    #     cidr='0.0.0.0/0')
    # self.os_conn.nova.security_group_rules.create(
    #     default_sec_group.id,
    #     ip_protocol='tcp',
    #     from_port=1,
    #     to_port=65535,
    #     cidr='0.0.0.0/0')
    # self.os_conn.nova.security_group_rules.create(
    #     default_sec_group.id,
    #     ip_protocol='udp',
    #     from_port=1,
    #     to_port=65535,
    #     cidr='0.0.0.0/0')
    instance = [i for i in os_conn.nova.servers.list() if 'minion' in i.name][0]
    sec_group = instance.list_security_group()[0]
    os_conn.nova.security_group_rules.create(
        sec_group.id,
        ip_protocol='icmp',
        from_port=-1,
        to_port=-1,
        cidr='0.0.0.0/0')
    os_conn.nova.security_group_rules.create(
        sec_group.id,
        ip_protocol='tcp',
        from_port=1,
        to_port=65535,
        cidr='0.0.0.0/0')
    os_conn.nova.security_group_rules.create(
        sec_group.id,
        ip_protocol='udp',
        from_port=1,
        to_port=65535,
        cidr='0.0.0.0/0')
    import pdb; pdb.set_trace()
    assert os_conn.is_server_ssh_ready(instance)
    with os_conn.ssh_to_instance(env, instance, vm_keypair=keypair,
                                 username='ubuntu') as remote:
        remote.check_call('uname')
        remote.check_call('sudo docker ps')