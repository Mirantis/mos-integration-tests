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
import math
import re

import pytest

from mos_tests.neutron.python_tests.base import TestBase

logger = logging.getLogger(__name__)


class Helpers(object):

    @staticmethod
    def wa_for_1543135(env):
        """WA for: Wrong OS_AUTH_URL makes keystone operations fail
        https://bugs.launchpad.net/mos/+bug/1543135
        Changes OS_AUTH_URL from ":5000/" --> ":5000/v2.0" in /root/openrc
        """
        logger.warning('Applying WA for bug #1543135')
        cmd = r"sed -i 's#:5000/\x27#:5000/v2.0\x27#g' /root/openrc"
        for controller in env.get_nodes_by_role('controller'):
            with controller.ssh() as remote:
                remote.check_call(cmd)


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ceph_enabled')
@pytest.mark.check_env_('is_radosgw_enabled')
class TestObjectStorageS3CMD(TestBase, Helpers):
    """Object Storage - CRUD Operations Tests
    """
    f_size = 100       # MB
    f_size_b = 5432    # MB
    chunk_size = 1024  # MB

    @pytest.fixture(autouse=True)
    def setUp_install_configure_s3cmd(
            self, s3cmd_install_configure, s3cmd_cleanup):
        logger.debug('Install and configure S3CMD on controller')
        # then remove s3cmd when tests are done

    @pytest.mark.testrail_id('838857')
    def test_object_storage_s3cmd_container_create(
            self, s3cmd_client, s3cmd_create_container):
        """Create container in Object Storage (RadosGW)

        Actions:
        1. Create container via s3cmd cli utility.
        2. Show containers list and check that container presents.
        3. Delete container.
        """
        bname, make_out = s3cmd_create_container
        ls_out = s3cmd_client.bucket_ls()
        s3cmd_client.bucket_remove(bname)
        assert re.match(
            'Bucket.+{0}.+created'.format(bname), make_out
        ) is not None
        assert bname in ''.join(ls_out)

    @pytest.mark.testrail_id('842477')
    def test_object_storage_s3cmd_container_delete(
            self, s3cmd_client, s3cmd_create_container):
        """Delete container from Object Storage (RadosGW)

        Actions:
        1. Create container via s3cmd cli utility.
        2. Delete container.
        3. Show containers list and check that container doesn't presents.
        """
        bname, _ = s3cmd_create_container
        rem_out = s3cmd_client.bucket_remove(bname)
        ls_out = s3cmd_client.bucket_ls()
        assert re.match(
            'Bucket.+{0}.+removed'.format(bname), rem_out) is not None
        assert bname not in ''.join(ls_out)

    @pytest.mark.testrail_id('842480')
    @pytest.mark.parametrize('create_file_on_node', [f_size], indirect=True)
    def test_object_storage_s3cmd_obj_upload(
            self, s3cmd_client, s3cmd_create_container, create_file_on_node):
        """Upload object to Object Storage (RadosGW)

        Actions:
        1. Create file (object) on controller.
        2. Create container via s3cmd cli utility.
        3. Put object to created container.
        4. With list check that object present in container.
        5. Delete container.
        """
        f_path, f_name = create_file_on_node
        bname, _ = s3cmd_create_container
        s3cmd_client.bucket_put_file(bname, f_path)
        ls_in = s3cmd_client.bucket_ls(bname)
        s3cmd_client.bucket_remove(bname, recursive=True)
        obj_path = '{0}/{1}'.format(bname, f_name)
        assert obj_path in ''.join(ls_in)

    @pytest.mark.testrail_id('842478')
    @pytest.mark.parametrize('create_file_on_node', [f_size], indirect=True)
    def test_object_storage_s3cmd_obj_delete(
            self, s3cmd_client, s3cmd_create_container, create_file_on_node):
        """Delete object from Object Storage (RadosGW)

        Actions:
        1. Create file (object) on controller.
        2. Create container via s3cmd cli utility.
        3. Put object to created container.
        4. Delete object from created container.
        4. With list check that object doesn't present in container.
        5. Delete container.
        """
        f_path, f_name = create_file_on_node
        bname, _ = s3cmd_create_container
        s3cmd_client.bucket_put_file(bname, f_path)
        s3cmd_client.bucket_del_file(bname, f_name)
        ls_in = s3cmd_client.bucket_ls(bname)
        s3cmd_client.bucket_remove(bname, recursive=True)
        obj_path = '{0}/{1}'.format(bname, f_name)
        assert obj_path not in ''.join(ls_in)

    @pytest.mark.testrail_id('842479')
    @pytest.mark.parametrize('create_file_on_node', [f_size_b], indirect=True)
    def test_object_storage_s3cmd_obj_upload_big(
            self, s3cmd_client, s3cmd_create_container, create_file_on_node):
        """Upload big object to Object Storage (RadosGW)

        Actions:
        1. Create file (object) on controller.
        2. Create container via s3cmd cli utility.
        3. Put object to container with option 'multipart-chunk-size-mb'.
        4. With list check that object present in container.
        5. Check that size of container is the same as it was created.
        6. Check expected and actual chunk slice number.
        5. Delete container.
        """
        file_size_b = str(self.f_size_b * 1024 * 1024)
        f_path, f_name = create_file_on_node
        bname, _ = s3cmd_create_container

        put_out = s3cmd_client.bucket_put_file(
            bname, f_path, chunk=self.chunk_size)
        ls_in = s3cmd_client.bucket_ls(bname)
        s3cmd_client.bucket_remove(bname, recursive=True)
        obj_path = '{0}/{1}'.format(bname, f_name)
        # check object present in ls
        assert obj_path in ''.join(ls_in)
        # check size of obj is correct
        assert file_size_b in ''.join(ls_in)
        # check num of slices is correct
        exp_chunk_slices = math.ceil(
            float(self.f_size_b) / float(self.chunk_size))
        # MBs left in last slice
        mbleft = int(
            self.f_size_b - (self.chunk_size * (exp_chunk_slices - 1)))
        exp_string = (
            "upload:.+{f_path}.+->.+s3://{obj_path}.+"
            "[part {part} of {part}, {mbleft}MB]"
        ).format(f_path=f_path, obj_path=obj_path, part=int(exp_chunk_slices),
                 mbleft=mbleft)
        # check string present in output
        assert re.match(exp_string, put_out) is not None
        # Example of search string for re.match (exp_string):
        #   upload: '/root/s3cmd_test_obj' ->
        #   's3://TESTBUCKET1772/s3cmd_test_obj'  [part 4 of 4, 138MB] [1 of 1]


@pytest.mark.undestructive
@pytest.mark.check_env_('is_ceph_enabled')
@pytest.mark.check_env_('is_radosgw_enabled')
class TestObjectStorageSWIFT(TestBase, Helpers):
    """Object Storage - CRUD Operations Tests
    """
    f_size = 100         # MB
    f_size_b = 5432      # MB
    segment_size = 1024  # MB

    # Set "autouse=True" only for test-automation purposes
    @classmethod
    @pytest.fixture(scope='class', autouse=False)  # True to enable
    def apply_wa(cls, env):
        cls.wa_for_1543135(env)

    @pytest.mark.testrail_id('842481')
    def test_object_storage_swift_container_create(
            self, swift_client, swift_container):
        """Create container in Object Storage (RadosGW)

        Actions:
        1. Create container with swift.
        2. Show containers list and check that container presents.
        3. Delete container.
        """
        bname = swift_container
        list_out = swift_client.list()
        assert bname in ''.join(list_out)
        swift_client.delete(bname)

    @pytest.mark.testrail_id('842482')
    def test_object_storage_swift_container_delete(
            self, swift_client, swift_container):
        """Delete container from Object Storage (RadosGW)

        Actions:
        1. Create container with swift.
        2. Delete container.
        3. Show containers list and check that container doesn't presents.
        """
        bname = swift_container
        del_out = swift_client.delete(bname)
        list_out = swift_client.list()
        assert bname in del_out
        assert bname not in ''.join(list_out)

    @pytest.mark.testrail_id('842485')
    @pytest.mark.parametrize('create_file_on_node', [f_size], indirect=True)
    def test_object_storage_swift_obj_upload(
            self, swift_client, swift_container, create_file_on_node):
        """Upload object to Object Storage (RadosGW)

        Actions:
        1. Create file (object) on controller.
        2. Create container with swift.
        3. Put object to created container.
        4. With list check that object present in container.
        5. Delete container.
        """
        f_path, f_name = create_file_on_node
        bname = swift_container
        upl_out = swift_client.upload(bname, f_path)
        ls_in_out = swift_client.list(bname)
        swift_client.delete(bname)
        assert upl_out == f_path[1:]
        assert f_path[1:] in ''.join(ls_in_out)

    @pytest.mark.testrail_id('842483')
    @pytest.mark.parametrize('create_file_on_node', [f_size], indirect=True)
    def test_object_storage_swift_obj_delete(
            self, swift_client, swift_container, create_file_on_node):
        """Delete object from Object Storage (RadosGW)

        Actions:
        1. Create file (object) on controller.
        2. Create container with swift.
        3. Put object to created container.
        4. Delete object from created container.
        4. With list check that object doesn't present in container.
        5. Delete container.
        """
        f_path, f_name = create_file_on_node
        bname = swift_container
        swift_client.upload(bname, f_path)
        del_out = swift_client.delete(bname, f_path[1:])
        ls_in_out = swift_client.list(bname)
        swift_client.delete(bname)
        assert f_path[1:] in del_out
        assert bname not in ''.join(ls_in_out)

    @pytest.mark.testrail_id('842484')
    @pytest.mark.parametrize('create_file_on_node', [f_size_b], indirect=True)
    def test_object_storage_swift_obj_upload_big(
            self, swift_client, swift_container, create_file_on_node):
        """Upload big object to Object Storage (RadosGW)

        Actions:
        1. Create file (object) on controller.
        2. Create container with swift.
        3. Put object to container with option 'segment-size'.
        4. With list check that object present in container.
        5. Check that size of container is the same as it was created.
        6. Check expected and actual chunk slice number.
        5. Delete container.
        """
        file_size_b = str(self.f_size_b * 1024 * 1024)  # 3365928960
        f_path, f_name = create_file_on_node
        bname = swift_container
        swift_client.upload(bname, f_path,
                            option='-S %sM' % self.segment_size)
        ls_in_out = swift_client.list(bname + '_segments')
        swift_client.delete(bname)
        swift_client.delete(bname + '_segments')
        # check file present in container
        assert f_path[1:] in ''.join(ls_in_out)
        # check file size is the same on node and on swift
        assert ls_in_out[-1].strip() == file_size_b
        # check num of slices
        exp_chunk_slices = math.ceil(
            float(self.f_size_b) / float(self.segment_size))
        actual_slices = len(ls_in_out[:-1])
        assert exp_chunk_slices == actual_slices
