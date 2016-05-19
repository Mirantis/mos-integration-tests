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

    def details(self, output, mapping=('Field', 'Value')):
        """List with one dict with data"""
        data = json.loads(output)
        if isinstance(data, list):
            data = {x[mapping[0]]: x[mapping[1]] for x in data}
        return data

    def listing(self, output, mapping=False):
        """List with several dicts with data"""
        data = json.loads(output)
        if mapping:
            if isinstance(data, list):
                data = [{x[mapping[0]]: x[mapping[1]]} for x in data]
        return data

    def project_list(self, longout=False):
        cmd = 'project list -f json'
        if longout:
            cmd += ' --long'
        return json.loads(self(cmd))

    def project_create(self, name):
        output = self('project create', params='{} -f json'.format(name))
        return self.details(output)

    def project_delete(self, name):
        return self('project delete', params=name)

    def project_show(self, name):
        output = self('project show', params='{} -f json'.format(name))
        return self.details(output)

    def user_list(self, longout=False):
        cmd = 'user list -f json'
        if longout:
            cmd += ' --long'
        return json.loads(self(cmd))

    def user_show(self, name):
        output = self('user show', params='{} -f json'.format(name))
        return self.details(output)

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

    def ec2_cred_list(self):
        output = self('ec2 credentials list -f json')
        return json.loads(output)

    def ec2_cred_create(self, user='admin', project='admin'):
        output = self(('ec2 credentials create --user {user}'
                       ' --project {project} -f json').format(user=user,
                                                              project=project))
        return self.details(output)

    def ec2_cred_del(self, access_key):
        return self('ec2 credentials delete {0}'.format(access_key))

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


class S3CMD(CLICLient):
    command = 's3cmd'

    def bucket_make(self, name):
        return self('mb s3://{0}'.format(name))

    def bucket_ls(self, name=None):
        params = ''
        if name:
            params += 's3://{0}'.format(name)
        output = self('ls', params=params)
        return output.split('\n')

    def bucket_remove(self, name, recursive=False):
        params = 's3://{0}'.format(name)
        if recursive:
            params += ' --recursive'
        return self('rb', params=params)

    def bucket_put_file(self, bucket_name, file_path, chunk=False):
        params = '{0} s3://{1}'.format(file_path, bucket_name)
        if chunk:
            params += ' --multipart-chunk-size-mb={0}'.format(chunk)
        return self('put', params=params)

    def bucket_del_file(self, bucket_name, filename):
        return self('del s3://{0}/{1}'.format(bucket_name, filename))


class OpenStackSwift(CLICLient):
    command = 'openstack'

    def container_list(self):
        output = self('container list --long -f json')
        return json.loads(output)

    def container_create(self, name):
        output = self('container create {name} -f json'.format(name=name))
        return json.loads(output)

    def container_delete(self, name):
        output = self('container delete --recursive {name}'.format(name=name))
        return output

    def container_show(self, name):
        output = self('container show {name} -f json'.format(name=name))
        return json.loads(output)

    def object_list(self, container):
        output = self('object list {container} --long -f json'.format(
            container=container))
        return json.loads(output)

    def object_create(self, container, filename):
        output = self('object create {container} {filename} -f json'.format(
                container=container, filename=filename))
        return json.loads(output)

    def object_delete(self, container, filename):
        output = self('object delete {container} {filename}'.format(
            container=container, filename=filename))
        return output

    def object_show(self, container, filename):
        output = self('object show {container} {filename} -f json'.format(
            container=container, filename=filename))
        return json.loads(output)


class Nova(CLICLient):
    command = 'nova'
