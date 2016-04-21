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

import json

import six
from tempest.lib.cli import output_parser as parser
from tempest.lib import exceptions


class Result(six.text_type):
    def listing(self):
        return parser.listing(self)

    def details(self):
        return parser.details(self)

    def __add__(self, other):
        if not isinstance(other, six.text_type):
            other = other.decode('utf-8')
        return self.__class__(super(Result, self).__add__(other))


def os_execute(remote, command, fail_ok=False, merge_stderr=False):
    command = '. openrc && {}'.format(command.encode('utf-8'))
    result = remote.execute(command)
    if not fail_ok and not result.is_ok:
        raise exceptions.CommandFailed(result['exit_code'],
                                       command.decode('utf-8'),
                                       result.stdout_string,
                                       result.stderr_string)
    output = Result()
    if merge_stderr:
        output += result.stderr_string
    return output + result.stdout_string


class CLICLient(object):

    command = ''

    def __init__(self, remote):
        self.remote = remote
        super(CLICLient, self).__init__()

    def build_command(self, action, flags='', params='', prefix=''):
        return u' '.join([prefix, self.command, flags, action, params])

    def __call__(self, action, flags='', params='', prefix='', fail_ok=False,
                merge_stderr=False):
        command = self.build_command(action, flags, params, prefix)
        return os_execute(self.remote, command, fail_ok=fail_ok,
                          merge_stderr=merge_stderr)


class OpenStack(CLICLient):
    command = 'openstack'

    def details(self, output):
        data = json.loads(output)
        if isinstance(data, list):
            data = {x['Field']: x['Value'] for x in data}
        return data

    def project_create(self, name):
        output = self('project create', params='{} -f json'.format(name))
        return self.details(output)

    def project_delete(self, name):
        return self('project delete', params=name)

    def user_create(self, name, password, project=None):
        params = '{name} --password {password} -f json'.format(
            name=name, password=password)
        if project is not None:
            params += ' --project {}'.format(project)
        output = self('user create', params=params)
        return self.details(output)

    def user_delete(self, name):
        return self('user delete', params=name)

    def role_create(self, name):
        output = self('role create', params='{} -f json'.format(name))
        return self.details(output)

    def role_delete(self, name):
        return self('role delete', params=name)

    def assign_role_to_user(self, role_name, user, project):
        output = self(
            'role add',
            params='{name} --user {user} --project {project} -f json'.format(
                name=role_name, user=user, project=project))
        return self.details(output)

    def user_set_new_name(self, name, new_name):
        params = '{name} --name {new_name}'.format(
            name=name, new_name=new_name)
        return self('user set', params=params)

    def user_set_new_password(self, name, new_password):
        params = '{name} --password {password}'.format(
            name=name, password=new_password)
        return self('user set', params=params)


class Glance(CLICLient):
    command = 'glance'

    def build_command(self, action, flags='', params='', prefix=''):
        # disable stdin
        params += u' <&-'
        return super(Glance, self).build_command(action, flags, params, prefix)


class Ironic(CLICLient):
    command = 'ironic'


class Murano(CLICLient):
    command = 'murano'


class Ceilometer(CLICLient):
    command = 'ceilometer'


class Aodh(CLICLient):
    command = 'aodh'

    def __call__(self, *args, **kwargs):
        result = super(Aodh, self).__call__(*args, **kwargs)
        lines = result.splitlines()
        if len(lines) > 0:
            # Change output to tempest parser
            lines[1] = lines[1].replace('Field   ', 'Property')
        return Result('\n'.join(lines))
