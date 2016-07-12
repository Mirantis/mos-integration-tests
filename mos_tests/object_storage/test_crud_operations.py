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


def calc_md5(remote, filename):
    logger.debug("Calculate md5 checksum")
    res = remote.check_call('md5sum {0}'.format(filename))['stdout'][0]
    return res.split()[0]


@pytest.mark.undestructive
@pytest.mark.check_env_('is_radosgw_enabled')
class TestObjectStorageS3CMD(TestBase):
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

    @pytest.mark.testrail_id('1616773', create_file_on_node=f_size)
    @pytest.mark.testrail_id('1616775', create_file_on_node=f_size_b)
    @pytest.mark.parametrize('create_file_on_node', [f_size, f_size_b],
                             ids=['100Mb', '5432Mb'], indirect=True)
    def test_object_storage_s3cmd_obj_download(self, create_file_on_node,
                                               s3cmd_client, ctrl_remote,
                                               s3cmd_create_container):
        """Download object from Object Storage (RadosGW)

        Actions:
        1. Create file (object) on controller.
        2. Create container with swift.
        3. Put object to created container.
        4. Download object from created container.
        5. Check that MD5 checksum is the same as for initial file.
        6. Delete container.
        """
        f_path, f_name = create_file_on_node
        initial_md5 = calc_md5(ctrl_remote, f_path)
        b_name, _ = s3cmd_create_container
        s3cmd_client.bucket_put_file(b_name, f_path)

        destination_path = '{0}_new'.format(f_path)
        s3cmd_client.bucket_get_file(b_name, f_name, destination_path)
        final_md5 = calc_md5(ctrl_remote, destination_path)

        assert initial_md5 == final_md5

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
class TestObjectStorageSWIFT(TestBase):
    """Object Storage - CRUD Operations Tests
    """
    f_size = 100         # MB
    f_sizebig = 5432      # MB
    segment_size = 1024  # MB
    f_size_bytes = f_size * 1024 * 1024

    @pytest.mark.testrail_id('842481')
    def test_object_storage_swift_container_create(
            self, os_swift_client, swift_container):
        """Create container in Object Storage (RadosGW)

        Actions:
        1. Create container with swift.
        2. Show containers list and check that container presents.
        3. Delete container.
        """
        bname = swift_container
        list_out = os_swift_client.container_list()
        assert bname in [x['Name'] for x in list_out]

    @pytest.mark.testrail_id('842482')
    def test_object_storage_swift_container_delete(
            self, os_swift_client, swift_container):
        """Delete container from Object Storage (RadosGW)

        Actions:
        1. Create container with swift.
        2. Delete container.
        3. Show containers list and check that container doesn't presents.
        """
        bname = swift_container
        os_swift_client.container_delete(bname)
        list_out = os_swift_client.container_list()
        assert bname not in str(list_out)

    @pytest.mark.testrail_id('842485')
    @pytest.mark.parametrize('create_file_on_node', [f_size], indirect=True)
    def test_object_storage_swift_obj_upload(
            self, os_swift_client, swift_container, create_file_on_node):
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
        upl_out = os_swift_client.object_create(bname, f_path)
        ls_in_out = os_swift_client.object_list(bname)
        assert any(f_path == x['object'] for x in upl_out)
        assert any(f_path == x['Name'] for x in ls_in_out)
        assert any(self.f_size_bytes == x['Bytes'] for x in ls_in_out)

    @pytest.mark.testrail_id('842483')
    @pytest.mark.parametrize('create_file_on_node', [f_size], indirect=True)
    def test_object_storage_swift_obj_delete(
            self, os_swift_client, swift_container, create_file_on_node):
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
        os_swift_client.object_create(bname, f_path)
        os_swift_client.object_delete(bname, f_path)
        ls_in_out = os_swift_client.object_list(bname)
        assert bname not in str(ls_in_out)

    @pytest.mark.testrail_id('1616772', create_file_on_node=f_size)
    @pytest.mark.testrail_id('1616830', create_file_on_node=f_sizebig)
    @pytest.mark.parametrize('create_file_on_node', [f_size, f_sizebig],
                             ids=['100Mb', '5432Mb'], indirect=True)
    def test_object_storage_os_swift_obj_download(self, ctrl_remote,
                                                  os_swift_client,
                                                  swift_container,
                                                  create_file_on_node):
        """Download object from Object Storage

        Actions:
        1. Create file (object) on controller.
        2. Create container with swift.
        3. Put object to created container.
        4. Download object from created container.
        5. Check that file exists
        6. Check that MD5 checksum is the same as for initial file.
        7. Delete container.

        BUG: https://bugs.launchpad.net/mos/+bug/1583033
        openstack cli can not upload big (5432MB) file to container
        """
        f_path = create_file_on_node[0]
        initial_md5 = calc_md5(ctrl_remote, f_path)

        # Object creation doesn't work for big file due to
        # https://bugs.launchpad.net/mos/+bug/1583033
        os_swift_client.object_create(swift_container, f_path)

        f_dest = '{0}_new'.format(f_path)
        os_swift_client.object_download(swift_container, f_path, f_dest)

        ctrl_remote.check_call('ls {0}'.format(f_path))
        final_md5 = calc_md5(ctrl_remote, f_dest)
        assert initial_md5 == final_md5

    @pytest.mark.testrail_id('842484')
    @pytest.mark.parametrize('create_file_on_node', [f_sizebig], indirect=True)
    def test_object_storage_os_swift_obj_upload_big(
            self, os_swift_client, swift_container, create_file_on_node):
        """Upload big object to Object Storage (openstack cli)

        Actions:
        1. Create file (object) on controller.
        2. Create container with swift.
        3. Put object to container with option 'segment-size'.
        4. With list check that object present in container.
        5. Check that size of container is the same as it was created.
        6. Check expected and actual chunk slice number.
        5. Delete container.

        BUG: https://bugs.launchpad.net/mos/+bug/1583033
        """
        f_path, f_name = create_file_on_node
        bname = swift_container
        os_swift_client.object_create(bname, f_path)   # not working
        ls_in_out = os_swift_client.object_list(bname)
        assert any(f_path == x['Name'] for x in ls_in_out)
        assert any(self.f_size_bytes == x['Bytes'] for x in ls_in_out)

    @pytest.mark.testrail_id('1616831')
    @pytest.mark.parametrize('create_file_on_node', [f_sizebig], indirect=True)
    def test_object_storage_swift_obj_upload_big(
            self, swift_cli, swift_container, create_file_on_node):
        """Upload big object to Object Storage (swift cli)

        Actions:
        1. Create file (object) on controller.
        2. Create container with swift.
        3. Put object to container with option 'segment-size'.
        4. With list check that object present in container.
        5. Check that size of container is the same as it was created.
        6. Check expected and actual chunk slice number.
        5. Delete container.

        BUG: https://bugs.launchpad.net/mos/+bug/1543135
        """
        f_path, f_name = create_file_on_node
        f_size_big_bytes = self.f_sizebig * 1024 * 1024
        seg_count = math.ceil(float(self.f_sizebig) / float(self.segment_size))

        swift_cli.upload_object(
            swift_container, f_path, f_name, segment=self.segment_size)

        objects_list = swift_cli.object_list(swift_container)
        assert f_name in objects_list[0], (
            "No file {0} found in {1}".format(f_name, swift_container))

        segments = swift_cli.object_list(swift_container + '_segments')
        assert int(segments[-1]) == f_size_big_bytes, "Unexpected object size"
        assert len(segments[:-1]) == seg_count, "Unexpected segments count"

    @pytest.mark.testrail_id('1616774')
    @pytest.mark.parametrize('create_file_on_node', [f_sizebig], indirect=True)
    def test_object_storage_swift_obj_download_big(self, create_file_on_node,
                                                   swift_cli, swift_container,
                                                   ctrl_remote):
        """Download big object from Object Storage (swift cli)

        Actions:
        1. Create file (object) on controller.
        2. Create container with swift.
        3. Put object to created container.
        4. Download object from created container.
        5. Check that MD5 checksum is the same as for initial file.
        6. Delete container.

        BUG: https://bugs.launchpad.net/mos/+bug/1543135
        """
        f_path, f_name = create_file_on_node
        initial_md5 = calc_md5(ctrl_remote, f_path)
        swift_cli.upload_object(
            swift_container, f_path, f_name, segment=self.segment_size)

        destination_file = '{0}_new'.format(f_path)
        swift_cli.download_object(swift_container, f_name, destination_file)
        final_md5 = calc_md5(ctrl_remote, destination_file)

        assert initial_md5 == final_md5
