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
import re
import time

from cinderclient import client as cinderclient
from contextlib2 import suppress
from dateutil.parser import parse as dateparse
from glanceclient.v2.client import Client as GlanceClient
from heatclient.v1.client import Client as HeatClient
from keystoneclient.auth.identity.v2 import Password as KeystonePassword
from keystoneclient import session
from keystoneclient.v2_0 import Client as KeystoneClient
from neutronclient.common.exceptions import Conflict as NeutronConflict
from neutronclient.common.exceptions import NeutronClientException
from neutronclient.v2_0 import client as neutron_client
from novaclient import client as nova_client
from novaclient import exceptions as nova_exceptions
import paramiko
import six

from keystoneauth1.identity import v3
from keystoneauth1 import session as sessionV3
from keystoneclient.v3 import Client as KeystoneClientV3

from mos_tests.environment.ssh import NetNsProxy
from mos_tests.environment.ssh import SSHClient
from mos_tests.functions.common import gen_temp_file
from mos_tests.functions.common import wait
from mos_tests.functions import os_cli

logger = logging.getLogger(__name__)


class InstanceError(Exception):
    def __init__(self, instance):
        self.instance = instance

    def __str__(self):
        message = self.instance.fault.get('message')
        details = self.instance.fault.get('details')
        return ('Instance {0.name} is in ERROR status\n'
                '{1}\n'
                '{2}'.format(self.instance, message, details))


class OpenStackActions(object):
    """OpenStack base services clients and helper actions"""

    def __init__(self, controller_ip, keystone_version=2, domain='Default',
                 user='admin', password='admin', tenant='admin',
                 cert=None, env=None, proxy_session=None):
        logger.debug('Init OpenStack clients on {0}'.format(controller_ip))

        self.controller_ip = controller_ip
        self.username = user
        self.password = password
        self.tenant = tenant

        if cert is None:
            if keystone_version == 2:
                auth_url = 'http://{0}:5000/v2.0/'.format(self.controller_ip)
            else:
                auth_url = 'http://{0}:5000/v3/'.format(self.controller_ip)
            self.path_to_cert = None
            self.insecure = True
        else:
            if keystone_version == 2:
                auth_url = 'https://{0}:5000/v2.0/'.format(self.controller_ip)
            else:
                auth_url = 'https://{0}:5000/v3/'.format(self.controller_ip)
            with gen_temp_file(prefix="fuel_cert_", suffix=".pem") as f:
                f.write(cert)
            self.path_to_cert = f.name
            self.insecure = False

        logger.debug('Auth URL is {0}'.format(auth_url))
        if keystone_version == 2:
            self.auth = KeystonePassword(username=user,
                                         password=password,
                                         auth_url=auth_url,
                                         tenant_name=tenant)
            self.session = session.Session(auth=self.auth,
                                           verify=self.path_to_cert)
            self.keystone = KeystoneClient(session=self.session)
        else:
            self.auth = v3.Password(auth_url=auth_url,
                                    user_domain_name=domain,
                                    username=user,
                                    password=password,
                                    project_domain_name=domain,
                                    project_name=tenant)
            self.session = sessionV3.Session(auth=self.auth,
                                             verify=self.path_to_cert)
            self.keystone = KeystoneClientV3(session=self.session)

        self.keystone.management_url = auth_url

        self.nova = nova_client.Client(version=2, session=self.session)

        self.cinder = cinderclient.Client(version=2, session=self.session)

        if keystone_version == 2:
            self.neutron = neutron_client.Client(session=self.session)
        else:
            self.neutron = neutron_client.Client(session=self.session,
                                                 project_name=tenant)

        self.glance = GlanceClient(session=self.session)

        # TODO(akuznetsova): Need to refactor initialization of heatclient

        self.endpoint_url = self.session.get_endpoint(
            service_type='orchestration',
            endpoint_type='publicURL'
        )
        token = self.session.get_token()
        self.heat = HeatClient(endpoint=self.endpoint_url, token=token)

        self.env = env

    def get_auth_token(self):
        return self.auth.get_auth_ref(self.session).auth_token

    def reinit_heat_client(self):
        token = self.get_auth_token()
        self.heat = HeatClient(endpoint=self.endpoint_url, token=token)

    def _get_cirros_image(self):
        for image in self.glance.images.list():
            if image.name.startswith("TestVM"):
                return image

    def is_nova_ready(self):
        """Checks that all nova computes are available"""

        def get_hosts():
            zone = self.nova.availability_zones.find(zoneName="nova")
            hosts = [x for y in zone.hosts.values() for x in y.values()]
            for host in hosts:
                host['updated_at'] = dateparse(host['updated_at'])
            return hosts

        last_updated = max([x['updated_at'] for x in get_hosts()])
        wait(lambda: all([x['updated_at'] > last_updated
                          for x in get_hosts()]),
             timeout_seconds=2 * 60,
             sleep_seconds=10,
             waiting_for='nova host data to be updated')
        return all(x['available'] for x in get_hosts() if x['active'])

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

    def server_status_is(self, server, status):
        server = self.nova.servers.get(server)
        if server.status == 'ERROR':
            raise InstanceError(server)
        return server.status == status

    def image_status_is(self, image, status):
        image = self.glance.images.get(image.get('id'))
        return image.get('status') == status

    def is_server_active(self, server):
        return self.server_status_is(server, 'ACTIVE')

    def is_image_active(self, image):
        return self.image_status_is(image, 'active')

    def wait_servers_active(self, servers, timeout=10 * 60):
        wait(lambda: all(self.is_server_active(x) for x in servers),
             timeout_seconds=timeout,
             sleep_seconds=10,
             waiting_for='instances to become at ACTIVE status')

    def wait_images_active(self, images, timeout=10 * 60):
        wait(lambda: all(self.is_image_active(x) for x in images),
             timeout_seconds=timeout,
             sleep_seconds=10,
             waiting_for='images to become at ACTIVE status')

    def wait_servers_ssh_ready(self, servers, timeout=10 * 60):
        wait(lambda: all(self.is_server_ssh_ready(x) for x in servers),
             timeout_seconds=timeout,
             sleep_seconds=10,
             waiting_for='instances to be ssh ready')

    def wait_servers_deleted(self, servers, timeout=3 * 60):
        wait(lambda: all(self.is_server_deleted(x) for x in servers),
             timeout_seconds=timeout,
             waiting_for='instances to be deleted')

    def wait_marker_in_servers_log(self, servers, marker, timeout=10 * 60):
        wait(lambda: all(marker in x.get_console_output() for x in servers),
             timeout_seconds=timeout,
             waiting_for='marker appears in all servers log')

    def create_server(self, name, image_id=None, flavor=1, userdata=None,
                      files=None, key_name=None, timeout=600,
                      wait_for_active=True, wait_for_avaliable=True, **kwargs):

        if image_id is None:
            image_id = self._get_cirros_image().id
        srv = self.nova.servers.create(name=name,
                                       image=image_id,
                                       flavor=flavor,
                                       userdata=userdata,
                                       files=files,
                                       key_name=key_name,
                                       **kwargs)

        if wait_for_active:
            self.wait_servers_active([srv], timeout=timeout)

        # wait for ssh ready
        if wait_for_avaliable:
            self.wait_servers_ssh_ready([srv], timeout=timeout)
        return self.get_instance_detail(srv.id)

    def is_server_ssh_ready(self, server):
        """Check ssh connect to server"""

        ssh_client = self.ssh_to_instance(self.env,
                                          server,
                                          username='fake',
                                          password='fake')
        return bool(ssh_client.check_connection())

    def is_server_deleted(self, server_id):
        try:
            instance = self.nova.servers.get(server_id)
            if instance.status == 'ERROR':
                raise InstanceError(instance)
            return False
        except nova_exceptions.NotFound:
            return True

    def get_hypervisor_capacity(self, hypervisor, flavor):
        """Return max available count of instances, which can be booted on
            hypervisor with choosed flavor

        :returns: possible instances count
        """
        if hypervisor.vcpus < flavor.vcpus:
            return 0
        if flavor.disk > 0:
            return min(hypervisor.disk_available_least // flavor.disk,
                       hypervisor.free_ram_mb // flavor.ram)
        else:
            return hypervisor.free_ram_mb // flavor.ram

    def wait_hypervisor_be_free(self, hypervisor):
        hyp_id = hypervisor.id
        wait(lambda: (self.nova.hypervisors.get(hyp_id).running_vms == 0),
             timeout_seconds=2 * 60,
             sleep_seconds=5,
             waiting_for='hypervisor {0} to be free'.format(
                 hypervisor.hypervisor_hostname))

    def get_nova_instance_ips(self, srv, version=None):
        """Return all nova instance ip addresses as dict

        Example return:
        {'floating': '10.109.2.2',
        'fixed': '192.168.1.2'}

        :param srv: nova instance
        :rtype: dict
        :return: Dict with server ips
        """
        srv.get()
        if version is None:
            return {x['OS-EXT-IPS:type']: x['addr']
                    for y in srv.addresses.values()
                    for x in y}
        else:
            return {x['OS-EXT-IPS:type']: x['addr']
                    for y in srv.addresses.values()
                    for x in y
                    if x['version'] == version}

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

    def add_router_to_l3_agent(self, router_id, l3_agent_id):
        return self.neutron.add_router_to_l3_agent(l3_agent_id,
                                                   {'router_id': router_id})

    def remove_router_from_l3_agent(self, router_id, l3_agent_id):
        return self.neutron.remove_router_from_l3_agent(router_id=router_id,
                                                        l3_agent=l3_agent_id)

    def list_ports_for_network(self, network_id, device_owner):
        return self.neutron.list_ports(
            network_id=network_id, device_owner=device_owner)['ports']

    def create_port(self, network_id):
        return self.neutron.create_port({'port': {'network_id': network_id}})

    def list_l3_agents(self):
        return self.list_all_neutron_agents('l3')

    def get_l3_agent_hosts(self, router_id):
        agents = self.get_l3_for_router(router_id)
        hosts = [i['host'] for i in agents]
        return hosts

    def get_l3_for_router(self, router_id, condition=lambda x: True):
        result = self.neutron.list_l3_agent_hosting_routers(router_id)
        return list(filter(condition, result['agents']))

    def create_network(self, name, tenant_id=None, qos_policy_id=None):
        network = {'name': name, 'admin_state_up': True}
        if tenant_id is not None:
            network['tenant_id'] = tenant_id
        if qos_policy_id is not None:
            network['qos_policy_id'] = qos_policy_id
        return self.neutron.create_network({'network': network})

    def delete_network(self, id):
        return self.neutron.delete_network(id)

    def create_subnet(self, network_id, name, cidr, tenant_id=None,
                      dns_nameservers=('8.8.8.8', '8.8.4.4')):
        subnet = {
            "network_id": network_id,
            "ip_version": 4,
            "cidr": cidr,
            "name": name
        }
        if tenant_id is not None:
            subnet['tenant_id'] = tenant_id
        if dns_nameservers is not None:
            subnet['dns_nameservers'] = dns_nameservers
        return self.neutron.create_subnet({'subnet': subnet})

    def create_subnet_ipv6(self, network_id, name, cidr, tenant_id=None,
                           **subnet_params):
        addr_mode = subnet_params.get('ipv6_addr_mode')
        ra_mode = subnet_params.get('ipv6_ra_mode')
        subnet = {
            "network_id": network_id,
            "ip_version": 6,
            "cidr": cidr,
            "name": name,
            "ipv6_ra_mode": ra_mode,
            "ipv6_address_mode": addr_mode
        }
        if tenant_id is not None:
            subnet['tenant_id'] = tenant_id
        return self.neutron.create_subnet({'subnet': subnet})

    def delete_subnet(self, id):
        return self.neutron.delete_subnet(id)

    def delete_net_subnet_smart(self, net_id):
        """Delete network and it's subnetwork(s).
        If subnet has dependencies like instances or routers - remove interface
        from instance or router.
        :param net_id: ID of network
        """
        def subnet_in_router_ports(subnet_id):
            routers_ports = self.neutron.list_ports(
                device_owner='network:router_interface')['ports']
            return subnet_id in str(routers_ports)

        net_info = self.neutron.list_networks(id=net_id)['networks']
        if len(net_info) == 0:
            logger.debug('Network [{0}] not present. '
                         'Nothing to delete.'.format(net_id))
            return

        net_name = net_info[0]['name']
        subnets_id = net_info[0]['subnets']

        # delete all subnets from net
        del_msg = 'Deleting SubNetwork [{sn}] from Network [{n}] ... '
        for subnet_id in subnets_id:
            subnet_name = self.neutron.show_subnet(subnet_id)['subnet']['name']
            logger.debug(del_msg.format(n=net_name, sn=subnet_name) + 'start')

            try:
                self.neutron.delete_subnet(subnet_id)
            except NeutronConflict:
                # Inst/router has assigned IP/port from subnet
                logger.debug("Seems that SubNetwork still in use. "
                             "Deleting interfaces from dependencies.")

                # -- Delete IPs from subnet from instances --
                # get instances with IPs from net
                insts_with_net = [x for x in self.nova.servers.findall()
                                  if net_name in getattr(x, 'networks', [])]
                for inst in insts_with_net:
                    # get ports(ips) from instances
                    inst_ports = self.neutron.list_ports(
                        device_id=inst.id, network_id=net_id)['ports']
                    inst_ports_ids = [x['id'] for x in inst_ports]
                    # detach interface/port/ip from instance
                    for port_id in inst_ports_ids:
                        self.nova.servers.interface_detach(inst.id, port_id)
                    # wait till interface will be deleted from instance
                    wait(
                        lambda: net_name not in str(
                            self.nova.servers.find(id=inst.id).networks),
                        timeout_seconds=60,
                        waiting_for="interface deletion from instance")

                # -- Delete Internal Interface from router --
                routers_ports = self.neutron.list_ports(
                    device_owner='network:router_interface')['ports']
                for router_ports in routers_ports:
                    # get router id that has attached port from subnet
                    routers_with_subnet_id = [
                        router_ports['device_id']
                        for x in router_ports['fixed_ips']
                        if x['subnet_id'] == subnet_id]
                    # delete interface from router
                    for router_id in routers_with_subnet_id:
                            self.router_interface_delete(
                                router_id=router_id, subnet_id=subnet_id)
                # wait till no subnet_id in list of router's ports
                wait(lambda: subnet_in_router_ports(subnet_id) is False,
                     timeout_seconds=60,
                     waiting_for="interface deletion from router")

                # -- Delete subnet --
                self.neutron.delete_subnet(subnet_id)
            logger.debug(del_msg.format(n=net_name, sn=subnet_name) + 'done')

        # Delete Network
        logger.debug('Deleting Network [{n}]'.format(n=net_name))
        self.neutron.delete_network(net_id)

    def list_subnets(self):
        return self.neutron.list_subnets()

    def list_networks(self):
        return self.neutron.list_networks()

    def list_subnetpools(self):
        return self.neutron.list_subnepools()

    def list_address_scopes(self):
        return self.neutron.list_address_scopes()

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
            wait(lambda:
                 self.neutron.show_port(port_id)['port']['status'] == "ACTIVE",
                 timeout_seconds=60,
                 waiting_for="floating_ip port is active")
            return flip['floatingip']

        fl_ips_pool = self.nova.floating_ip_pools.list()
        if fl_ips_pool:
            floating_ip = self.nova.floating_ips.create(
                pool=fl_ips_pool[0].name)
            self.nova.servers.add_floating_ip(srv, floating_ip)
            return floating_ip

    def disassociate_floating_ip(self, srv, floating_ip, use_neutron=False):
        def is_floating_ip_down():
            fl_ip = self.neutron.show_floatingip(identifier)
            return fl_ip['floatingip']['status'] == 'DOWN'
        if use_neutron:
            try:
                self.neutron.update_floatingip(
                    floatingip=floating_ip['id'],
                    body={'floatingip': {}})

                identifier = floating_ip['id']
                wait(is_floating_ip_down, timeout_seconds=60)
            except NeutronClientException:
                logger.info('The floatingip {} can not be disassociated.'
                            .format(floating_ip['id']))
        else:
            try:
                self.nova.servers.remove_floating_ip(srv, floating_ip)
            except nova_exceptions.ClientException:
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
            except nova_exceptions.ClientException:
                logger.info('floating_ip {} is not deletable'
                            .format(floating_ip))
            else:
                wait(
                    lambda: len(
                        self.nova.floating_ips.findall(
                            ip=floating_ip.ip)) == 0,
                    timeout_seconds=1 * 60,
                    waiting_for='floating {0} removal'.format(floating_ip.ip))

    def create_router(self, name, tenant_id=None, distributed=False):
        router = {'name': name, 'distributed': distributed}
        if tenant_id is not None:
            router['tenant_id'] = tenant_id
        return self.neutron.create_router({'router': router})

    def router_interface_add(self, router_id, subnet_id=None, port_id=None):
        body = {}
        if subnet_id:
            body['subnet_id'] = subnet_id
        elif port_id:
            body['port_id'] = port_id
        else:
            raise ValueError("subnet_id or port_id must be indicated.")
        self.neutron.add_interface_router(router_id, body)

    def router_interface_delete(self, router_id, subnet_id=None, port_id=None):
        body = {}
        if subnet_id:
            body['subnet_id'] = subnet_id
        elif port_id:
            body['port_id'] = port_id
        else:
            raise ValueError("subnet_id or port_id must be indicated.")
        self.neutron.remove_interface_router(router_id, body)

    def router_gateway_add(self, router_id, network_id):
        network = {
            'network_id': network_id
        }
        self.neutron.add_gateway_router(router_id, network)

    def delete_router(self, router_id):
        binded_ports = self.neutron.list_ports(
            device_id=router_id, device_owner=u'network:router_interface'
        )['ports']
        for port in binded_ports:
            self.router_interface_delete(router_id, port_id=port['id'])
        self.neutron.delete_router(router_id)

    def create_qos_policy(self, name):
        return self.neutron.create_qos_policy({'policy': {'name': name}})

    def delete_qos_policy(self, policy_id):
        self.neutron.delete_qos_policy(policy_id)

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

    def create_sec_group_for_ssh_ipv6(self):
        """Create security group with ipv6 and ipv4 rules
        for ping and ssh actions
        """
        name = "test-sg" + str(random.randint(1, 0x7fffffff))
        secgroup = self.nova.security_groups.create(
            name, "descr")
        logger.debug("Create new security group '{name}'".format(name=name))
        rulesets = [
            {
                # ssh ipv4
                'protocol': 'tcp',
                'port_range_min': 22,
                'port_range_max': 22,
                'security_group_id': secgroup.id,
                'ethertype': 'ipv4',
                'direction': 'ingress',
                'remote_ip_prefix': '0.0.0.0/0',
            },
            {
                # ping ipv4
                'protocol': 'icmp',
                'security_group_id': secgroup.id,
                'ethertype': 'ipv4',
                'direction': 'ingress',
                'remote_ip_prefix': '0.0.0.0/0',
            },
            {
                # ssh ipv6
                'protocol': 'tcp',
                'port_range_min': 22,
                'port_range_max': 22,
                'security_group_id': secgroup.id,
                'ethertype': 'ipv6',
                'direction': 'ingress',
            },
            {
                # ping ipv6
                'protocol': 'icmp',
                'security_group_id': secgroup.id,
                'ethertype': 'ipv6',
                'direction': 'ingress',
            }

        ]

        for ruleset in rulesets:
            self.neutron.create_security_group_rule(
                {'security_group_rule': ruleset})
        return secgroup

    def delete_security_group(self, sg):
        """Delete security group.
        If security group used by instances -> delete it from instances first.
        :param sg: security group to delete
        :type sg: novaclient.v2.security_groups.SecurityGroup
        """
        logger.debug("Deleting security group '{sg.name}'".format(sg=sg))

        # if sec group in use -> remove it from instance
        sg_search = {'name': sg.name}
        srvs_with_sg = [x
                        for x in self.nova.servers.findall()
                        if sg_search in getattr(x, 'security_groups', [])]
        for srv in srvs_with_sg:
            # remove sec group from instance
            logger.debug(('Removing sec group "{sg.name}" from instance '
                          '[{srv.name}:{srv.id}]').format(sg=sg,
                                                          srv=srv))
            self.nova.servers.remove_security_group(srv.id, sg.id)
        # delete security group
        self.nova.security_groups.delete(sg)
        logger.debug("Deleting security group "
                     "'{sg.name}' ... done".format(sg=sg))

    def create_key(self, key_name):
        return self.nova.keypairs.create(key_name)

    def delete_key(self, key_name):
        return self.nova.keypairs.delete(key_name)

    def get_port_by_fixed_ip(self, ip):
        """Returns neutron port by instance fixed ip"""
        for port in self.neutron.list_ports()['ports']:
            for ips in port['fixed_ips']:
                if ip == ips['ip_address']:
                    return port

    @property
    def ext_network(self):
        ext_networks = self.neutron.list_networks(
            **{'router:external': True, 'status': 'ACTIVE'})
        return ext_networks['networks'][0]

    @property
    def int_networks(self):
        return self.neutron.list_networks(**{'router:external': False,
                                             'status': 'ACTIVE'})['networks']

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
                self.neutron.delete_router(router['id'])
            except NeutronClientException:
                logger.info('the router {} is not deletable'.format(router))

    def delete_floating_ips(self):
        for floating_ip in self.nova.floating_ips.list():
            try:
                self.nova.floating_ips.delete(floating_ip)
            except nova_exceptions.ClientException:
                self.delete_floating_ip(floating_ip, use_neutron=True)

    def delete_servers(self):
        for server in self.nova.servers.list():
            try:
                self.nova.servers.delete(server)
            except nova_exceptions.ClientException:
                logger.info('nova server {} is not deletable'.format(server))

    def delete_keypairs(self):
        for key_pair in self.nova.keypairs.list():
            try:
                self.nova.keypairs.delete(key_pair)
            except nova_exceptions.ClientException:
                logger.info('key pair {} is not deletable'.format(key_pair.id))

    def delete_security_groups(self):
        for sg in self.nova.security_groups.list():
            if sg.description == 'Default security group':
                continue
            try:
                self.nova.security_groups.delete(sg)
            except nova_exceptions.ClientException:
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
                    self.neutron.remove_interface_router(
                        port['device_id'],
                        {
                            'router_id': port['device_id'],
                            'subnet_id': fixed_ip['subnet_id'],
                        }
                    )
            except NeutronClientException:
                logger.info('the port {} is not deletable'
                            .format(port['id']))

    def remove_port(self, port_id):
        """Remove port by port_id.

        :param port_id: id of port that should be deleted.
        """
        port = self.neutron.show_port(port_id)['port']
        try:
            for fixed_ip in port['fixed_ips']:
                self.neutron.remove_interface_router(
                    port['device_id'],
                    {
                        'router_id': port['device_id'],
                        'subnet_id': fixed_ip['subnet_id'],
                    }
                )
        except NeutronClientException:
            logger.info('port {} could not be deleted'.format(port['id']))

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

    def ssh_to_instance(self,
                        env,
                        vm,
                        vm_keypair=None,
                        username='cirros',
                        password=None,
                        proxy_node=None,
                        vm_ip=None):
        """Returns direct ssh client to instance via proxy"""
        # Update vm data
        vm.get()
        instance_ips = {ip['addr']: {'type': ip['OS-EXT-IPS:type'],
                                     'mac': ip['OS-EXT-IPS-MAC:mac_addr'],
                                     'net': n}
                        for n, ips in vm.addresses.items() for ip in ips}
        if vm_ip is not None:
            ip_type = instance_ips[vm_ip]['type']
        else:
            ip_type = 'fixed'
            vm_ip = next(k for k, v in instance_ips.items()
                         if v['type'] == 'fixed')

        logger.debug('Try to connect to vm {name} '
                     'with {ip} ({ip_type})'.format(name=vm.name,
                                                    ip=vm_ip,
                                                    ip_type=ip_type))
        proxies = []

        # retrieve proxy nodes
        if ip_type == 'fixed':
            vm_mac = instance_ips[vm_ip]['mac']
            net_id = self.neutron.list_ports(
                mac_address=vm_mac)['ports'][0]['network_id']
            dhcp_namespace = "qdhcp-{0}".format(net_id)
            if proxy_node is None:
                proxy_nodes = wait(
                    lambda: self.get_node_with_dhcp_for_network(net_id),
                    expected_exceptions=NeutronClientException,
                    timeout_seconds=60 * 3,
                    sleep_seconds=10,
                    waiting_for="any alive DHCP agent for instance network",
                    log=False)
            else:
                proxy_nodes = [proxy_node]

            for node in proxy_nodes:
                for pkey in env.admin_ssh_keys:
                    ip = env.find_node_by_fqdn(node).data['ip']
                    proxy = NetNsProxy(ip=ip, pkey=pkey, ns=dhcp_namespace,
                                       proxy_to_ip=vm_ip)
                    proxies.append(proxy)
        instance_keys = []
        if vm_keypair is not None:
            instance_keys.append(paramiko.RSAKey.from_private_key(six.StringIO(
                vm_keypair.private_key)))
        return SSHClient(vm_ip,
                         port=22,
                         username=username,
                         password=password,
                         private_keys=instance_keys,
                         proxies=proxies)

    def run_on_vm(self,
                  env,
                  vm,
                  vm_keypair=None,
                  command='uname',
                  vm_login="cirros",
                  timeout=3 * 60,
                  vm_password='cubswin:)',
                  vm_ip=None):
        """Execute command on vm and return CommandResult instance

        :param vm: server to execute command on
        :param vm_keypair: keypair used during vm creating
        :param command: command (or commands list) to execute
        :param vm_login: username to login to vm via ssh
        :param vm_password: password to login to vm via ssh
        :param timeout: type - int or None
            - if None - execute command and return results
            - if int - wait `timeout` seconds until command exit_code will be 0
        :rtype: mos_tests.environment.ssh.CommandResult
        :returns: result of command executing
        """
        results = []

        def execute(expected_exceptions=None):
            if not self.server_status_is(vm, 'ACTIVE'):
                return False
            expected_exceptions = expected_exceptions or ()
            with suppress(*expected_exceptions):
                with self.ssh_to_instance(env,
                                          vm,
                                          vm_keypair,
                                          username=vm_login,
                                          password=vm_password,
                                          vm_ip=vm_ip) as remote:
                    result = remote.execute(command)
                    results.append(result)
                    return result.is_ok

        if timeout is None:
            logger.info('Executing `{cmd}` on {vm}'.format(cmds=command,
                                                           vm=vm.name))
            execute()
        else:
            wait(lambda: execute(expected_exceptions=(Exception, )),
                 sleep_seconds=(1, 20, 2),
                 timeout_seconds=timeout,
                 waiting_for=("SSH commands: `{cmd}` completed "
                              "with 0 exit code").format(cmd=command))
        return results[-1]

    def wait_agents_alive(self, agt_ids_to_check):
        wait(lambda: all(agt['alive'] for agt in
                         self.neutron.list_agents()['agents']
                         if agt['id'] in agt_ids_to_check),
             timeout_seconds=5 * 60,
             waiting_for='agents is alive')

    def wait_agents_down(self, agt_ids_to_check):
        wait(lambda: all(not agt['alive'] for agt in
                         self.neutron.list_agents()['agents']
                         if agt['id'] in agt_ids_to_check),
             timeout_seconds=5 * 60,
             waiting_for='agents go down')

    def add_net(self, router_id, **subnet_params):
        i = len(self.neutron.list_networks()['networks']) + 1
        network = self.create_network(name='net%02d' % i)['network']
        logger.info('network {name}({id}) is created'.format(**network))
        self.create_subnet_and_interface(router_id, network['id'], i,
                                         **subnet_params)
        return network['id']

    def create_subnet_and_interface(self, router_id, net_id, num,
                                    **subnet_params):
        version = subnet_params.get('version')
        if version == 6:
            subnet = self.create_subnet_ipv6(
                network_id=net_id,
                name='netip6%02d__subnet' % num,
                cidr="2a00:11d8:1201:%d::/64" % num,
                **subnet_params)
        else:
            subnet = self.create_subnet(
                network_id=net_id,
                name='net%02d__subnet' % num,
                cidr="192.168.%d.0/24" % num)
        logger.info('subnet {name}({id}) is created'.format(
            **subnet['subnet']))
        self.router_interface_add(
            router_id=router_id,
            subnet_id=subnet['subnet']['id'])

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
        self.force_l3_reschedule(router_id, agt_id_to_move_on)

    def force_l3_reschedule(self, router_id, new_l3_agt_id=None,
                            current_l3_agt_id=None):
        logger.info('going to reschedule the router on new agent')
        if current_l3_agt_id is None:
            l3_agents = self.neutron.list_l3_agent_hosting_routers(
                router_id)['agents']
            if len(l3_agents) != 1:
                raise Exception("Can't determine l3 agent to move router from")
            current_l3_agt_id = l3_agents[0]['id']
        if new_l3_agt_id is None:
            all_l3_agts = self.neutron.list_agents(
                binary='neutron-l3-agent')['agents']
            available_l3_agts = [agt for agt in all_l3_agts
                                 if agt['id'] != current_l3_agt_id]
            new_l3_agt_id = available_l3_agts[0]['id']
        self.neutron.remove_router_from_l3_agent(current_l3_agt_id,
                                                 router_id)
        self.neutron.add_router_to_l3_agent(new_l3_agt_id,
                                            {"router_id": router_id})

        wait(lambda: self.neutron.list_l3_agent_hosting_routers(router_id),
             timeout_seconds=5 * 60, waiting_for="router moved to new agent")

    def reschedule_dhcp_agent(self, net_id, controller_fqdn):
        agent_list = self.neutron.list_agents(
            binary='neutron-dhcp-agent')['agents']
        agt_id_to_move_on = [agt['id'] for agt in agent_list
                             if agt['host'] == controller_fqdn][0]
        self.force_dhcp_reschedule(net_id, agt_id_to_move_on)

    def force_dhcp_reschedule(self, net_id, new_dhcp_agt_id):
        logger.info('going to reschedule network to specified '
                    'controller dhcp agent')
        current_dhcp_agt_id = self.neutron.list_dhcp_agent_hosting_networks(
            net_id)['agents'][0]['id']
        self.neutron.remove_network_from_dhcp_agent(current_dhcp_agt_id,
                                                    net_id)
        self.neutron.add_network_to_dhcp_agent(new_dhcp_agt_id,
                                               {'network_id': net_id})
        wait(lambda: self.neutron.list_dhcp_agent_hosting_networks(net_id),
             timeout_seconds=5 * 60,
             waiting_for="network reschedule to new dhcp agent")

    def _get_controller(self):
        # TODO(gdyuldin) remove this methods after moving to functions.os_cli
        return self.env.get_nodes_by_role('controller')[0]

    def tenant_create(self, name):
        # TODO(gdyuldin) remove this methods after moving to functions.os_cli
        with self._get_controller().ssh() as remote:
            return os_cli.OpenStack(remote).tenant_create(name=name)

    def tenant_delete(self, name):
        # TODO(gdyuldin) remove this methods after moving to functions.os_cli
        with self._get_controller().ssh() as remote:
            return os_cli.OpenStack(remote).tenant_delete(name=name)

    def user_create(self, name, password, tenant=None):
        # TODO(gdyuldin) remove this methods after moving to functions.os_cli
        with self._get_controller().ssh() as remote:
            return os_cli.OpenStack(remote).user_create(name=name,
                                                        password=password,
                                                        tenant=tenant)

    def user_delete(self, name):
        # TODO(gdyuldin) remove this methods after moving to functions.os_cli
        with self._get_controller().ssh() as remote:
            return os_cli.OpenStack(remote).user_delete(name=name)

    def server_hard_reboot(self, server):
        try:
            self.nova.servers.reboot(server.id, reboot_type='HARD')
        except nova_exceptions.ClientException:
            logger.info("nova server {} can't be rebooted".format(server))

    def server_start(self, server):
        try:
            self.nova.servers.start(server.id)
        except nova_exceptions.ClientException:
            logger.info("nova server {} can't be started".format(server))

    def server_stop(self, server):
        try:
            self.nova.servers.stop(server.id)
        except nova_exceptions.ClientException:
            logger.info("nova server {} can't be stopped".format(server))

    def rebuild_server(self, server, image):
        srv = server.rebuild(image)
        wait(lambda: self.nova.servers.get(srv).status == 'REBUILD',
             timeout_seconds=60, waiting_for='start of instance rebuild')
        return srv

    def delete_volume(self, volume):
        """Delete volume and check that it is absent in the list
        :param volume: volume object
        """
        self.delete_volumes([volume])

    def delete_volumes(self, volumes):
        ids = ', '.join([x.id for x in volumes])
        # Exclude non-existing volumes
        all_volumes = self.cinder.volumes.findall()
        provided_volumes_ids = [x.id for x in volumes]
        volumes = [x for x in all_volumes
                   if x.id in provided_volumes_ids]
        del all_volumes, provided_volumes_ids
        # Detach volume from instances; delete snapshots and backups from VOL.
        for volume in volumes:
            # if volume attached to any instance
            for attach in volume.attachments:
                serv_id = attach['server_id']
                self.nova.volumes.delete_server_volume(serv_id, volume.id)
            # if volume have snapshots
            snapshots = self.cinder.volume_snapshots.findall(
                volume_id=volume.id)
            for snapshot in snapshots:
                self.cinder.volume_snapshots.delete(snapshot)
            # if volume have backups
            backups = self.cinder.backups.findall(volume_id=volume.id)
            for backup in backups:
                self.cinder.backups.delete(backup)
        # Wait till volume will be detached and all connections will be removed
        wait(lambda: not any([self.cinder.backups.findall(volume_id=x.id)
                              for x in volumes]),
             timeout_seconds=60 * 10,
             waiting_for=('backups from volumes [{ids}] '
                          'to be deleted').format(ids=ids))
        wait(lambda: not any([self.cinder.volume_snapshots.findall(
                              volume_id=x.id) for x in volumes]),
             timeout_seconds=60 * 5,
             sleep_seconds=10,
             waiting_for=('snapshots from volumes [{ids}] '
                          'to be deleted').format(ids=ids))
        wait(lambda: all([self.cinder.volumes.get(x.id).status == 'available'
                          for x in volumes]),
             timeout_seconds=60 * 5,
             sleep_seconds=10,
             waiting_for=('volumes [{ids}] '
                          'to became available').format(ids=ids))
        # Delete volumes
        for volume in volumes:
            self.cinder.volumes.delete(volume.id)
            # Too fast deletion requests make deletion too long
            time.sleep(2)
        self.wait_volumes_deleted(volumes)

    def wait_volumes_deleted(self, volumes):
        ids = ', '.join([x.id for x in volumes])
        wait(
            lambda: not any([self.cinder.volumes.findall(id=x.id)
                             for x in volumes]),
            timeout_seconds=60 * 2,
            sleep_seconds=10,
            waiting_for='volumes [{ids}] to be deleted'.format(ids=ids))

    def is_server_cloud_init_finished(self, vm):
        finish_mark = 'Cloud-init .* finished'
        vm.get()
        if re.findall(finish_mark, vm.get_console_output()):
            return True
        else:
            return False

    def wait_servers_cloud_init_finished(self, vms, timeout=5 * 60):
        """Wait till vm will be booted and ready"""
        wait(lambda: all(self.is_server_cloud_init_finished(x) for x in vms),
             timeout_seconds=timeout,
             waiting_for='cloud init finish')
