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
import logging

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


def delete_instances(os_conn, instances):
    instances_ids = [x.id for x in instances]

    # Stop instances (to prevent error during deletion)
    for instance_id in instances_ids:
        os_conn.nova.servers.stop(instance_id)

    def isnstances_shutdowned():
        instances = [x
                       for x in os_conn.nova.servers.list()
                       if x.id in instances_ids]
        if any([x.status == 'ERROR' for x in instances]):
            raise Exception(
                'Some server(s) became to ERROR state after stop')
        return all([x.status == 'SHUTOFF' for x in instances])

    common.wait(isnstances_shutdowned, timeout_seconds=10 * 60)

    # Delete instances
    for instance_id in instances_ids:
        os_conn.nova.servers.delete(instance_id)

    def instances_deleted():
        not_deleted = [x
                       for x in os_conn.nova.servers.list()
                       if x.id in instances_ids]
        if len(not_deleted) == 0:
            return True
        if any([x.status == 'ERROR' for x in not_deleted]):
            raise Exception(
                'Some server(s) became to ERROR state after deletion')

    common.wait(instances_deleted, timeout_seconds=2 * 60)


def delete_ports_policy(os_conn):
    for port in os_conn.neutron.list_ports()['ports']:
        policy_id = port['qos_policy_id']
        if policy_id is not None:
            os_conn.neutron.update_port(port['id'],
                                        {'port': {'qos_policy_id': None}})
            os_conn.delete_qos_policy(policy_id)


@pytest.yield_fixture(scope='module')
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


@pytest.yield_fixture(scope='module')
def instance_keypair(os_conn):
    keypair = os_conn.create_key(key_name='instancekey')
    yield keypair
    os_conn.delete_key(key_name='instancekey')


@pytest.yield_fixture(scope='module')
def security_group(os_conn):
    security_group = os_conn.create_sec_group_for_ssh()
    yield security_group
    os_conn.nova.security_groups.delete(security_group.id)


@pytest.mark.check_env_('is_qos_enabled')
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
    @pytest.yield_fixture(scope='class')
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
        yield
        os_conn.delete_router(cls.router['router']['id'])
        os_conn.delete_network(cls.net['network']['id'])

    @pytest.yield_fixture
    def clean_net_policy(self, os_conn):
        yield
        net = os_conn.neutron.show_network(self.net['network']['id'])
        policy_id = net['network']['qos_policy_id']
        if policy_id is not None:
            os_conn.neutron.update_network(
                net['network']['id'], {'network': {'qos_policy_id': None}})
            os_conn.delete_qos_policy(policy_id)

    @pytest.yield_fixture
    def clean_port_policy(self, os_conn):
        yield
        delete_ports_policy(os_conn)

    @classmethod
    def boot_iperf_instance(cls, name, compute_node, net, udp=False):
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
            flavor=2,
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
                assert (limit * 0.8) < bandwidth <= limit * 1.05


@pytest.mark.check_env_('has_1_or_more_computes')
class TestSingleCompute(TestQoSBase):
    @classmethod
    @pytest.yield_fixture(scope='class')
    def instances(cls, variables, network, iperf_image_id, os_conn):
        instances = []
        compute_node = cls.zone.hosts.keys()[0]
        for i in range(2):
            instance = cls.boot_iperf_instance(name='server%02d' % i,
                                               compute_node=compute_node,
                                               net=cls.net)
            instances.append(instance)
        wait_instances_to_boot(os_conn, instances)
        yield instances
        delete_instances(os_conn, instances)

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
    @pytest.yield_fixture(scope='class')
    def instances(cls, variables, network, iperf_image_id, os_conn):
        instances = []
        compute_nodes = cls.zone.hosts.keys()[:2]
        for i in range(2):
            instance = cls.boot_iperf_instance(name='server%02d' % i,
                                               compute_node=compute_nodes[i],
                                               net=cls.net)
            instances.append(instance)
        wait_instances_to_boot(os_conn, instances)
        yield instances
        delete_instances(os_conn, instances)


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


class TestPolicyWithNetCreate(DifferentComputesInstancesMixin, TestQoSBase):
    @classmethod
    @pytest.yield_fixture(scope='class')
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
        yield
        os_conn.delete_router(cls.router['router']['id'])
        os_conn.delete_network(cls.net['network']['id'])
        os_conn.delete_qos_policy(cls.policy['policy']['id'])

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
    @pytest.yield_fixture(scope='class')
    def instances(cls, variables, network, iperf_image_id, os_conn):
        instances = []
        compute_nodes = cls.zone.hosts.keys()[:2]
        compute_nodes.insert(0, compute_nodes[0])
        for i, node in enumerate(compute_nodes):
            instance = cls.boot_iperf_instance(name='server%02d' % i,
                                               compute_node=node,
                                               net=cls.net)
            instances.append(instance)
        wait_instances_to_boot(os_conn, instances)
        yield instances
        delete_instances(os_conn, instances)

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


@pytest.mark.incremental
@pytest.mark.check_env_('has_2_or_more_computes')
class TestTraficBetween3InstancesInDifferentNet(TestQoSBase):
    @classmethod
    @pytest.yield_fixture(scope='class')
    def network2(cls, variables, os_conn, network):
        net = os_conn.create_network(name='net02')
        subnet = os_conn.create_subnet(network_id=net['network']['id'],
                                       name='net02__subnet',
                                       cidr='10.0.1.0/24')

        os_conn.router_interface_add(router_id=cls.router['router']['id'],
                                     subnet_id=subnet['subnet']['id'])
        yield net
        os_conn.delete_network(net['network']['id'])

    @classmethod
    @pytest.yield_fixture(scope='class')
    def instances(cls, variables, network, iperf_image_id, os_conn, network2):
        instances = []
        compute_nodes = cls.zone.hosts.keys()[:2]
        compute_nodes.insert(0, compute_nodes[0])
        networks = [cls.net, network2, network2]
        for i, (node, net) in enumerate(zip(compute_nodes, networks)):
            instance = cls.boot_iperf_instance(name='server%02d' % i,
                                               compute_node=node,
                                               net=net)
            instances.append(instance)
        wait_instances_to_boot(os_conn, instances)
        for instance in instances:
            os_conn.assign_floating_ip(instance)
        yield instances
        delete_instances(os_conn, instances)

    @classmethod
    @pytest.yield_fixture(scope='class')
    def clean_port_policy(cls, os_conn):
        yield
        delete_ports_policy(os_conn)

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
