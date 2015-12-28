#    Copyright 2015 Mirantis, Inc.
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

import logging
import random
from tempfile import NamedTemporaryFile
import time

from cinderclient import client as cinderclient
from glanceclient.v1 import Client as GlanceClient
from keystoneclient.exceptions import ClientException as KeyStoneException
from keystoneclient.v2_0 import Client as KeystoneClient
from neutronclient.common.exceptions import NeutronClientException
import neutronclient.v2_0.client as neutronclient
from novaclient import client as nova_client
from novaclient.exceptions import ClientException as NovaClientException
import paramiko
import six
from waiting import wait

from mos_tests.environment.ssh import SSHClient

logger = logging.getLogger(__name__)


class OpenStackActions(object):

    def __init__(self, controller_ip, user='admin', password='admin',
                 tenant='admin', cert=None, env=None):
        logger.debug('Init OpenStack clients on {0}'.format(controller_ip))
        self.controller_ip = controller_ip

        if cert is None:
            auth_url = 'http://{0}:5000/v2.0/'.format(self.controller_ip)
            path_to_cert = None
        else:
            auth_url = 'https://{0}:5000/v2.0/'.format(self.controller_ip)
            with NamedTemporaryFile(prefix="fuel_cert_", suffix=".pem",
                                    delete=False) as f:
                f.write(cert)
            path_to_cert = f.name

        logger.debug('Auth URL is {0}'.format(auth_url))
        self.nova = nova_client.Client(version=2,
                                       username=user,
                                       api_key=password,
                                       project_id=tenant,
                                       auth_url=auth_url,
                                       cacert=path_to_cert)

        self.cinder = cinderclient.Client(1, user, password,
                                          tenant, auth_url,
                                          cacert=path_to_cert)

        self.neutron = neutronclient.Client(username=user,
                                            password=password,
                                            tenant_name=tenant,
                                            auth_url=auth_url,
                                            ca_cert=path_to_cert)

        self.keystone = self._get_keystoneclient(username=user,
                                                 password=password,
                                                 tenant_name=tenant,
                                                 auth_url=auth_url,
                                                 ca_cert=path_to_cert)

        token = self.keystone.auth_token
        logger.debug('Token is {0}'.format(token))
        glance_endpoint = self.keystone.service_catalog.url_for(
            service_type='image', endpoint_type='publicURL')
        logger.debug('Glance endpoind is {0}'.format(glance_endpoint))

        self.glance = GlanceClient(endpoint=glance_endpoint,
                                   token=token,
                                   cacert=path_to_cert)
        self.env = env

    def _get_keystoneclient(self, username, password, tenant_name, auth_url,
                            retries=3, ca_cert=None):
        keystone = None
        for i in range(retries):
            try:
                if ca_cert:
                    keystone = KeystoneClient(username=username,
                                              password=password,
                                              tenant_name=tenant_name,
                                              auth_url=auth_url,
                                              cacert=ca_cert)

                else:
                    keystone = KeystoneClient(username=username,
                                              password=password,
                                              tenant_name=tenant_name,
                                              auth_url=auth_url)
                break
            except KeyStoneException as e:
                err = "Try nr {0}. Could not get keystone client, error: {1}"
                logger.warning(err.format(i + 1, e))
                time.sleep(5)
        if not keystone:
            raise
        return keystone

    def _get_cirros_image(self):
        for image in self.glance.images.list():
            if image.name.startswith("TestVM"):
                return image

    def is_nova_ready(self):
        """Checks that all nova computes are avaliable"""
        hosts = self.nova.availability_zones.find(zoneName="nova").hosts
        return all(x['available'] for y in hosts.values()
                   for x in y.values() if x['active'])

    def get_instance_detail(self, server):
        details = self.nova.servers.get(server)
        return details

    def get_servers(self):
        servers = self.nova.servers.list()
        if servers:
            return servers

    def get_srv_hypervisor_name(self, srv):
        srv = self.nova.servers.get(srv.id)
        return getattr(srv, "OS-EXT-SRV-ATTR:hypervisor_hostname")

    def create_server(self, name, image_id=None, flavor=1, scenario='',
                      files=None, key_name=None, timeout=100, **kwargs):
        try:
            if scenario:
                with open(scenario, "r+") as f:
                    scenario = f.read()
        except Exception as exc:
            logger.info("Error opening file: %s" % exc)
            raise Exception()

        if image_id is None:
            image_id = self._get_cirros_image().id
        srv = self.nova.servers.create(name=name,
                                       image=image_id,
                                       flavor=flavor,
                                       userdata=scenario,
                                       files=files,
                                       key_name=key_name,
                                       **kwargs)

        def is_server_active():
            status = self.get_instance_detail(srv).status
            if status == 'ACTIVE':
                return True
            if status == 'ERROR':
                raise Exception('Server {} status is error'.format(srv.name))

        wait(is_server_active, timeout_seconds=timeout, sleep_seconds=5,
            waiting_for='instance {0} status change to ACTIVE'.format(
                name))

        # wait for ssh ready
        if self.env is not None:
            wait(lambda: self.is_server_ssh_ready(srv), timeout_seconds=60,
                waiting_for='server avaliable via ssh')
        logger.info('the server {0} is ready'.format(srv.name))
        return self.get_instance_detail(srv.id)

    def is_server_ssh_ready(self, server):
        """Check ssh connect to server"""
        paramiko_logger = logging.getLogger("paramiko")
        try:
            paramiko_logger.setLevel('CRITICAL')
            self.ssh_to_instance(self.env, server)
        except paramiko.SSHException as e:
            if 'No authentication methods available' in e:
                return True
            else:
                logger.debug('Instance unavaliable yet: {}'.format(e))
                return False
        finally:
            paramiko_logger.setLevel('DEBUG')

    def get_nova_instance_ips(self, srv):
        """Return all nova instance ip addresses as dict

        Example return:
        {'floating': '10.109.2.2',
        'fixed': '192.168.1.2'}

        :param srv: nova instance
        :rtype: dict
        :return: Dict with server ips
        """
        return {x['OS-EXT-IPS:type']: x['addr']
                for y in srv.addresses.values()
                for x in y}

    def get_node_with_dhcp_for_network(self, net_id, filter_attr='host',
                                       is_alive=True):
        filter_fn = lambda x: x[filter_attr] if filter_attr else x
        result = self.list_dhcp_agents_for_network(net_id)
        nodes = [filter_fn(node) for node in result['agents']
                 if node['alive'] == is_alive]
        return nodes

    def get_node_with_dhcp_for_network_by_host(self, net_id, hostname):
        result = self.list_dhcp_agents_for_network(net_id)
        nodes = [node for node in result['agents'] if node['host'] == hostname]
        return nodes

    def list_all_neutron_agents(self, agent_type=None,
                                filter_attr=None, is_alive=True):
        agents_type_map = {
            'dhcp': 'neutron-dhcp-agent',
            'ovs': 'neutron-openvswitch-agent',
            'metadata': 'neutron-metadata-agent',
            'l3': 'neutron-l3-agent',
            None: ''
            }
        filter_fn = lambda x: x[filter_attr] if filter_attr else x
        agents = [
            filter_fn(agent) for agent in self.neutron.list_agents(
                binary=agents_type_map[agent_type])['agents']
            if agent['alive'] == is_alive]
        return agents

    def list_dhcp_agents_for_network(self, net_id):
        return self.neutron.list_dhcp_agent_hosting_networks(net_id)

    def get_networks_on_dhcp_agent(self, agent_id):
        return self.list_networks_on_dhcp_agent(agent_id)['networks']

    def list_networks_on_dhcp_agent(self, agent_id):
        return self.neutron.list_networks_on_dhcp_agent(agent_id)

    def add_network_to_dhcp_agent(self, agent_id, network_id):
        self.neutron.add_network_to_dhcp_agent(
            agent_id, body={'network_id': network_id})

    def remove_network_from_dhcp_agent(self, agent_id, network_id):
        self.neutron.remove_network_from_dhcp_agent(agent_id, network_id)

    def list_ports_for_network(self, network_id, device_owner):
        return self.neutron.list_ports(
            network_id=network_id, device_owner=device_owner)['ports']

    def list_l3_agents(self):
        return self.list_all_neutron_agents('l3')

    def get_l3_agent_hosts(self, router_id):
        result = self.get_l3_for_router(router_id)
        hosts = [i['host'] for i in result['agents']]
        return hosts

    def get_l3_for_router(self, router_id):
        return self.neutron.list_l3_agent_hosting_routers(router_id)

    def create_network(self, name):
        network = {'name': name, 'admin_state_up': True}
        return self.neutron.create_network({'network': network})

    def create_subnet(self, network_id, name, cidr):
        subnet = {
            "network_id": network_id,
            "ip_version": 4,
            "cidr": cidr,
            "name": name
        }
        return self.neutron.create_subnet({'subnet': subnet})

    def list_networks(self):
        return self.neutron.list_networks()

    def assign_floating_ip(self, srv, use_neutron=False):
        if use_neutron:
            #   Find external net id for tenant
            nets = self.neutron.list_networks()['networks']
            err_msg = "Active external network not found in nets:{}"
            ext_net_ids = [
                net['id'] for net in nets
                if net['router:external'] and net['status'] == "ACTIVE"]
            assert ext_net_ids, err_msg.format(nets)
            net_id = ext_net_ids[0]
            #   Find instance port
            ports = self.neutron.list_ports(device_id=srv.id)['ports']
            err_msg = "Not found active ports for instance:{}"
            assert ports, err_msg.format(srv.id)
            port = ports[0]
            #   Create floating IP
            body = {'floatingip': {'floating_network_id': net_id,
                                   'port_id': port['id']}}
            flip = self.neutron.create_floatingip(body)
            #   Wait active state for port
            port_id = flip['floatingip']['port_id']
            state = lambda: self.neutron.show_port(port_id)['port']['status']
            wait(lambda: state() == "ACTIVE")
            return flip['floatingip']

        fl_ips_pool = self.nova.floating_ip_pools.list()
        if fl_ips_pool:
            floating_ip = self.nova.floating_ips.create(
                pool=fl_ips_pool[0].name)
            self.nova.servers.add_floating_ip(srv, floating_ip)
            return floating_ip

    def disassociate_floating_ip(self, srv, floating_ip, use_neutron=False):
        if use_neutron:
            try:
                self.neutron.update_floatingip(
                    floatingip=floating_ip['id'],
                    body={'floatingip': {}})

                id = floating_ip['id']
                wait(
                    lambda: self.neutron.show_floatingip(id)
                            ['floatingip']['status'] == "DOWN",
                    timeout_seconds=60)
            except NeutronClientException:
                logger.info('The floatingip {} can not be disassociated.'
                            .format(floating_ip['id']))
        else:
            try:
                self.nova.servers.remove_floating_ip(srv, floating_ip)
            except NovaClientException:
                logger.info('The floatingip {} can not be disassociated.'
                            .format(floating_ip))

    def delete_floating_ip(self, floating_ip, use_neutron=False):
        if use_neutron:
            try:
                self.neutron.delete_floatingip(floating_ip['id'])
            except NeutronClientException:
                logger.info('floating_ip {} is not deletable'
                            .format(floating_ip['id']))
        else:
            try:
                self.nova.floating_ips.delete(floating_ip)
            except NovaClientException:
                logger.info('floating_ip {} is not deletable'
                            .format(floating_ip))

    def create_router(self, name, tenant_id=None, distributed=False):
        router = {'name': name, 'distributed': distributed}
        if tenant_id is not None:
            router['tenant_id'] = tenant_id
        return self.neutron.create_router({'router': router})

    def router_interface_add(self, router_id, subnet_id):
        subnet = {
            'subnet_id': subnet_id
        }
        self.neutron.add_interface_router(router_id, subnet)

    def router_gateway_add(self, router_id, network_id):
        network = {
            'network_id': network_id
        }
        self.neutron.add_gateway_router(router_id, network)

    def create_sec_group_for_ssh(self):
        name = "test-sg" + str(random.randint(1, 0x7fffffff))
        secgroup = self.nova.security_groups.create(
            name, "descr")

        rulesets = [
            {
                # ssh
                'ip_protocol': 'tcp',
                'from_port': 22,
                'to_port': 22,
                'cidr': '0.0.0.0/0',
            },
            {
                # ping
                'ip_protocol': 'icmp',
                'from_port': -1,
                'to_port': -1,
                'cidr': '0.0.0.0/0',
            }
        ]

        for ruleset in rulesets:
            self.nova.security_group_rules.create(
                secgroup.id, **ruleset)
        return secgroup

    def create_key(self, key_name):
        logger.debug('Try to create key {0}'.format(key_name))
        return self.nova.keypairs.create(key_name)

    def get_port_by_fixed_ip(self, ip):
        """Returns neutron port by instance fixed ip"""
        for port in self.neutron.list_ports()['ports']:
            for ips in port['fixed_ips']:
                if ip == ips['ip_address']:
                    return port

    @property
    def ext_network(self):
        exist_networks = self.list_networks()['networks']
        return [x for x in exist_networks if x.get('router:external')][0]

    def delete_subnets(self, networks):
        # Subnets and ports are simply filtered by network ids
        for subnet in self.neutron.list_subnets()['subnets']:
            if subnet['network_id'] not in networks:
                continue
            try:
                self.neutron.delete_subnet(subnet['id'])
            except NeutronClientException:
                logger.info(
                    'the subnet {} is not deletable'.format(subnet['id']))

    def delete_routers(self):
        # Did not find the better way to detect the fuel admin router
        # Looks like it just always has fixed name router04
        for router in self.neutron.list_routers()['routers']:
            if router['name'] == 'router04':
                continue
            try:
                self.neutron.delete_router(router)
            except NeutronClientException:
                logger.info('the router {} is not deletable'.format(router))

    def delete_floating_ips(self):
        for floating_ip in self.nova.floating_ips.list():
            try:
                self.nova.floating_ips.delete(floating_ip)
            except NovaClientException:
                self.delete_floating_ip(floating_ip, use_neutron=True)

    def delete_servers(self):
        for server in self.nova.servers.list():
            try:
                self.nova.servers.delete(server)
            except NovaClientException:
                logger.info('nova server {} is not deletable'.format(server))

    def delete_keypairs(self):
        for key_pair in self.nova.keypairs.list():
            try:
                self.nova.keypairs.delete(key_pair)
            except NovaClientException:
                logger.info('key pair {} is not deletable'.format(key_pair.id))

    def delete_security_groups(self):
        for sg in self.nova.security_groups.list():
            if sg.description == 'Default security group':
                continue
            try:
                self.nova.security_groups.delete(sg)
            except NovaClientException:
                logger.info(
                    'The Security Group {} is not deletable'.format(sg))

    def delete_ports(self, networks):
        # After some experiments the following sequence for deletion was found
        # router_interface and ports -> subnets -> routers -> nets
        # Delete router interface and ports
        # TBD some ports are still kept after the cleanup.
        # Need to find why and delete them as well
        # But it does not fail the execution so far.
        for port in self.neutron.list_ports()['ports']:
            if port['network_id'] not in networks:
                continue
            try:
                # TBD Looks like the port might be used either by router or
                # l3 agent
                # in case of router this condition is true
                # port['network'] == 'router_interface'
                # dunno what will happen in case of the l3 agent
                for fixed_ip in port['fixed_ips']:
                    logger.debug(
                        self.neutron.remove_interface_router(
                            port['device_id'],
                            {
                                'router_id': port['device_id'],
                                'subnet_id': fixed_ip['subnet_id'],
                            }
                        )
                    )
            except NeutronClientException:
                logger.info('the port {} is not deletable'
                            .format(port['id']))

    def cleanup_network(self, networks_to_skip=tuple()):
        """Clean up the neutron networks.

        :param networks_to_skip: list of networks names that should be kept
        """
        # net ids with the names from networks_to_skip are filtered out
        networks = [x['id'] for x in self.neutron.list_networks()['networks']
                    if x['name'] not in networks_to_skip]

        self.delete_keypairs()

        self.delete_floating_ips()

        self.delete_servers()

        self.delete_security_groups()

        self.delete_ports(networks)

        self.delete_subnets(networks)

        self.delete_routers()

        # Delete nets
        for net in networks:
            try:
                self.neutron.delete_network(net)
            except NeutronClientException:
                logger.info('the net {} is not deletable'
                            .format(net))

    def execute_through_host(self, ssh, vm_host, cmd, creds=()):
        logger.debug("Making intermediate transport")
        intermediate_transport = ssh._ssh.get_transport()

        logger.debug("Opening channel to VM")
        intermediate_channel = intermediate_transport.open_channel(
            'direct-tcpip', (vm_host, 22), (ssh.host, 0))
        logger.debug("Opening paramiko transport")
        transport = paramiko.Transport(intermediate_channel)
        logger.debug("Starting client")
        transport.start_client()
        logger.info("Passing authentication to VM: {}".format(creds))
        if not creds:
            creds = ('cirros', 'cubswin:)')
        transport.auth_password(creds[0], creds[1])

        logger.debug("Opening session")
        channel = transport.open_session()
        logger.info("Executing command: {}".format(cmd))
        channel.exec_command(cmd)

        result = {
            'stdout': [],
            'stderr': [],
            'exit_code': 0
        }

        logger.debug("Receiving exit_code")
        result['exit_code'] = channel.recv_exit_status()
        logger.debug("Receiving stdout")
        result['stdout'] = channel.recv(1024)
        logger.debug("Receiving stderr")
        result['stderr'] = channel.recv_stderr(1024)

        logger.debug("Closing channel")
        channel.close()

        return result

    def ssh_to_instance(self, env, vm, vm_keypair=None, username='cirros',
                        password=None):
        """Returns direct ssh client to instance via proxy"""
        logger.debug('Try to connect to vm {0}'.format(vm.name))
        net_name = [x for x in vm.addresses if len(vm.addresses[x]) > 0][0]
        vm_ip = vm.addresses[net_name][0]['addr']
        net_id = self.neutron.list_networks(
            name=net_name)['networks'][0]['id']
        dhcp_namespace = "qdhcp-{0}".format(net_id)
        devops_nodes = self.get_node_with_dhcp_for_network(net_id)
        if not devops_nodes:
            raise Exception("Nodes with dhcp for network with id:{}"
                            " not found.".format(net_id))
        devops_node = random.choice(devops_nodes)
        ip = env.find_node_by_fqdn(devops_node).data['ip']
        key_paths = []
        for i, key in enumerate(env.admin_ssh_keys):
            path = '/tmp/fuel_key{0}.rsa'.format(i)
            key.write_private_key_file(path)
            key_paths.append(path)
        proxy_command = ("ssh {keys} -o 'StrictHostKeyChecking no' "
                         "root@{node_ip} ip netns exec {ns} "
                         "nc {vm_ip} 22".format(
                            keys=' '.join('-i {}'.format(k)
                                          for k in key_paths),
                            ns=dhcp_namespace,
                            node_ip=ip,
                            vm_ip=vm_ip))
        logger.debug('Proxy command for ssh: "{0}"'.format(proxy_command))
        instance_keys = []
        if vm_keypair is not None:
            instance_keys.append(paramiko.RSAKey.from_private_key(
                six.StringIO(vm_keypair.private_key)))
        return SSHClient(vm_ip, port=22, username=username, password=password,
                         private_keys=instance_keys,
                         proxy_command=proxy_command)

    def wait_agents_alive(self, agt_ids_to_check):
        logger.info('waiting until the agents get alive')
        assert(wait(lambda: all([agt['alive'] for agt in
                                  self.neutron.list_agents()['agents']
                                  if agt['id'] in agt_ids_to_check]),
                    timeout_seconds=5 * 60))

    def wait_agents_down(self, agt_ids_to_check):
        logger.info('waiting until the agents go down')
        assert(wait(lambda: all([not agt['alive'] for agt in
                                  self.neutron.list_agents()['agents']
                                  if agt['id'] in agt_ids_to_check]),
                    timeout_seconds=5 * 60))

    def add_net(self, router_id):
        i = len(self.neutron.list_networks()['networks']) + 1
        network = self.create_network(name='net%02d' % i)['network']
        logger.info('network with id {} is created'.
                    format(network['id']))
        subnet = self.create_subnet(
            network_id=network['id'],
            name='net%02d__subnet' % i,
            cidr="192.168.%d.0/24" % i)
        logger.info('subnet with id {} is created'.
                    format(subnet['subnet']['id']))
        self.router_interface_add(
            router_id=router_id,
            subnet_id=subnet['subnet']['id'])
        return network['id']

    def add_server(self, network_id, key_name, hostname, sg_id):
        i = len(self.nova.servers.list()) + 1
        zone = self.nova.availability_zones.find(zoneName="nova")
        srv = self.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(zone.zoneName, hostname),
                key_name=key_name,
                nics=[{'net-id': network_id}],
                security_groups=[sg_id])
        return srv

    def reschedule_router_to_primary_host(self, router_id, primary_host):
        agent_list = self.neutron.list_agents(
                          binary='neutron-l3-agent')['agents']
        agt_id_to_move_on = [agt['id'] for agt in agent_list
                             if agt['host'] == primary_host][0]
        self.force_l3_reshedule(router_id,
                                 agt_id_to_move_on)

    def force_l3_reshedule(self, router_id, new_l3_agt_id=''):
        logger.info('going to reshedule the router on new agent')
        current_l3_agt_id = self.neutron.list_l3_agent_hosting_routers(
                                 router_id)['agents'][0]['id']
        if not new_l3_agt_id:
            all_l3_agts = self.neutron.list_agents(
                              binary='neutron-l3-agent')['agents']
            for agt in all_l3_agts:
                logger.info(agt['id'])
            availabe_l3_agts = [agt for agt in all_l3_agts
                                if agt['id'] != current_l3_agt_id]
            for agt in availabe_l3_agts:
                logger.info(agt['id'])
            new_l3_agt_id = availabe_l3_agts[0]['id']
        self.neutron.remove_router_from_l3_agent(current_l3_agt_id,
                                                 router_id)
        self.neutron.add_router_to_l3_agent(new_l3_agt_id,
                                            {"router_id": router_id})
        assert(wait(
            lambda: self.neutron.list_l3_agent_hosting_routers(router_id),
            timeout_seconds=5 * 60))

    def reschedule_dhcp_agent(self, net_id, controller_fqdn):
        agent_list = self.neutron.list_agents(
            binary='neutron-dhcp-agent')['agents']
        agt_id_to_move_on = [agt['id'] for agt in agent_list
                             if agt['host'] == controller_fqdn][0]
        logger.info('Agent id to move on {0}'.format(agt_id_to_move_on))
        self.force_dhcp_reschedule(net_id, agt_id_to_move_on)

    def force_dhcp_reschedule(self, net_id, new_dhcp_agt_id):
        logger.info('going to reshedule network to specified '
                    'controller dhcp agent')
        current_dhcp_agt_id = self.neutron.list_dhcp_agent_hosting_networks(
            net_id)['agents'][0]['id']
        self.neutron.remove_network_from_dhcp_agent(current_dhcp_agt_id,
                                                    net_id)
        self.neutron.add_network_to_dhcp_agent(new_dhcp_agt_id,
                                               {'network_id': net_id})
        assert(wait(
            lambda: self.neutron.list_dhcp_agent_hosting_networks(net_id),
            timeout_seconds=5 * 60))
