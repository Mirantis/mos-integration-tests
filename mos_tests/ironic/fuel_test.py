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

import dpath.util
import pytest
import yaml

from mos_tests.environment.fuel_client import Environment

pytestmark = pytest.mark.undestructive


@pytest.yield_fixture
def new_env(fuel, env):
    new_env = Environment.create(name='test',
                                 release_id=env.data['release_id'],
                                 net_segment_type='vlan')
    yield new_env
    new_env.delete()


@pytest.yield_fixture
def admin_remote(fuel):
    with fuel.ssh_admin() as remote:
        yield remote


def check_net_settings_equals(fuel_settings, cli_settings):
    __tracebackhide__ = True

    for key in set(fuel_settings.keys()) & set(cli_settings.keys()):
        if str(fuel_settings[key]) != cli_settings[key]:
            pytest.fail('Network settings are not equals')


@pytest.mark.testrail_id('631890')
def test_baremetal_network_settings(new_env, admin_remote):
    """Check baremetal network settings with enabled/disabled Ironic

    Scenario:
        1. Create new environment with enabled Ironic
        2. Check that baremetal network are present
        3. Check that baremetal network settings are same on API and cli
        4. Disable Ironic
        5. Check that baremetal network is not present on API and cli
        6. Enable Ironic
        7. Check that baremetal network are present
        8. Check that baremetal network settings are same on API and cli
    """

    def get_baremetal_net_settings_from_cli():
        result = admin_remote.check_call(
            'fuel network-group --nodegroup {}'.format(new_env.id))
        headers = [x.strip() for x in result['stdout'][0].split('|')]
        for row in result['stdout'][2:]:
            values = [x.strip() for x in row.split('|')]
            if 'baremetal' in values:
                return dict(zip(headers, values))

    new_env.set_ironic(True)
    networks = {x['name']: x for x in new_env.get_network_data()['networks']}
    assert 'baremetal' in networks

    check_net_settings_equals(networks['baremetal'],
                              get_baremetal_net_settings_from_cli())

    # Disable Ironic
    new_env.set_ironic(False)

    networks = {x['name']: x for x in new_env.get_network_data()['networks']}
    assert 'baremetal' not in networks
    assert get_baremetal_net_settings_from_cli() is None

    # Enable Ironic
    new_env.set_ironic(True)

    networks = {x['name']: x for x in new_env.get_network_data()['networks']}
    assert 'baremetal' in networks
    check_net_settings_equals(networks['baremetal'],
                              get_baremetal_net_settings_from_cli())


@pytest.mark.testrail_id('631892', new_config={})
@pytest.mark.testrail_id(
    '631893',
    new_config={'/editable/storage/images_ceph/value': True,
                '/editable/storage/objects_ceph/value': True})
@pytest.mark.testrail_id('631894',
                         new_config={
                             '/editable/storage/images_ceph/value': True,
                             '/editable/storage/objects_ceph/value': True,
                             '/editable/storage/ephemeral_ceph/value': True,
                             '/editable/storage/volumes_ceph/value': True,
                         })
@pytest.mark.parametrize('new_config', [
    {}, {'/editable/storage/images_ceph/value': True,
         '/editable/storage/objects_ceph/value': True}, {
             '/editable/storage/images_ceph/value': True,
             '/editable/storage/objects_ceph/value': True,
             '/editable/storage/ephemeral_ceph/value': True,
             '/editable/storage/volumes_ceph/value': True,
         }
])
def test_edit_config_with_yaml(new_env, admin_remote, new_config):
    """Ironic role can be enabled in cluster via yaml config file

    Scenario:
        1. Create environment with disabled Ironic
        2. Get environment settings with
            `fuel settings --env <env id> --download`
        3. Change Ironic value to true in downloaded file
        4. Upload changed settings file with
            `fuel settings --env <env id> --upload`
        5. Check that Ironic is enabled in Fuel API
    """
    old_settings = new_env.get_settings_data()
    new_config['/editable/additional_components/ironic/value'] = True
    for key, value in new_config.items():
        assert dpath.util.get(old_settings, key) != value

    result = admin_remote.check_call(
        'fuel --env {0.id} settings --download'.format(new_env))
    path = result.stdout_string.split()[-1]
    with admin_remote.open(path, 'r+') as f:
        data = yaml.load(f)
        for key, value in new_config.items():
            dpath.util.set(data, key, value)
        yaml.dump(data, f)

    admin_remote.check_call('fuel --env {0.id} settings --upload'.format(
        new_env))

    new_settings = new_env.get_settings_data()
    for key, value in new_config.items():
        assert dpath.util.get(new_settings, key) == value
