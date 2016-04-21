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
from six.moves import configparser
import yaml

pytestmark = pytest.mark.undestructive


@pytest.fixture
def compute(env):
    return env.get_nodes_by_role('compute')[0]


@pytest.yield_fixture
def patch_config(compute):
    pipeline_path = '/etc/ceilometer/pipeline.yaml'
    ceilometer_conf_path = '/etc/ceilometer/ceilometer.conf'

    with compute.ssh() as remote:
        for path in (pipeline_path, ceilometer_conf_path):
            remote.check_call('cp {0} {0}.bak'.format(path))

        with remote.open(pipeline_path) as f:
            data = yaml.load(f)
        for s in data['sources']:
            if s['name'] == 'cpu_source':
                s['interval'] = 10
                break
        with remote.open(pipeline_path, 'w') as f:
            yaml.dump(data, f)

        parser = configparser.RawConfigParser()
        with remote.open(ceilometer_conf_path) as f:
            parser.readfp(f)
        parser.set('compute', 'resource.update.interval', 600)
        with remote.open(ceilometer_conf_path, 'w') as f:
            parser.write(f)

        yield

        for path in (pipeline_path, ceilometer_conf_path):
            remote.execute('mv {0}.bak {0}'.format(path))


@pytest.yield_fixture
def instance(os_conn, compute):
    net = os_conn.neutron.list_networks(**{'router:external': False,
                                           'status': 'ACTIVE'})['networks'][0]
    server = os_conn.create_server('server01',
                                   nics=[{'net-id': net['id']}],
                                   wait_for_avaliable=False)
    yield
    server.delete()


@pytest.mark.testrail_id('842507')
def test_nova_polling(env, compute, patch_config, instance, ceilometer_client):
    """Test nova polling

    Scenario:
        1. Boot instance with name test1:
            nova boot test1 --image <Image ID> --flavor <Flavor ID> \
            --nic net-id=<Net ID>
        2. Connect database on the mongo node:
            mongo ceilometer
        3. Clear datebase:
            db.meter.remove({}), db.resource.remove({})
        4. Execute on contorller:
            . openrc && ceilometer sample-list -m cpu_util
        5. Check that output list is empty
    """
    with env.get_nodes_by_role('mongo')[0].ssh() as remote:
        remote.check_call('echo "db.meter.remove({}), db.resource.remove({})" '
                          '| mongo ceilometer')
    result = ceilometer_client('sample-list -m cpu_util').listing()
    assert len(result) == 0
