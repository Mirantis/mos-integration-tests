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

import random
import socket
import telnetlib
import uuid

from mos_tests.functions.common import wait
from muranoclient.v1.client import Client as MuranoClient


class MuranoActions(object):
    """Murano-specific actions"""

    def __init__(self, os_conn):
        self.os_conn = os_conn
        self.murano_endpoint = os_conn.session.get_endpoint(
            service_type='application-catalog', endpoint_type='publicURL')
        self.murano = MuranoClient(endpoint=self.murano_endpoint,
                                   token=os_conn.session.get_token(),
                                   cacert=os_conn.path_to_cert)

    def rand_name(self, name):
        return name + '_' + str(random.randint(1, 0x7fffffff))

    def create_service(self, environment, session, json_data):
        service = self.murano.services.post(
            environment.id, path='/', data=json_data, session_id=session.id)
        return service.to_dict()

    def delete_service(self, environment, session, service):
        self.murano.services.delete(
            environment.id, path='/{0}'.format(service['?']['id']),
            session_id=session.id)

    def wait_for_deploy(self, environment):
        def is_murano_env_deployed():
            status = self.murano.environments.get(environment.id).status
            if status == 'deploy failure':
                raise Exception('Environment deploy finished with errors')
            return status == 'ready'
        wait(is_murano_env_deployed, timeout_seconds=1200,
             waiting_for='environment is ready')

        environment = self.murano.environments.get(environment.id)
        logs = self.get_log(environment)
        assert 'Deployment finished' in logs
        return environment

    def deploy_environment(self, environment, session):
        self.murano.sessions.deploy(environment.id, session.id)
        return self.wait_for_deploy(environment)

    def get_action_id(self, environment, name, service):
        env_data = environment.to_dict()
        a_dict = env_data['services'][service]['?']['_actions']
        for action_id, action in a_dict.items():
            if action['name'] == name:
                return action_id

    def run_action(self, environment, action_id):
        self.murano.actions.call(environment.id, action_id)
        return self.wait_for_deploy(environment)

    def status_check(self, environment, configurations, kubernetes=False,
                     negative=False):
        for configuration in configurations:
            if kubernetes:
                service_name = configuration[0]
                inst_name = configuration[1]
                ports = configuration[2:]
                ip = self.get_k8s_ip_by_instance_name(environment, inst_name,
                                                      service_name)
                if ip:
                    for port in ports:
                        assert self.check_port_access(ip, port, negative)
                        assert self.check_k8s_deployment(ip, port, negative)
                else:
                    raise Exception("Instance {} doesn't have floating IP"
                                    .format(inst_name))
            else:
                inst_name = configuration[0]
                ports = configuration[1:]
                ip = self.get_ip_by_instance_name(environment, inst_name)
                if ip and ports:
                    for port in ports:
                        assert self.check_port_access(ip, port)
                else:
                    raise Exception("Instance {} doesn't have floating IP"
                                    .format(inst_name))

    def check_port_access(self, ip, port, negative=False):
        def is_port_accessible():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex((str(ip), port))
            sock.close()
            return result == 0

        return wait(lambda: not negative == is_port_accessible(),
                    timeout_seconds=300, waiting_for='port access check')

    def check_k8s_deployment(self, ip, port, negative=False):
        def is_link_accessible():
            try:
                tn = telnetlib.Telnet(ip, port)
                tn.write('GET / HTTP/1.0\n\n')
                buf = tn.read_all()
                if len(buf) != 0:
                    tn.sock.sendall(telnetlib.IAC + telnetlib.NOP)
                    return True
            except socket.error:
                    return False
            return False

        return wait(lambda: not negative == is_link_accessible(),
                    timeout_seconds=300,
                    waiting_for='kubernetes access check')

    def get_k8s_ip_by_instance_name(self, environment, inst_name,
                                    service_name):
        for service in environment.services:
            if service_name in service['name']:
                if "gateway" in inst_name:
                    for gateway in service['gatewayNodes']:
                        if inst_name in gateway['instance']['name']:
                            return gateway['instance']['floatingIpAddress']
                elif "master" in inst_name:
                    return service['masterNode']['instance'][
                        'floatingIpAddress']
                elif "minion" in inst_name:
                    for minion in service['minionNodes']:
                        if inst_name in minion['instance']['name']:
                            return minion['instance']['floatingIpAddress']

    def get_ip_by_instance_name(self, environment, inst_name):
        for service in environment.services:
            if inst_name in service['instance']['name']:
                return service['instance']['floatingIpAddress']

    def get_environment(self, environment):
        return self.murano.environments.get(environment.id)

    def check_instances(self, gateways_count=0, nodes_count=0, docker_count=0):
        instance_list = self.os_conn.nova.servers.list()
        names = []
        if gateways_count and nodes_count:
            names.append("master-1")
            for i in range(gateways_count):
                names.append("gateway-{}".format(i + 1))
            for i in range(nodes_count):
                names.append("minion-{}".format(i + 1))
        if docker_count:
            names.append("Docker")
        count = 0
        for instance in instance_list:
            for name in names:
                if instance.name.find(name) > -1:
                    count += 1
                    assert instance.status == 'ACTIVE', \
                        "Instance {} is not in active status".format(name)
        assert count == len(names)

    def get_log(self, environment):
        deployments = self.murano.deployments.list(environment.id)
        logs = []
        for deployment in deployments:
            if deployment.updated == environment.updated:
                reports = self.murano.deployments.reports(
                    environment.id, deployment.id)
                for r in reports:
                    logs.append(r.text)
        return logs

    def deployment_success_check(self, environment, ports):
        deployment = self.murano.deployments.list(environment.id)[-1]

        assert deployment.state == 'success', \
            'Deployment status is {0}'.format(deployment.state)

        ip = environment.services[0]['instance']['floatingIpAddress']

        if ip:
            for port in ports:
                self.check_port_access(ip, port)
        else:
            raise Exception('Docker Instance does not have floating IP')

    def create_session(self, environment):
        return self.murano.sessions.configure(environment.id)

    def influxdb(self, host, name='Influx', db='db1;db2'):
        post_body = {
            "host": host,
            "image": 'tutum/influxdb',
            "name": name,
            "interfacePort": 8083,
            "apiPort": 8086,
            "preCreateDB": db,
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker InfluxDB"
                },
                "type": "io.murano.apps.docker.DockerInfluxDB",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def grafana(self, host, influx_service):
        post_body = {
            "host": host,
            "image": 'tutum/grafana',
            "name": "Grafana",
            "port": 80,
            "influxDB": influx_service,
            "grafanaUser": self.rand_name("user"),
            "grafanaPassword": self.rand_name("pass"),
            "dbName": self.rand_name("base"),
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker Grafana"
                },
                "type": "io.murano.apps.docker.DockerGrafana",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def mongodb(self, host):
        post_body = {
            "host": host,
            "name": "Mongo",
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker MongoDB"
                },
                "type": "io.murano.apps.docker.DockerMongoDB",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def nginx(self, host):
        post_body = {
            "host": host,
            "image": 'nginx',
            "name": "Nginx",
            "port": 80,
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker Nginx"
                },
                "type": "io.murano.apps.docker.DockerNginx",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def glassfish(self, host):
        post_body = {
            "host": host,
            "image": 'tutum/glassfish',
            "name": "Glass",
            "password": self.rand_name("O5t@"),
            "adminPort": 4848,
            "httpPort": 8080,
            "httpsPort": 8181,
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker GlassFish"
                },
                "type": "io.murano.apps.docker.DockerGlassFish",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def mariadb(self, host):
        post_body = {
            "host": host,
            "image": 'tutum/mariadb',
            "name": "MariaDB",
            "port": 3306,
            "password": self.rand_name("O5t@"),
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker MariaDB"
                },
                "type": "io.murano.apps.docker.DockerMariaDB",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def mysql(self, host):
        post_body = {
            "host": host,
            "image": 'mysql',
            "name": "MySQL",
            "port": 3306,
            "password": self.rand_name("O5t@"),
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker MySQL"
                },
                "type": "io.murano.apps.docker.DockerMySQL",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def jenkins(self, host):
        post_body = {
            "host": host,
            "image": 'jenkins',
            "name": "Jenkins",
            "port": 8080,
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker Jenkins"
                },
                "type": "io.murano.apps.docker.DockerJenkins",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def postgres(self, host):
        post_body = {
            "host": host,
            "image": 'postgres',
            "name": "Postgres",
            "port": 5432,
            "password": self.rand_name("O5t@"),
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker PostgreSQL"
                },
                "type": "io.murano.apps.docker.DockerPostgreSQL",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def crate(self, host):
        post_body = {
            "host": host,
            "name": "Crate",
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker Crate"
                },
                "type": "io.murano.apps.docker.DockerCrate",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def redis(self, host):
        post_body = {
            "host": host,
            "image": 'redis',
            "name": "Redis",
            "port": 6379,
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker Redis"
                },
                "type": "io.murano.apps.docker.DockerRedis",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def tomcat(self, host):
        post_body = {
            "host": host,
            "image": 'tutum/tomcat',
            "name": "Tomcat",
            "port": 8080,
            "password": self.rand_name("O5t@"),
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker Tomcat"
                },
                "type": "io.murano.apps.docker.DockerTomcat",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def httpd(self, host):
        post_body = {
            "host": host,
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
        return post_body

    def httpd_site(self, host):
        post_body = {
            "host": host,
            "image": 'httpd',
            "name": "HTTPdS",
            "port": 80,
            "publish": True,
            "siteRepo": "https://github.com/gabrielecirulli/2048.git",
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker HTTPd"
                },
                "type": "io.murano.apps.docker.DockerHTTPdSite",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def nginx_site(self, host):
        post_body = {
            "host": host,
            "image": 'nginx',
            "name": "NginxS",
            "port": 80,
            "siteRepo": 'https://github.com/gabrielecirulli/2048.git',
            "publish": True,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Docker Nginx Site"
                },
                "type": "io.murano.apps.docker.DockerNginxSite",
                "id": str(uuid.uuid4())
            }
        }
        return post_body

    def pod(self, host, replicas):
        post_body = {
            "kubernetesCluster": host,
            "labels": "testkey=testvalue",
            "name": "testpodtwo",
            "replicas": replicas,
            "?": {
                "_{id}".format(id=uuid.uuid4().hex): {
                    "name": "Kubernetes Pod"
                },
                "type": "io.murano.apps.docker.kubernetes.KubernetesPod",
                "id": str(uuid.uuid4())
            }
        }
        return post_body
