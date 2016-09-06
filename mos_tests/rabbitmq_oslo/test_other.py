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

import json
import logging
import pytest
import random

from six.moves import configparser
from tempest.lib.cli import output_parser

from mos_tests.functions.common import is_task_ready
from mos_tests.functions.common import wait
from mos_tests.neutron.python_tests.base import TestBase
from mos_tests.rabbitmq_oslo.utils import BashCommand

logger = logging.getLogger(__name__)


class Helpers(TestBase):

    @pytest.fixture(autouse=True)
    def tools(self):
        self.cmd = BashCommand

    TIMEOUT_FOR_DEPLOY = 120  # minutes

    def reset_env(self, timeout=2):
        self.env.reset()
        wait(lambda: self.env.status == 'new',
             timeout_seconds=60 * timeout,
             sleep_seconds=20,
             waiting_for="Env reset finish")

    def delete_env(self, timeout=2):
        self.env.reset()
        wait(lambda: self.env.status == 'new',
             timeout_seconds=60 * timeout,
             sleep_seconds=20,
             waiting_for="Env reset finish")
        self.env.delete()

    def deploy_env(self):
        """Deploy env and wait till it will be deployed"""
        deploy_task = self.env.deploy_changes()
        wait(lambda: is_task_ready(deploy_task),
             timeout_seconds=60 * self.TIMEOUT_FOR_DEPLOY,
             sleep_seconds=60,
             waiting_for='changes to be deployed')

    def enable_kombu_compression(self, admin_remote):
        """Enable kombu compression from nailgun node
        :param admin_remote: Nailgun ssh connection point.
        """
        logger.debug("Enable kombu compression inside env config for nodes.")

        admin_remote.execute('rm -rf /root/deployment_1')
        admin_remote.check_call('fuel deployment --env 1 --default')
        admin_remote.check_call(
            "for i in "
            "$(find /root/deployment_1/ -type f -name '*[0-9]*.yaml'); "
            "do echo 'kombu_compression: gzip' >> ${i}; "
            "done")

    def get_rabbit_user_password(self):
        """Get rabbit user and password from config file"""
        logger.debug("Get RabbitMQ credentials from nova config file.")

        nova_cfg_f = '/etc/nova/nova.conf'
        controller = random.choice(self.env.get_nodes_by_role('controller'))
        with controller.ssh() as remote:
            with remote.open(nova_cfg_f) as f:
                parser = configparser.RawConfigParser()
                parser.readfp(f)
                r_usr = parser.get('oslo_messaging_rabbit', 'rabbit_userid')
                r_pwd = parser.get('oslo_messaging_rabbit', 'rabbit_password')

        return {'usr': r_usr,
                'pwd': r_pwd}

    def rabbitmqadmin_get_queue(self, user, passwd):
        """Get get queue=conductor from rabbitmqadmin.
        :param user: RabbitMQ username.
        :param passwd: RabbitMQ password.
        :return: Parsed output.
        """
        logger.debug("Get queue from rabbitmqadmin")

        controller = random.choice(self.env.get_nodes_by_role('controller'))
        with controller.ssh() as remote:
            out = remote.check_call(
                self.cmd.rabbitmqctl.get_queue.format(usr=user, pwd=passwd))
        out = out.stdout_string
        return output_parser.listing(out)


@pytest.mark.check_env_("is_ha")
class TestOtherRabbit(Helpers):

    # destructive
    @pytest.mark.testrail_id('1617223')
    def test_kombu_message_compression(self, env, os_conn, admin_remote):
        """Tests Kombu message compression.

        Actions:
        1. Enable combu gzip compression for all nodes.
        2. Reset Fuel env.
        3. Deploy Fuel env.
        4. Stop nova-conductor service on all controllers.
        5. Create VM.
        6. Get queue=conductor from rabbitmqadmin.
        7. Check that in 'payload' column information in encoded.
        8. Check that after decoding information is a Json data.

        Duration: ~1.5 hours
        """
        cmd_fuel_upload = 'fuel deployment --env 1 --upload'
        cmd_nova_stop = 'service nova-conductor stop'

        # Enable compression
        self.enable_kombu_compression(admin_remote)

        # Reset, update, deploy env
        self.reset_env()
        admin_remote.check_call(cmd_fuel_upload)
        self.deploy_env()

        # Stop nova-conductor from controllers
        for one in env.get_nodes_by_role('controller'):
            with one.ssh() as remote:
                remote.check_call(cmd_nova_stop)

        # Create VM, do not wait for it
        internal_net = os_conn.int_networks[0]
        instance_keypair = os_conn.create_key(key_name='instancekey')
        security_group = os_conn.create_sec_group_for_ssh()

        os_conn.create_server(
            name='vm1',
            availability_zone='nova',
            key_name=instance_keypair.name,
            nics=[{'net-id': internal_net['id']}],
            security_groups=[security_group.id],
            wait_for_active=False,
            wait_for_avaliable=False,)

        # Get rabbit credentials
        creds = self.get_rabbit_user_password()
        r_usr, r_pwd = creds['usr'], creds['pwd']

        # Get nova conductor queue
        queues = self.rabbitmqadmin_get_queue(r_usr, r_pwd)
        nova_queues = [x for x in queues if x['exchange'] == 'nova']

        # Check that information is a encoded json.
        # If no - there will be a decoding error.
        # Without enabled 'kombu_compression' there will be just plain json.
        for item in nova_queues:
            json_info = json.loads(
                item['payload'].decode('base64').decode('zlib'))

            logger.debug(json_info)
            assert isinstance(json_info, dict), (
                'Decoded instance in not a JSON object')

    @pytest.mark.undestructive
    @pytest.mark.testrail_id('1617226')
    def test_appropriate_async_thread_pool_size_on_master(self, admin_remote):
        """Check appropriate async thread pool size on master node.

        Actions:
        1. Get number of CPU from master node. (Should be > 4).
        2. Get Rabbit async thread pool size.
        3. Rabbit async thread pool size should be between 64 and 1024,
        closest to 16 * <number of CPU cores>.
        """
        # Get num of CPU from master node
        cpu_count = admin_remote.check_call(self.cmd.system.cpu_count)
        cpu_count = int(cpu_count.stdout_string)

        if cpu_count <= 4:
            pytest.skip(
                '\nFor this test Master node should have more then 4 CPUs.'
                '\nNow it has only "{0}" CPU(s).'.format(cpu_count))

        # Get rabbit async thread pool size
        pool_size = admin_remote.check_call(
            self.cmd.system.master_thread_pool_size)
        pool_size = int(pool_size.stdout_string)

        calculated_pool_size = cpu_count * 16
        if calculated_pool_size < 64:
            calculated_pool_size = 64

        assert 64 <= pool_size, ("Rabbit appropriate async thread pool "
                                 "size smaller then 64.")

        assert 1024 >= pool_size, ("Rabbit appropriate async thread pool "
                                   "size bigger then 1024.")

        assert calculated_pool_size == pool_size, (
            "Real rabbit thread_pool_size != calculated.")
