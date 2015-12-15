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

<<<<<<< efbdb9f5ddc5278927c84f89a6457b4be5133af6
import pytest

from paramiko.ssh_exception import SSHException, NoValidConnectionsError
=======
from paramiko.ssh_exception import SSHException, NoValidConnectionsError
import pytest
import time
>>>>>>> Added test_ssh_after_deleting_floating.

from mos_tests.neutron.python_tests.base import TestBase


@pytest.mark.usefixtures("setup")
class TestFloatingIP(TestBase):
    """Check association and disassociation floating ip"""

    @pytest.fixture(autouse=True)
<<<<<<< efbdb9f5ddc5278927c84f89a6457b4be5133af6
    def _prepare_openstack(self, init):
=======
    def prepare_openstack(self, init):
>>>>>>> Added test_ssh_after_deleting_floating.
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create network net01, subnet net01__subnet with CIDR 10.1.1.0/24
            2. Create new security group sec_group1
            3. Add Ingress rule for TCP protocol to sec_group1
            4. Boot vm1 net01 with sec_group1
        """
        # init variables
        exist_networks = self.os_conn.list_networks()['networks']
<<<<<<< efbdb9f5ddc5278927c84f89a6457b4be5133af6
        ext_net = [x for x in exist_networks
                   if x.get('router:external')][0]
        zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        security_group = self.os_conn.create_sec_group_for_ssh()
        hostname = zone.hosts.keys()[0]
        cidr = "10.1.1.0/24"
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')

        self.os_conn.nova.security_group_rules.create(
            security_group.id,
            ip_protocol='tcp',
            from_port=1,
            to_port=65535,
            cidr='0.0.0.0/0')

        net, subnet = self.create_internal_network_with_subnet(cidr=cidr)
        # create router
        self.create_router_between_nets(ext_net, subnet)

        self.os_conn.create_server(
            name='server01',
            availability_zone='{}:{}'.format(zone.zoneName,
                                             hostname),
            key_name=self.instance_keypair.name,
            nics=[{'net-id': net['network']['id']}],
            security_groups=[security_group.id])
=======
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
>>>>>>> Added test_ssh_after_deleting_floating.

        # add floating ip to first server
        server = self.os_conn.nova.servers.find(name="server01")
        self.floating_ip = self.os_conn.assign_floating_ip(server,
                                                           use_neutron=True)

<<<<<<< efbdb9f5ddc5278927c84f89a6457b4be5133af6
        pkeys = self.convert_private_key_for_vm(
            [self.instance_keypair.private_key])

        self.check_vm_is_accessible_with_ssh(
            vm_ip=self.floating_ip['floating_ip_address'],
            pkeys=pkeys)

    def check_vm_inaccessible_by_ssh(self, vm_ip, pkeys):
        """Check that instance is inaccessible with ssh via floating_ip.

        :param vm_ip: floating_ip of instance
        :param pkeys: ip of instance to ping
        """
        with pytest.raises(NoValidConnectionsError) as exc:
            with self.env.get_ssh_to_cirros(vm_ip, pkeys) as vm_remote:
                vm_remote.execute("date")
        assert "Unable to connect to port 22 on  or {}".format(vm_ip) \
               in exc.value.strerror

    def test_ssh_after_deleting_floating(self):
        """Check ssh-connection by floating ip for vm after
        deleting floating ip
=======
    def test_ssh_after_deleting_floating(self):
        """Check ssh-connection by floating ip for vm after deleting floating ip
>>>>>>> Added test_ssh_after_deleting_floating.

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
<<<<<<< efbdb9f5ddc5278927c84f89a6457b4be5133af6
        ip = self.floating_ip["floating_ip_address"]
        server = self.os_conn.nova.servers.find(name="server01")
        pkeys = self.convert_private_key_for_vm(
            [self.instance_keypair.private_key])

        res1 = None
        res2 = None

        with pytest.raises(SSHException):
            with self.env.get_ssh_to_cirros(ip, pkeys) as vm_remote:
                res1 = vm_remote.execute("ping -c1 8.8.8.8")
                self.os_conn.disassociate_floating_ip(
                    server, self.floating_ip, use_neutron=True)
                res2 = vm_remote.execute("date")

        assert (0 == res1['exit_code'],
                'Instance has no connectivity, exit code {0},'
                'stdout {1}, stderr {2}'.format(res1['exit_code'],
                res1['stdout'], res1['stderr']))

        # check that disassociate_floating_ip has been performed
=======

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
>>>>>>> Added test_ssh_after_deleting_floating.
        assert self.os_conn.neutron.show_floatingip(
            self.floating_ip['id'])['floatingip']['status'] == 'DOWN', \
            'Floatingip is not in the DOWN state.' \
            'disassociate_floating_ip has failed.'

<<<<<<< efbdb9f5ddc5278927c84f89a6457b4be5133af6
        assert res2 is None, 'SSH hasn\'t been stopped'

        # check that vm became inaccessible with ssh
        self.check_vm_inaccessible_by_ssh(vm_ip=ip, pkeys=pkeys)

        # for cleanup delete floating_ip using neutron
=======
        with pytest.raises(NoValidConnectionsError) as exc:
            with self.env.get_ssh_to_cirros(ip, pkeys) as vm_remote:
                vm_remote.execute("date")
        assert "Unable to connect to port 22 on  or {}".format(ip) \
               in exc.value.strerror

        # for cleanup
>>>>>>> Added test_ssh_after_deleting_floating.
        self.os_conn.delete_floating_ip(self.floating_ip, use_neutron=True)
