import os
from time import sleep, time
import urllib2

def check_stack(stack_name, heat):
    """ Check the presence of stack_name in stacks list
            :param heat: Heat API client connection point
            :param stack_name: Name of stack
            :return True or False
    """
    if stack_name in [s.stack_name for s in heat.stacks.list()]:
        return True
    return False


def clean_stack(stack_name, heat):
    """ Delete stack
            :param heat: Heat API client connection point
            :param stack_name: Name of stack
            :return None
    """
    if stack_name in [s.stack_name for s in heat.stacks.list()]:
        heat.stacks.delete(stack_name)
        while check_stack(stack_name, heat):
            sleep(1)


def check_stack_status(stack_name, heat, status, timeout=60):
    """ Check stack status
            :param heat: Heat API client connection point
            :param stack_name: Name of stack
            :param status: Expected stack status
            :param timeout: Timeout for check operation
            :return True or False
    """
    if check_stack(stack_name, heat):
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


def create_stack(heatclient, stack_name, template, parameters={}):
    """ Create a stack from template and check STATUS == CREATE_COMPLETE
            :param parameters: parameters from template
            :param heatclient: Heat API client connection point
            :param stack_name: Name of a new stack
            :param template:   Content of a template name
            :return uid: UID of created stack
    """
    timeout_value = 10  # Timeout in minutes to wait for stack status change
    stack = heatclient.stacks.create(
        stack_name=stack_name,
        template=template,
        parameters=parameters)
    uid = stack['stack']['id']
    sleep(1)

    stack = heatclient.stacks.get(stack_id=uid).to_dict()
    # default: 10 minutes of timeout to change stack status
    timeout = time() + 60 * timeout_value
    while stack['stack_status'] == 'CREATE_IN_PROGRESS':
        stack = heatclient.stacks.get(stack_id=uid).to_dict()
        if time() > timeout:
            break
        else:
            sleep(1)

    # Check that final status of a newly created stack is 'CREATE_COMPLETE'
    if stack['stack_status'] != 'CREATE_COMPLETE':
        raise Exception("ERROR: Stack is not in 'CREATE_COMPLETE' "
                        "state:\n{0}".format(stack))
    return uid


def delete_stack(heatclient, uid):
    """ Delete stack and check STATUS == DELETE_COMPLETE
            :param heatclient: Heat API client connection point
            :param uid:        UID of stack
    """
    timeout_value = 10  # Timeout in minutes to wait for stack status change
    heatclient.stacks.delete(uid)
    sleep(1)

    stack = heatclient.stacks.get(stack_id=uid).to_dict()
    # default: 10 minutes of timeout to change stack status
    timeout = time() + 60 * timeout_value
    while stack['stack_status'] == 'DELETE_IN_PROGRESS':
        stack = heatclient.stacks.get(stack_id=uid).to_dict()
        if time() > timeout:
            break
        else:
            sleep(1)

    # Check that final status of a newly deleted stack is 'DELETE_COMPLETE'
    if stack['stack_status'] != 'DELETE_COMPLETE':
        raise Exception("ERROR: Stack is not in 'DELETE_COMPLETE' "
                        "state:\n{0}".format(stack))


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
