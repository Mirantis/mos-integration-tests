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

from collections import defaultdict
import logging
import time

import pytest
from waiting import wait
import neutronclient.v2_0.client as neutronclient
from neutronclient.common.exceptions import NeutronClientException
from tempfile import NamedTemporaryFile

from mos_tests.environment.devops_client import DevopsClient
from mos_tests.neutron.python_tests import base


logger = logging.getLogger(__name__)


@pytest.mark.check_env_('is_dvr')
@pytest.mark.usefixtures("setup")
class TestDVRBase(base.TestBase):
    """DVR specific test base class"""

    @pytest.fixture
    def variables(self, init):
        """Init Openstack variables"""
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        self.hosts = self.zone.hosts.keys()

    def reset_computes(self, hostnames, env_name):

        def get_hypervisors():
            return [x for x in self.os_conn.nova.hypervisors.list()
                    if x.hypervisor_hostname in hostnames]

        node_states = defaultdict(list)

        def is_nodes_started():
            for hypervisor in get_hypervisors():
                state = hypervisor.state
                prev_states = node_states[hypervisor.hypervisor_hostname]
                if len(prev_states) == 0 or state != prev_states[-1]:
                    prev_states.append(state)

            return all(x[-2:] == ['down', 'up'] for x in node_states.values())

        logger.info('Resetting computes {}'.format(hostnames))
        for hostname in hostnames:
            node = self.env.find_node_by_fqdn(hostname)
            devops_node = DevopsClient.get_node_by_mac(env_name=env_name,
                                                       mac=node.data['mac'])
            devops_node.reset()

        wait(is_nodes_started, timeout_seconds=10 * 60)

    def find_snat_controller(self, excluded=()):
        """Find controller with SNAT service.

        :param excluded: excluded nodes fqdns
        :returns: controller node with SNAT
        """
        all_controllers = self.env.get_nodes_by_role('controller')
        controller_with_snat = None
        for controller in all_controllers:
            if controller.data['fqdn'] in excluded:
                continue
            with controller.ssh() as remote:
                cmd = 'ip net | grep snat'
                res = remote.execute(cmd)
                if res['exit_code'] == 0:
                    controller_with_snat = controller
                    break
        return controller_with_snat


@pytest.mark.check_env_('has_1_or_more_computes')
class TestDVR(TestDVRBase):
    """DVR specific test cases"""

    def _prepare_openstack_env(self, distributed_router=True,
                               assign_floating_ip=True):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Revert snapshot with neutron cluster
            2. Create network net01, subnet net01_subnet
            3. Create router with gateway to external net and
               interface with net01
            4. Launch instance
            5. Associate floating IP if needed
        """
        self.zone = self.os_conn.nova.availability_zones.find(zoneName="nova")
        self.security_group = self.os_conn.create_sec_group_for_ssh()
        self.instance_keypair = self.os_conn.create_key(key_name='instancekey')
        net, subnet = self.create_internal_network_with_subnet(1)
        router = self.os_conn.create_router(name='router01',
                                            distributed=distributed_router)
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])

        self.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])

        self.server = self.os_conn.create_server(
            name='server01',
            availability_zone=self.zone.zoneName,
            key_name=self.instance_keypair.name,
            nics=[{'net-id': net['network']['id']}],
            security_groups=[self.security_group.id])

        if assign_floating_ip:
            self.os_conn.assign_floating_ip(self.server)

    @pytest.mark.parametrize('floating_ip', (True, False),
                             ids=('with floating', 'without floating'))
    @pytest.mark.parametrize('dvr_router', (True, False),
                             ids=('distributed router', 'centralized_router'))
    def test_north_south_connectivity(self, floating_ip, dvr_router):
        """Check North-South connectivity

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with external network and
                router type `dvr_router`
            3. Add interfaces to the router01 with net01__subnet
            4. Boot vm_1 in the net01
            5. Add floating ip if case of `floating_ip` arg is True
            6. Go to the vm_1
            7. Ping 8.8.8.8
        """
        self._prepare_openstack_env(distributed_router=dvr_router,
                                    assign_floating_ip=floating_ip)

        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair)

    def test_connectivity_after_reset_compute(self, env_name):
        """Check North-South connectivity with floatingIP after reset compute

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with external network and
                router type Distributed
            3. Add interfaces to the router01 with net01__subnet
            4. Boot vm_1 in the net01
            5. Associate floating IP
            6. Go to the vm_1 with ssh and floating IP
            7. Reset compute where vm resides and wait when it's starting
            8. Go to the vm_1 with ssh and floating IP
            9. Ping 8.8.8.8
        """
        self._prepare_openstack_env()

        with self.os_conn.ssh_to_instance(self.env, self.server,
                                          self.instance_keypair) as remote:
            remote.check_call('uname -a')

        # reset compute
        compute_hostname = getattr(self.server, 'OS-EXT-SRV-ATTR:host')
        self.reset_computes([compute_hostname], env_name)

        time.sleep(60)

        self.check_ping_from_vm(self.server, vm_keypair=self.instance_keypair)

    def test_shutdown_snat_controller(self, env_name):
        """Shutdown controller with SNAT-namespace and check it reschedules.

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create router01 with external network and
                router type Distributed
            3. Add interfaces to the router01 with net01__subnet
            4. Boot vm_1 in the net01
            5. Go to the vm_1 and ping 8.8.8.8
            6. Find controller with SNAT-namespace
               and kill this controller with virsh:
               ``ip net | grep snat`` on all controllers
               ``virsh destroy <controller_with_snat>``
            7. Check SNAT moved to another
            8. Go to the vm_1 and ping 8.8.8.8

        Duration 10m

        """
        self._prepare_openstack_env()
        self.check_ping_from_cirros(self.server)
        # Get controller with SNAT and destroy it
        controller_with_snat = self.find_snat_controller()
        logger.info('Destroying controller with SNAT: {}'.format(
            controller_with_snat.data['fqdn']))
        devops_node = DevopsClient.get_node_by_mac(
            env_name=env_name, mac=controller_with_snat.data['mac'])
        self.env.destroy_nodes([devops_node])
        # Wait for SNAT reschedule
        wait_msg = "Waiting for snat is rescheduled"
        new_controller_with_snat = wait(
            lambda: self.find_snat_controller(
                excluded=[controller_with_snat.data['fqdn']]),
            timeout_seconds=60 * 3,
            sleep_seconds=(1, 60, 5),
            waiting_for=wait_msg)
        # Check external ping and proper SNAT rescheduling
        self.check_ping_from_cirros(self.server)
        assert (
            controller_with_snat.data['fqdn'] !=
            new_controller_with_snat.data['fqdn'])


@pytest.mark.check_env_('has_2_or_more_computes')
class TestDVRWestEastConnectivity(TestDVRBase):
    """Test DVR west-east routing"""

    @pytest.fixture
    def prepare_openstack(self, variables):
        # Create router
        router = self.os_conn.create_router(name="router01", distributed=True)
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])
        # Create network and instance
        self.compute_nodes = self.zone.hosts.keys()[:2]
        for i, compute_node in enumerate(self.compute_nodes, 1):
            net, subnet = self.create_internal_network_with_subnet(suffix=i)
            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(self.zone.zoneName,
                                                 compute_node),
                key_name=self.instance_keypair.name,
                nics=[{'net-id': net['network']['id']}],
                security_groups=[self.security_group.id])

        self.server1 = self.os_conn.nova.servers.find(name="server01")
        self.server1_ip = self.os_conn.get_nova_instance_ips(
            self.server1).values()[0]
        self.server2 = self.os_conn.nova.servers.find(name="server02")
        self.server2_ip = self.os_conn.get_nova_instance_ips(
            self.server2).values()[0]

    def test_routing(self, prepare_openstack):
        """Check connectivity to East-West-Routing

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed
                and with gateway to external network
            4. Add interfaces to the router01_02
                with net01_subnet and net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on different compute
            7. Add rules for ping
            8. Go to the vm_1
            9. Ping vm_2
        """
        self.check_ping_from_vm(vm=self.server1,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server2_ip)

    def test_routing_after_ban_and_clear_l3_agent(self, prepare_openstack):
        """Check West-East-Routing connectivity with floatingIP after ban
            and clear l3-agent on compute

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed and
                with gateway to external network
            4. Add interfaces to the router01_02 with net01_subnet
                and net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on different compute
            7. Ban l3-agent on the compute with vm_1: service l3-agent stop
            8. Wait 15 seconds
            9. Clear this l3-agent: service l3-agent stop
            10. Go to vm_1
            11. Ping vm_2 with internal IP
        """
        # Ban l3 agent
        compute1 = self.env.find_node_by_fqdn(self.compute_nodes[0])
        with compute1.ssh() as remote:
            remote.check_call('service neutron-l3-agent stop')

        time.sleep(15)

        # Clear l3 agent
        with compute1.ssh() as remote:
            remote.check_call('service neutron-l3-agent start')

        self.check_ping_from_vm(vm=self.server1,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server2_ip)

    def test_routing_after_reset_computes(self, prepare_openstack, env_name):
        """Check East-West connectivity after reset compute nodes

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create router01_02 with router type Distributed and
                with gateway to external network
            4. Add interfaces to the router01_02 with net01_subnet
                and net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on different compute
            7. Go to vm_1 and ping vm_2
            8. Reset computers on which vm_1 and vm_2 are
            9. Wait some time while computers are resetting
            10. Go to vm_2 and ping vm_1
        """
        self.check_ping_from_vm(vm=self.server1,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server2_ip)

        self.reset_computes(self.compute_nodes, env_name)

        time.sleep(60)
        # Check ping after reset
        self.check_ping_from_vm(vm=self.server2,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server1_ip)


@pytest.mark.check_env_('has_2_or_more_computes')
class TestDVREastWestConnectivity(TestDVRBase):
    """Test DVR east-west connectivity"""

    @pytest.fixture
    def prepare_openstack(self, variables):
        # Create router
        router = self.os_conn.create_router(name="router01")
        self.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=self.os_conn.ext_network['id'])
        # Create network and instance
        self.compute_nodes = self.zone.hosts.keys()[:2]
        for i, compute_node in enumerate(self.compute_nodes, 1):
            net, subnet = self.create_internal_network_with_subnet(suffix=i)
            self.os_conn.router_interface_add(
                router_id=router['router']['id'],
                subnet_id=subnet['subnet']['id'])
            self.os_conn.create_server(
                name='server%02d' % i,
                availability_zone='{}:{}'.format(self.zone.zoneName,
                                                 compute_node),
                key_name=self.instance_keypair.name,
                nics=[{'net-id': net['network']['id']}],
                security_groups=[self.security_group.id])

        self.server1 = self.os_conn.nova.servers.find(name="server01")
        self.server1_ip = self.os_conn.get_nova_instance_ips(
            self.server1).values()[0]
        self.server2 = self.os_conn.nova.servers.find(name="server02")
        self.server2_ip = self.os_conn.get_nova_instance_ips(
            self.server2).values()[0]

    def test_routing_east_west(self, prepare_openstack):
        """Check connectivity to East-West-Routing

        Scenario:
            1. Create net01, subnet net01__subnet for it
            2. Create net02, subnet net02__subnet for it
            3. Create centralized router01_02 with gateway to external network
            4. Add interfaces to the router01_02
                with net01_subnet and net02_subnet
            5. Boot vm_1 in the net01
            6. Boot vm_2 in the net02 on different compute
            7. Add rules for ping
            8. Go to the vm_1
            9. Ping vm_2
        """
        self.check_ping_from_vm(vm=self.server1,
                                vm_keypair=self.instance_keypair,
                                ip_to_ping=self.server2_ip)


@pytest.mark.check_env_('has_1_or_more_computes')
class TestDVRTypeChange(TestDVRBase):

    def check_exception_on_router_update_to_centralize(self, router_id):
        # Change admin_state_up to False
        # and then try to set distributed to False
        self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'admin_state_up': False}})

        # distributed parameter can't be changed from True to False
        # exception is expected here
        # in case if no exception is generated the py.test will fail
        with pytest.raises(NeutronClientException) as e:
            self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'distributed': False}})

        # allowed_msg is for doulbe check
        # There is no separate exception for each case
        # So just check that generated exception contains the expected message
        # Otherwise the test is failed
        allowed_msg = 'Migration from distributed router'
        allowed_msg = allowed_msg + ' to centralized is not supported'
        err_msg = 'Failed to update the router, exception: {}'.format(e)
        assert allowed_msg in str(e.value), err_msg

    def test_distributed_router_is_not_updated_to_centralized(self, init):
        """[Neutron DVR] Check that it is not poissible to update
           distributed router to centralized

        TestRail ids are: C542770 C542771

        Scenario:
            1. Create router with enabled dvr feature
            2. Check that distributed attribute is set to True
            3. Set admin_state_up of the router to False
            4. Try to change the distributed attribute to False
                The value should not be changed and exception occured
        """

        # Create router with default value of distributed
        # In case of dvr feature distributed default value should be True
        router = {'name': 'router01'}
        router_id = self.os_conn.neutron.create_router(
                        {'router': router})['router']['id']
        logger.info('router {} was created'.format(router_id))

        # Check that router is distributed by default
        router = self.os_conn.neutron.show_router(router_id)['router']
        err_msg = ('distributed parameter for the router {0} is {1}. '
                   "But it's expected value is True"
                  ).format(router['name'], router['distributed'])
        assert router['distributed'], err_msg

        self.check_exception_on_router_update_to_centralize(router['id'])

    @pytest.fixture
    def legacy_router(self, variables):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create centralized router1 and connect it with external net
        """

        router = self.os_conn.create_router(
                     name="router01", distributed=False)['router']
        self.os_conn.router_gateway_add(router_id=router['id'],
            network_id=self.os_conn.ext_network['id'])
        logger.info('router {} was created'.format(router['id']))
        return router

    @pytest.fixture
    def dvr_router(self, variables):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create distributed router1 and connect it with external net
        """

        router = self.os_conn.create_router(
                     name="router01", distributed=True)['router']
        self.os_conn.router_gateway_add(router_id=router['id'],
            network_id=self.os_conn.ext_network['id'])
        logger.info('router {} was created'.format(router['id']))
        return router

    def create_net_and_vm(self, router_id):
        """Prepare OpenStack for scenarios run

        Steps:
            1. Create network1 and connect it with router01
            2. Boot vm1 in network1 and associate floatidvrng ip
            3. Add rules for ping
            4. ping 8.8.8.8 from vm1
        """
        # create one network and one instacne in it
        net_id = self.os_conn.add_net(router_id)
        srv = self.os_conn.add_server(net_id,
                                      self.instance_keypair.name,
                                      self.hosts[0],
                                      self.security_group.id)

        # add floating ip to first server
        self.os_conn.assign_floating_ip(srv)

        # check pings
        self.check_vm_connectivity()

        # find the compute where the vm is run
        computes = self.env.get_nodes_by_role('compute')
        compute_ips = [node.data['ip'] for node in computes
                           if node.data['fqdn'] == self.hosts[0]]

        assert compute_ips, "Can't find the compute node with the vm"

        return compute_ips

    def test_centralized_update_to_distributed(self, legacy_router, variables):
        """[Neutron DVR] Create centralized router and update it to distributed

        TestRail ids are: C542772 C542773

        Steps:
            1. Check that the router is not distributed by default
            2. Try to change the distributed parameter
                It shouldn't be possible without
                setting admin_state_up to False
            3. Change admin_state_up to False and than set distributed to True
            4. Change admin_state_up to True to enable the router
            5. Check that the router namespace is available on the compute
            6. Ping 8.8.8.8 from vm1
            7. And finally as a bonus check that it is not poissible
                to change the router type from distributed to centralized
        """

        router_id = legacy_router['id']
        compute_ips = self.create_net_and_vm(router_id)

        # Check that router is not distributed by default
        router = self.os_conn.neutron.show_router(router_id)['router']
        err_msg = ('distributed parameter for the router {0} is {1}. '
                   "But it's expected value is False"
                  ).format(router['name'], router['distributed'])
        assert not router['distributed'], err_msg

        # Try to change the distributed parameter
        # That shouldn't be possible without setting admin_state_up to False
        # exception is expected here
        # in case if no exception is generated the py.test will fail
        with pytest.raises(NeutronClientException) as e:
            self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'distributed': True}})

        # allowed_msg is for doulbe check
        # There is no separate exception for each case
        # So just check that generated exception contains the expected message
        # Otherwise the test is failed
        allowed_msg = 'admin_state_up to False prior to upgrade'
        err_msg = 'Failed to update the router, exception: {}'.format(e)
        assert allowed_msg in str(e.value), err_msg

        # Change admin_state_up to False and than set distributed to True
        self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'admin_state_up': False}})

        self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'distributed': True}})

        # Change admin_state_up to True to enable the router
        self.os_conn.neutron.update_router(router_id,
                                           {'router': {
                                            'admin_state_up': True}})

        # Check that distributed is really changed to True
        router = self.os_conn.neutron.show_router(router_id)['router']
        err_msg = ('distributed parameter for the router {0} is {1}. '
                   "But it's expected value is True"
                  ).format(router['name'], router['distributed'])
        assert router['distributed'], err_msg

        # Check that the router namespace is available on the compute now
        with self.env.get_ssh_to_node(compute_ips[0]) as remote:
            cmd = "ip netns | grep [q]router-{}".format(router_id)
            remote.check_call(cmd)

        # check pings
        self.check_vm_connectivity()

        # And finally check that after all it is not poissible
        # to change the router type from distributed to centralized

        self.check_exception_on_router_update_to_centralize(router['id'])

    def get_snat_controller(self, host_name, router_id):
        snat_controller = None
        controllers = self.env.get_nodes_by_role('controller')
        for node in controllers:
            if node.data['fqdn'] == host_name:
                with self.env.get_ssh_to_node(node.data['ip']) as remote:
                    cmd = 'ip netns | grep [s]nat-{}'.format(router_id)
                    result = remote.execute(cmd)
                    if result['exit_code'] == 0:
                        snat_controller = node
                        break
        return snat_controller

    @pytest.mark.check_env_('is_ha')
    def test_reschedule_router_from_snat_controller(self, dvr_router):
        """[Neutron DVR] Reschedule router from snat controller

        TestRail ids are: C542780 C542781

        Steps:
            1.  Find controller with SNAT-namespace:
                ip net | grep snat on all controller
            2.  Reshedule router to another controller
            3.  Check that snat-namespace moved to another controller
            4.  Go to the vm_1 with ssh and floating IP and Ping 8.8.8.8
        """

        router_id = dvr_router['id']
        self.create_net_and_vm(router_id)

        # Find the current controller with snat namespace
        current_l3_agt = self.os_conn.neutron.list_l3_agent_hosting_routers(
                             router_id)['agents'][0]
        current_snat_controller = self.get_snat_controller(
                                      current_l3_agt['host'], router_id)
        err_msg = "Can't find controller with snat namespace"
        assert current_snat_controller, err_msg

        # Reschedule the router to any other available controller
        self.os_conn.force_l3_reschedule(router_id)
        new_l3_agt = self.os_conn.neutron.list_l3_agent_hosting_routers(
                         router_id)['agents'][0]

        # Find the new controller where the snat namespace should appear
        new_snat_controller = self.get_snat_controller(
                                      new_l3_agt['host'], router_id)
        err_msg = "Can't find controller with snat namespace"
        assert new_snat_controller, err_msg

        # Check that the router and the snat namespace
        # are really moved to other controller
        err_msg = 'SNAT namepspace and router were not moved!'
        old_host = current_snat_controller.data['fqdn']
        new_host = new_snat_controller.data['fqdn']
        assert old_host != new_host, err_msg

        # Check pings
        self.check_vm_connectivity()

    def test_create_dvr_by_no_admin_user(self):
        """[Neutron DVR] Create distributed router with member user

        TestRail ids are: C542758 C542759

        Steps:
            1.  Create new user for admin tenant with member role
            2.  Login with this user in the CLI
            3.  Create router with parameter Distributed = True
            4.  Check that creation isn't available
            5.  Create router with parameter Distributed = False
            6.  Check that creation isn't available
            7.  Create router without this parameter
            8.  Log in as admin user
            9.  Check that parameter Distributed is true
        """

        # Find the admin tenant
        admin_role = self.os_conn.keystone.roles.find(name='admin')
        admin_tenant = None
        for tenant in self.os_conn.keystone.tenants.list():
            if admin_role in tenant.manager.role_manager.list():
                admin_tenant = tenant
                break
        assert admin_tenant, "Can't find the tenant with admin role"

        # Create new user
        # Member role is used by default
        username = 'test_dvr'
        userpass = 'test_dvr'
        # But at first check if the same user exist
        # try to find it and delete
        try:
            user = self.os_conn.keystone.users.find(name=username)
            self.os_conn.keystone.users.delete(user)
        except Exception as e:
            logger.info('Tried to clean up user with result: {}'.format(e))
        # Actual user creation is here
        user = self.os_conn.keystone.users.create(name=username,
                                                  password=userpass,
                                                  tenant_id=admin_tenant.id)

        # Find the certificate for the current env
        # and log in with new user in new netron client
        cert = self.env.certificate
        path_to_cert = None
        if cert:
            with NamedTemporaryFile(prefix="fuel_cert_", suffix=".pem",
                                    delete=False) as f:
                f.write(cert)
            path_to_cert = f.name

        auth_url = self.os_conn.keystone.auth_url
        tenant_name = self.os_conn.keystone.project_name
        neutron = neutronclient.Client(username=username,
                                       password=userpass,
                                       tenant_name=tenant_name,
                                       auth_url=auth_url,
                                       ca_cert=path_to_cert)

        # Try to create router with explicit distributed True value
        # by user with memeber role but in admin tenant
        # That shouldn't be possible, exception is expected here
        # in case if no exception is generated the py.test will fail
        with pytest.raises(NeutronClientException) as e:
            router = {'name': 'router01', 'distributed': True}
            router_id = neutron.create_router(
                            {'router': router})['router']['id']
        # allowed_msg is for doulbe check
        # There is no separate exception for each case
        # So just check that generated exception contains the expected message
        # Otherwise the test is failed
        allowed_msg = 'disallowed by policy'
        err_msg = 'Failed to create the router, exception: {}'.format(e)
        assert allowed_msg in str(e.value), err_msg

        # Try to create router with explicit distributed False value
        # by user with memeber role but in admin tenant
        # exception is expected here
        with pytest.raises(NeutronClientException) as e:
            router = {'name': 'router01', 'distributed': False}
            router_id = neutron.create_router(
                            {'router': router})['router']['id']
        allowed_msg = 'disallowed by policy'
        err_msg = 'Failed to create the router, exception: {}'.format(e)
        assert allowed_msg in str(e.value), err_msg

        # Try to create router with default distributed value
        # by user with memeber role but in admin tenant
        router = {'name': 'router01'}
        router_id = neutron.create_router(
                        {'router': router})['router']['id']

        # Check that the created router has distributed value set to True
        # Check is done by admin user
        router = self.os_conn.neutron.show_router(router_id)['router']
        err_msg = ('distributed parameter for the router {0} is {1}. '
                   "But it's expected value is True"
                  ).format(router['name'], router['distributed'])
        assert router['distributed'], err_msg

        self.check_exception_on_router_update_to_centralize(router['id'])
