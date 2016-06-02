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

import logging

import pytest
from six.moves import configparser

from mos_tests.functions import common


logger = logging.getLogger(__name__)


@pytest.yield_fixture
def set_recl_inst_interv(env, request):
    """Set 'reclaim_instance_interval' to 'nova.conf' on all nodes"""

    def nova_service_restart(nodes):
        for node in nodes:
            with node.ssh() as remote:
                if 'controller' in node.data['roles']:
                    remote.check_call(nova_restart_ctrllr)
                elif 'compute' in node.data['roles']:
                    remote.check_call(nova_restart_comput)

    nova_cfg_f = '/etc/nova/nova.conf'
    nova_restart_ctrllr = 'service nova-api restart && sleep 3'
    nova_restart_comput = 'service nova-compute restart && sleep 3'
    interv_sec = request.param  # reclaim_instance_interval

    logger.debug('In {0} set "reclaim_instance_interval={1}"'.format(
        nova_cfg_f, interv_sec))
    # take backup
    backup_f = nova_cfg_f + '_backup'
    backup = 'cp {0} {1}'.format(nova_cfg_f, backup_f)
    # modify nova config file
    nodes = (env.get_nodes_by_role('controller') +
             env.get_nodes_by_role('compute'))
    for node in nodes:
        with node.ssh() as remote:
            remote.check_call(backup)
            # set value
            with remote.open(nova_cfg_f, 'r') as f:
                parser = configparser.RawConfigParser()
                parser.readfp(f)
                parser.set('DEFAULT', 'reclaim_instance_interval', interv_sec)
            # write file
            with remote.open(nova_cfg_f, 'w') as new_f:
                parser.write(new_f)
    # restart services
    nova_service_restart(nodes)
    yield
    # revert original file
    logger.debug('Revert changes of nova.conf back')
    for node in nodes:
        with node.ssh() as remote:
            cmd = 'mv {0} {1}'.format(backup_f, nova_cfg_f)
            remote.check_call(cmd)
    # restart services
    nova_service_restart(nodes)


@pytest.yield_fixture
def network(os_conn, request):
    network = os_conn.create_network(name='net01')
    subnet = os_conn.create_subnet(network_id=network['network']['id'],
                                   name='net01__subnet',
                                   cidr='192.168.1.0/24')
    yield network
    if 'undestructive' in request.node.keywords:
        os_conn.delete_net_subnet_smart(
            network['network']['id'], subnet['subnet']['id'])


@pytest.yield_fixture
def keypair(os_conn, request):
    keypair = os_conn.create_key(key_name='instancekey')
    yield keypair
    if 'undestructive' in request.node.keywords:
        os_conn.delete_key(key_name=keypair.name)


@pytest.yield_fixture
def security_group(os_conn, request):
    sec_group = os_conn.create_sec_group_for_ssh()
    yield sec_group
    if 'undestructive' in request.node.keywords:
        os_conn.delete_security_group(sec_group)


@pytest.yield_fixture
def instances(request, os_conn, security_group, keypair, network):
    """Some instances (2 by default) on one compute node at one network"""
    zone = os_conn.nova.availability_zones.find(zoneName="nova")
    compute_host = zone.hosts.keys()[0]
    instances = []
    param = getattr(request, 'param', {'count': 2})
    for i in range(param['count']):
        instance = os_conn.create_server(
            name='server%02d' % i,
            availability_zone='{}:{}'.format(zone.zoneName, compute_host),
            key_name=keypair.name,
            nics=[{'net-id': network['network']['id']}],
            security_groups=[security_group.id],
            wait_for_active=False,
            wait_for_avaliable=False)
        instances.append(instance)
    os_conn.wait_servers_active(instances)
    os_conn.wait_servers_ssh_ready(instances)

    yield instances
    if 'undestructive' in request.node.keywords:
        for instance in instances:
            try:                         # if instance was deleted in test
                instance.force_delete()  # force - if soft deletion enabled
            except Exception as e:
                assert e.code == 404     # Instance not found
        common.wait(
            lambda: all(os_conn.is_server_deleted(x.id) for x in instances),
            timeout_seconds=60,
            waiting_for='instances to be deleted')
