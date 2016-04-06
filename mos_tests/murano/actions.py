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

import json
import random
import socket
import telnetlib
import time
import yaml


class MuranoActions(object):
    """Murano-specific actions"""

    def __init__(self, os_conn):
        self.os_conn = os_conn

    def rand_name(self, name):
        return name + '_' + str(random.randint(1, 0x7fffffff))

    def create_service(self, environment, session, json_data, to_json=True):
        service = self.os_conn.murano.services.post(environment.id, path='/',
                                                    data=json_data,
                                                    session_id=session.id)
        if to_json:
            service = service.to_dict()
            service = json.dumps(service)
            return yaml.load(service)
        else:
            return service

    def wait_for_environment_deploy(self, environment):
        start_time = time.time()
        status = self.os_conn.murano.environments.get(environment.id).status
        while status != 'ready' and time.time() - start_time < 1500:
            if status == 'deploy failure':
                assert 0, 'Environment deploy finished with errors'
            time.sleep(15)
            status = self.os_conn.murano.environments.get(environment.id).\
                status
        environment = self.os_conn.murano.environments.get(environment.id)
        logs = self.get_log(environment)
        assert 'Deployment finished' in logs
        return environment

    def deploy_environment(self, environment, session):
        self.os_conn.murano.sessions.deploy(environment.id, session.id)
        return self.wait_for_environment_deploy(environment)

    def get_action_id(self, environment, name, service):
        env_data = environment.to_dict()
        a_dict = env_data['services'][service]['?']['_actions']
        for action_id, action in a_dict.items():
            if action['name'] == name:
                return action_id

    def run_action(self, environment, action_id):
        self.os_conn.murano.actions.call(environment.id, action_id)
        return self.wait_for_environment_deploy(environment)

    def status_check(self, environment, configurations, kubernetes=False,
                     negative=False):
        for configuration in configurations:
            if kubernetes:
                service_name = configuration[0]
                inst_name = configuration[1]
                ports = configuration[2:]
                ip = self.get_k8s_ip_by_instance_name(environment, inst_name,
                                                      service_name)
                if ip and ports and negative:
                    for port in ports:
                        assert self.check_port_access(ip, port, negative)
                        assert self.check_k8s_deployment(ip, port, negative)
                elif ip and ports:
                    for port in ports:
                        assert self.check_port_access(ip, port)
                        assert self.check_k8s_deployment(ip, port)
                else:
                    assert 0, "Instance {} doesn't have floating IP"\
                        .format(inst_name)
            else:
                inst_name = configuration[0]
                ports = configuration[1:]
                ip = self.get_ip_by_instance_name(environment, inst_name)
                if ip and ports:
                    for port in ports:
                        assert self.check_port_access(ip, port)
                else:
                    assert 0, "Instance {} doesn't have floating IP"\
                        .format(inst_name)

    def check_port_access(self, ip, port, negative=False):
        result = 1
        start_time = time.time()
        while time.time() - start_time < 600:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex((str(ip), port))
            sock.close()

            if result == 0 or negative:
                break
            time.sleep(5)
        if negative:
            assert result != 0, '{} port is opened on instance'.format(port)
        else:
            assert result == 0, '{} port is closed on instance'.format(port)
        return True

    def check_k8s_deployment(self, ip, port, timeout=3600, negative=False):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                self.verify_connection(ip, port, negative)
                return True
            except RuntimeError:
                time.sleep(10)
        assert 0, 'Containers are not ready'

    def verify_connection(self, ip, port, negative=False):
        try:
            tn = telnetlib.Telnet(ip, port)
            tn.write('GET / HTTP/1.0\n\n')
            buf = tn.read_all()
            if negative and len(buf) == 0:
                return True
            elif len(buf) != 0:
                tn.sock.sendall(telnetlib.IAC + telnetlib.NOP)
                return True
            else:
                raise RuntimeError('Resource at {0}:{1} not exist'.
                                   format(ip, port))
        except socket.error as e:
            raise RuntimeError('Found reset: {0}'.format(e))

    def get_k8s_ip_by_instance_name(self, environment, inst_name,
                                    service_name):
        """Returns ip of specific kubernetes node (gateway, master, minion)
        based. Search depends on service name of kubernetes and names of
        spawned instances
        :param environment: Murano environment
        :param inst_name: Name of instance or substring of instance name
        :param service_name: Name of Kube Cluster application in Murano
        environment
        :return: Ip of Kubernetes instances
        """
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
        """Returns ip of instance using instance name
        :param environment: Murano environment
        :param name: String, which is substring of name of instance or name of
        instance
        :return:
        """
        for service in environment.services:
            if inst_name in service['instance']['name']:
                return service['instance']['floatingIpAddress']

    def get_environment(self, environment):
        return self.os_conn.murano.environments.get(environment.id)

    def check_instance(self, gateways_count, nodes_count):
        instance_list = self.os_conn.nova.servers.list()
        names = ["master-1", "minion-1", "gateway-1"]
        if gateways_count == 2:
            names.append("gateway-2")
        if nodes_count == 2:
            names.append("minion-2")
        count = 0
        for instance in instance_list:
            for name in names:
                if instance.name.find(name) > -1:
                    count += 1
                    assert instance.status == 'ACTIVE', \
                        "Instance {} is not in active status".format(name)
        assert count == len(names)

    def get_log(self, environment):
        deployments = self.os_conn.murano.deployments.list(environment.id)
        logs = []
        for deployment in deployments:
            if deployment.updated == environment.updated:
                reports = self.os_conn.murano.deployments.reports(
                    environment.id, deployment.id)
                for r in reports:
                    logs.append(r.text)
        return logs
