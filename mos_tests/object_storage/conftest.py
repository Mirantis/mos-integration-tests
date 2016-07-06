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

import logging
import ntpath
import os
import random
import tempfile

import pytest
from six.moves import configparser
from swiftclient import client

from mos_tests.functions import os_cli

logger = logging.getLogger(__name__)


@pytest.yield_fixture(scope='module')
def ctrl_remote(env):
    """SSH remote to random controller"""
    controller = env.get_nodes_by_role('controller')[0]
    with controller.ssh() as remote:
        yield remote


@pytest.fixture(scope='module')
def openstack_client(ctrl_remote):
    """Client to Openstack"""
    return os_cli.OpenStack(ctrl_remote)


@pytest.fixture
def os_swift_client(ctrl_remote):
    """Client to Swift"""
    return os_cli.OpenStackSwift(ctrl_remote)


@pytest.fixture
def s3cmd_client(ctrl_remote):
    """Client to s3cmd tool"""
    return os_cli.S3CMD(ctrl_remote)


@pytest.yield_fixture
def swift_container(os_swift_client):
    """Creates container with OpenStack Swift client"""
    bucketname = 'TESTBUCKET{0}'.format(random.randint(0, 10000))
    container = os_swift_client.container_create(bucketname)[0]
    yield container['container']
    # remove buckets if it wasn't done in test
    try:
        os_swift_client.container_delete(bucketname)
    except Exception:
        pass


@pytest.yield_fixture
def s3cmd_create_container(s3cmd_client):
    """Creates container with S3cmd client"""
    bucketname = 'TESTBUCKET{0}'.format(random.randint(0, 10000))
    out = s3cmd_client.bucket_make(bucketname)
    yield bucketname, out
    # remove buckets if it wasn't done in test
    try:
        s3cmd_client.bucket_remove(bucketname, recursive=True)
    except Exception:
        pass


@pytest.yield_fixture
def create_file_on_node(ctrl_remote, request):
    """Creates tmp file with requested size"""
    size_mb = getattr(request, 'param', 111)
    _, f_path = tempfile.mkstemp(prefix='ObjStor_')
    f_name = ntpath.basename(f_path)
    cmd = 'fallocate -l {0}M {1}'.format(size_mb, f_path)
    ctrl_remote.check_call(cmd)
    yield f_path, f_name
    # delete file
    cmd = 'rm -rf {0}'.format(f_path)
    ctrl_remote.check_call(cmd)


@pytest.yield_fixture(scope='class')
def s3cmd_install_configure(env, ctrl_remote, openstack_client):
    """Install and configure s3cmd on controller"""

    ceph_config_file = '/etc/ceph/ceph.conf'         # cfg file on controller
    restart_radosgw = "/etc/init.d/radosgw restart"  # restart command
    remote_cfg_file = '/root/.s3cfg'                 # s3cmd cfg file on node
    local_templ_name = 's3cfg'                       # local template name

    def templates_dir_path():
        """Returns full path to local template dir"""
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'templates/')

    def get_management_vip_ip(env):
        """Get 'management_vip' from fuel network config"""
        return env.get_network_data()['management_vip']

    def _s3cmd_enable_keystone_auth(env):
        """Enable the Keystone auth backend in RadosGW on all controllers"""
        logger.debug('Enable the Keystone auth backend in RadosGW on '
                     'all controllers ')

        def parser_set_value():
            """set new value in config file"""
            with node.open(ceph_config_file, 'r') as f:
                parser = configparser.RawConfigParser()
                parser.readfp(f)
                # if value already set -> don't modify and restart radosgw.
                try:
                    parser.get('client.radosgw.gateway',
                               'rgw_s3_auth_use_keystone')
                except Exception:
                    parser.set('client.radosgw.gateway',
                               'rgw_s3_auth_use_keystone', True)
                    logger.debug('Set "rgw_s3_auth_use_keystone" on %s' %
                                 node.host)
                else:
                    logger.debug('Already enabled on %s' % node.host)
            # write file
            with node.open(ceph_config_file, 'w') as new_f:
                parser.write(new_f)
            # restart radosgw
            node.check_call(restart_radosgw)

        for controller in env.get_nodes_by_role('controller'):
            with controller.ssh() as node:
                parser_set_value()

    def _s3cmd_create_ec2_credentials(openstack_client):
        """Create admin ec2-credentials with access+secret keys"""
        admin_id = openstack_client.user_show('admin')['id']
        admin_prj_id = openstack_client.project_show('admin')['id']
        # Check if admin's ec2 keys already present. If so - use them.
        ec2_cred_list = openstack_client.ec2_cred_list()
        if len(ec2_cred_list) > 0:
            access_key, secret_key = [[x['Access'], x['Secret']]
                                      for x in ec2_cred_list
                                      if x['User ID'] == admin_id and
                                      x['Project ID'] == admin_prj_id][0]
            if access_key and secret_key:
                return access_key, secret_key
        # Create new pair of ec2 keys
        creds = openstack_client.ec2_cred_create(admin_id, admin_prj_id)
        access_key, secret_key = creds['access'], creds['secret']
        return access_key, secret_key

    def _s3cmd_install_on_ctrllr(remote):
        """Install s3cmd on controller"""
        logger.debug('Install s3cmd on %s' % remote.host)
        # Check if s3cmd already installed on node
        if remote.execute('which s3cmd', verbose=False).is_ok:
            logger.debug('s3cmd already installed on %s' % remote.host)
            return
        # If s3cmd not installed on node
        cmd = ('apt-get update && apt-get install python-pip -y && '
               'pip install setuptools --upgrade && '
               'pip install wheel && pip install s3cmd ;')
        remote.check_call(cmd)

    def _s3cmd_create_conf_file(remote, access_key, secret_key, vip_ip):
        """Create config file for s3cmd and put in on controller"""
        logger.debug('Create config file [{0}] for s3cmd on {1}'.format(
            remote_cfg_file, remote.host))
        # read template
        cfg_tmpl = templates_dir_path() + local_templ_name
        with open(cfg_tmpl, 'r') as f:
            parser = configparser.RawConfigParser()
            parser.readfp(f)
            parser.set('default', 'access_key', access_key)
            parser.set('default', 'secret_key', secret_key)
            parser.set('default', 'host_base', '{0}:8080'.format(vip_ip))
            parser.set('default', 'host_bucket', '%(bucket)s.{0}:8080'.format(
                vip_ip))
        # write file on node
        with remote.open(remote_cfg_file, 'w') as new_f:
            parser.write(new_f)

    # Enable the Keystone auth backend in RadosGW
    _s3cmd_enable_keystone_auth(env)
    # Create admin ec2-credentials with access+secret keys
    access_key, secret_key = _s3cmd_create_ec2_credentials(
        openstack_client)
    # Install s3cmd on one controller
    _s3cmd_install_on_ctrllr(ctrl_remote)
    # get vip_ip from nailgun node
    vip_ip = get_management_vip_ip(env)
    # Create config file for s3cmd on one controller
    _s3cmd_create_conf_file(ctrl_remote, access_key, secret_key, vip_ip)
    yield
    # ec2 delete credentials
    openstack_client.ec2_cred_del(access_key)


@pytest.yield_fixture(scope='class')
def s3cmd_cleanup(ctrl_remote, env):
    yield
    ceph_config_file = '/etc/ceph/ceph.conf'         # cfg file on controller
    restart_radosgw = "/etc/init.d/radosgw restart"  # restart command
    remote_cfg_file = '/root/.s3cfg'                 # s3cmd cfg file on node
    cmd = ('rm -rf {0} ; '
           'pip uninstall s3cmd -y ; '
           'apt-get remove python-pip -y').format(remote_cfg_file)
    ctrl_remote.check_call(cmd)

    # Remove config file changes and restart radosgw
    def parser_set_value():
        with node.open(ceph_config_file, 'r') as f:
            parser = configparser.RawConfigParser()
            parser.readfp(f)
            try:
                parser.remove_option(
                    'client.radosgw.gateway', 'rgw_s3_auth_use_keystone')
            except Exception:
                pass
        # write file
        with node.open(ceph_config_file, 'w') as new_f:
            parser.write(new_f)
        # restart radosgw
        node.check_call(restart_radosgw)

    for controller in env.get_nodes_by_role('controller'):
        with controller.ssh() as node:
            parser_set_value()


@pytest.fixture
def swift_client(os_conn):
    return client.Connection(authurl=os_conn.session.auth.auth_url,
                             user=os_conn.session.auth.username,
                             key=os_conn.session.auth.password,
                             tenant_name=os_conn.session.auth.tenant_name,
                             auth_version='2')
