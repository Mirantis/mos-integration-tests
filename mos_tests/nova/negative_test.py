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


@pytest.mark.testrail_id('842537')
def test_retrieve_nonroot_certificate(controller_remote, os_conn):
    """Try to retrieve non-root certificate

    Scenario:
        1. Create a default certificate:
            nova x509-create-cert
        2. Make curl query to retrieve root certificate:
            curl -s -H "X-Auth-Token: {token}" \
            {endpoint}/os-certificates/root
        3. Check that certificate data is present in output
        4. Make curl query to retrieve nonroot certificate:
            curl -s -H "X-Auth-Token: {token}" \
            {endpoint}/os-certificates/nonroot
        5. Check that 'Only root certificate can be retrieved' is present
            in output
    """
    os_conn.nova.certs.create()
    token = os_conn.session.get_token()
    endpoint = os_conn.session.get_endpoint(service_type='compute')
    command = (
        'curl -s -H "X-Auth-Token: {token}" '
        '{endpoint}/os-certificates/{{cert_type}}'.format(token=token,
                                                          endpoint=endpoint))
    result = controller_remote.check_call(command.format(cert_type='root'))
    assert 'BEGIN CERTIFICATE' in result.stdout_string
    result = controller_remote.execute(command.format(cert_type='nonroot'))
    assert 'Only root certificate can be retrieved.' in result.stdout_string
