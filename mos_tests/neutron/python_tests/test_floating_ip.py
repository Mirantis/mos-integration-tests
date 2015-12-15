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

from paramiko.ssh_exception import SSHException, NoValidConnectionsError
import pytest
import time

from mos_tests.neutron.python_tests.base import TestBase


@pytest.mark.usefixtures("setup")
class TestFloatingIP(TestBase):
    """Check association and disassociation floating ip"""

    @pytest.fixture(autouse=True)
    def prepare_openstack(self, init):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create network net01, subnet net01__subnet with CIDR 10.1.1.0/24
            2. Create new security group sec_group1
            3. Add Ingress rule for TCP protocol to sec_group1
            4. Boot vm1 net01 with sec_group1
        """
        # init variables
        exist_networks = self.os_conn.list_networks()['networks']
        ext_network = [x for x in exist_networks
                       if x.get('router:external')][0]
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.hostname = self.zone.hosts.keys()[0]
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        cidr = "10.1.1.0/24"

        self.os_conn.nova.security_group_rules.create(
            self.security_group.id,
            ip_protocol='tcp',
            from_port=1,
            to_port=65535,
            cidr='0.0.0.0/0'
        )

        # create router
        self.router = self.os_conn.create_router(name="router01")
        self.os_conn.router_gateway_add(router_id=self.router['router']['id'],
                                        network_id=ext_network['id'])

        network = self.os_conn.create_network(name='net01')
        subnet = self.os_conn.create_subnet(
            network_id=network['network']['id'],
            name='net01__subnet',
            cidr=cidr)
        self.os_conn.router_interface_add(
            router_id=self.router['router']['id'],
            subnet_id=subnet['subnet']['id'])
        self.os_conn.create_server(
            name='server01',
            availability_zone='{}:{}'.format(self.zone.zoneName,
                                             self.hostname),
            key_name=self.instance_keypair.name,
            nics=[{'net-id': network['network']['id']}],
            security_groups=[self.security_group.id])

        # add floating ip to first server
        server = self.os_conn.nova.servers.find(name="server01")
        self.floating_ip = self.os_conn.assign_floating_ip(server,
                                                           use_neutron=True)

    def test_ssh_after_deleting_floating(self):
        """Check ssh-connection by floating ip for vm after deleting floating ip

        Steps:
            1. Create network net01, subnet net01__subnet with CIDR 10.1.1.0/24
            2. Create new security group sec_group1
            3. Add Ingress rule for TCP protocol to sec_group1
            4. Boot vm1 net01 with sec_group1
            5. Associate floating IP for vm1
            6. Go to vm1 with ssh and floating IP
            7. Without stopping ssh-connection dissociate floating ip from vm
            8. Check that connection is stopped
            9.Try to go to vm1 with ssh and floating IP

        Duration 10m

        """

        time.sleep(30)
        ip = self.floating_ip["floating_ip_address"]
        server = self.os_conn.nova.servers.find(name="server01")
        pkeys = [self.instance_keypair.private_key]

        with self.env.get_ssh_to_cirros(ip, pkeys) as vm_remote:
            res = vm_remote.execute("ping -c1 8.8.8.8")

        assert (0 == res['exit_code'],
                'Instance has no connectivity, exit code {0},'
                'stdout {1}, stderr {2}'.format(res['exit_code'],
                res['stdout'], res['stderr']))

        assert self.os_conn.neutron.show_floatingip(
            self.floating_ip['id'])['floatingip']['status'] == 'ACTIVE', \
            'Floatingip is not in the ACTIVE state.'

        with pytest.raises(SSHException) as exc:
            with self.env.get_ssh_to_cirros(ip, pkeys) as vm_remote:
                vm_remote.execute("date")
                self.os_conn.disassociate_floating_ip(
                    server, self.floating_ip, use_neutron=True)
                vm_remote.execute("date")

        assert "Timeout openning channel." in exc.value
        assert self.os_conn.neutron.show_floatingip(
            self.floating_ip['id'])['floatingip']['status'] == 'DOWN', \
            'Floatingip is not in the DOWN state.' \
            'disassociate_floating_ip has failed.'

        with pytest.raises(NoValidConnectionsError) as exc:
            with self.env.get_ssh_to_cirros(ip, pkeys) as vm_remote:
                vm_remote.execute("date")
        assert "Unable to connect to port 22 on  or {}".format(ip) \
               in exc.value.strerror

        # for cleanup
        self.os_conn.delete_floating_ip(self.floating_ip, use_neutron=True)
