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

import logging

import pytest

from mos_tests.functions.base import OpenStackTestCase

logger = logging.getLogger(__name__)


@pytest.mark.undestructive
class SaharaScenarioTests(OpenStackTestCase):
    """Sahara scenario tests for checking of plugins."""

    @pytest.mark.testrail_id('675264')
    def test_vanilla_plugin(self):
        """Run Sahara scenario tests (1 controller Neutron VXLAN)

        Scenario:
            1. Install packages
            2. Clone repo with sahara-scenario tests
            3. Separate files for 8.0 release
            4. Genarate .ini file for tests
            5. Run sahara tests for vanilla 2
        """
        logging.info("Sahara scenario tests started")
        cmd = (
            "sudo apt-get install -y git python-pip python-tox libpq-dev && "
            "rm -rf sahara && "
            "git clone https://github.com/openstack/sahara && "
            "mkdir sahara/etc/scenario/8.0 && "
            "cp sahara/etc/scenario/sahara-ci/{credentials.yaml.mako,"
            "edp.yaml.mako,vanilla-2.7.1.yaml.mako,ambari-2.3.yaml.mako,"
            "cdh-5.4.0.yaml.mako,mapr-5.0.0.mrv2.yaml.mako,"
            "spark-1.3.1.yaml.mako,transient.yaml.mako} "
            "sahara/etc/scenario/8.0 && "
            "echo '[DEFAULT]\n"
            "OS_USERNAME: saharaHA\n"
            "OS_PASSWORD: saharaHA\n"
            "OS_TENANT_NAME: saharaHA\n"
            "OS_AUTH_URL: http://%s:5000/v2.0\n"
            "network_type: neutron\n"
            "network_private_name: net04\n"
            "network_public_name: net04_ext\n"
            "cluster_name: test-cluster\n"
            "vanilla_two_seven_one_image: "
            "sahara-liberty-vanilla-2.7.1-ubuntu-14.04\n"
            "ci_flavor_id: m1.small\n"
            "medium_flavor_id: m1.medium\n"
            "large_flavor_id: m1.large\n' > templatesvar.ini && "
            "cd sahara && "
            "echo 'concurrency: 2' >> "
            "etc/scenario/8.0/credentials.yaml.mako && "
            "tox -e venv -- sahara scenario --verbose -V ~/templatesvar.ini "
            "etc/scenario/8.0/credentials.yaml.mako "
            "etc/scenario/8.0/edp.yaml.mako "
            "etc/scenario/8.0/vanilla-2.7.1.yaml.mako " % (self.controller_ip))

        os.system(cmd)
