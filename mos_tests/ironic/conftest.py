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

import os
import shutil
import socket

from Crypto.PublicKey import RSA
from ironicclient import client
import pytest

from mos_tests.environment import devops_client
from mos_tests.functions import common
from mos_tests import settings


@pytest.yield_fixture
def server_ssh_credentials():
    # determine server ip
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 53))
    server_ip = s.getsockname()[0]
    s.close()

    # backup original authorized_keys file
    ssh_folder = os.path.expanduser('~/.ssh')
    if not os.path.exists(ssh_folder):
        os.mkdir(ssh_folder)
    authorized_keys = os.path.join(ssh_folder, 'authorized_keys')
    authorized_keys_backup = os.path.join(ssh_folder, 'authorized_keys.backup')
    if os.path.exists(authorized_keys):
        shutil.copy(authorized_keys, authorized_keys_backup)

    # make ssh key pair
    key = RSA.generate(2048)
    with open(authorized_keys, 'a+') as f:
        f.write(key.publickey().exportKey('OpenSSH'))
        f.write('\n')

    credentials = {
        'username': os.getlogin(),
        'ip': server_ip,
        'key': key.exportKey('PEM')
    }

    yield credentials

    # revert authorized_keys
    os.unlink(authorized_keys)
    if os.path.exists(authorized_keys_backup):
        shutil.move(authorized_keys_backup, authorized_keys)


@pytest.fixture
def wait_sanity_test(env):
    common.wait(lambda: env.is_ostf_tests_pass('sanity'),
                timeout_seconds=60 * 5,
                waiting_for='OSTF sanity tests to pass')


@pytest.fixture
def ironic(os_conn, wait_sanity_test):
    token = os_conn.keystone.auth_token
    ironic_endpoint = os_conn.keystone.service_catalog.url_for(
        service_type='baremetal', endpoint_type='publicURL')
    return client.get_client(api_version=1, os_auth_token=token,
                             ironic_url=ironic_endpoint)


@pytest.yield_fixture
def baremetal_node(env_name, suffix):
    devops_env = devops_client.DevopsClient.get_env(env_name=env_name)
    node = devops_env.add_node(
        memory=1024, name='baremetal_{}'.format(suffix[:4]))
    disk = node.attach_disk('system', settings.IRONIC_DISK_GB * (1024 ** 3))
    disk.volume.define()
    node.attach_to_networks(['baremetal'])
    node.define()
    node.start()
    yield node
    node.destroy()
    node.erase()
    disk.volume.erase()
    disk.delete()
