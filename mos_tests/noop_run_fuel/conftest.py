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

from keystoneclient.v3 import Client as KeystoneClientV3


logger = logging.getLogger(__name__)


@pytest.yield_fixture
def admin_remote(fuel):
    with fuel.ssh_admin() as remote:
        yield remote


@pytest.yield_fixture
def rename_role(os_conn):
    """Rename the role 'SwiftOperator'"""
    role_name_old = "SwiftOperator"
    role_name_new = role_name_old + "-new"
    logger.info("Rename role {0} -> {1}".format(role_name_old, role_name_new))
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    role = keystone_v3.roles.find(name=role_name_old)
    keystone_v3.roles.update(role=role, name=role_name_new)
    yield
    keystone_v3.roles.update(role=role, name=role_name_old)


@pytest.yield_fixture
def disable_user(os_conn):
    """Disable/enable the user 'glare'"""
    user_name = "glare"
    logger.info("Disable user {0}".format(user_name))
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    user = keystone_v3.users.find(name=user_name)
    keystone_v3.users.update(user=user, enabled=False)
    yield
    keystone_v3.users.update(user=user, enabled=True)


@pytest.fixture
def delete_project(os_conn):
    """Delete/create the project 'services'"""
    project_name = "services"
    logger.info("Delete project {0}".format(project_name))
    keystone_v3 = KeystoneClientV3(session=os_conn.session)
    project = keystone_v3.projects.find(name=project_name)
    keystone_v3.projects.delete(project=project)
