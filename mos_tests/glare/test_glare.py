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

pytestmark = pytest.mark.undestructive


@pytest.yield_fixture
def artifacts(glare_client):
    art1 = glare_client.create(name="new_art1", version='3')
    art2 = glare_client.create(name="new_art2", version='3')
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
