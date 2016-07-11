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
from mos_tests.neutron.python_tests.base import TestBase

logger = logging.getLogger(__name__)


@pytest.yield_fixture
def projects(os_conn):
    names = ['A', 'B']
    projects = []
    for name in names:
        project = os_conn.keystone.tenants.create(name)
        projects.append(project)
        user = os_conn.session.get_user_id()
        admin_role = os_conn.keystone.roles.find(name='admin')
        project.add_user(user=user, role=admin_role)
    yield projects
    for project in projects:
        os_conn.keystone.tenants.delete(project)


@pytest.yield_fixture
def networks(projects, os_conn):
    networks = []
    for project in projects:
        network = os_conn.create_network('{0.name}_net'.format(project),
                                         tenant_id=project.id)['network']
        networks.append(network)
        os_conn.create_subnet(network['id'], '{0.name}_subnet'.format(project),
                              '10.0.0.0/24', tenant_id=project.id)
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
            'name': '{0.name}_sec_group'.format(project),
            'tenant_id': project.id
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
            cert=env.certificate, env=env, tenant=project.name)
        os_clients.append(os_conn)
    return os_clients


@pytest.yield_fixture
def servers(os_clients, networks, sec_groups):
    # boot instances
    zone = os_clients[0].nova.availability_zones.find(zoneName="nova")
    hostname = zone.hosts.keys()[0]

    servers = []
    for i, (os_conn, network, sec_group) in enumerate(
        zip(os_clients, networks, sec_groups)
    ):
        server1 = os_conn.create_server(
            name='server%02d' % (i * 2 + 1),
            availability_zone='{}:{}'.format(zone.zoneName, hostname),
            nics=[{'net-id': network['id'], 'v4-fixed-ip': '10.0.0.4'}],
            security_groups=[sec_group['id']],
            wait_for_active=False, wait_for_avaliable=False)
        server2 = os_conn.create_server(
            name='server%02d' % (i * 2 + 2),
            availability_zone='{}:{}'.format(zone.zoneName, hostname),
            nics=[{'net-id': network['id'], 'v4-fixed-ip': '10.0.0.5'}],
            security_groups=[sec_group['id']],
            wait_for_active=False, wait_for_avaliable=False)
        servers.append([server1, server2])

    for os_conn, servers_group in zip(os_clients, servers):
        os_conn.wait_servers_active(servers_group)

    for os_conn, servers_group in zip(os_clients, servers):
        os_conn.wait_servers_ssh_ready(servers_group)

    yield servers

    for servers_group in servers:
        for server in servers_group:
            server.delete()

    for os_conn, servers_group in zip(os_clients, servers):
        os_conn.wait_servers_deleted(servers_group)


def restart_ping(os_conn, env, servers):
    ping_cmd = 'ping {target_ip}'

    with os_conn.ssh_to_instance(env, servers[0], username='cirros',
                                 password='cubswin:)') as remote:
        remote.execute('killall ping')
        target_ip = servers[1].networks.values()[0][0]
        remote.background_call(ping_cmd.format(target_ip=target_ip))


def cmp_pings_ids(compute):
    """Compare pings isd and returns:
        <0 if UNREPLIED has lower id
        0 if ids is equal
        >0 if UNREPLIED has upper id
    """
    id_expr = re.compile(r'id=(?P<id>\d+)')
    with compute.ssh() as remote:
        output = remote.execute('conntrack -L | grep 10.0.0.4 | grep icmp')

    ping_ids = dict.fromkeys([True, False])
    for line in output['stdout']:
        id_val = int(id_expr.search(line).group('id'))
        key = '[UNREPLIED]' in line
        ping_ids[key] = max(id_val, ping_ids[key])
    return ping_ids[True] - ping_ids[False]


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
    def test_connectivity_between_vms_with_same_internal_ips(
            self, env, servers, os_clients):
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

        compute_fqdn = getattr(servers[0][0], 'OS-EXT-SRV-ATTR:host')
        compute = env.find_node_by_fqdn(compute_fqdn)

        for os_conn, servers_group in zip(os_clients, servers):
            restart_ping(os_conn, env, servers_group)

        for i in range(20):
            result = cmp_pings_ids(compute)
            if result == 0:
                break
            elif result > 0:
                logger.info('Restart pings without UNREPLIED')
                group = 0
            else:
                logger.info('Restart pings with UNREPLIED')
                group = 1
            restart_ping(os_clients[group], env, servers[group])
            time.sleep(30)
        else:
            raise Exception("Can't set same ids for pings")

        check_zones_assigment_to_devices(compute)
