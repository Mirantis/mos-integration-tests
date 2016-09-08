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

import csv
import itertools
import logging
from random import randint
import re

import pytest

from mos_tests.functions import common
from mos_tests.functions import file_cache
from mos_tests.neutron.python_tests import base
from mos_tests import settings

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.undestructive

BOOT_MARKER = 'INSTANCE BOOT COMPLETED'
TCP_PORT = 5002
UDP_PORT = 5003


def wait_instances_to_boot(os_conn, instances):
    common.wait(lambda: all(os_conn.is_server_active(x) for x in instances),
                timeout_seconds=5 * 60,
                waiting_for="instances became to active state")
    common.wait(
        lambda: all(BOOT_MARKER in x.get_console_output() for x in instances),
        timeout_seconds=5 * 60,
        waiting_for="instances to be ready")


def delete_ports_policy(os_conn):
    for port in os_conn.neutron.list_ports()['ports']:
        policy_id = port['qos_policy_id']
        if policy_id is not None:
            logger.debug('Deleting QoS policy from port')
            os_conn.neutron.update_port(port['id'],
                                        {'port': {'qos_policy_id': None}})
            os_conn.delete_qos_policy(policy_id)


def delete_net_policy(os_conn):
    for net in os_conn.neutron.list_networks()['networks']:
        policy_id = net['qos_policy_id']
        if policy_id is not None:
            logger.debug('Deleting QoS policy from net')
            os_conn.neutron.update_network(
                net['id'], {'network': {'qos_policy_id': None}})
            os_conn.delete_qos_policy(policy_id)


@pytest.yield_fixture(scope='class')
def iperf_image_id(os_conn):
    logger.info('Creating ubuntu image')
    image = os_conn.glance.images.create(name="image_ubuntu",
                                         disk_format='qcow2',
                                         container_format='bare')
    with file_cache.get_file(settings.UBUNTU_QCOW2_URL) as f:
        os_conn.glance.images.upload(image.id, f)

    logger.info('Ubuntu image created')
    yield image.id
    os_conn.glance.images.delete(image.id)


@pytest.fixture(scope='class')
def instance_keypair(os_conn):
    return os_conn.create_key(key_name='instancekey{0}'.format(
        randint(0, 1000)))


@pytest.fixture(scope='class')
def security_group(os_conn):
    secgroup = os_conn.create_sec_group_for_ssh()
    iperf_ruleset = [
        {
            'ip_protocol': 'tcp',
            'from_port': TCP_PORT,
            'to_port': TCP_PORT,
            'cidr': '0.0.0.0/0',
        },
        {
            'ip_protocol': 'udp',
            'from_port': UDP_PORT,
            'to_port': UDP_PORT,
            'cidr': '0.0.0.0/0',
        }
    ]
    for ruleset in iperf_ruleset:
        os_conn.nova.security_group_rules.create(
            secgroup.id, **ruleset)
    return secgroup


@pytest.fixture(scope='class')
def flavor(os_conn):
    return os_conn.nova.flavors.create(name='iperf_flavor',
                                       ram=1024,
                                       vcpus=1,
                                       disk=5)


@pytest.mark.check_env_('is_qos_enabled')
@pytest.mark.need_devops
class TestQoSBase(base.TestBase):
    @classmethod
    @pytest.fixture(scope='class', autouse=True)
    def variables(cls, os_conn, iperf_image_id, instance_keypair,
                  security_group):
        cls.zone = os_conn.nova.availability_zones.find(zoneName="nova")
        cls.security_group = security_group
        cls.instance_keypair = instance_keypair
        cls.os_conn = os_conn
        cls.image_id = iperf_image_id

    @classmethod
    @pytest.fixture(scope='class')
    def network(cls, variables, os_conn):
        cls.net = os_conn.create_network(name='net01')
        cls.subnet = os_conn.create_subnet(network_id=cls.net['network']['id'],
                                           name='net01__subnet',
                                           cidr='10.0.0.0/24')
        ext_net = os_conn.ext_network
        cls.router = os_conn.create_router(name='router01')
        os_conn.router_gateway_add(router_id=cls.router['router']['id'],
                                   network_id=ext_net['id'])

        os_conn.router_interface_add(router_id=cls.router['router']['id'],
                                     subnet_id=cls.subnet['subnet']['id'])

    @classmethod
    @pytest.yield_fixture(scope='class', autouse=True)
    def revert(cls, request, devops_env, snapshot_name):
        yield
        if hasattr(request.session, 'nextitem') and snapshot_name is not None:
            devops_env.revert_snapshot(snapshot_name)

    @pytest.yield_fixture
    def clean_net_policy(self, os_conn):
        yield
        delete_net_policy(os_conn)

    @pytest.yield_fixture
    def clean_port_policy(self, os_conn):
        yield
        delete_ports_policy(os_conn)

    @classmethod
    def boot_iperf_instance(cls, name, compute_node, net, udp=False, flavor=2):
        userdata = '\n'.join([
            '#!/bin/bash -v',
            'apt-get install -yq iperf',
            'iperf -s -p {tcp_port} <&- > /tmp/iperf.log 2>&1 &',
            'iperf -u -s -p {udp_port} <&- > /tmp/iperf_udp.log 2>&1 &',
            'echo "{marker}"',
        ]).format(marker=BOOT_MARKER,
                  tcp_port=TCP_PORT,
                  udp_port=UDP_PORT)

        return cls.os_conn.create_server(
            name=name,
            availability_zone='{}:{}'.format(cls.zone.zoneName, compute_node),
            image_id=cls.image_id,
            flavor=flavor,
            userdata=userdata,
            key_name=cls.instance_keypair.name,
            nics=[{'net-id': net['network']['id']}],
            security_groups=[cls.security_group.id],
            wait_for_active=False,
            wait_for_avaliable=False)

    def get_iperf_result(self,
                         remote,
                         server_ip,
                         time=80,
                         interval=20,
                         udp=False):
        interval = min(interval, time)
        port = UDP_PORT if udp else TCP_PORT
        if udp:
            cmd = ('iperf -u -c {ip} -p {port} -x CDMS -y C -t {time} '
                   '-i {interval} --bandwidth 10M')
        else:
            cmd = 'iperf -c {ip} -p {port} -y C -t {time} -i {interval}'
        result = remote.check_call(cmd.format(ip=server_ip,
                                              port=port,
                                              time=time,
                                              interval=interval))
        assert not result['stderr'], 'Error during iperf execution, {}'.format(
            result)
        if udp:
            # Show only server report
            stdout = result['stdout'][-1:]
        else:
            stdout = result['stdout']
            # Exclude summary
            if len(stdout) > 1:
                stdout = stdout[:-1]
            # Strip first result, because it almost always too high
            if len(stdout) > 1:
                stdout = stdout[1:]
        reader = csv.reader(stdout)
        for line in reader:
            yield line

    def check_iperf_bandwidth(self,
                              client,
                              server,
                              limit,
                              ip_type='fixed',
                              **kwargs):
        server_ip = self.os_conn.get_nova_instance_ips(server)[ip_type]
        with self.os_conn.ssh_to_instance(
                self.env,
                client,
                username='ubuntu',
                vm_keypair=self.instance_keypair) as remote:
            for line in self.get_iperf_result(remote, server_ip, **kwargs):
                bandwidth = int(line[8])
                if bandwidth < 0.75 * limit:
                    raise Exception(
                        'Bandwidth is too low: {0}, limit is {1}'.format(
                            bandwidth, limit))
                assert bandwidth <= limit * 1.05


@pytest.mark.check_env_('has_1_or_more_computes')
class TestSingleCompute(TestQoSBase):
    @classmethod
    @pytest.fixture(scope='class')
    def instances(cls, variables, network, iperf_image_id, os_conn, flavor):
        instances = []
        compute_node = cls.zone.hosts.keys()[0]
        for i in range(2):
            instance = cls.boot_iperf_instance(name='server%02d' % i,
                                               compute_node=compute_node,
                                               net=cls.net,
                                               flavor=flavor)
            instances.append(instance)
        wait_instances_to_boot(os_conn, instances)
        return instances

    @pytest.mark.testrail_id('838298')
    def test_traffic_restriction_with_max_burst(self, instances, os_conn,
                                                clean_net_policy):
        """Check traffic restriction between vm for different max-burst
        parameter

        Scenario:
            1. Create net01, subnet
            2. Create router01, set gateway and add interface to net01
            3. Create new policy: neutron qos-policy-create policy_1
            4. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id policy_1 \
                --max-kbps 4000 --max-burst-kbps 300
            5. Update net01 with --qos-policy parameter
            6. Boot ubuntu vm1 in net01 on compute-1
            7. Boot ubuntu vm2 in net01 on compute-1
            8. Start iperf between vm1 and vm2
            9. Check that egress traffic on vm1 must be eq
                --max-kbps + --max-burst
            10. Update rule for vm port:
                neutron qos-bandwidth-limit-rule-update rule-id bw-limiter \
                --max-kbps 6000 --max-burst-kbps 500
            9. Check that egress traffic on vm1 must be eq
                --max-kbps + --max-burst
        """
        policy = os_conn.create_qos_policy('policy_1')
        rule = os_conn.neutron.create_bandwidth_limit_rule(
            policy['policy']['id'], {
                'bandwidth_limit_rule': {
                    'max_kbps': 4000,
                    'max_burst_kbps': 300,
                }
            })
        os_conn.neutron.update_network(
            self.net['network']['id'],
            {'network': {'qos_policy_id': policy['policy']['id']}})

        client, server = instances
        self.check_iperf_bandwidth(client, server, (4000 + 300) * 1024)

        self.os_conn.neutron.update_bandwidth_limit_rule(
            rule['bandwidth_limit_rule']['id'], policy['policy']['id'], {
                'bandwidth_limit_rule': {
                    'max_kbps': 6000,
                    'max_burst_kbps': 500,
                }
            })
        self.check_iperf_bandwidth(client, server, (6000 + 500) * 1024)


@pytest.mark.check_env_('has_2_or_more_computes')
class DifferentComputesInstancesMixin(object):
    @classmethod
    @pytest.fixture(scope='class')
    def instances(cls, variables, network, iperf_image_id, os_conn, flavor):
        instances = []
        compute_nodes = cls.zone.hosts.keys()[:2]
        for i in range(2):
            instance = cls.boot_iperf_instance(name='server%02d' % i,
                                               compute_node=compute_nodes[i],
                                               net=cls.net,
                                               flavor=flavor)
            instances.append(instance)
        wait_instances_to_boot(os_conn, instances)
        return instances


@pytest.mark.check_env_('is_qos_enabled')
class TestTraficBetweenComputes(DifferentComputesInstancesMixin, TestQoSBase):
    @pytest.mark.testrail_id('838303')
    def test_qos_between_vms_on_different_computes(self, instances, os_conn,
                                                   clean_port_policy):
        """Check different traffic restriction for vms between two vms
        in one net on different compute node

        Scenario:
            1. Create net01, subnet
            2. Create router01, set gateway and add interface to net01
            3. Boot ubuntu vm1 in net01 on compute-1
            4. Boot ubuntu vm2 in net01 on compute-2
            5. Start iperf between vm1 and vm2
            6. Look on the traffic with nload on vm port on compute-1
            7. Create new policy: neutron qos-policy-create bw-limiter
            8. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id bw-limiter \
                --max-kbps 3000
            9. Find neutron port for vm1: neutron port-list | grep <vm1 ip>
            10. Update port with new policy:
                neutron port-update your-port-id --qos-policy bw-limiter
            11. Create new policy: neutron qos-policy-create bw-limiter_2
            12. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id bw-limiter_2 \
                --max-kbps 4000
            13. Update port with new policy:
                neutron port-update your-port-id --qos-policy bw-limiter_2
            14. Check in nload that traffic changed properly for both vms
        """

        instance1, instance2 = instances
        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1,
                                       instance2,
                                       limit=4000 * 1024,
                                       time=20)

        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance2,
                                       instance1,
                                       limit=4000 * 1024,
                                       time=20)

        instance1_ip = os_conn.get_nova_instance_ips(instance1)['fixed']
        port1 = os_conn.get_port_by_fixed_ip(instance1_ip)

        # Create policy with rule and apply it to instance1 port
        policy1 = os_conn.create_qos_policy('bw-limiter')
        os_conn.neutron.create_bandwidth_limit_rule(policy1['policy']['id'], {
            'bandwidth_limit_rule': {
                'max_kbps': 3000,
            }
        })
        os_conn.neutron.update_port(
            port1['id'], {'port': {'qos_policy_id': policy1['policy']['id']}})

        instance2_ip = os_conn.get_nova_instance_ips(instance2)['fixed']
        port2 = os_conn.get_port_by_fixed_ip(instance2_ip)

        # Create policy with rule and apply it to instance2 port
        policy2 = os_conn.create_qos_policy('bw-limiter_2')
        os_conn.neutron.create_bandwidth_limit_rule(policy2['policy']['id'], {
            'bandwidth_limit_rule': {
                'max_kbps': 4000,
            }
        })
        os_conn.neutron.update_port(
            port2['id'], {'port': {'qos_policy_id': policy2['policy']['id']}})

        self.check_iperf_bandwidth(instance1, instance2, limit=3000 * 1024)

        self.check_iperf_bandwidth(instance2, instance1, limit=4000 * 1024)

    @pytest.mark.testrail_id('838310')
    def test_restrictions_on_net_and_vm(self, instances, os_conn,
                                        clean_port_policy, clean_net_policy):
        """Check traffic restriction between vms if there are different
        restrictions in the net and vm

        Scenario:
            1. Create net01, subnet
            2. Create router01, set gateway and add interface to net01
            3. Create new policy: neutron qos-policy-create policy_1
            4. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id policy_1 \
                --max-kbps 4000 --max-burst-kbps 300
            5. Update net01 with --qos-policy parameter
            6. Boot ubuntu vm1 in net01 on compute-1
            7. Boot ubuntu vm2 in net01 on compute-2
            8. Start iperf between vm1 and vm2
            9. Look on the traffic with nload on vm port on compute-1
            10. Create new policy: neutron qos-policy-create bw-limiter
            11. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id bw-limiter \
                --max-kbps 3000
            12. Find neutron port for vm1: neutron port-list | grep <vm1 ip>
            13. Update port with new policy:
                neutron port-update your-port-id --qos-policy bw-limiter
            14. Check in nload that traffic changed properly
            15. Update rule for vm port:
                neutron qos-bandwidth-limit-rule-update rule-id bw-limiter \
                --max-kbps 6000
        """
        instance1, instance2 = instances

        # Create policy for net
        policy1 = os_conn.create_qos_policy('policy_1')
        os_conn.neutron.create_bandwidth_limit_rule(policy1['policy']['id'], {
            'bandwidth_limit_rule': {
                'max_kbps': 4000,
                'max_burst_kbps': 300,
            }
        })
        os_conn.neutron.update_network(
            self.net['network']['id'],
            {'network': {'qos_policy_id': policy1['policy']['id']}})

        self.check_iperf_bandwidth(instance1, instance2, (4000 + 300) * 1024)

        # Create policy for port
        instance1_ip = os_conn.get_nova_instance_ips(instance1)['fixed']
        port1 = os_conn.get_port_by_fixed_ip(instance1_ip)
        port_policy = os_conn.create_qos_policy('policy_2')
        port_rule = os_conn.neutron.create_bandwidth_limit_rule(
            port_policy['policy']['id'], {
                'bandwidth_limit_rule': {
                    'max_kbps': 3000,
                }
            })

        os_conn.neutron.update_port(
            port1['id'],
            {'port': {'qos_policy_id': port_policy['policy']['id']}})

        self.check_iperf_bandwidth(instance1, instance2, limit=3000 * 1024)

        # Update rule for port
        os_conn.neutron.update_bandwidth_limit_rule(
            port_rule['bandwidth_limit_rule']['id'],
            port_policy['policy']['id'], {
                'bandwidth_limit_rule': {
                    'max_kbps': 6000,
                }
            })

        self.check_iperf_bandwidth(instance1, instance2, limit=6000 * 1024)

    @pytest.mark.testrail_id('838305')
    def test_restriction_for_net(self, instances, os_conn, clean_net_policy):
        """Check traffic restriction for net between two vms after
        updating rule for net

        Scenario:
            1. Create net01, subnet
            2. Create router01, set gateway and add interface to net01
            3. Create new policy: neutron qos-policy-create bw-limiter
            4. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id bw-limiter \
                --max-kbps 3000
            5. Boot ubuntu vm1 in net01 on compute-1
            6. Boot ubuntu vm2 in net01 on compute-2
            7. Start iperf between vm1 and vm2
            8. Look on the traffic with nload on vm port on compute-1
            9. Check in nload that traffic changed properly for both vms
            10. Update your net:
                neutron net-update net01 --qos-policy bw-limiter
            11. Check in nload that traffic changed properly for both vms
        """
        # Create policy
        policy1 = os_conn.create_qos_policy('policy_1')
        os_conn.neutron.create_bandwidth_limit_rule(policy1['policy']['id'], {
            'bandwidth_limit_rule': {
                'max_kbps': 3000,
            }
        })

        instance1, instance2 = instances
        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1,
                                       instance2,
                                       limit=3000 * 1024,
                                       time=20)

        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance2,
                                       instance1,
                                       limit=3000 * 1024,
                                       time=20)
        # Update net with policy
        os_conn.neutron.update_network(
            self.net['network']['id'],
            {'network': {'qos_policy_id': policy1['policy']['id']}})

        self.check_iperf_bandwidth(instance1, instance2, limit=3000 * 1024)

        self.check_iperf_bandwidth(instance2, instance1, limit=3000 * 1024)


@pytest.mark.check_env_('is_qos_enabled')
class TestPolicyWithNetCreate(DifferentComputesInstancesMixin, TestQoSBase):
    @classmethod
    @pytest.fixture(scope='class')
    def network(cls, variables, os_conn):
        cls.policy = os_conn.create_qos_policy('policy_1')
        cls.rule = os_conn.neutron.create_bandwidth_limit_rule(
            cls.policy['policy']['id'], {
                'bandwidth_limit_rule': {
                    'max_kbps': 3000,
                }
            })
        cls.net = os_conn.create_network(
            name='net01',
            qos_policy_id=cls.policy['policy']['id'])
        cls.subnet = os_conn.create_subnet(network_id=cls.net['network']['id'],
                                           name='net01__subnet',
                                           cidr='10.0.0.0/24')
        ext_net = os_conn.ext_network
        cls.router = os_conn.create_router(name='router01')
        os_conn.router_gateway_add(router_id=cls.router['router']['id'],
                                   network_id=ext_net['id'])

        os_conn.router_interface_add(router_id=cls.router['router']['id'],
                                     subnet_id=cls.subnet['subnet']['id'])

    @pytest.mark.testrail_id('838306')
    def test_create_net_with_policy(self, os_conn, instances):
        """Check traffic restriction for net between two vms in one net
        on different compute nodes (create net with policy)

        Scenario:
            1. Create new policy: neutron qos-policy-create bw-limiter
            2. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id bw-limiter \
                --max-kbps 3000
            3. Create net01 with parameter --qos-policy bw-limiter , subnet
            4. Create router01, set gateway and add interface to net01
            5. Boot ubuntu vm1 in net01 on compute-1
            6. Boot ubuntu vm2 in net01 on compute-2
            7. Start iperf between vm1 and vm2
            8. Look on the traffic with nload on vm port on compute-1
            9. Check in nload that traffic changed properly for both vms
            10. Delete rule:
                neutron qos-bandwidth-limit-rule-delete rule-id bw-limiter
            11. Check in nload that traffic changed properly for both vms
        """

        self.check_iperf_bandwidth(instances[0],
                                   instances[1],
                                   limit=3000 * 1024)

        os_conn.neutron.delete_bandwidth_limit_rule(
            self.rule['bandwidth_limit_rule']['id'],
            self.policy['policy']['id'])

        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instances[0],
                                       instances[1],
                                       limit=3000 * 1024,
                                       time=20)


@pytest.mark.check_env_('has_2_or_more_computes')
class TestTraficBetween3InstancesInOneNet(TestQoSBase):
    @classmethod
    @pytest.fixture(scope='class')
    def instances(cls, variables, network, iperf_image_id, os_conn, flavor):
        instances = []
        compute_nodes = cls.zone.hosts.keys()[:2]
        compute_nodes.insert(0, compute_nodes[0])
        for i, node in enumerate(compute_nodes):
            instance = cls.boot_iperf_instance(name='server%02d' % i,
                                               compute_node=node,
                                               net=cls.net,
                                               flavor=flavor)
            instances.append(instance)
        wait_instances_to_boot(os_conn, instances)
        return instances

    @pytest.mark.testrail_id('838299', udp=False)
    @pytest.mark.testrail_id('839064', udp=True)
    @pytest.mark.parametrize('udp', [True, False], ids=['udp', 'tcp'])
    def test_traffic_for_one_vm_and_2_another(self, instances, os_conn, udp,
                                              clean_port_policy):
        """Check traffic restriction for one vm between two vms in one net

        Scenario:
            1. Create net01, subnet
            2. Create router01, set gateway and add interface to net01
            3. Boot ubuntu vm1 in net01 on compute-1
            4. Boot ubuntu vm2 in net01 on compute-1
            5. Boot ubuntu vm3 in net01 on compute-2
            6. Start iperf between vm1 and vm2
            7. Look on the traffic with nload on vm port on compute-1
            8. Start iperf between vm1 and vm3
            9. Look on the traffic with nload on vm port on compute-1
            10. Create new policy: neutron qos-policy-create bw-limiter
            11. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id bw-limiter \
                --max-kbps 3000
            12. Find neutron port for vm1: Neutron port-list | grep <vm1 ip>
            13. Update port with new policy:
                neutron port-update your-port-id --qos-policy bw-limiter
            14. Check in nload that traffic changed properly
        """

        instance1, instance2, instance3 = instances

        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1,
                                       instance2,
                                       limit=3000 * 1024,
                                       time=10,
                                       udp=udp)

        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1,
                                       instance3,
                                       limit=3000 * 1024,
                                       time=10,
                                       udp=udp)

        # Create policy for port
        instance1_ip = os_conn.get_nova_instance_ips(instance1)['fixed']
        port1 = os_conn.get_port_by_fixed_ip(instance1_ip)
        port_policy = os_conn.create_qos_policy('policy_2')
        os_conn.neutron.create_bandwidth_limit_rule(
            port_policy['policy']['id'], {
                'bandwidth_limit_rule': {
                    'max_kbps': 3000,
                }
            })

        os_conn.neutron.update_port(
            port1['id'],
            {'port': {'qos_policy_id': port_policy['policy']['id']}})

        self.check_iperf_bandwidth(instance1,
                                   instance2,
                                   limit=3000 * 1024,
                                   udp=udp)

        self.check_iperf_bandwidth(instance1,
                                   instance3,
                                   limit=3000 * 1024,
                                   udp=udp)

    @pytest.mark.testrail_id('844685')
    def test_traffic_for_one_vm_and_2_another_dissociate_policy(
            self, instances, os_conn, clean_port_policy):
        """Check traffic restriction creating vm with qos policy and
        dissociate this policy.

        Scenario:
            1. Create net01, subnet;
            2. Create router01, set gateway and add interface to net01;
            3. Boot ubuntu vm1 in net01 on compute-1;
            4. Boot ubuntu vm2 in net01 on compute-1;
            5. Boot ubuntu vm3 in net01 on compute-2;
            6. Start iperf between vm1 and vm2;
            7. Look on the traffic with nload on vm port on compute-1;
            8. Start iperf between vm1 and vm3;
            9. Look on the traffic with nload on vm port on compute-1;
            10. Create new policy: neutron qos-policy-create bw-limiter;
            11. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id bw-limiter \
                --max-kbps 3000;
            12. Find neutron port for vm1: Neutron port-list | grep <vm1 ip>;
            13. Update port with new policy:
                neutron port-update your-port-id --qos-policy bw-limiter;
            14. Check in nload that traffic changed properly;
            15. Delete qos rule from port;
            16. Check that there are no bandwidth limitation.
        """
        limit = 3000  # 3 Mbit/sec
        instance1, instance2, instance3 = instances

        # Check that there are no QoS limits and VMs accessible
        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1, instance2,
                                       limit=limit * 1024, time=20)
        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1, instance3,
                                       limit=limit * 1024, time=20)

        # Create limit policy for VM's port
        instance1_ip = os_conn.get_nova_instance_ips(instance1)['fixed']
        port1 = os_conn.get_port_by_fixed_ip(instance1_ip)
        port_policy = os_conn.create_qos_policy('policy_2')
        os_conn.neutron.create_bandwidth_limit_rule(
            port_policy['policy']['id'],
            {'bandwidth_limit_rule': {'max_kbps': limit, }})
        # Update VM's port with a new policy
        os_conn.neutron.update_port(
            port1['id'],
            {'port': {'qos_policy_id': port_policy['policy']['id']}})

        # Check bandwidth after set QoS limit
        self.check_iperf_bandwidth(instance1, instance2,
                                   limit=limit * 1024)
        self.check_iperf_bandwidth(instance1, instance3,
                                   limit=limit * 1024,)

        # Delete QoS limit and check that bandwidth has no limits
        delete_ports_policy(os_conn)
        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1, instance3,
                                       limit=limit * 1024)


@pytest.mark.check_env_('has_2_or_more_computes')
class TwoNetAndComputesThreeInstances(object):
    @classmethod
    @pytest.fixture(scope='class')
    def instances(cls, variables, network, iperf_image_id, os_conn, network2,
                  flavor):
        instances = []
        compute_nodes = cls.zone.hosts.keys()[:2]
        compute_nodes.insert(0, compute_nodes[0])
        networks = [cls.net, network2, network2]
        for i, (node, net) in enumerate(zip(compute_nodes, networks)):
            instance = cls.boot_iperf_instance(name='server%02d' % i,
                                               compute_node=node,
                                               net=net,
                                               flavor=flavor)
            instances.append(instance)
        wait_instances_to_boot(os_conn, instances)
        for instance in instances:
            os_conn.assign_floating_ip(instance)
        return instances


@pytest.mark.check_env_('is_qos_enabled')
@pytest.mark.incremental
class TestTraficBetween3InstancesInDifferentNet(
        TwoNetAndComputesThreeInstances, TestQoSBase):
    @classmethod
    @pytest.fixture(scope='class')
    def network2(cls, variables, os_conn, network):
        net = os_conn.create_network(name='net02')
        subnet = os_conn.create_subnet(network_id=net['network']['id'],
                                       name='net02__subnet',
                                       cidr='10.0.1.0/24')

        os_conn.router_interface_add(router_id=cls.router['router']['id'],
                                     subnet_id=subnet['subnet']['id'])
        return net

    @pytest.mark.testrail_id('838301')
    def test_traffic_with_different_nets(self, instances, os_conn):
        """Check traffic restriction for one vm between two vms in different
        nets with router between them

        Scenario:
            1. Create net01, subnet
            2. Create net02, subnet
            3. Create router01, set gateway and add interfaces to net01 and
                to net02
            4. Boot ubuntu vm1 in net01 on compute-1
            5. Boot ubuntu vm2 in net02 on compute-1
            6. Boot ubuntu vm3 in net02 on compute-2
            7. Associate floatings to all vms
            8. Start iperf between vm1 and vm2 by floating
            9. Look on the traffic with nload on vm port on compute-1
            10. Start iperf between vm1 and vm3
            11. Look on the traffic with nload on vm port on compute-1
            12. Create new policy: neutron qos-policy-create bw-limiter
            13. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id bw-limiter \
                --max-kbps 3000
            14. Find neutron port for vm1: neutron port-list | grep <vm1 ip>
            15. Update port with new policy:
                neutron port-update your-port-id --qos-policy bw-limiter
            16. Check in nload that traffic changed properly
        """
        instance1, instance2, instance3 = instances

        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1,
                                       instance2,
                                       limit=3000 * 1024,
                                       ip_type='floating',
                                       time=20)

        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1,
                                       instance3,
                                       limit=3000 * 1024,
                                       time=20)

        # Create policy for port
        instance1_ip = os_conn.get_nova_instance_ips(instance1)['fixed']
        port1 = os_conn.get_port_by_fixed_ip(instance1_ip)
        self.__class__.policy = os_conn.create_qos_policy('policy_1')
        self.__class__.rule = os_conn.neutron.create_bandwidth_limit_rule(
            self.__class__.policy['policy']['id'], {
                'bandwidth_limit_rule': {
                    'max_kbps': 3000,
                }
            })

        os_conn.neutron.update_port(
            port1['id'],
            {'port': {'qos_policy_id': self.__class__.policy['policy']['id']}})

        self.check_iperf_bandwidth(instance1,
                                   instance2,
                                   limit=3000 * 1024,
                                   ip_type='floating')

        self.check_iperf_bandwidth(instance1, instance3, limit=3000 * 1024)

    @pytest.mark.testrail_id('838302')
    def test_traffic_with_different_nets_after_rule_update(self, instances,
                                                           os_conn):
        """Check traffic restriction for one vm between two vms in one net
        on one compute node during updating rule

        Scenario:
            1. Create net01, subnet
            2. Create net02, subnet
            3. Create router01, set gateway and add interfaces to net01 and
                to net02
            4. Boot ubuntu vm1 in net01 on compute-1
            5. Boot ubuntu vm2 in net02 on compute-1
            6. Boot ubuntu vm3 in net02 on compute-2
            7. Associate floatings to all vms
            8. Start iperf between vm1 and vm2 by floating
            9. Look on the traffic with nload on vm port on compute-1
            10. Start iperf between vm1 and vm3
            11. Look on the traffic with nload on vm port on compute-1
            12. Create new policy: neutron qos-policy-create bw-limiter
            13. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id bw-limiter \
                --max-kbps 3000
            14. Find neutron port for vm1: neutron port-list | grep <vm1 ip>
            15. Update port with new policy:
                neutron port-update your-port-id --qos-policy bw-limiter
            16. Check in nload that traffic changed properly
            17. Update rule:
                neutron qos-bandwidth-limit-rule-update rule-id bw-limiter \
                --max-kbps 1000
            18. Check in nload that traffic is changed properly
        """
        instance1, instance2, instance3 = instances

        os_conn.neutron.update_bandwidth_limit_rule(
            self.__class__.rule['bandwidth_limit_rule']['id'],
            self.__class__.policy['policy']['id'], {
                'bandwidth_limit_rule': {
                    'max_kbps': 1000,
                }
            })
        self.check_iperf_bandwidth(instance1,
                                   instance2,
                                   limit=1000 * 1024,
                                   ip_type='floating')

        self.check_iperf_bandwidth(instance1, instance3, limit=1000 * 1024)


@pytest.mark.check_env_('is_qos_enabled')
class TestWithFloating(TwoNetAndComputesThreeInstances, TestQoSBase):
    @classmethod
    @pytest.fixture(scope='class')
    def router2(cls, variables, os_conn):
        ext_net = os_conn.ext_network
        router = os_conn.create_router(name='router02')
        os_conn.router_gateway_add(router_id=router['router']['id'],
                                   network_id=ext_net['id'])
        return router

    @classmethod
    @pytest.fixture(scope='class')
    def network2(cls, variables, os_conn, router2):
        net = os_conn.create_network(name='net02')
        subnet = os_conn.create_subnet(network_id=net['network']['id'],
                                       name='net02__subnet',
                                       cidr='10.0.1.0/24')

        os_conn.router_interface_add(router_id=router2['router']['id'],
                                     subnet_id=subnet['subnet']['id'])
        return net

    @pytest.mark.testrail_id('838300')
    def test_restrictions(self, instances, os_conn, clean_port_policy):
        """Check traffic restriction for one vm between two vms
        in different nets by floatings

        Scenario:
            1. Create net01, subnet
            2. Create router01, set gateway and add interface to net01
            3. Create net02, subnet
            4. Create router02, set gateway and add interface to net02
            5. Boot ubuntu vm1 in net01 on compute-1
            6. Boot ubuntu vm2 in net02 on compute-1
            7. Boot ubuntu vm3 in net02 on compute-2
            8. Associate floatings to all vms
            9. Start iperf between vm1 and vm2 by floating
            10. Look on the traffic with nload on vm port on compute-1
            11. Start iperf between vm1 and vm3
            12. Look on the traffic with nload on vm port on compute-1
            13. Create new policy: neutron qos-policy-create bw-limiter
            14. Create new rule:
                neutron qos-bandwidth-limit-rule-create rule-id bw-limiter \
                --max-kbps 3000
            15. Find neutron port for vm1: neutron port-list | grep <vm1 ip>
            16. Update port with new policy:
                neutron port-update your-port-id --qos-policy bw-limiter
            17. Check in nload that traffic changed properly
        """
        instance1, instance2, instance3 = instances

        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1,
                                       instance2,
                                       limit=3000 * 1024,
                                       time=20,
                                       ip_type='floating')

        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(instance1,
                                       instance3,
                                       limit=3000 * 1024,
                                       time=20,
                                       ip_type='floating')

        # Create policy for port
        instance1_ip = os_conn.get_nova_instance_ips(instance1)['fixed']
        port1 = os_conn.get_port_by_fixed_ip(instance1_ip)
        policy = os_conn.create_qos_policy('policy_1')
        os_conn.neutron.create_bandwidth_limit_rule(policy['policy']['id'], {
            'bandwidth_limit_rule': {
                'max_kbps': 3000,
            }
        })

        os_conn.neutron.update_port(
            port1['id'], {'port': {'qos_policy_id': policy['policy']['id']}})

        self.check_iperf_bandwidth(instance1,
                                   instance2,
                                   limit=3000 * 1024,
                                   ip_type='floating')

        self.check_iperf_bandwidth(instance1,
                                   instance3,
                                   limit=3000 * 1024,
                                   ip_type='floating')


@pytest.mark.check_env_('is_qos_enabled')
@pytest.mark.check_env_('is_vlan')
class TestTrafficRestrictionWithSRIoV(TestQoSBase):

    # no limits bandwidth on BM server = ~ 700 Mbits/sec
    default_limit = 20000  # 20 Mbits/sec

    @classmethod
    @pytest.fixture(scope='class')
    def sriov_hosts(cls, get_env):
        """Find computes with SR-IOV enabled"""
        env = get_env()
        computes_list = []
        for compute in env.get_nodes_by_role('compute'):
            with compute.ssh() as remote:
                result = remote.execute(
                    'lspci -vvv | grep -i "initial vf"').stdout_string
            vfs_number = re.findall('Number of VFs: (\d+)', result)
            if sum(map(int, vfs_number)) > 0:
                computes_list.append(compute)
        if len(computes_list) < 2:
            pytest.skip("Insufficient count of compute with SR-IOV")
        hosts = [compute.data['fqdn'] for compute in computes_list]
        return hosts

    @classmethod
    @pytest.yield_fixture(scope='class', autouse=True)
    def cleanup_env(cls, os_conn, sriov_hosts):
        """SR-IOV env has no support of snapshots.
        So need to clean all manually.
        """
        initial_floating_ips = os_conn.nova.floating_ips.list()
        yield
        # delete floatings
        for floating_ip in [x for x in os_conn.nova.floating_ips.list()
                            if x not in initial_floating_ips]:
            os_conn.delete_floating_ip(floating_ip)
        cls.instance_keypair.delete()
        cls.security_group.delete()
        os_conn.nova.flavors.find(name='iperf_flavor').delete()

    @pytest.yield_fixture
    def cleanup_vms(self, os_conn):
        """SR-IOV env has no support of snapshots.
        So need to clean all manually.
        """
        def instances_cleanup():
            instances = os_conn.nova.servers.list()
            for instance in instances:
                instance.delete()

            os_conn.wait_servers_deleted(instances)

        instances_cleanup()
        yield
        instances_cleanup()

    @pytest.yield_fixture
    def two_connected_networks(self, os_conn):
        """Creates 2 networks with access to external net
        with router between them.
        """
        router = os_conn.create_router(name="router_test")['router']
        ext_net = os_conn.ext_network
        os_conn.router_gateway_add(router_id=router['id'],
                                   network_id=ext_net['id'])
        net01 = os_conn.add_net(router['id'])
        net02 = os_conn.add_net(router['id'])
        yield [net01, net02]
        logger.debug("Delete router and networks")
        os_conn.delete_net_subnet_smart(net01)
        os_conn.delete_net_subnet_smart(net02)
        os_conn.delete_router(router['id'])

    @pytest.yield_fixture
    def ports(self, os_conn, two_connected_networks):
        """Creates SR-IOV ports"""
        nets = {}
        vnic_types = ['direct', 'macvtap']
        for net in two_connected_networks:
            ovs_ports = []
            vf_ports = {}
            for i in range(2):
                # OVS ports
                ovs_port = os_conn.neutron.create_port(
                    {'port': {'network_id': net,
                              'name': 'ovs-port{}'.format(i),
                              'security_groups': [self.security_group.id]}
                     })
                ovs_ports.append(ovs_port['port']['id'])
                # vnic_type: direct, macvtap
                for vnic_type in vnic_types:
                    vf_port = os_conn.neutron.create_port(
                        {'port': {'network_id': net,
                                  'name': 'sriov-port-{}-{}'.format(vnic_type,
                                                                    i),
                                  'binding:vnic_type': vnic_type,
                                  'device_owner': 'nova-compute',
                                  'security_groups': [self.security_group.id]}
                         })
                    if vnic_type not in vf_ports.keys():
                        vf_ports[vnic_type] = []
                    vf_ports[vnic_type].append(vf_port['port']['id'])

            nets[net] = {'ovs_ports': ovs_ports, 'vf_ports': vf_ports}
        yield nets
        for ports in nets.values():
            for port in itertools.chain.from_iterable(
                    [ports['ovs_ports']] + ports['vf_ports'].values()):
                os_conn.neutron.delete_port(port)

    def set_policy_for_vm_port(self, vm, limit=None):
        """Creates limit policy for port with fixed IP for VM.
        :param vm: VM instance
        :param limit: Limit in kbps
        """
        if limit is None:
            limit = self.default_limit
        vm.get()
        vm_ips = [x['addr'] for y in vm.addresses.values()
                  for x in y
                  if x['OS-EXT-IPS:type'] == 'fixed']
        for vm_ip in vm_ips:
            policy = self.os_conn.create_qos_policy('policy_qos-sriov')
            self.os_conn.neutron.create_bandwidth_limit_rule(
                policy['policy']['id'],
                {'bandwidth_limit_rule': {'max_kbps': limit, }})
            port = self.os_conn.get_port_by_fixed_ip(vm_ip)
            logger.debug("Set limit for VM's ({0}) "
                         "port with IP {1}".format(vm.name, vm_ip))
            self.os_conn.neutron.update_port(
                port['id'], {'port': {'qos_policy_id': policy['policy']['id']}}
            )

    def create_instance(self, num, host, flavor_id, nics):
        """Creates instance with installed iperf.
        :param num: Just index number. Like: 1,2,3,4;
        :param host: (str) FQDN name of a compute.
        Like: 'node-2.test.domain.local'
        :param flavor_id: (str) ID of a flavor;
        :param nics: nics for new VM. Like: [{'port-id': '1111'}]
        :return: VM instance.
        """
        # Userdata to install iperf on instance
        iperf_userdata = '\n'.join([
            '#!/bin/bash -v',
            'apt-get install -yq iperf',
            'iperf -s -p {tcp_port} <&- > /tmp/iperf.log 2>&1 &',
            'iperf -u -s -p {udp_port} <&- > /tmp/iperf_udp.log 2>&1 &',
            'echo "{marker}"', ]).format(
                marker=BOOT_MARKER, tcp_port=TCP_PORT, udp_port=UDP_PORT)
        # Create instance
        vm = self.os_conn.create_server(
            name='vm_ports_{}'.format(num),
            image_id=self.image_id,
            key_name=self.instance_keypair.id,
            flavor=flavor_id,
            availability_zone='nova:{}'.format(host),
            nics=nics,
            userdata=iperf_userdata,
            security_groups=[self.security_group.id],
            wait_for_active=False,
            wait_for_avaliable=False)
        return vm

    def check_policy_before_after_set(
            self, vms, limit=None, assign_floating=True):
        """Assign floating IP to one VM.
        Then check that all VMs accessible by floating/fixed IPs.
        After that apply limit policy to one VM and check policy.
        :param vms: List of VMs.
        :param limit: Value for policy to limit bandwidth
        :param assign_floating: Assign floatIP to VM here or it was done before
        """
        if limit is None:
            limit = self.default_limit

        if assign_floating:
            # Assign floating IP to first VM
            floating_ip = self.os_conn.nova.floating_ips.create()
            vms[0].add_floating_ip(floating_ip)

        # Check floating IP connection for the first VM with rest VMs
        srv = vms[0]
        for client in vms[1:]:
            logger.debug(
                "Check floating IP connection: "
                "client={0}, server={1}".format(client.name, srv.name))
            with pytest.raises(AssertionError):
                self.check_iperf_bandwidth(
                    client, srv, limit=limit * 1024, time=20,
                    ip_type='floating')
        # Check fixed IPs connection between all VMs
        for client, srv in itertools.combinations(vms, 2):
            logger.debug(
                "Check fixed IP connection: "
                "client={0}, server={1}".format(client.name, srv.name))
            with pytest.raises(AssertionError):
                self.check_iperf_bandwidth(
                    client, srv, limit=limit * 1024, time=20, ip_type='fixed')
        # Set policy for the first VM
        self.set_policy_for_vm_port(vms[0], limit=limit)
        # Check policy for first VM
        client = vms[0]
        for srv in vms[1::]:
            logger.debug(
                "Check fixed IP connection after policy apply: "
                "client={0}, server={1}".format(client.name, srv.name))
            self.check_iperf_bandwidth(
                client, srv, limit=limit * 1024, ip_type='fixed')

    @pytest.mark.testrail_id('838307')
    def test_traffic_restriction_between_vms_on_vf_ports(
            self, cleanup_vms, os_conn, ports, flavor, sriov_hosts,
            clean_port_policy):
        """Check traffic restriction for vm between two vms on vf ports.

        1. Create net01, subnet. Create net02, subnet;
        2. Create router01, set gateway and add interfaces to net01 and net02;
        3. Create 4 vf ports (binding:vnic-type direct) for future vms: 2
        ports on net01, 2 ports on net02;
        4. Boot 4 ubuntu VMs: 2 on first compute, 2 on second compute;
        5. Assign floating to first VM;
        6. Start iperf between all vms by floating and fixed IP;
        7. Create new policy: neutron qos-policy-create bw-limiter;
        8. Create new rule: neutron qos-bandwidth-limit-rule-create
        rule-id bw-limiter --max-kbps 50000;
        9. Find neutron port for vm1: neutron port-list | grep <vm1 ip>;
        10. Update port with new policy:
        neutron port-update your-port-id --qos-policy bw-limiter;
        11. Check in nload that traffic changed properly.
        """
        nets_id = ports.keys()
        vm_distribution = [
            (sriov_hosts[0], ports[nets_id[0]]['vf_ports']['direct'][0]),
            (sriov_hosts[0], ports[nets_id[0]]['vf_ports']['direct'][1]),
            (sriov_hosts[1], ports[nets_id[1]]['vf_ports']['direct'][0]),
            (sriov_hosts[1], ports[nets_id[1]]['vf_ports']['direct'][1])]

        # Create VMs
        vms = []
        for i, (host, port) in enumerate(vm_distribution, 1):
            vm = self.create_instance(
                i, host, flavor.id,
                nics=[{'port-id': port}])
            vms.append(vm)
        os_conn.wait_servers_active(vms)
        os_conn.wait_servers_ssh_ready(vms)

        self.check_policy_before_after_set(vms)

    @pytest.mark.testrail_id('838308')
    def test_traffic_restriction_between_vms_on_vf_ovs_ports(
            self, cleanup_vms, os_conn, ports, flavor, sriov_hosts,
            clean_port_policy):
        """Check traffic restriction for vm between two vms on vf ports
        and ovs ports.

        1. Create net01, subnet. Create net02, subnet;
        2. Create router01, set gateway and add interfaces to net01 and net02;
        3. Create 4 vf and ovs ports for future vms:
        2 ports on net01, 2 ports on net02;
        4. Boot 4 ubuntu VMs: 2 on first compute, 2 on second compute;
        5. Assign floating to first VM;
        6. Start iperf between all vms by floating and fixed IP;
        7. Create new policy: neutron qos-policy-create bw-limiter;
        8. Create new rule: neutron qos-bandwidth-limit-rule-create
        rule-id bw-limiter --max-kbps 50000;
        9. Find neutron port for vm1: neutron port-list | grep <vm1 ip>;
        10. Update port with new policy:
        neutron port-update your-port-id --qos-policy bw-limiter;
        11. Check in nload that traffic changed properly.
        """
        nets_id = ports.keys()
        vm_distribution = [
            (sriov_hosts[0], ports[nets_id[0]]['vf_ports']['direct'][0],
                ports[nets_id[1]]['ovs_ports'][0]),
            (sriov_hosts[0], ports[nets_id[0]]['vf_ports']['direct'][1],
                ports[nets_id[1]]['ovs_ports'][1]),
            (sriov_hosts[1], ports[nets_id[1]]['vf_ports']['direct'][0],
                ports[nets_id[0]]['ovs_ports'][0]),
            (sriov_hosts[1], ports[nets_id[1]]['vf_ports']['direct'][1],
                ports[nets_id[0]]['ovs_ports'][1])]

        # Create VMs
        vms = []
        for i, (host, vf_port, ovs_port) in enumerate(vm_distribution, 1):
            if i == 1:
                nics = [{'port-id': ovs_port}, {'port-id': vf_port}]
            else:
                nics = [{'port-id': vf_port}]
            vm = self.create_instance(
                i, host, flavor.id, nics=nics)
            vms.append(vm)
        os_conn.wait_servers_active(vms)
        os_conn.wait_servers_cloud_init_finished(vms)

        # Add floating to first VM
        vm = vms[0]
        floating_ip = self.os_conn.nova.floating_ips.create()
        vm.add_floating_ip(floating_ip.ip)
        vm.get()
        # Add and activate eth1 interface on first VM
        tmp_file = '/tmp/eth1.cfg'
        eth1_file = '/etc/network/interfaces.d/eth1.cfg'
        with os_conn.ssh_to_instance(
                os_conn.env, vm, vm_keypair=self.instance_keypair,
                username='ubuntu', password='ubuntu',
                vm_ip=floating_ip.ip) as remote:
            with remote.open(tmp_file, 'w') as f:
                f.write('auto eth1' + '\n' + 'iface eth1 inet dhcp')
            remote.check_call('sudo mv {0} {1}'.format(tmp_file, eth1_file))
            remote.check_call('sudo ifup eth1')

        os_conn.wait_servers_ssh_ready(vms)
        self.check_policy_before_after_set(vms, assign_floating=False)

    @pytest.mark.testrail_id('838309')
    def test_traffic_restriction_between_vms_on_vf_ports_after_upd_del(
            self, cleanup_vms, os_conn, ports, flavor, sriov_hosts,
            clean_port_policy):
        """Check traffic restriction for vm between two vms on vf ports
        during updating and after deleting.

        1. Create net01, subnet. Create net02, subnet;
        2. Create router01, set gateway and add interfaces to net01 and net02;
        3. Create 4 vf ports (binding:vnic-type direct) for future vms:
        2 ports on net01, 2 ports on net02;
        4. Boot 2 ubuntu VMs: 1 on first compute, 1 on second compute;
        6. Start iperf between all vms to check connection;
        7. Create new policy: neutron qos-policy-create bw-limiter;
        8. Create new rule: neutron qos-bandwidth-limit-rule-create
        rule-id bw-limiter --max-kbps 50000;
        9. Find neutron port for vm1: neutron port-list | grep <vm1 ip>;
        10. Update port with new policy:
        neutron port-update your-port-id --qos-policy bw-limiter;
        11. Check in nload that traffic changed properly;
        12. Modify rule to set bandwidth to 80000;
        13. Check in nload that traffic changed properly.
        14. Delete qos-bandwidth-limit-rule;
        15. Check in nload that traffic changed properly.
        """
        limit_1 = self.default_limit
        limit_2 = self.default_limit * 2

        nets_id = ports.keys()
        vm_distribution = [
            (sriov_hosts[0], ports[nets_id[0]]['vf_ports']['direct'][0]),
            (sriov_hosts[1], ports[nets_id[1]]['vf_ports']['direct'][0])]

        # Create VMs
        vms = []
        for i, (host, port) in enumerate(vm_distribution, 1):
            vm = self.create_instance(
                i, host, flavor.id, nics=[{'port-id': port}])
            vms.append(vm)
        os_conn.wait_servers_active(vms)
        os_conn.wait_servers_ssh_ready(vms)

        # Check VMs has connection between them
        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(
                client=vms[0], server=vms[1], limit=limit_1 * 1024, time=20)

        # Set first limit and check it
        self.set_policy_for_vm_port(vms[0], limit=limit_1)
        self.check_iperf_bandwidth(
            client=vms[0], server=vms[1], limit=limit_1 * 1024)

        # Set second limit and check it
        self.set_policy_for_vm_port(vms[0], limit=limit_2)
        self.check_iperf_bandwidth(
            client=vms[0], server=vms[1], limit=limit_2 * 1024)

        # Delete limit and check that there are no restrictions
        delete_ports_policy(os_conn)
        with pytest.raises(AssertionError):
            self.check_iperf_bandwidth(
                client=vms[0], server=vms[1], limit=limit_2 * 1024)
