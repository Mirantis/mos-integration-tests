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

import os
import subprocess
import tempfile

import pytest
from six import BytesIO

from mos_tests.functions import file_cache


@pytest.fixture
def content():
    return 'test bytes'


def tar_archive_factory(compression):
    if compression == 'gz':
        comp_param = '-z'
    elif compression == 'bz2':
        comp_param = '-j'

    @pytest.yield_fixture
    def tar_archive(content):
        """Create compressed tar archive with single file"""
        _, temp1 = tempfile.mkstemp()
        _, temp2 = tempfile.mkstemp(suffix='.tar.{0}'.format(compression))
        with open(temp1, 'wb') as f:
            f.write(content)
        subprocess.check_call(['tar', '-cv', comp_param, '-f', temp2, temp1])
        os.unlink(temp1)
        with open(temp2) as f:
            yield f
        os.unlink(temp2)

    return tar_archive

tar_gz = tar_archive_factory(compression='gz')
tar_bz2 = tar_archive_factory(compression='bz2')


def get_cache_files():
    path = file_cache.settings.TEST_IMAGE_PATH
    try:
        before = [os.path.join(path, x) for x in os.listdir(path)]
    except OSError:
        before = []
    return set(before)


@pytest.yield_fixture
def clean_cache():
    before = get_cache_files()
    yield
    after = get_cache_files()
    for path in after - before:
        os.unlink(path)


def test_fake_decoder(content):
    buf = BytesIO(content)
    with file_cache._fake_decoder(buf) as f:
        result = f.read()

    assert result == content


def test_tar_gz_decoder(tar_gz, content):
    with file_cache._tar_decoder(tar_gz, compression='gz') as f:
        result = f.read()

    assert result == content


def test_tar_xz_decoder(tar_bz2, content):
    with file_cache._tar_decoder(tar_bz2, compression='bz2') as f:
        result = f.read()

    assert result == content


def test_get_from_url(clean_cache):
    url = 'http://httpbin.org/get'
    with file_cache.get_and_unpack(url) as f:
        content = f.read()

    assert url in content


def test_read_from_file(tar_gz, clean_cache, content):
    path = tar_gz.name
    with file_cache.get_and_unpack(path) as f:
        result = f.read()

    assert result == content

def test_no_cache_local_files(tar_gz, clean_cache):
    cache_before = get_cache_files()
    path = tar_gz.name
    with file_cache.get_and_unpack(path) as f:
        f.read()

    cache_after = get_cache_files()

    assert cache_before == cache_after
