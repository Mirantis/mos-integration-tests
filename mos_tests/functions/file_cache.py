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

from contextlib import contextmanager
import email.utils
import logging
import os

import requests

from mos_tests import settings

logger = logging.getLogger(__name__)


@contextmanager
def get_file(url, name=None):
    with open(get_file_path(url, name), 'rb') as f:
        yield f


def get_file_path(url, name=None):
    if not os.path.exists(settings.TEST_IMAGE_PATH):
        try:
            os.makedirs(settings.TEST_IMAGE_PATH)
        except Exception as e:
            logger.warning("Can't make dir for files: {}".format(e))
            return None

    file_path = os.path.join(settings.TEST_IMAGE_PATH,
                             get_file_name(url))
    headers = {}
    if os.path.exists(file_path):
        file_date = os.path.getmtime(file_path)
        headers['If-Modified-Since'] = email.utils.formatdate(file_date,
                                                              usegmt=True)

    response = requests.get(url, stream=True, headers=headers)

    if response.status_code == 304:
        logger.info("Image file is up to date")
    elif response.status_code == 200:
        logger.info("Start downloading image")
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(65536):
                f.write(chunk)
        logger.info("Image downloaded")
    else:
        logger.warning("Can't get fresh image. HTTP status code is "
                       "{0.status_code}".format(response))

    response.close()
    return file_path


def get_file_name(url):
    keepcharacters = (' ', '.', '_', '-')
    name = url.rsplit('/')[-1]
    return "".join(c for c in name
                   if c.isalnum() or c in keepcharacters).rstrip()
