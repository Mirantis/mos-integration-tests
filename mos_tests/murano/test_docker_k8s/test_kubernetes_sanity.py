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


pytestmark = pytest.mark.undestructive


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.testrail_id('836463')
def test_deploy_k8s_influxdb(environment, murano, session, cluster, pod):

    murano.create_service(environment, session, murano.influxdb(pod))
    deployed_environment = murano.deploy_environment(environment, session)
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
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 8083, 8086, 80],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerMongoDB',)], indirect=['package'])
@pytest.mark.testrail_id('836467')
def test_deploy_k8s_mongodb(environment, murano,
                            session, cluster, pod, package):

    murano.create_service(environment, session, murano.mongodb(pod))
    deployed_environment = murano.deploy_environment(environment, session)
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
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)
    murano.check_postgresql(environment, "gateway-1", cluster['name'])


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
@pytest.mark.parametrize('package', [('DockerCrate',)], indirect=['package'])
@pytest.mark.testrail_id('836459')
def test_deploy_k8s_crate(environment, murano, session, cluster, pod, package):

    murano.create_service(environment, session, murano.crate(pod))
    deployed_environment = murano.deploy_environment(environment, session)
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
    murano.status_check(deployed_environment,
                        [[cluster['name'], "master-1", 8080],
                         [cluster['name'], "gateway-1", 80],
                         [cluster['name'], "minion-1", 4194]
                         ],
                        kubernetes=True)


@pytest.mark.check_env_("is_any_compute_suitable_for_max_flavor")
class Test_k8s_DockerRegistry(object):

    docker_registry_port = 5000
    docker_mirror_port = 5005

    @pytest.yield_fixture
    def keypair(self, os_conn):
        """Create ssh key"""
        keypair = os_conn.create_key(key_name='muranokey')
        yield keypair
        os_conn.delete_key(key_name=keypair.name)

    @pytest.yield_fixture
    def security_group(self, os_conn):
        """Add security groups"""
        sec_group = os_conn.create_sec_group_for_ssh()
        rulesets = [
            {
                # Custom Docker registry
                'ip_protocol': 'tcp',
                'from_port': self.docker_registry_port,
                'to_port': self.docker_registry_port,
                'cidr': '0.0.0.0/0',
            },
            {
                # Docker registry mirror
                'ip_protocol': 'tcp',
                'from_port': self.docker_mirror_port,
                'to_port': self.docker_mirror_port,
                'cidr': '0.0.0.0/0',
            }]

        for ruleset in rulesets:
            os_conn.nova.security_group_rules.create(
                sec_group.id, **ruleset)

        yield sec_group
        os_conn.delete_security_group(sec_group)

    @pytest.yield_fixture
    def vm_with_docker(
            self, os_conn, env, keypair, ubuntu_image_id, security_group):
        """Create VM with ubuntu and install docker on it"""
        os_conn.delete_servers()  # less servers -> more resources for future

        network = os_conn.int_networks[0]
        flavor = os_conn.nova.flavors.find(name='m1.medium')

        vm = os_conn.create_server(
            name='ubuntu_docker_registry',
            key_name=keypair.name,
            image_id=ubuntu_image_id,
            flavor=flavor.id,
            nics=[{'net-id': network['id']}],
            security_groups=[security_group.id],
            wait_for_active=True,
            wait_for_avaliable=True)

        floating_ip = os_conn.nova.floating_ips.create()
        vm.add_floating_ip(floating_ip.ip)

        vm.get()
        vm_ssh = os_conn.ssh_to_instance(
            env, vm, vm_keypair=keypair, username='ubuntu')

        # install Docker on VM
        with vm_ssh as remote:
            remote.check_call('sudo apt-get update')
            remote.check_call('curl -sSL https://get.docker.com/gpg '
                              '| sudo apt-key add -')
            remote.check_call('curl -sSL https://get.docker.com/ | sudo sh')
            remote.check_call('sudo usermod -aG docker $(whoami)')

        yield vm, floating_ip.ip, keypair
        os_conn.delete_servers()
        os_conn.delete_floating_ip(floating_ip.ip)

    @pytest.fixture
    def configure_docker(self, vm_with_docker, os_conn, env):
        """Run 'Docker Custom Registry' and 'Docker Registry Mirror' on VM"""
        vm, vm_floating_ip, keypair = vm_with_docker

        vm_ssh = os_conn.ssh_to_instance(
            env, vm, vm_keypair=keypair, username='ubuntu',
            vm_ip=vm_floating_ip)

        # Run docker custom registry on VM
        with vm_ssh as remote:
            remote.check_call('docker version')
            remote.check_call('docker run hello-world')
            remote.check_call(
                'docker run -d -p {registry_port}:5000 '
                '--restart=always '
                '--name registry registry:2'.format(
                    registry_port=self.docker_registry_port))
            # put some images to local repo
            for i in ('redmine', 'ubuntu'):
                remote.check_call(
                    'docker pull {0}'.format(i))
                remote.check_call(
                    'docker tag {0} localhost:5000/local_{0}'.format(i))
                remote.check_call(
                    'docker push localhost:5000/local_{0}'.format(i))
                remote.check_call(
                    'docker pull localhost:5000/local_{0}'.format(i))

        # Run docker registry mirror on VM
        with vm_ssh as remote:
            remote.check_call(
                'docker run -d --name mirror -p {mirror_port}:5000 '
                '--restart=always '
                '-e STANDALONE=false '
                '-e MIRROR_SOURCE=https://registry-1.docker.io '
                '-e MIRROR_SOURCE_INDEX=https://index.docker.io '
                'registry'.format(mirror_port=self.docker_mirror_port))

        return vm, vm_floating_ip, keypair

    @pytest.mark.testrail_id('1681295', role='custom_registry')
    @pytest.mark.testrail_id('1682005', role='registry_mirr')
    @pytest.mark.testrail_id('1682006', role='both')
    @pytest.mark.parametrize(
        'package', [('DockerHTTPd', 'DockerApp')], indirect=['package'])
    @pytest.mark.parametrize(
        'role', ['custom_registry', 'registry_mirr', 'both'])
    def test_k8s_docker_registry_local_and_mirror(
            self, os_conn, env, configure_docker, environment, murano, session,
            cluster, pod, package, role):
        """Deploy "Kubernetes Cluster (package)" with setting
        "Custom Docker registry URL" and "Docker registry mirror URL".

        Actions:
        1) Create VM with ubuntu and install Docker on it.
        2) On VM run 'Docker Custom Registry' and 'Docker Registry Mirror'.
        3) Add 'Kubernetes Cluster' and 'Docker Container' packages to murano.
        4) Set 'Custom Docker registry URL' and/or 'Docker registry mirror URL'
        in 'Kubernetes Cluster' config.
        5) Set local image location inside Docker Container' package.
        6) Deploy murano env.
        7) Check that 'insecure-registry' and/or 'registry-mirror' presents
        in docker-config file on minion-node.
        8) From minion-node pull local and public docker image.
        9) In Docker mirror logs check that only public image presents there.

        Has bugs:
        https://bugs.launchpad.net/fuel/+bug/1616074
        https://bugs.launchpad.net/k8s-docker-suite-app-murano/+bug/1622899

        Duration: ~ 30 min (each test)
        """
        docker_cfg_f = '/etc/default/docker'
        vm, vm_floating_ip, keypair = configure_docker

        # Add DockerHTTPd configuration
        environment = murano.get_environment(environment)
        murano.create_service(environment, session, murano.httpd(pod))

        # Get updated information about services for deploy
        all_services = murano.murano.services.list(environment.id, session.id)
        all_services_dict = [i.to_dict() for i in all_services]

        # Delete from murano env info about services to update them
        for service in all_services_dict:
            murano.delete_service(environment, session, service)

        # Set "Custom Docker registry URL" and "Docker registry mirror URL" in
        # "Kubernetes Cluster" config.
        local_reg_path = '{0}:{1}'.format(
            vm_floating_ip, self.docker_registry_port)
        local_mirr_path = 'http://{0}:{1}'.format(
            vm_floating_ip, self.docker_mirror_port)

        if role == 'custom_registry':
            all_services_dict[0]['dockerRegistry'] = local_reg_path
        elif role == 'registry_mirr':
            all_services_dict[0]['dockerMirror'] = local_mirr_path
        else:
            # both
            all_services_dict[0]['dockerRegistry'] = local_reg_path
            all_services_dict[0]['dockerMirror'] = local_mirr_path

        # Add back updated info about KubernetesCluster to murano env
        for service in all_services_dict:
            murano.create_service(environment, session, service)

        if role in ('custom_registry', 'both'):
            # Add 'Docker Container' service with local docker image
            docker_app = murano.docker_app(
                host=pod,
                image_location='{0}/local_redmine'.format(vm_floating_ip),
                port=3000,
                app_name='DockerImageFromLocalRepo')
            murano.create_service(environment, session, docker_app)

        # Deploy environment
        murano.deploy_environment(environment, session)

        # Get ssh to nodes
        vms = os_conn.nova.servers.list()
        minion_vm = [x for x in vms if 'minion' in x.to_dict()['name']][0]
        minion_vm_ssh = os_conn.ssh_to_instance(
            env, minion_vm, vm_keypair=keypair, username='ubuntu')
        vm_ssh = os_conn.ssh_to_instance(
            env, vm, vm_keypair=keypair, username='ubuntu')

        # Read docker cfg file from minion node
        with minion_vm_ssh as remote:
            remote.check_call('sudo chmod 777 %s' % docker_cfg_f)
            docker_cfg_out = remote.check_call('cat %s' % docker_cfg_f)
            docker_cfg_out = docker_cfg_out.stdout_string

        # Check content of docker cfg file
        if role in ('custom_registry', 'both'):

            assert ('--insecure-registry {0}'.format(local_reg_path)
                    in docker_cfg_out), (
                "Docker local registry link does not present in Docker cfg "
                "file on Minion node.\n{0}".format(docker_cfg_out))

        if role in ('registry_mirr', 'both'):

            assert ('--registry-mirror={0}'.format(local_mirr_path)
                    in docker_cfg_out), (
                "Docker local mirror link does not present on Docker cfg file"
                "on Minion node.\n{0}".format(docker_cfg_out))

        # Check local registry and local mirror
        with minion_vm_ssh as remote:
            if role in ('registry_mirr', 'both'):
                remote.check_call('sudo docker pull wordpress')

            if role in ('custom_registry', 'both'):
                remote.check_call('sudo docker pull {0}/local_ubuntu'.format(
                    local_reg_path))

        # Check logs of a docker registry mirror.
        # Time compare to pull from internet/mirror is not working as the
        # difference is very low.
        with vm_ssh as remote:
            mirr_logs = remote.check_call('docker logs mirror')
            mirr_logs = mirr_logs.stdout_string

        if role in ('registry_mirr', 'both'):
            assert 'wordpress' in mirr_logs, (
                "Remote image does not present inside Docker Mirror logs")

        if role in ('custom_registry', 'both'):
            assert 'local_ubuntu' not in mirr_logs, (
                "Local image presents inside Docker Mirror logs")
