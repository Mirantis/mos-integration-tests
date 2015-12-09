#    Copyright 2014 Mirantis, Inc.
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
"""Doc."""

import time

# TBD change the logger
from tools.settings import DISABLE_SSL
from tools.settings import logger
from tools.settings import PATH_TO_CERT

from cinderclient import client as cinderclient
from glanceclient.v1 import Client as glanceclient
from keystoneclient.exceptions import ClientException as KeyStoneException
from keystoneclient.v2_0 import Client as keystoneclient
from neutronclient.common.exceptions import NeutronClientException
from neutronclient.v2_0 import client as neutronclient
from novaclient.exceptions import ClientException as NovaClientException
from novaclient.v1_1 import Client as novaclient


class OpenStackActions(object):
    """Provides connection to the deployed OS cluster."""

    def __init__(self, controller_ip, user, password, tenant):
        """Doc."""
        self.controller_ip = controller_ip

        if DISABLE_SSL:
            auth_url = 'http://{0}:5000/v2.0/'.format(self.controller_ip)
            path_to_cert = None
        else:
            auth_url = 'https://{0}:5000/v2.0/'.format(self.controller_ip)
            path_to_cert = PATH_TO_CERT

        logger.debug('Auth URL is {0}'.format(auth_url))
        self.nova = novaclient(username=user,
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

        self.glance = glanceclient(endpoint=glance_endpoint,
                                   token=token,
                                   cacert=path_to_cert)

    def _get_keystoneclient(self, username, password, tenant_name, auth_url,
                            retries=3, ca_cert=None):
        keystone = None
        for i in range(retries):
            try:
                if ca_cert:
                    keystone = keystoneclient(username=username,
                                              password=password,
                                              tenant_name=tenant_name,
                                              auth_url=auth_url,
                                              cacert=ca_cert)

                else:
                    keystone = keystoneclient(username=username,
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

    def cleanup_network(self, networks_to_skip=[]):
        """Clean up the neutron networks.

        The networks that should be kept are passed as list of names
        """
        # net ids with the names from networks_to_skip are filtered out
        networks = [x['id'] for x in self.neutron.list_networks()['networks']
                    if x['name'] not in networks_to_skip]
        # Subnets and ports are simply filtered by network ids
        subnets = [x['id'] for x in self.neutron.list_subnets()['subnets']
                   if x['network_id'] in networks]
        ports = [x for x in self.neutron.list_ports()['ports']
                 if x['network_id'] in networks]
        # Did not find the better way to detect the fuel admin router
        # Looks like it just always has fixed name router04
        routers = [x['id'] for x in self.neutron.list_routers()['routers']
                   if x['name'] != 'router04']

        for key_pair in self.nova.keypairs.list():
            try:
                self.nova.keypairs.delete(key_pair)
            except NovaClientException:
                logger.info('key pair {} is not deletable'.
                             format(key_pair.id))

        for floating_ip in self.nova.floating_ips.list():
            try:
                self.nova.floating_ips.delete(floating_ip)
            except NovaClientException:
                logger.info('floating_ip {} is not deletable'.
                             format(floating_ip.id))

        for server in self.nova.servers.list():
            try:
                self.nova.servers.delete(server)
            except NovaClientException:
                logger.info('nova server {} is not deletable'.format(server))

        for sg in self.nova.security_groups.list():
            if sg.description != 'Default security group':
                try:
                    self.nova.security_groups.delete(sg)
                except NovaClientException:
                    logger.info('The Security Group {} is not deletable'
                                 .format(sg))

        # After some experiments the followin sequence for deleteion was found
        # roter_interface and ports -> subnets -> routers -> nets
        # Delete router interafce and ports
        # TBD some ports are still kept after the cleanup.
        # Need to find why and delete them as well
        # But it does not fail the executoin so far.
        for port in ports:
            try:
                # TBD Looks like the port migh be used either by router or
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
                logger.debug(
                    self.neutron.delete_port(port['id'])
                )
            except NeutronClientException:
                logger.info('the port {} is not deletable'
                            .format(port['id']))

        # Delete subnets
        for subnet in subnets:
            try:
                self.neutron.delete_subnet(subnet)
            except NeutronClientException:
                logger.info('the subnet {} is not deletable'
                            .format(subnet))

        # Delete routers
        for router in routers:
            try:
                self.neutron.delete_router(router)
            except NeutronClientException:
                logger.info('the router {} is not deletable'
                            .format(router))

        # Delete nets
        for net in networks:
            try:
                self.neutron.delete_network(net)
            except NeutronClientException:
                logger.info('the net {} is not deletable'
                            .format(net))
