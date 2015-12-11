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

import os

# Fuel master server ip
SERVER_ADDRESS = os.environ.get('SERVER_ADDRESS', '10.109.0.2')

# Default SSH password 'ENV_FUEL_PASSWORD' can be changed on Fuel master node
SSH_CREDENTIALS = {
    'login': os.environ.get('ENV_FUEL_LOGIN', 'root'),
    'password': os.environ.get('ENV_FUEL_PASSWORD', 'r00tme')}

KEYSTONE_USER = os.environ.get('KEYSTONE_USER', 'admin')
KEYSTONE_PASS = os.environ.get('KEYSTONE_PASS', 'admin')

# Default 'KEYSTONE_PASSWORD' can be changed for keystone on Fuel master node
KEYSTONE_CREDS = {'username': KEYSTONE_USER,
                  'password': KEYSTONE_PASS,
                  'tenant_name': os.environ.get('KEYSTONE_TENANT', 'admin')}

PUBLIC_TEST_IP = os.environ.get('PUBLIC_TEST_IP', '8.8.8.8')
