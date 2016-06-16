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
import uuid


flavor = 'm1.medium'
linux = 'debian-8-m-agent.qcow2'
availability_zone = 'nova'


@pytest.mark.parametrize('package', [('ApacheHttpServer',)],
                         indirect=['package'])
@pytest.mark.testrail_id('844935')
def test_deploy_app_with_volume_creation(environment, murano,
                                         session, keypair):
    """Check app deployment with volume creation
    Steps:
        1. Create Murano environment
        2. Add ApacheHTTPServer application with ability to create and attach
        Cinder volume with size 1 GiB to the instance
        3. Deploy environment
        4. Make sure that deployment finished successfully
        5. Check that application is accessible
        6. Check that volume is attached to the instance and has size 1GiB
        7. Delete environment
    """
    post_body = {
        "instance": {
            "flavor": flavor,
            "image": linux,
            "assignFloatingIp": True,
            "keyname": keypair.id,
            "availabilityZone": availability_zone,
            "volumes": {
                "/dev/vdb": {
                    "?": {
                        "type": "io.murano.resources.CinderVolume"
                    },
                    "size": 1
                }
            },
            "?": {
                "type": "io.murano.resources.LinuxMuranoInstance",
                "id": str(uuid.uuid4())
            },
            "name": murano.rand_name("testMurano")
        },
        "name": murano.rand_name("Apache"),
        "?": {
            "_{id}".format(id=uuid.uuid4().hex): {
                "name": "Apache"
            },
            "type": "io.murano.apps.apache.ApacheHttpServer",
            "id": str(uuid.uuid4())
        }
    }
    murano.create_service(environment, session, post_body)
    murano.deploy_environment(environment, session)
    murano.deployment_success_check(environment, ports=[22, 80])
    vm = murano.get_instance_id('testMurano')
    volume_data = murano.get_volume(environment.id)
    assert volume_data.attributes['attachments'][0]['server_id'] == vm
    assert volume_data.attributes['size'] == 1
