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

from collections import defaultdict
import logging
import re
import time

import pytest

from mos_tests.environment.os_actions import OpenStackActions
from mos_tests.functions.common import wait
from mos_tests.neutron.python_tests.base import TestBase

logger = logging.getLogger(__name__)


@pytest.yield_fixture
def projects(openstack_client):
    names = ['A', 'B']
    projects = []
    for name in names:
        project = openstack_client.project_create(name)
        projects.append(project)
        openstack_client('role add',
                         params='--user admin --project {0} '
                                'admin -f json'.format(name))
    yield projects
    for name in names:
        openstack_client.project_delete(name)


@pytest.yield_fixture
def networks(projects, os_conn):
    networks = []
    for project in projects:
        network = os_conn.create_network('{name}_net'.format(**project),
                                         tenant_id=project['id'])['network']
        networks.append(network)
        os_conn.create_subnet(network['id'], '{name}_subnet'.format(**project),
                              '10.0.0.0/24', tenant_id=project['id'])
    yield networks
    for network in networks:
        for subnet in network['subnets']:
            os_conn.delete_subnet(subnet)
        os_conn.delete_network(network['id'])


@pytest.yield_fixture
def sec_groups(projects, os_conn):
    groups = []
    for i, project in enumerate(projects):
        group_data = {
            'name': '{name}_sec_group'.format(**project),
            'tenant_id': project['id']
        }
        group = os_conn.neutron.create_security_group({
            'security_group': group_data})['security_group']
        groups.append(group)

        rulesets = [
            {
                # ssh
                'ip_protocol': 'tcp',
                'from_port': 22,
                'to_port': 22,
                'cidr': '0.0.0.0/0',
            }
        ]
        if i == 0:
            rulesets += [
                {
                    # ping
                    'ip_protocol': 'icmp',
                    'from_port': -1,
                    'to_port': -1,
                    'cidr': '0.0.0.0/0',
                }
            ]
        for ruleset in rulesets:
            os_conn.nova.security_group_rules.create(
                group['id'], **ruleset)
    yield groups
    for group in groups:
        os_conn.neutron.delete_security_group(group['id'])


@pytest.fixture
def os_clients(env, projects):
    os_clients = []
    for project in projects:
        os_conn = OpenStackActions(
            controller_ip=env.get_primary_controller_ip(),
            cert=env.certificate, env=env, tenant=project['name'])
        os_clients.append(os_conn)
    return os_clients


@pytest.yield_fixture
def servers(os_conn, os_clients, networks, sec_groups):
    # boot instances
    zone = os_conn.nova.availability_zones.find(zoneName="nova")
    hostname = zone.hosts.keys()[0]

    servers = []
    for i, (os_conn, network, sec_group) in enumerate(
        zip(os_clients, networks, sec_groups)
    ):
        server1 = os_conn.create_server(
            name='server%02d' % (i * 2 + 1),
            availability_zone='{}:{}'.format(zone.zoneName, hostname),
            nics=[{'net-id': network['id']}],
            security_groups=[sec_group['id']],
            fixed_ip='10.0.0.4',
            wait_for_active=False, wait_for_avaliable=False)
        server2 = os_conn.create_server(
            name='server%02d' % (i * 2 + 2),
            availability_zone='{}:{}'.format(zone.zoneName, hostname),
            nics=[{'net-id': network['id']}],
            security_groups=[sec_group['id']],
            fixed_ip='10.0.0.5',
            wait_for_active=False, wait_for_avaliable=False)
        servers.extend([server1, server2])

    def is_all_instances_ready():
        for os_conn in os_clients:
            for server in os_conn.nova.servers.list():
                if not os_conn.is_server_active(server):
                    return False
                if not os_conn.is_server_ssh_ready(server):
                    return False
        return True

    wait(is_all_instances_ready, timeout_seconds=3 * 60,
         waiting_for='all instances are ready')
    # update states
    for i, server in enumerate(servers):
        servers[i] = server.manager.get(server)

    yield servers

    for server in servers:
        server.delete()

    def is_instances_deleted():
        for os_conn in os_clients:
            if not all(os_conn.is_server_deleted(x.id) for x in servers):
                return False
        return True

    wait(is_instances_deleted, timeout_seconds=60,
         waiting_for='instances deleted')


def restart_ping(os_clients, env, servers, group_num=None):
    os_conn1, os_conn2 = os_clients
    ping_cmd = 'ping {target_ip} < /dev/null > /dev/null 2&>1 &'
    if group_num is None or group_num % 2 == 0:
        with os_conn1.ssh_to_instance(env, servers[0], username='cirros',
                                      password='cubswin:)') as remote:
            remote.execute('killall ping')
            target_ip = servers[1].networks.values()[0][0]
            remote.check_call(ping_cmd.format(target_ip=target_ip))

    if group_num is None or group_num % 2 == 1:
        with os_conn2.ssh_to_instance(env, servers[2], username='cirros',
                                      password='cubswin:)') as remote:
            remote.execute('killall ping')
            target_ip = servers[3].networks.values()[0][0]
            remote.check_call(ping_cmd.format(target_ip=target_ip))


def is_ping_has_same_id(compute):
    id_expr = re.compile(r'id=(?P<id>\d+)')
    with compute.ssh() as remote:
        output = remote.execute('conntrack -L | grep 10.0.0.4 | grep icmp')

    if 'UNREPLIED' not in output.stdout_string:
        return False
    ids_data = defaultdict(set)
    for line in output['stdout']:
        id_val = int(id_expr.search(line).group('id'))
        ids_data[id_val].add('[UNREPLIED]' in line)
    last_id = max(ids_data.keys())
    return ids_data[last_id] == set([True, False])


def check_zones_assigment_to_devices(compute):
    __tracebackhide__ = True
    with compute.ssh() as remote:
        conntrack_output = remote.check_call(
            'conntrack -L | grep 10.0.0.4 | grep icmp')
        iptables_output = remote.check_call('iptables -L -t raw')

    zones = set()
    for line in conntrack_output['stdout']:
        zone = re.search(r'zone=(?P<zone>\d+)', line).group('zone')
        zones.add(zone)

    for start, line in enumerate(iptables_output['stdout']):
        if 'Chain neutron-openvswi-PREROUTING' in line:
            break
    start += 2
    zones_devices = defaultdict(list)

    for line in iptables_output['stdout'][start:]:
        data = re.split('\s+', line, maxsplit=6)
        if data[:-1] != ['CT', 'all', '--', 'anywhere', 'anywhere', 'PHYSDEV']:
            continue
        dev_data = re.search(
            r'match --physdev-in (?P<dev>.+?) CTzone (?P<zone>\d+)', data[-1]
        ).groupdict()
        if dev_data['zone'] not in zones:
            continue
        zones_devices[dev_data['zone']].append(dev_data['dev'])

    iptables_output = ''.join(iptables_output['stdout'][start - 2:])
    for devices in zones_devices.values():
        if len(devices) != 2:
            pytest.fail('Count of devices for some zone is not 2\n{}'.format(
                iptables_output))
        dev_types = set(x[:3] for x in devices)
        if dev_types != set(['tap', 'qvb']):
            pytest.fail('Devices is not tap and qvb for some zones\n{}'.format(
                iptables_output))


@pytest.mark.check_env_('is_ha', 'has_1_or_more_computes')
@pytest.mark.undestructive
class TestConntrackZones(TestBase):

    @pytest.mark.testrail_id('542629')
    def test_connectivity_between_vms_with_same_internal_ips(self, env,
            servers, os_clients):
        """Check connectivity between vms with the same internal ips in
        different tenants

        Scenario:
            1. Create tenants A and B
            2. In tenant A create net1 and subnet1 with CIDR 10.0.0.0/24
            3. In tenant A create security group sec1 and add rule that allows
                ingress icmp traffic
            4. In tenant B create net2 and subnet2 with CIDR 10.0.0.0/24
            5. In tenant B create security group sec2
            6. In tenant A boot 2 VMs in net1 specifying sec1 as security
                group: test1 with ip 10.0.0.4 and test2 with ip 10.0.0.5
            7. In tenant B boot 2 VMs: test3 with ip 10.0.0.4 and test4 with
                ip 10.0.0.5
            8. Check that all vms are on the same compute node
                (in another situation migrate them to the one compute)
            9. Go to test1 and ping test2 (don't stop ping)
            10. Go to compute node and run "conntrack -L | grep 10.0.0.4"
            11. Go to test3 and ping test4 (don't stop ping)
            12. Go to compute node and run "conntrack -L | grep 10.0.0.4 again"
            13. If ids is'n equal, go to the step 13. Else go to 16
            14. On test1 stop and start ping. Check that id for non UNREPLIED
                connection is equal to UNREPLIED (if not repeat this step some
                times)
            15. Check ping between test3 and test 4
            16. Run "conntrack -L | grep 10.0.0.4"
            17. On compute node run "iptables -L -t raw"
            18. Check that ouput contain rules that assign zones for tap and
                qvb devices
        """

        compute_fqdn = getattr(servers[0], 'OS-EXT-SRV-ATTR:host')
        compute = env.find_node_by_fqdn(compute_fqdn)

        restart_ping(os_clients, env, servers)
        for i in range(6):
            if is_ping_has_same_id(compute):
                break
            logger.info('Restart pings to make conntrack ids equal')
            restart_ping(os_clients, env, servers, i)
            time.sleep(30)
        else:
            raise Exception("Can't set same ids for pings")

        check_zones_assigment_to_devices(compute)
