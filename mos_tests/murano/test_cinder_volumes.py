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


def deploy_and_check_apache(environment, murano, session, keypair, volumes):
    post_body = {
        "instance": {
            "flavor": flavor,
            "image": linux,
            "assignFloatingIp": True,
            "keyname": keypair.id,
            "availabilityZone": availability_zone,
            "volumes": volumes,
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
    volumes = {
        "/dev/vdb": {
            "?": {
                "type": "io.murano.resources.CinderVolume"
            },
            "size": 1
        }
    }
    deploy_and_check_apache(environment, murano, session, keypair, volumes)
    volume_data = murano.get_volume(environment.id)
    murano.check_volume_attached('testMurano',
                                 volume_data.physical_resource_id)
    assert volume_data.attributes['size'] == 1


@pytest.mark.check_env_("not is_ceph_enabled")
@pytest.mark.testrail_id('844936')
def test_deploy_app_with_volume_creation_multiattach_readonly(environment,
                                                              murano, session,
                                                              keypair):
    """Check app deployment with volume creation with multiattach and readonly
    attributes
    Steps:
        1. Create Murano environment
        2. Add ApacheHTTPServer application with ability to create and attach
        Cinder volume with size 1 GiB, multiattach and readonly properties
        to the instance
        3. Deploy environment
        4. Make sure that deployment finished successfully
        5. Check that application is accessible
        6. Check that volume is attached to the instance, has size 1GiB,
        multiattach, readonly attributes
        7. Delete environment
    """
    volumes = {
        "/dev/vdb": {
            "?": {
                "type": "io.murano.resources.CinderVolume"
            },
            "size": 1,
            "readOnly": True,
            "multiattach": True
        }
    }
    deploy_and_check_apache(environment, murano, session, keypair, volumes)
    volume_data = murano.get_volume(environment.id)
    murano.check_volume_attached('testMurano',
                                 volume_data.physical_resource_id)
    assert volume_data.attributes['size'] == 1
    assert volume_data.attributes['metadata']['readonly']
    assert volume_data.attributes['multiattach']


@pytest.mark.testrail_id('844937')
def test_deploy_app_with_volume_creation_from_image(environment, murano,
                                                    session, keypair):
    """Check app deployment with volume creation from image
    Steps:
        1. Create Murano environment
        2. Add ApacheHTTPServer application with ability to create Cinder
        volume with size 2 GiB from image TestVM and attach it to the instance
        3. Deploy environment
        4. Make sure that deployment finished successfully
        5. Check that application is accessible
        6. Check that volume is attached to the instance, has size 2GiB and
        created from image
        7. Delete environment
    """
    volumes = {
        "/dev/vdb": {
            "?": {
                "type": "io.murano.resources.CinderVolume"
            },
            "size": 2,
            "sourceImage": linux
        }
    }
    deploy_and_check_apache(environment, murano, session, keypair, volumes)
    volume_data = murano.get_volume(environment.id)
    murano.check_volume_attached('testMurano',
                                 volume_data.physical_resource_id)
    assert volume_data.attributes['size'] == 2
    image = volume_data.attributes['volume_image_metadata']['image_name']
    assert image == linux


@pytest.mark.testrail_id('844938')
def test_deploy_app_with_volume_creation_from_volume(volume, environment,
                                                     murano, session, keypair):
    """Check app deployment with volume creation from image
    Steps:
        1. Create Murano environment
        2. Add ApacheHTTPServer application with ability to create Cinder
        volume with size 1 GiB from exist volume and attach it to the instance
        3. Deploy environment
        4. Make sure that deployment finished successfully
        5. Check that application is accessible
        6. Check that volume is attached to the instance, has size 1GiB and
        created from exist volume
        7. Delete environment
    """
    volumes = {
        "/dev/vdb": {
            "?": {
                "type": "io.murano.resources.CinderVolume"
            },
            "size": 1,
            "sourceVolume": {
                "?": {
                    "type": "io.murano.resources.ExistingCinderVolume"
                },
                "openstackId": volume.id
            }
        }
    }
    deploy_and_check_apache(environment, murano, session, keypair, volumes)
    volume_data = murano.get_volume(environment.id)
    murano.check_volume_attached('testMurano',
                                 volume_data.physical_resource_id)
    assert volume_data.attributes['size'] == 1
    assert volume_data.attributes['source_volid'] == volume.id


@pytest.mark.testrail_id('844939')
def test_deploy_app_with_volume_creation_from_snapshot(volume_snapshot,
                                                       environment, murano,
                                                       session, keypair):
    """Check app deployment with volume creation from volume snapshot
    Steps:
        1. Create Cinder volume and make snapshot from it
        2. Create Murano environment
        3. Add ApacheHTTPServer application with ability to create Cinder
        volume with size 1 GiB from exist volume snapshot and attach it to
        the instance
        4. Deploy environment
        5. Make sure that deployment finished successfully
        6. Check that application is accessible
        7. Check that volume is attached to the instance, has size 1GiB and
        created from exist volume snapshot
        8. Delete environment, volume, snapshot
    """
    volumes = {
        "/dev/vdb": {
            "?": {
                "type": "io.murano.resources.CinderVolume"
            },
            "size": 1,
            "sourceSnapshot": {
                "?": {
                    "type": "io.murano.resources.CinderVolumeSnapshot"
                },
                "openstackId": volume_snapshot.id
            }
        }
    }
    deploy_and_check_apache(environment, murano, session, keypair, volumes)
    volume_data = murano.get_volume(environment.id)
    murano.check_volume_attached('testMurano',
                                 volume_data.physical_resource_id)
    assert volume_data.attributes['size'] == 1
    assert volume_data.attributes['snapshot_id'] == volume_snapshot.id


@pytest.mark.testrail_id('844940')
def test_deploy_app_with_volume_creation_from_backup(volume_backup,
                                                     environment, murano,
                                                     session, keypair):
    """Check app deployment with volume creation from volume backup
    Steps:
        1. Create Cinder volume and make backup from it
        2. Create Murano environment
        3. Add ApacheHTTPServer application with ability to create Cinder
        volume with size 1 GiB from exist volume backup and attach it to
        the instance
        4. Deploy environment
        5. Make sure that deployment finished successfully
        6. Check that application is accessible
        7. Check that volume is attached to the instance, has size 1GiB and
        restored from exist volume backup
        8. Delete environment, volume, backup
    """
    volumes = {
        "/dev/vdb": {
            "?": {
                "type": "io.murano.resources.CinderVolume"
            },
            "size": 1,
            "name": "restore_backup" + volume_backup.id,
            "sourceVolumeBackup": {
                "?": {
                    "type": "io.murano.resources.CinderVolumeBackup"
                },
                "openstackId": volume_backup.id
            }
        }
    }
    deploy_and_check_apache(environment, murano, session, keypair, volumes)
    volume_data = murano.get_volume(environment.id)
    murano.check_volume_attached('testMurano',
                                 volume_data.physical_resource_id)
    assert volume_data.attributes['size'] == 1
    assert volume_backup.id in volume_data.attributes['name']


@pytest.mark.testrail_id('844941')
def test_deploy_app_with_existing_volume(volume, environment, murano,
                                         session, keypair):
    """Check app deployment with existing volume attached to instance
    Steps:
        1. Create Cinder volume
        2. Create Murano environment
        3. Add ApacheHTTPServer application with ability to attach existing
        Cinder volume to the instance
        4. Deploy environment
        5. Make sure that deployment finished successfully
        6. Check that application is accessible
        7. Check that volume is attached to the instance
        8. Delete environment, volume
    """
    volumes = {
        "/dev/vdb": {
            "?": {
                "type": "io.murano.resources.ExistingCinderVolume"
            },
            "openstackId": volume.id
        }
    }
    deploy_and_check_apache(environment, murano, session, keypair, volumes)
    murano.check_volume_attached('testMurano', volume.id)


@pytest.mark.testrail_id('844942')
def test_deploy_app_with_boot_volume_as_image(environment, murano, session,
                                              keypair):
    """Check app deployment using boot volume as image
    Steps:
        1. Create Murano environment
        2. Add ApacheHTTPServer application with ability to boot instance from
        Cinder volume as image
        3. Deploy environment
        4. Make sure that deployment finished successfully
        5. Check that application is accessible
        6. Check that instance is not booted from image, volume is attached
        to the instance, has size 4GiB and created from image
        7. Delete environment
    """
    post_body = {
        "instance": {
            "flavor": flavor,
            "blockDevices": {
                "volume": {
                    "?": {
                        "type": "io.murano.resources.CinderVolume"
                    },
                    "size": 4,
                    "sourceImage": linux
                },
                "bootIndex": 0,
                "deviceName": "vda",
                "deviceType": "disk"
            },
            "assignFloatingIp": True,
            "keyname": keypair.id,
            "availabilityZone": availability_zone,
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

    volume_data = murano.get_volume(environment.id)
    vm_id = murano.get_instance_id('testMurano')
    assert not murano.os_conn.nova.servers.get(vm_id).image
    assert volume_data.attributes['size'] == 4
    image = volume_data.attributes['volume_image_metadata']['image_name']
    assert image == linux
