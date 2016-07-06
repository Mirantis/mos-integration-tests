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


@pytest.mark.testrail_id('1295482')
@pytest.mark.check_env_('not is_images_ceph_enabled')
def test_all_swift_services_restart(env, os_conn, swift_client):
    """Check Glance work correctly after restarting all Swift services

    Scenario:
        1. Restart all Swift services on all containers
        2. Create new container
        3. Check that created container in container's list
        4. Upload/download test file to container and check it content
        5. Upload new image to Glance
        6. Download image created on step 5 and compare it content
    """
    # Restart swift services
    swift_services_cmd = ("initctl list | grep running | grep swift | "
                          "awk '{ print $1 }'")
    for node in env.get_nodes_by_role('controller'):
        with node.ssh() as remote:
            output = remote.check_call(swift_services_cmd).stdout_string
            for service in output.splitlines():
                remote.check_call('restart {0}'.format(service))

    container_name = 'test_container'
    swift_client.put_container(container_name)

    _, containers = swift_client.get_account()
    assert len([x for x in containers if x['name'] == container_name]) == 1

    file_name = 'test_content.txt'
    content = 'test_content'

    swift_client.put_object(container_name, file_name, content)

    _, downloaded_content = swift_client.get_object(container_name, file_name)

    assert downloaded_content == content

    image = os_conn.glance.images.create(name="test_image",
                                         disk_format='qcow2',
                                         container_format='bare')

    os_conn.glance.images.upload(image.id, content)

    assert ''.join(os_conn.glance.images.data(image.id)) == content
