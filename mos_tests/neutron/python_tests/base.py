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

from environment.fuel_client import FuelClient
from environment.os_actions import OpenStackActions
from mos_tests.settings import SERVER_ADDRESS
from mos_tests.settings import KEYSTONE_USER
from mos_tests.settings import KEYSTONE_PASS
from mos_tests.settings import SSH_CREDENTIALS


class BaseTest(object):
    """Base class for networking tests"""
    fuel = FuelClient(ip=SERVER_ADDRESS,
                      login=KEYSTONE_USER,
                      password=KEYSTONE_PASS,
                      ssh_login=SSH_CREDENTIALS['login'],
                      ssh_password=SSH_CREDENTIALS['password'])
    env = fuel.get_last_created_cluster()
    os_conn = OpenStackActions(
                controller_ip=env.get_primary_controller_ip())
