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

import pytest


@pytest.mark.testrail_id('1295468')
def test_restart_all_services(env, os_conn, ceilometer_client):
    """Restart all Ceilometer services

    Scenario:
        1. Boot vm1
        2. Check that vm1 meters list is not empty
        3. Restart ceilometer services on all controllers
        4. Boot vm2
        5. Check that vm2 meters list is not empty
    """
    internal_net = os_conn.int_networks[0]
    instance_keypair = os_conn.create_key(key_name='instancekey')
    security_group = os_conn.create_sec_group_for_ssh()

    # Boot vm1
    vm1 = os_conn.create_server(name='vm1',
                                availability_zone='nova',
                                key_name=instance_keypair.name,
                                nics=[{'net-id': internal_net['id']}],
                                security_groups=[security_group.id])

    query = [dict(field='resource_id', op='eq', value=vm1.id)]
    meters = ceilometer_client.meters.list(q=query)

    assert len(meters) > 0

    # Restart ceilometer services
    ceilometer_services_cmd = ("initctl list | grep running | "
                               "grep ceilometer | awk '{ print $1 }'")
    for node in env.get_nodes_by_role('controller'):
        with node.ssh() as remote:
            output = remote.check_call(ceilometer_services_cmd).stdout_string
            for service in output.splitlines():
                remote.check_call('service {0} restart'.format(service))

    # Boot vm2
    vm2 = os_conn.create_server(name='vm2',
                                availability_zone='nova',
                                key_name=instance_keypair.name,
                                nics=[{'net-id': internal_net['id']}],
                                security_groups=[security_group.id])

    query = [dict(field='resource_id', op='eq', value=vm2.id)]
    meters = ceilometer_client.meters.list(q=query)

    assert len(meters) > 0
