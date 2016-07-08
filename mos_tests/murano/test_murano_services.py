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


@pytest.mark.parametrize('package', [('ApacheHttpServer',)],
                         indirect=['package'])
@pytest.mark.testrail_id('1295478')
def test_restart_murano_services(
        environment, murano, session, keypair, restart_murano_services):

    """Check that all Murano services works after restart
    Steps:
        1. Login to OpenStack controller nodes and restart all murano services
        2. Get list of Murano applications and verify that API is available
        3. Deploy Murano application to verify that all Murano services work
        fine(e.g rabbit connection, engine) after the restart
    """

    murano.create_service(environment, session, murano.apache(keypair))
    murano.deploy_environment(environment, session)
    murano.deployment_success_check(environment, ports=[22, 80])
    murano.murano.packages.delete([pkg.id for pkg in
                                   murano.murano.packages.list()
                                   if pkg.name == 'Apache HTTP Server'][0])
