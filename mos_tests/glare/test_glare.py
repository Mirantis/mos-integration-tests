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


from glanceclient.exc import Forbidden
from glanceclient.exc import HTTPBadRequest
from glanceclient.exc import HTTPNotFound
from muranoclient.glance.client import Client as GlanceClient

import pytest

from mos_tests.environment.os_actions import OpenStackActions

pytestmark = pytest.mark.undestructive


@pytest.yield_fixture
def artifacts(glare_client):
    art1 = glare_client.create(name="new_art1", version='3')
    art2 = glare_client.create(name="new_art2", version='3')
    art2 = glare_client.update(art2.id, visibility='public')
    yield art1, art2
    art_list = glare_client.drafts()
    for art in art_list:
        art = glare_client.update(art.id,
                                  remove_props=['depends_on'])
        glare_client.delete(art.id)


@pytest.mark.testrail_id('857384')
def test_create_delete_artifact(glare_client):
    """Create and delete artifact"""
    art = glare_client.create(name="new_art", version='3')
    art_list = glare_client.drafts()
    assert 1 == len(list(art_list))
    glare_client.delete(art.id)
    art_list = glare_client.drafts()
    assert 0 == len(list(art_list))


@pytest.mark.testrail_id('857368')
def test_create_delete_artifact_with_dependency(glare_client, artifacts):
    """Test ability of glare create artifacts with dependency

    Scenario:
        1. Create artifact art1
        2. Create new artifact with dependency from art1
        3. Check that artifacts was created
        4. Delete artifacts
        5. Check that artifacts was deleted
    """
    art1, _ = artifacts
    art_dependency = glare_client.create(name="new_art3",
                                         version='3',
                                         depends_on=art1.id)
    assert art1.id == art_dependency.type_specific_properties['depends_on'].id


@pytest.mark.testrail_id('857370')
def test_update_dependency(glare_client, artifacts):
    """Update dependency of artifact

    Scenatio:
        1. Create 2 artifacts
        2. Update dependency one of them
        3. Check that dependency was updated
        4. Delete artifacts
    """
    art1, art2 = artifacts
    art1 = glare_client.update(art1.id,
                               depends_on=art2.id)
    assert art2.id == art1.type_specific_properties['depends_on'].id


@pytest.mark.testrail_id('857380')
def test_update_property(glare_client, artifacts):
    """Update artifact

    Scenario:
        1. Update properties for one of artifacts
        2. Check that artifact was updated
    """
    art1, _ = artifacts
    art1 = glare_client.update(art1.id,
                               name='updated_name',
                               description='my_description')
    assert 'updated_name' == art1.name
    assert 'my_description' == art1.description


@pytest.mark.testrail_id('857376')
def test_upload_blob(glare_client, artifacts):
    """Upload artifact

    Scenario:
        1. Create 2 artifacts
        2. Upload data to artifact
        3. Check that data was uploaded
        4. Delete artifacts
    """
    art1, _ = artifacts
    data = 'data'
    glare_client.upload_blob(artifact_id=art1.id,
                             blob_property='image_file',
                             data=data)
    art1 = glare_client.get(art1.id)
    assert art1.type_specific_properties['image_file'] is not None


@pytest.mark.testrail_id('857378')
def test_download_blob(glare_client, artifacts):
    """Download artifact

    Scenario:
        1. Create 2 artifacts
        2. Upload data to artifact
        3. Check that data was uploaded
        5. Download artifact
        4. Delete artifacts
    """
    art1, _ = artifacts
    data = 'data'
    blob_property = 'image_file'
    glare_client.upload_blob(artifact_id=art1.id,
                             blob_property=blob_property,
                             data=data)
    data1 = glare_client.download_blob(artifact_id=art1.id,
                                       blob_property=blob_property)
    actual_result = ''.join(data1.iterable)
    assert data == actual_result


@pytest.mark.testrail_id('857371')
def test_publish_artifact(glare_client, artifacts):
    """Publish artifact

    Scenario:
       1. Create two artifacts
       2. Add dependency for one of them
       3. Publish artifacts
    """
    art1, art2 = artifacts
    art1 = glare_client.update(art1.id,
                               depends_on=art2.id)
    with pytest.raises(HTTPBadRequest):
        glare_client.active(art1.id)

    glare_client.active(art2.id)
    glare_client.active(art1.id)
    art_list = glare_client.list()
    assert 2 == len(list(art_list))


@pytest.yield_fixture
def glare_client_non_adm(env, os_conn):
    user = 'glare_user'
    password = 'glare'
    project = 'glare_project'
    new_tenant = os_conn.keystone.tenants.create(project)
    new_user = os_conn.keystone.users.create(user, password=password, )
    os_conn_non_adm = OpenStackActions(
        controller_ip=env.get_primary_controller_ip(),
        cert=env.certificate,
        env=env,
        user=user,
        password=password,
        tenant=project)

    type_name = 'myartifact'
    type_version = '2.0'
    endpoint = os_conn_non_adm.session.get_endpoint(service_type='artifact',
                                                    interface="internalURL")
    token = os_conn_non_adm.session.get_auth_headers()['X-Auth-Token']
    glanceclient = GlanceClient(endpoint=endpoint,
                                type_name=type_name,
                                type_version=type_version,
                                token=token)
    yield glanceclient.artifacts
    os_conn.keystone.users.delete(new_user.id)
    os_conn.keystone.tenants.delete(new_tenant)


@pytest.mark.testrail_id('857382')
def test_access_to_artifact(glare_client, artifacts, glare_client_non_adm):
    """Access To Artifacts by admin and different user

    Scenario:
        1. Create Artifact
        2. Check that public and private artifacts accessable
           with admin user
        3. Check that private artifact not accessable by different user
        4. Check that public artifact accessable by different user
        5. Delete Artifacts
        6. Check that artifacts was deleted
    """
    art1, art2 = artifacts
    test_art = glare_client.get(art1.id)
    assert test_art.id == art1.id
    test_art = glare_client.get(art2.id)
    assert test_art.id == art2.id
    with pytest.raises(HTTPNotFound):
        glare_client_non_adm.get(art1.id)
    test_art = glare_client_non_adm.get(art2.id)
    assert test_art.id == art2.id


@pytest.mark.testrail_id('857383')
def test_edit_artifact(glare_client, artifacts, glare_client_non_adm):
    """Editing of Artifacts by admin and different user

    Scenario:
        1. Create Artifact
        2. Check that public and private artifacts editable
           with admin user
        3. Check that private artifact not editable by different user
        4. Check that public artifact not editable by different user
        5. Delete Artifacts
        6. Check that artifacts was deleted
    """
    art1, art2 = artifacts
    art1 = glare_client.update(art1.id,
                               name='private_adm')
    assert art1.name == 'private_adm'
    art2 = glare_client.update(art2.id,
                               name='public_adm')
    assert art2.name == 'public_adm'
    with pytest.raises(HTTPNotFound):
        glare_client_non_adm.update(art1.id,
                                    name='private_diff_user')
    art1 = glare_client.get(art1.id)
    assert art1.name == 'private_adm'
    with pytest.raises(Forbidden):
        glare_client_non_adm.update(art2.id,
                                    name='public_diff_user')
    art2 = glare_client.get(art2.id)
    assert art2.name == 'public_adm'
