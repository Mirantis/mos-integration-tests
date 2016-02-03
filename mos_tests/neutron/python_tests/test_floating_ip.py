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

from paramiko.ssh_exception import NoValidConnectionsError
from paramiko.ssh_exception import SSHException
import pytest

from mos_tests.functions.common import wait
from mos_tests.neutron.python_tests.base import TestBase


class TestFloatingIP(TestBase):
    """Check association and disassociation floating ip"""

    def _prepare_openstack(self):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create network net01, subnet net01__subnet with CIDR 10.1.1.0/24
            2. Create new security group sec_group1
            3. Add Ingress rule for TCP protocol to sec_group1
            4. Boot vm1 net01 with sec_group1
        """
        # init variables
        exist_networks = self.os_conn.list_networks()['networks']
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

        # add floating ip to first server
        server = self.os_conn.nova.servers.find(name="server01")
        self.floating_ip = self.os_conn.assign_floating_ip(server,
                                                           use_neutron=True)

        pkeys = self.convert_private_key_for_vm(
            [self.instance_keypair.private_key])

        self.check_vm_is_accessible_with_ssh(
            vm_ip=self.floating_ip['floating_ip_address'],
            pkeys=pkeys, **self.cirros_creds)

    def check_vm_inaccessible_by_ssh(self, vm_ip, pkeys):
        """Check that instance is inaccessible with ssh via floating_ip.

        :param vm_ip: floating_ip of instance
        :param pkeys: ip of instance to ping
        """
        with pytest.raises(NoValidConnectionsError):
            with self.env.get_ssh_to_vm(vm_ip, private_keys=pkeys,
                                        **self.cirros_creds) as vm_remote:
                vm_remote.execute("date")

    @pytest.mark.testrail_id('542634')
    def test_ssh_after_deleting_floating(self):
        """Check ssh-connection by floating ip for vm after
        deleting floating ip

        Steps:
            1. Create network net01, subnet net01__subnet with CIDR 10.1.1.0/24
            2. Create new security group sec_group1
            3. Add Ingress rule for TCP protocol to sec_group1
            4. Boot vm1 net01 with sec_group1
            5. Associate floating IP for vm1
            6. Go to vm1 with ssh and floating IP
            7. Without stopping ssh-connection dissociate floating ip from vm
            8. Check that connection is stopped
            9. Try to go to vm1 with ssh and floating IP

        Duration 10m

        """
        self._prepare_openstack()
        ip = self.floating_ip["floating_ip_address"]
        server = self.os_conn.nova.servers.find(name="server01")
        pkeys = self.convert_private_key_for_vm(
            [self.instance_keypair.private_key])

        def is_ssh_raise_exception(remote):
            try:
                remote.execute('uname')
                return False
            except SSHException:
                return True
            except Exception:
                raise

        with self.env.get_ssh_to_vm(ip, private_keys=pkeys,
                                    **self.cirros_creds) as vm_remote:
            vm_remote.check_call("ping -c1 8.8.8.8")
            self.os_conn.disassociate_floating_ip(
                server, self.floating_ip, use_neutron=True)
            vm_remote.timeout = 10
            wait(lambda: is_ssh_raise_exception(vm_remote), timeout_seconds=60,
                 waiting_for='ssh connection be stopped')

        # check that vm became inaccessible with ssh
        self.check_vm_inaccessible_by_ssh(vm_ip=ip, pkeys=pkeys)
