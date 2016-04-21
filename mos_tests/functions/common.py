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

import inspect
import logging
import os
import socket
from tempfile import NamedTemporaryFile
from time import sleep
from time import time
import urllib2

import uuid
from waiting import TimeoutExpired
from waiting import wait as base_wait
import yaml


logger = logging.getLogger(__name__)


def is_stack_exists(stack_name, heat):
    """Check the presence of stack_name in stacks list
        :param stack_name: Name of stack
        :param heat: Heat API client connection point
        :return True or False
    """
    return stack_name in [s.stack_name for s in heat.stacks.list()]


def get_stack_id(heat_client, stack_name):
    """Check stack status
        :param heat_client: Heat API client connection point
        :param stack_name: Name of stack
        :return Stack uid
    """
    if is_stack_exists(stack_name, heat_client):
        return heat_client.stacks.list(filter={'name': stack_name}).id
    raise Exception("ERROR: Stack {} is not defined".format(stack_name))


def check_stack_status(stack_name, heat, status, timeout=60):
    """Check stack status
        :param stack_name: Name of stack
        :param heat: Heat API client connection point
        :param status: Expected stack status
        :param timeout: Timeout for check operation
        :return True if stack status is equals to expected status
        False otherwise
    """
    if is_stack_exists(stack_name, heat):
        start_time = time()
        stack_status = [s.stack_status for s in heat.stacks.list()
                        if s.stack_name == stack_name][0]
        while 'IN_PROGRESS' in stack_status \
                and time() < start_time + 60 * timeout:
            sleep(1)
            stack_status = [s.stack_status for s in heat.stacks.list()
                            if s.stack_name == stack_name][0]
        return stack_status == status
    return False


def create_stack(heat_client, stack_name, template, parameters={}, timeout=20,
                 files=None):
    """Create a stack from template and check STATUS == CREATE_COMPLETE
        :param parameters: parameters from template
        :param heat_client: Heat API client connection point
        :param stack_name: Name of a new stack
        :param template:   Content of a template name
        :param timeout: Timeout for check operation
        :param files: In case if template uses file as reference
        e.g: "type: volume_with_attachment.yaml"
        :return uid: UID of created stack
    """
    templ_files = files or {}
    stack = heat_client.stacks.create(
        stack_name=stack_name,
        template=template,
        files=templ_files,
        parameters=parameters,
        timeout_mins=timeout)
    uid = stack['stack']['id']

    def is_stack_created():
        stack = heat_client.stacks.get(uid)
        if stack.stack_status == 'CREATE_FAILED':
            raise Exception(stack.stack_status_reason)
        elif stack.stack_status == 'CREATE_COMPLETE':
            return True

    wait(is_stack_created, timeout_seconds=timeout * 60, sleep_seconds=10,
        waiting_for='stack {} status to be CREATE_COMPLETE'.format(stack_name))
    return uid


def delete_stack(heat_client, uid):
    """Delete stack and check STATUS == DELETE_COMPLETE
        :param heat_client: Heat API client connection point
        :param uid:         UID of stack
    """
    if uid in [s.id for s in heat_client.stacks.list()]:
        heat_client.stacks.delete(uid)
        while uid in [s.id for s in heat_client.stacks.list()]:
            sleep(1)


def check_stack_status_complete(heat_client, uid, action, timeout=10):
    """Check stack STATUS in COMPLETE state
        :param heat_client: Heat API client connection point
        :param uid: ID stack
        :param action: status that will be checked.
        Could be CREATE, UPDATE, DELETE.
        :param timeout: Timeout for check operation
        :return uid: UID of created stack
    """
    stack = heat_client.stacks.get(stack_id=uid).to_dict()
    end_time = time() + 60 * timeout
    while stack['stack_status'] == '{}_IN_PROGRESS'.format(action):
        stack = heat_client.stacks.get(stack_id=uid).to_dict()
        if time() > end_time:
            break
        else:
            sleep(1)
    if stack['stack_status'] != '{}_COMPLETE'.format(action):
        raise Exception("ERROR: Stack {} is not in '{}_COMPLETE' "
                        "state:\n".format(stack, action))


def read_template(templates_dir, template_name):
    """Read template file and return it content.
        :param templates_dir: dir
        :param template_name: name of template,
        for ex.: empty_heat_template.yaml
        :return: template file content
    """

    template_path = os.path.join(templates_dir, template_name)
    try:
        with open(template_path) as template:
            return template.read()
    except IOError as e:
        raise IOError('Can\'t read template: {}'.format(e))


def update_stack(heat_client, uid, template_file, parameters={}):
    """Update stack using template file
        :param heat_client:   Heat API client connection point
        :param uid:           ID of stack
        :param template_file: Path to stack template file.
        :param parameters:    Parameters from template
        :return: -
    """
    heat_client.stacks.update(stack_id=uid, template=template_file,
                              parameters=parameters)
    check_stack_status_complete(heat_client, uid, 'UPDATE')


def get_resource_id(heat_client, uid):
    """Get stack resource id
        :param heat_client: Heat API client connection point
        :param uid:         ID of stack
        :return: -
    """
    stack_resources = heat_client.resources.list(stack_id=uid)
    return stack_resources[0].physical_resource_id


def get_specific_resource_id(heat_client, uid, resource_name):
    """Get stack resource id by name
        :param heat_client:   heat API client connection point
        :param uid:           ID of stack
        :param resource_name: resource name
        :return: resource id
    """
    stack_resources = heat_client.resources.get(uid, resource_name).to_dict()
    return stack_resources['physical_resource_id']


def update_template_file(template_file, type_of_changes, **kwargs):
    """Update template file specific fields.
        :param template_file: path to template file.
        :param type_of_changes:
        if changes in format - 'format'
        if changes in flavor size - 'flavor'
        :param kwargs: the key-value dictionary of parameters.
        currently following keys are supported
        disk_format: new disk_format value (optional parameter)
        container_format: new container_format value (optional parameter)
        flavor: new flavor size
        :return -
    """
    with open(template_file, 'r') as stream:
        data = yaml.load(stream)
    if type_of_changes == 'format':
        data['resources']['cirros_image']['properties']['disk_format'] \
            = kwargs['disk_format']
        data['resources']['cirros_image']['properties']['container_format'] \
            = kwargs['container_format']
    elif type_of_changes == 'flavor':
        data['resources']['vm']['properties']['flavor'] = kwargs['flavor']
    with open(template_file, 'w') as yaml_file:
        yaml_file.write(yaml.dump(data, default_flow_style=False))


def download_image(image_link_file, where_to_put='/tmp/'):
    """This function will download image from internet and write it
        if image is not already present on node.
        :param image_link_file: Location of file with a link
        :param where_to_put:    Path to output folder on node
        :return: full path to downloaded image. Default: '/tmp/blablablb.bla'
    """
    # Get URL from file
    try:
        with open(image_link_file, 'r') as file_with_link:
            image_url = file_with_link.readline().rstrip('\n')
    except Exception:
        raise Exception("Can not find or read from file on node:"
                        "\n\t{}".format(image_link_file))

    # Get image name from URL. Like: 'fedora-heat-test-image.qcow2'
    image_name_from_url = image_url.rsplit('/', 1)[-1]

    # Prepare full path on node. Like: '/tmp/fedora-heat-test-image.qcow2'
    image_path_on_node = where_to_put + image_name_from_url

    # Check if image already exists on node with path above.
    # If present - return full path to it. If NOT -> download.
    if os.path.isfile(image_path_on_node):
        return image_path_on_node
    else:
        # Open URL
        try:
            response = urllib2.urlopen(image_url)
        except urllib2.HTTPError as e:
            raise Exception('Can not get file from URL. HTTPError = {}.'
                            '\n\tURL = "{}"'.format(str(e.code), image_url))
        except urllib2.URLError as e:
            raise Exception('Can not get file from URL. URLError = {}.'
                            '\n\tURL = "{}"'.format(str(e.reason), image_url))
        except Exception:
            raise Exception("Can not get file from URL:"
                            "\n\t{}".format(image_url))

        # Write image to file. With Chunk to avoid memory errors.
        CHUNK = 16 * 1024
        with open(image_path_on_node, 'wb') as f:
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
        return image_path_on_node


# Instance functions
def get_inst_id(nova_client, inst_name):
    """Get instance id for instance with the name
        :param nova_client: Heat API client connection point
        :param inst_name: Name of instance
        :return Instance uid
    """
    inst_list = nova_client.servers.list()
    if inst_name in [s.name for s in inst_list]:
        inst_dict = {s.name: s.id for s in inst_list}
        return inst_dict[inst_name]
    raise Exception("ERROR: Instance {} is not defined".format(inst_name))


def is_instance_exists(nova_client, uid):
    """Check the presence of instance id in the list of instances
        :param nova_client: Nova API client connection point
        :param uid: UID of instance
        :return True or False
    """
    return uid in [s.id for s in nova_client.servers.list()]


def check_volume(cinder_client, uid):
    """Check the presence of volume id in the list of volume
        :param cinder_client: Cinder API client connection point
        :param uid: UID of volume
        :return True or False
    """
    return uid in [s.id for s in cinder_client.volumes.list()]


def check_volume_snapshot(cinder_client, uid):
    """Check the presence of volume status id in the list of volume status
        :param cinder_client: Cinder API client connection point
        :param uid: UID of volume status
        :return True or False
    """
    return uid in [s for s in cinder_client.volume_snapshots.list()]


def check_inst_status(nova_client, uid, status, timeout=5):
    """Check status of instance
        :param nova_client: Nova API client connection point
        :param uid: UID of instance
        :param status: Expected instance status
        :param timeout: Timeout for check operation
        :return True or False
    """
    if is_instance_exists(nova_client, uid):
        start_time = time()
        inst_status = [s.status for s in nova_client.servers.list()
                       if s.id == uid][0]
        while inst_status != status and time() < start_time + 60 * timeout:
            sleep(1)
            inst_status = [s.status for s in nova_client.servers.list()
                           if s.id == uid][0]
        return inst_status == status
    return False


def delete_instance(nova_client, uid):
    """Delete instance and check that it is absent in the list
        :param nova_client: Nova API client connection point
        :param uid: UID of instance
    """
    if is_instance_exists(nova_client, uid):
        nova_client.servers.delete(uid)
        while is_instance_exists(nova_client, uid):
            sleep(1)


def create_instance(nova_client, inst_name, flavor_id, net_id,
                    security_groups, image_id='', block_device_mapping=None,
                    timeout=5, key_name=None, inst_list=None):
    """Check instance creation
        :param nova_client: Nova API client connection point
        :param inst_name: name for instance
        :param flavor_id: id of flavor
        :param net_id: id of network
        :param security_groups: list of corresponding security groups
        :param image_id: id of image
        :param block_device_mapping: if volume is used
        :param timeout: Timeout for check operation
        :param key_name: Keypair name
        :param inst_list: instances list for cleaning
        :return instance
    """
    end_time = time() + 60 * timeout
    inst = nova_client.servers.create(
            name=inst_name,
            nics=[{"net-id": net_id}],
            flavor=flavor_id,
            image=image_id,
            security_groups=security_groups,
            block_device_mapping=block_device_mapping,
            key_name=key_name)
    if inst_list:
        inst_list.append(inst.id)
    inst_status = [s.status for s in nova_client.servers.list()
                   if s.id == inst.id][0]
    while inst_status != 'ACTIVE':
        if time() > end_time:
            raise AssertionError(
                "Instance status is '{}' instead of 'ACTIVE'".format(
                    inst_status))
        sleep(1)
        inst_status = [s.status for s in nova_client.servers.list()
                       if s.id == inst.id][0]
    return inst


# Floating IP functions
def delete_floating_ip(nova_client, floating_ip):
    """Delete floating ip and check that it is absent in the list
        :param nova_client: Nova API client connection point
        :param floating_ip: floating ip
    """
    if floating_ip in nova_client.floating_ips.list():
        nova_client.floating_ips.delete(floating_ip)
        while floating_ip in nova_client.floating_ips.list():
            sleep(1)


def check_ip(nova_client, uid, fip, timeout=1):
    """Check floating ip address adding to instance
        :param nova_client: Nova API client connection point
        :param uid: UID of instance
        :param fip: Floating ip
        :param timeout: Timeout for check operation
        :return True or False
    """
    if is_instance_exists(nova_client, uid):
        start_time = time()
        ips = [ip['addr'] for ip in nova_client.servers.ips(uid)[
                'admin_internal_net']]
        while fip not in ips and time() < start_time + 60 * timeout:
            sleep(1)
            ips = [ip['addr'] for ip in nova_client.servers.ips(uid)[
                'admin_internal_net']]
        return fip in ips
    return False


# Volume functions
def is_volume_exists(cinder_client, uid):
    """Check the presence of volume id in the list of volume
        :param cinder_client: Cinder API client connection point
        :param uid: UID of volume
        :return True or False
    """
    return uid in [s.id for s in cinder_client.volumes.list()]


def create_volume(cinder_client, image_id, size=1, timeout=5,
                  name='Test_volume', volume_type=None,):
    """Check volume creation
        :param cinder_client: Cinder API client connection point
        :param image_id: UID of image
        :param size: Size of volume in GB
        :param timeout: Timeout for check operation
        :param name: name for volume
        :param volume_type: type for volume
        :return volume
    """
    end_time = time() + 60 * timeout
    volume = cinder_client.volumes.create(size, name=name, imageRef=image_id,
                                          volume_type=volume_type)
    status = cinder_client.volumes.get(volume.id).status
    while status != 'available':
        if time() > end_time:
            raise AssertionError(
                "Volume status is '{}' instead of 'available".format(status))
        sleep(1)
        status = cinder_client.volumes.get(volume.id).status
    return volume


def delete_volume(cinder_client, volume):
    """Delete volume and check that it is absent in the list
        :param cinder_client: Cinder API client connection point
        :param volume: volume
    """
    if volume in cinder_client.volumes.list():
        cinder_client.volumes.delete(volume)
        volume_id = volume.id
        while is_volume_exists(cinder_client, volume_id):
            sleep(1)


def check_volume_status(cinder_client, uid, status, timeout=5):
    """Check status of volume
        :param cinder_client: Cinder API client connection point
        :param uid: UID of volume
        :param status: Expected volume status
        :param timeout: Timeout for check operation
        :return True or False
    """
    if is_volume_exists(cinder_client, uid):
        start_time = time()
        inst_status = [s.status for s in cinder_client.volumes.list()
                       if s.id == uid][0]
        while inst_status != status and time() < start_time + 60 * timeout:
            sleep(1)
            inst_status = [s.status for s in cinder_client.volumes.list()
                           if s.id == uid][0]
        return inst_status == status
    return False


# Flavor functions
def is_flavor_exists(nova_client, flavor_id):
    """Check the presence of flavor in the system
        :param nova_client: Nova API client connection point
        :param flavor_id: name of the flavor
        :return True or False
    """
    return flavor_id in [f.id for f in nova_client.flavors.list()]


def get_flavor_id_by_name(nova_client, flavor_name):
    """The function returns flavor's id by its name
        :param nova_client: Nova API client connection point
        :param flavor_name: Name of the flavor
        :return: UID of the flavor
        None if the flavor with required name does not exist
    """
    for flavor in nova_client.flavors.list():
        if flavor.name == flavor_name:
            return flavor.id


def delete_flavor(nova_client, flavor_id):
    """This function delete the flavor by its name.
        :param nova_client: Nova API client connection point
        :param flavor_id: UID of the flavor to delete
        :return: Nothing
    """
    for flavor in nova_client.flavors.list():
        if flavor.id == flavor_id:
            nova_client.flavors.delete(flavor)
            break
    while is_flavor_exists(nova_client, flavor_id):
        sleep(1)


# Images
def is_image_exists(glance_client, image_id):
    """This function check if image with required id presents in the system
        or not
        :param glance_client: Glance API client connection point
        :param image_id: UID of the image to delete
        :return: True if the image with provided id presents in the system;
        False otherwise
    """
    return image_id in [image.id for image in glance_client.images.list()]


def delete_image(glance_client, image_id):
    """This function should delete the image with provided id from the system
        :param glance_client: Glance API client connection point
        :param image_id: UID of the image to delete
        :return: Nothing
    """
    glance_client.images.delete(image_id)
    while is_image_exists(glance_client, image_id):
        sleep(1)


# execution of system commands
def ping_command(ip_address, c=4, i=4, timeout=3, should_be_available=True):
    """This function executes the ping program and check its results
        :param ip_address: The IP address to ping
        :param c: value of the [-c count] parameter of the ping command
        :param i: value of the [-i interval] parameter of the ping command
        :param timeout: timeout in minutes that we are waiting for successful
        result of the ping operation
        :param should_be_available: this parameter described should we check
        successful result of the ping command or not.
        :return: True in case of success, False otherwise
    """
    end_time = time() + 60 * timeout
    ping_result = False
    while time() < end_time:
        the_result = os.system("ping -c {} -i {} {}".
                               format(c, i, ip_address))
        # TODO(mlaptev): Make sure that all packages has been received
        ping_result = \
            the_result == 0 if should_be_available else the_result != 0
        if ping_result:
            break
    return ping_result


def check_volume_snapshot_status(cinder_client, uid, status, timeout=5):
    """Check status of volume
            :param cinder_client: Cinder API client connection point
            :param uid: UID of volume snapshot
            :param status: Expected volume snapshot status
            :param timeout: Timeout for check operation
            :return True or False
    """
    if check_volume_snapshot(cinder_client, uid):
        start_time = time()
        while time() < start_time + 60 * timeout:
            sleep(1)
            snapshot_status = [s.status
                               for s in cinder_client.volume_snapshots.list()
                               if s.id == uid.id][0]
            if snapshot_status == status:
                return True
    return False


def delete_volume_snapshot(cinder_client, snapshot):
    """Delete volume snapshot and check that it is absent in the list
        :param cinder_client: Cinder API client connection point
        :param volume: volume snapshot
    """
    if snapshot in cinder_client.volume_snapshots.list():
        cinder_client.volume_snapshots.delete(snapshot)
        while snapshot in cinder_client.volume_snapshots.list():
            sleep(1)


# Keys
def is_key_exists(nova_client, key_name):
    """Check the presence of keys in the system
        :param nova_client: Nova API client connection point
        :param key_name: name of the keypair
        :return True or False
    """
    return len(nova_client.keypairs.findall(name=key_name)) > 0


def delete_keys(nova_client, key_name):
    """This function delete the keys by its name.
        :param nova_client: Nova API client connection point
        :param key_name: Name of the keypair to delete
        :return: Nothing
    """
    for key in nova_client.keypairs.list():
        if key.name == key_name:
            nova_client.keypairs.delete(key)
            break
    while is_key_exists(nova_client, key_name):
        sleep(1)


def wait(*args, **kwargs):
    __tracebackhide__ = True

    frame = inspect.stack()[1]
    called_from = '{0.f_globals[__name__]}:{2}'.format(*frame)
    event = kwargs.get('waiting_for', args[0].__name__)
    msg = '{called_from}: waiting for {event}'.format(event=event,
                                                      called_from=called_from)
    logger = logging.getLogger('waiting')

    logger.info(msg)

    try:
        result = base_wait(*args, **kwargs)
        logger.info(msg + ' ... done')
        return result
    except TimeoutExpired as e:
        # prevent shows traceback from waiting package
        raise e


def gen_random_resource_name(prefix=None, reduce_by=None):
    random_name = str(uuid.uuid4()).replace('-', '')[::reduce_by]
    if prefix:
        random_name = prefix + '_' + random_name
    return random_name


def gen_temp_file(prefix='tmp', suffix=''):
    tempdir = os.path.join(os.path.dirname(__file__), '../../temp')
    return NamedTemporaryFile(prefix=prefix, suffix=suffix, dir=tempdir,
                              delete=False)


def get_os_conn(environment):
    return environment.os_conn


def is_task_ready(task):
    logger.debug('Task progress is {0.progress}'.format(task))
    if task.status == 'ready':
        return True
    elif task.status in ('running', 'pending'):
        return False
    else:
        raise Exception('Task is {0.status}. {0.data}'.format(task))


def has_connect(ip, port=22, timeout=1):
    """Return True, if port available and False otherwise"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except Exception:
        return False
    finally:
        s.close()
