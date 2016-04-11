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
import os

import pytest

from mos_tests.functions import common
from mos_tests.neutron.python_tests import base
from mos_tests import settings

logger = logging.getLogger(__name__)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_qos_enabled')
class TestQoSBase(base.TestBase):
    @classmethod
    @pytest.fixture(scope='class')
    def variables(cls, os_conn):
        cls.zone = os_conn.nova.availability_zones.find(zoneName="nova")
        cls.security_group = os_conn.create_sec_group_for_ssh()
        cls.instance_keypair = os_conn.create_key(key_name='instancekey')

    @classmethod
    @pytest.fixture(scope='class')
    def iperf_image_id(cls, os_conn):
        logger.info('Creating ubuntu image')
        image_path = os.path.join(settings.TEST_IMAGE_PATH,
                                  settings.UBUNTU_IPERF_QCOW2)
        image = os_conn.glance.images.create(name="image_ubuntu",
                                             disk_format='qcow2',
                                             container_format='bare')
        with open(image_path, 'rb') as f:
            os_conn.glance.images.upload(image.id, f)

        logger.info('Ubuntu image created')
        return image.id

    @classmethod
    @pytest.fixture(scope='class')
    def networks(cls, variables, os_conn):
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
    def class_finalize(cls, request, devops_env, snapshot_name):
        yield
        if (hasattr(request.session, 'nextitem') and
                request.session.nextitem is None):
            return
        devops_env.revert_snapshot(snapshot_name)
        setattr(request.session, 'reverted', True)

    def get_iperf_result(self,
                         remote,
                         server_ip,
                         time=60,
                         interval=10,
                         port=5002):
        result = remote.check_call(
            'iperf -c {ip} -p {port} -y C -t {time} -i {interval}'.format(
                ip=server_ip,
                port=port,
                time=time,
                interval=interval))
        assert not result['stderr'], 'Error during iperf execution, {}'.format(
            result)
        reader = csv.reader(result['stdout'][:-1])
        for line in reader:
            yield line

    def check_iperf_bandwidth(self, client, server, limit, **kwargs):
        server_ip = self.os_conn.get_nova_instance_ips(server)['fixed']
        with self.os_conn.ssh_to_instance(
                self.env,
                client,
                username='ubuntu',
                vm_keypair=self.instance_keypair) as remote:
            for line in self.get_iperf_result(remote, server_ip, **kwargs):
                bandwidth = int(line[-1])
                assert (limit / 2) < bandwidth < limit


@pytest.mark.check_env_('has_1_or_more_computes')
class TestSingleCompute(TestQoSBase):
    @classmethod
    @pytest.fixture(scope='class')
    def instances(cls, variables, networks, iperf_image_id, os_conn):
        instances = []
        compute_node = cls.zone.hosts.keys()[0]
        userdata = (
            '#!/bin/bash -v\n'
            'iperf -s -p 5002 -D'
        )  # yapf: disable
        for i in range(2):
            instance = os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(cls.zone.zoneName,
                                                 compute_node),
                image_id=iperf_image_id,
                flavor=2,
                userdata=userdata,
                key_name=cls.instance_keypair.name,
                nics=[{'net-id': cls.net['network']['id']}],
                security_groups=[cls.security_group.id],
                wait_for_active=False,
                wait_for_avaliable=False)
            instances.append(instance)
        common.wait(
            lambda: all([os_conn.is_server_active(x) for x in instances]),
            timeout_seconds=5 * 60,
            waiting_for="instances became to active state")
        common.wait(
            lambda: all([os_conn.is_server_ssh_ready(x) for x in instances]),
            timeout_seconds=5 * 60,
            waiting_for="instances to be ssh ready")
        return instances

    @pytest.mark.testrail_id('838298')
    def test_traffic_restriction_with_max_burst(self, instances, os_conn):
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
        self.policy = os_conn.create_qos_policy('policy_1')
        self.rule = os_conn.neutron.create_bandwidth_limit_rule(
            self.policy['policy']['id'], {
                'bandwidth_limit_rule': {
                    'max_kbps': 4000,
                    'max_burst_kbps': 300,
                }
            })
        os_conn.neutron.update_network(
            self.net['network']['id'],
            {'network': {'qos_policy_id': self.policy['policy']['id']}})

        client, server = instances
        self.check_iperf_bandwidth(client, server, (4000 + 300) * 1024)

        self.os_conn.neutron.update_bandwidth_limit_rule(
            self.rule['bandwidth_limit_rule']['id'],
            self.policy['policy']['id'], {
                'bandwidth_limit_rule': {
                    'max_kbps': 6000,
                    'max_burst_kbps': 500,
                }
            })
        self.check_iperf_bandwidth(client, server, (6000 + 500) * 1024)


@pytest.mark.check_env_('has_2_or_more_computes')
class TestTraficBetweenComputes(TestQoSBase):
    @classmethod
    @pytest.fixture(scope='class')
    def instances(cls, variables, networks, iperf_image_id, os_conn):
        instances = []
        compute_nodes = cls.zone.hosts.keys()[:2]
        userdata = (
            '#!/bin/bash -v\n'
            'iperf -s -p 5002 -D'
        )  # yapf: disable
        for i in range(2):
            instance = os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(cls.zone.zoneName,
                                                 compute_nodes[i]),
                image_id=iperf_image_id,
                flavor=2,
                userdata=userdata,
                key_name=cls.instance_keypair.name,
                nics=[{'net-id': cls.net['network']['id']}],
                security_groups=[cls.security_group.id],
                wait_for_active=False,
                wait_for_avaliable=False)
            instances.append(instance)
        common.wait(
            lambda: all([os_conn.is_server_active(x) for x in instances]),
            timeout_seconds=5 * 60,
            waiting_for="instances became to active state")
        common.wait(
            lambda: all([os_conn.is_server_ssh_ready(x) for x in instances]),
            timeout_seconds=5 * 60,
            waiting_for="instances to be ssh ready")
        return instances

    @pytest.mark.testrail_id('838303')
    def test_qos_between_vms_on_different_computes(self, instances, os_conn):
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

        self.check_iperf_bandwidth(instance1,
                                   instance2,
                                   limit=3000 * 1024,
                                   time=60,
                                   interval=60)

        self.check_iperf_bandwidth(instance2,
                                   instance1,
                                   limit=4000 * 1024,
                                   time=60,
                                   interval=60)
