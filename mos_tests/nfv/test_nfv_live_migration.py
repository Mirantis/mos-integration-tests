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
import pytest
from time import sleep

logger = logging.getLogger(__name__)


class TestLiveMigration:

    @pytest.mark.parametrize(
        'nfv_flavor', [[[['m1.small.hpgs', 512, 1, 1],
                         [{'hw:mem_page_size': 2048},
                          {'aggregate_instance_extra_specs:hpgs': 'true'}]],
                        [['m1.small.hpgs-1', 2000, 20, 2],
                         [{'hw:mem_page_size': 1048576}, ]]]],
        indirect=['nfv_flavor'])
    def test_n1(self, os_conn, networks, nfv_flavor):
        sleep(10)

    def test_n2(self, os_conn, networks, nfv_flavor):
        sleep(10)
