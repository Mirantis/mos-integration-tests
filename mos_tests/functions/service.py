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

from contextlib import contextmanager
import logging

from contextlib2 import ExitStack
from six import BytesIO
from six.moves import configparser

from mos_tests.functions import common

logger = logging.getLogger(__name__)


@contextmanager
def patch_conf(remote, path, new_values, restart_cmd=None):
    """Patch ini-like config and restart corresponding service

    :param remote: SSH connection (closed)
    :param path: path to config file
    :param new_values: list with tuples: [(secion, key, value), (...), ...]
    :restart_cmd: command to run after change config
    :return: bool flag indicates this config was changed
    """
    changed = False
    try:
        with remote:
            parser = configparser.RawConfigParser()
            with remote.open(path, 'rb') as f:
                orig_cong = BytesIO(f.read())
            parser.readfp(orig_cong)

            for section, key, val in new_values:
                if section != 'DEFAULT' and not parser.has_section(section):
                    changed = True
                    parser.add_section(section)
                if (parser.has_option(section, key) and
                        parser.get(section, key) == str(val)):
                    continue

                changed = True
                parser.set(section, key, val)

            if changed:
                with remote.open(path, 'wb') as f:
                    parser.write(f)

                if restart_cmd is not None:
                    remote.check_call(restart_cmd, verbose=False)
        yield changed
    finally:
        if changed:
            with remote:
                orig_cong.seek(0)
                with remote.open(path, 'wb') as f:
                    f.write(orig_cong.read())
                if restart_cmd is not None:
                    remote.check_call(restart_cmd, verbose=False)


def nova_patch(env, config, nodes=None):
    nova_config_path = '/etc/nova/nova.conf'
    restart_cmd = 'service nova-api restart || service nova-compute restart'
    nodes = nodes or (
        env.get_nodes_by_role('controller') + env.get_nodes_by_role('compute'))

    with ExitStack() as stack:
        for node in nodes:
            remote = node.ssh()
            logger.info('Patch nova config on {fqdn}'.format(**node.data))
            stack.enter_context(patch_conf(remote,
                                           path=nova_config_path,
                                           new_values=config,
                                           restart_cmd=restart_cmd))
        common.wait(env.os_conn.is_nova_ready,
                    timeout_seconds=60 * 5,
                    expected_exceptions=Exception,
                    waiting_for="Nova services to be alive")
        yield

    common.wait(env.os_conn.is_nova_ready,
                timeout_seconds=60 * 5,
                expected_exceptions=Exception,
                waiting_for="Nova services to be alive")
