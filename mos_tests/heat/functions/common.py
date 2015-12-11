import os
from time import sleep, time
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
    stack = heatclient.stacks.create(
        stack_name=stack_name,
        template=template,
        parameters=parameters)
    uid = stack['stack']['id']
    check_stack_status_complete(heatclient, uid, 'CREATE')
    return uid


def delete_stack(heatclient, uid):
    """ Delete stack and check STATUS == DELETE_COMPLETE
            :param heatclient: Heat API client connection point
            :param uid:        UID of stack
    """
    heatclient.stacks.delete(uid)
    check_stack_status_complete(heatclient, uid, 'DELETE')


def check_stack_status_complete(heat_client, uid, action):
    """ Check stack STATUS in COMPLETE state
            :param heatclient: Heat API client connection point
            :param id: ID stack
            :param action: status that will be checked.
                           Could be CREATE, UPDATE, DELETE.
            :return uid: UID of created stack
    """
    timeout_value = 10
    stack = heat_client.stacks.get(stack_id=uid).to_dict()
    timeout = time() + 10 * timeout_value
    while stack['stack_status'] == '{0}_IN_PROGRESS'.format(action):
        stack = heat_client.stacks.get(stack_id=uid).to_dict()
        if time() > timeout:
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


def update_stack(heat_client, uid, template_file):
    """ Update stack using template file
            :param heat_client: Heat API client connection point
            :param id:        ID of stack
            :param template_file: path to stack template file.
            :return: -
    """
    heat_client.stacks.update(stack_id=uid, template=template_file)
    check_stack_status_complete(heat_client, uid, 'UPDATE')


def get_resource_id(heat_client, uid):
    """ Get stack resource id
            :param heat_client: Heat API client connection point
            :param id:        ID of stack
            :return: -
    """
    stack_resources = heat_client.resources.list(stack_id=uid)
    return stack_resources[0].physical_resource_id


def update_template_file(template_file, type_of_changes, **kwargs):
    """ Update template file specific fields.
        :param template_file: path to template file.
        :param type_of_changes: if changes in format - 'format'
                                if changes in flavor size - 'flavor'
        :param disk_format: new disk_format value(optional)
        :param container_format: new container_format value(optional)
        :param flavor: new flavor size
        :return -
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
