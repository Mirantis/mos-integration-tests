import os
from time import sleep, time
import urllib2
import yaml


def check_stack(stack_name, heat):
    """ Check the presence of stack_name in stacks list
            :param heat: Heat API client connection point
            :param stack_name: Name of stack
            :return True or False
    """
    if stack_name in [s.stack_name for s in heat.stacks.list()]:
        return True
    return False


def get_stack_id(heatclient, stack_name):
    """ Check stack status
            :param heatclient: Heat API client connection point
            :param stack_name: Name of stack
            :return Stack uid
    """
    if check_stack(stack_name, heatclient):
        stack_dict = {s.stack_name: s.id for s in heatclient.stacks.list()}
        return stack_dict[stack_name]
    raise Exception("ERROR: Stack {0} is not defined".format(stack_name))


def check_stack_status(stack_name, heat, status, timeout=60):
    """ Check stack status
            :param heat: Heat API client connection point
            :param stack_name: Name of stack
            :param status: Expected stack status
            :param timeout: Timeout for check operation
            :return True or False
    """
    if check_stack(stack_name, heat):
        start_time = time()
        stack_status = [s.stack_status for s in heat.stacks.list()
                    if s.stack_name == stack_name][0]
        while stack_status.find('IN_PROGRESS') != -1 and time() < \
                        start_time + 60 * timeout:
            sleep(1)
            stack_status = [s.stack_status for s in heat.stacks.list()
                            if s.stack_name == stack_name][0]
        if stack_status == status:
            return True
    return False


def create_stack(heatclient, stack_name, template, parameters={}, timeout=20):
    """ Create a stack from template and check STATUS == CREATE_COMPLETE
            :param parameters: parameters from template
            :param heatclient: Heat API client connection point
            :param stack_name: Name of a new stack
            :param template:   Content of a template name
            :param timeout: Timeout for check operation
            :return uid: UID of created stack
    """
    stack = heatclient.stacks.create(
        stack_name=stack_name,
        template=template,
        parameters=parameters,
        timeout_mins=timeout)
    uid = stack['stack']['id']
    check_stack_status_complete(heatclient, uid, 'CREATE', timeout)
    return uid


def delete_stack(heatclient, uid):
    """ Delete stack and check STATUS == DELETE_COMPLETE
            :param heatclient: Heat API client connection point
            :param uid:        UID of stack
    """
    if uid in [s.id for s in heatclient.stacks.list()]:
        heatclient.stacks.delete(uid)
        while uid in [s.id for s in heatclient.stacks.list()]:
            sleep(1)


def check_stack_status_complete(heatclient, uid, action, timeout=10):
    """ Check stack STATUS in COMPLETE state

    :param heatclient: Heat API client connection point
    :param uid: ID stack
    :param action: status that will be checked.
        Could be CREATE, UPDATE, DELETE.
    :param timeout: Timeout for check operation
    :return uid: UID of created stack
    """
    stack = heatclient.stacks.get(stack_id=uid).to_dict()
    end_time = time() + 60 * timeout
    while stack['stack_status'] == '{0}_IN_PROGRESS'.format(action):
        stack = heatclient.stacks.get(stack_id=uid).to_dict()
        if time() > end_time:
            break
        else:
            sleep(1)
    if stack['stack_status'] != '{0}_COMPLETE'.format(action):
        raise Exception("ERROR: Stack {0} is not in '{1}_COMPLETE' "
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
    """ Update stack using template file
            :param heat_client: Heat API client connection point
            :param id:        ID of stack
            :param template_file: path to stack template file.
            :param parameters: parameters from template
            :return: -
    """
    heat_client.stacks.update(stack_id=uid, template=template_file,
                              parameters=parameters)
    check_stack_status_complete(heat_client, uid, 'UPDATE')


def get_resource_id(heat_client, uid):
    """ Get stack resource id
            :param heat_client: Heat API client connection point
            :param id:        ID of stack
            :return: -
    """
    stack_resources = heat_client.resources.list(stack_id=uid)
    return stack_resources[0].physical_resource_id


def get_specific_resource_id(heat_client, uid, resource_name):
    """ Get stack resource id by name
            :param heat_client:   heat API client connection point
            :param id:            ID of stack
            :param resource_name: resource name
            :return: resource id
    """
    stack_resources = heat_client.resources.get(uid, resource_name).to_dict()
    return stack_resources['physical_resource_id']


def update_template_file(template_file, type_of_changes, **kwargs):
    """ Update template file specific fields.

    :param template_file: path to template file.
    :param type_of_changes:
        if changes in format - 'format'
        if changes in flavor size - 'flavor'
    :param disk_format: new disk_format value(optional)
    :param container_format: new container_format value(optional)
    :param flavor: new flavor size
    """
    with open(template_file, 'r') as stream:
        data = yaml.load(stream)
    if type_of_changes == 'format':
        data['resources']['cirros_image']['properties']['disk_format']\
            = kwargs['disk_format']
        data['resources']['cirros_image']['properties']['container_format']\
            = kwargs['container_format']
    elif type_of_changes == 'flavor':
        data['resources']['vm']['properties']['flavor'] = kwargs['flavor']
    with open(template_file, 'w') as yaml_file:
        yaml_file.write(yaml.dump(data, default_flow_style=False))


def download_image(image_link_file, where_to_put='/tmp/'):
    """ This function will download image from internet and write it
        if image is not already present on node.

    :param image_link_file: Location of file with a link
    :param where_to_put:    Path to output folder on node
    :return: full path to downloaded image. Default: '/tmp/blablablb.bla'
    """
    # Get URL from file
    try:
        with open(image_link_file, 'r') as file_with_link:
            image_url = file_with_link.read()
    except Exception:
        raise Exception("Can not find or read from file on node:"
                        "\n\t{0}".format(image_link_file))

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
        except urllib2.HTTPError, e:
            raise Exception('Can not get file from URL. HTTPError = {0}.'
                            '\n\tURL = "{1}"'.format(str(e.code), image_url))
        except urllib2.URLError, e:
            raise Exception('Can not get file from URL. URLError = {0}.'
                            '\n\tURL = "{1}"'.format(str(e.reason), image_url))
        except Exception:
            raise Exception("Can not get file from URL:"
                            "\n\t{0}".format(image_url))

        # Write image to file. With Chunk to avoid memory errors.
        CHUNK = 16 * 1024
        with open(image_path_on_node, 'wb') as f:
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
        return image_path_on_node


def get_inst_id(novaclient, inst_name):
    """ Get instance id for instance with the name
            :param novaclient: Heat API client connection point
            :param inst_name: Name of instance
            :return Instance uid
    """
    inst_list = novaclient.servers.list()
    if inst_name in [s.name for s in inst_list]:
        inst_dict = {s.name: s.id for s in inst_list}
        return inst_dict[inst_name]
    raise Exception("ERROR: Instance {0} is not defined".format(inst_name))


def check_instance(novaclient, uid):
    """ Check the presence of instance id in the list of instances
            :param novaclient: Nova API client connection point
            :param uid: UID of instance
            :return True or False
    """
    if uid in [s.id for s in novaclient.servers.list()]:
        return True
    return False


def check_inst_status(novaclient, uid, status, timeout=5):
    """ Check status of instance
            :param novaclient: Nova API client connection point
            :param uid: UID of instance
            :param status: Expected instance status
            :param timeout: Timeout for check operation
            :return True or False
    """
    if check_instance(novaclient, uid):
        start_time = time()
        inst_status = [s.status for s in novaclient.servers.list() if s.id ==
                       uid][0]
        while inst_status != status and time() < start_time + 60 * timeout:
            sleep(1)
            inst_status = [s.status for s in novaclient.servers.list() if
                           s.id == uid][0]
        if inst_status == status:
            return True
    return False


def check_ip(novaclient, uid, fip, timeout=1):
    """ Check floating ip address adding to instance
            :param novaclient: Nova API client connection point
            :param uid: UID of instance
            :param fip: Floating ip
            :param timeout: Timeout for check operation
            :return True or False
    """
    if check_instance(novaclient, uid):
        start_time = time()
        ips = [ip['addr'] for ip in novaclient.servers.ips(uid)[
                'admin_internal_net']]
        while fip not in ips and time() < start_time + 60 * timeout:
            sleep(1)
            ips = [ip['addr'] for ip in novaclient.servers.ips(uid)[
                'admin_internal_net']]
        if fip in ips:
            return True
        return False


def delete_instance(novaclient, uid):
    """ Delete instance and check that it is absent in the list
            :param novaclient: Nova API client connection point
            :param uid: UID of instance
    """
    if check_instance(novaclient, uid):
        novaclient.servers.delete(uid)
        while check_instance(novaclient, uid):
            sleep(1)


def create_volume(cinderclient, image_id, timeout=5):
    """ Check volume creation
            :param cinderclient: Nova API client connection point
            :param image_id: UID of image
            :param timeout: Timeout for check operation
            :return volume id
    """
    end_time = time() + 60 * timeout
    volume = cinderclient.volumes.create(1, name='Test_volume',
                                         imageRef=image_id)
    while True:
        status = cinderclient.volumes.get(volume.id).status
        if status == 'available':
            return volume.id
        elif time() > end_time:
            raise AssertionError(
                "Volume status is '{0}' instead of 'available".format(status))
        else:
            sleep(1)


def create_instance(novaclient, inst_name, flavor_id, net_id, security_group,
                    image_id='', block_device_mapping=None, timeout=5):
    """ Check instance creation
            :param novaclient: Nova API client connection point
            :param inst_name: name for instance
            :param image_id: id of image
            :param flavor_id: id of flavor
            :param net_id: id of network
            :param security_group: corresponding security_group
            :param block_device_mapping: if volume is used
            :param timeout: Timeout for check operation
            :return instance id
    """
    end_time = time() + 60 * timeout
    inst = novaclient.servers.create(name=inst_name, nics=[{"net-id": net_id}],
                                     flavor=flavor_id, image=image_id,
                                     security_groups=[security_group],
                                     block_device_mapping=block_device_mapping)
    while True:
        inst_status = [s.status for s in novaclient.servers.list() if s.id ==
                       inst.id][0]
        if inst_status == 'ACTIVE':
            return inst
        elif time() > end_time:
            raise AssertionError(
                "Instance status is '{0}' instead of 'ACTIVE".format(
                    inst_status))
        else:
            sleep(1)

