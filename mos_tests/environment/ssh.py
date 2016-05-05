#    Copyright 2015 Mirantis, Inc.
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

import functools
import logging
import os
import posixpath
import select
import stat
import time

import paramiko
import six


logger = logging.getLogger(__name__)


def retry(count=10, delay=1, pass_counter=None):
    """Retry until no exceptions decorator.

    :param pass_counter: argument to pass counter variable in
    :type pass_counter: None or str
    """
    def decorator(func):

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(count):
                if pass_counter is not None:
                    kwargs[pass_counter] = i
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    time.sleep(delay)
            else:
                logger.warning(e)
                raise

        return wrapper

    return decorator


@six.python_2_unicode_compatible
class CalledProcessError(Exception):
    def __init__(self, command, returncode, output=None):
        self.returncode = returncode
        if not isinstance(output, six.text_type):
            command = command.decode('utf-8')
        self.cmd = command
        self.output = output

    def __str__(self):
        message = u"Command '%s' returned non-zero exit status %s" % (
            self.cmd, self.returncode)
        if self.output:
            message += u"\n%s" % repr(self.output)
        return message


class CommandResult(dict):

    @property
    def is_ok(self):
        return self['exit_code'] == 0

    def _list_to_string(self, key):
        return (''.join(self[key])).decode('utf-8').strip()

    @property
    def stdout_string(self):
        return self._list_to_string('stdout')

    @property
    def stderr_string(self):
        return self._list_to_string('stderr')


class SSHClient(object):

    def __repr__(self):
        orig = super(SSHClient, self).__repr__()
        return '{} [{}:{}]'.format(orig, self.host, self.port)

    @property
    def _sftp(self):
        if self._sftp_client is None:
            self._sftp_client = self._ssh.open_sftp()
        return self._sftp_client

    class get_sudo(object):
        def __init__(self, ssh):
            self.ssh = ssh

        def __enter__(self):
            self.ssh.sudo_mode = True

        def __exit__(self, exc_type, value, traceback):
            self.ssh.sudo_mode = False

    def __init__(self, host, port=22, username=None, password=None,
                 private_keys=None, proxy_commands=(), timeout=120):
        self.host = str(host)
        self.port = int(port)
        self.username = username
        self.password = password
        if not private_keys:
            private_keys = []
        self.private_keys = private_keys

        self.sudo_mode = False
        self.sudo = self.get_sudo(self)
        self.timeout = timeout
        self.proxy_commands = proxy_commands
        self._ssh = None
        self._sftp_client = None
        self._proxy = None

    def clear(self):
        if self._sftp_client is not None:
            try:
                self._sftp_client.close()
            except Exception:
                logger.exception("Could not close sftp connection")

        if self._ssh is not None:
            try:
                self._ssh.close()
            except Exception:
                logger.exception("Could not close ssh connection")

        if self._proxy is not None:
            try:
                self._proxy.close()
            except Exception:
                logger.exception("Could not close proxy connection")

    def __del__(self):
        self.clear()

    def __enter__(self):
        try:
            self.reconnect()
        except Exception:
            self.clear()
            raise
        return self

    def __exit__(self, *err):
        self.clear()

    def connect(self, pkey=None, password=None):
        if pkey:
            logger.debug("Connecting to '{0.host}:{0.port}' "
                         "as '{0.username}' with key....".format(self))
        else:
            logger.debug("Connecting to '{0.host}:{0.port}' "
                         "as '{0.username}:{1}'....".format(self, password))

        kwargs = {}
        if self._proxy is not None:
            kwargs['sock'] = self._proxy
        return self._ssh.connect(self.host, port=self.port,
                                 username=self.username, password=password,
                                 pkey=pkey, banner_timeout=30, **kwargs)

    @retry(count=3, delay=3, pass_counter='counter')
    def reconnect(self, counter):
        params = [{'pkey': x} for x in self.private_keys]
        if self.password is not None:
            params.append({'password': self.password})
        for param in params:
            self.clear()
            self._ssh = paramiko.SSHClient()
            self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            proxies_count = len(self.proxy_commands)
            if proxies_count > 0:
                proxy_command = self.proxy_commands[counter % proxies_count]
                logger.debug('Proxy for ssh: "{0}"'.format(proxy_command))
                self._proxy = paramiko.ProxyCommand(proxy_command)
                self._proxy.settimeout(self.timeout)
            try:
                self.connect(**param)
                break
            except Exception as e:
                logger.warning(e)
        else:
            raise

    def check_call(self, command, verbose=True):
        ret = self.execute(command, verbose)
        if ret['exit_code'] != 0:
            raise CalledProcessError(command, ret['exit_code'],
                                     ret['stdout'] + ret['stderr'])
        return ret

    def check_stderr(self, command, verbose=True):
        ret = self.check_call(command, verbose)
        if ret['stderr']:
            raise CalledProcessError(command, ret['exit_code'],
                                     ret['stdout'] + ret['stderr'])
        return ret

    @classmethod
    def execute_together(cls, remotes, command):
        futures = {}
        errors = {}
        for remote in remotes:
            cmd = "%s\n" % command
            if remote.sudo_mode:
                cmd = 'sudo -S bash -c "%s"' % cmd.replace('"', '\\"')
            chan = remote._ssh.get_transport().open_session()
            chan.exec_command(cmd)
            futures[remote] = chan
        for remote, chan in futures.items():
            ret = chan.recv_exit_status()
            if ret != 0:
                errors[remote.host] = ret
        if errors:
            raise CalledProcessError(command, errors)

    def execute(self, command, verbose=True, merge_stderr=False):
        chan, stdin, stdout, stderr = self.execute_async(
            command, merge_stderr=merge_stderr)

        stdout_buf = ''
        stderr_buf = ''

        while not chan.closed or chan.recv_ready() or chan.recv_stderr_ready():
            select.select([chan], [], [chan], 60)

            if chan.recv_ready():
                stdout_buf += chan.recv(1024)
            if chan.recv_stderr_ready():
                stderr_buf += chan.recv_stderr(1024)

        result = CommandResult({
            'stdout': stdout_buf.splitlines(True),
            'stderr': stderr_buf.splitlines(True),
            'exit_code': chan.recv_exit_status()
        })
        stdin.close()
        stdout.close()
        stderr.close()
        chan.close()
        if verbose:
            logger.debug("'{0}' exit_code is {1}".format(
                command, result['exit_code']))
            if len(result['stdout']) > 0:
                logger.debug(u'Stdout:\n{0}'.format(result.stdout_string))
            if len(result['stderr']) > 0:
                logger.debug(u'Stderr:\n{0}'.format(result.stderr_string))
        return result

    def execute_async(self, command, merge_stderr=False):
        logger.debug("Executing command: '%s'" % command.rstrip())
        chan = self._ssh.get_transport().open_session(timeout=self.timeout)
        chan.set_combine_stderr(merge_stderr)
        stdin = chan.makefile('wb')
        stdout = chan.makefile('rb')
        stderr = chan.makefile_stderr('rb')
        cmd = "%s\n" % command
        if self.sudo_mode:
            cmd = 'sudo -S bash -c "%s"' % cmd.replace('"', '\\"')
            chan.exec_command(cmd)
            if stdout.channel.closed is False:
                stdin.write('%s\n' % self.password)
                stdin.flush()
        else:
            chan.exec_command(cmd)
        return chan, stdin, stdout, stderr

    def mkdir(self, path):
        if self.exists(path):
            return
        logger.debug("Creating directory: %s", path)
        self.execute("mkdir -p %s\n" % path)

    def rm_rf(self, path):
        logger.debug("Removing directory: %s", path)
        self.execute("rm -rf %s" % path)

    def open(self, path, mode='r'):
        return self._sftp.open(path, mode)

    def upload(self, source, target):
        logger.debug("Copying '%s' -> '%s'", source, target)

        if self.isdir(target):
            target = posixpath.join(target, os.path.basename(source))

        source = os.path.expanduser(source)
        if not os.path.isdir(source):
            self._sftp.put(source, target)
            return

        for rootdir, subdirs, files in os.walk(source):
            targetdir = os.path.normpath(
                os.path.join(
                    target,
                    os.path.relpath(rootdir, source))).replace("\\", "/")

            self.mkdir(targetdir)

            for entry in files:
                local_path = os.path.join(rootdir, entry)
                remote_path = posixpath.join(targetdir, entry)
                if self.exists(remote_path):
                    self._sftp.unlink(remote_path)
                self._sftp.put(local_path, remote_path)

    def download(self, destination, target):
        logger.debug(
            "Copying '%s' -> '%s' from remote to local host",
            destination, target
        )

        if os.path.isdir(target):
            target = posixpath.join(target, os.path.basename(destination))

        if not self.isdir(destination):
            if self.exists(destination):
                self._sftp.get(destination, target)
            else:
                logger.debug(
                    "Can't download %s because it doesn't exist", destination
                )
        else:
            logger.debug(
                "Can't download %s because it is a directory", destination
            )
        return os.path.exists(target)

    def exists(self, path):
        try:
            self._sftp.lstat(path)
            return True
        except IOError:
            return False

    def isfile(self, path):
        try:
            attrs = self._sftp.lstat(path)
            return attrs.st_mode & stat.S_IFREG != 0
        except IOError:
            return False

    def isdir(self, path):
        try:
            attrs = self._sftp.lstat(path)
            return attrs.st_mode & stat.S_IFDIR != 0
        except IOError:
            return False


def ssh(*args, **kwargs):
    return SSHClient(*args, **kwargs)
