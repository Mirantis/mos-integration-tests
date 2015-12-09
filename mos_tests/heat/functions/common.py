from time import sleep, time


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


def check_stack_status(stack_name, heat, status):
    """ Check stack status
            :param heat: Heat API client connection point
            :param stack_name: Name of stack
            :param status: Expected stack status
            :return True or False
    """
    if check_stack(stack_name, heat):
        stack_status = [s.stack_status for s in heat.stacks.list() if s.stack_name == stack_name][0]
        while stack_status.find('IN_PROGRESS') != -1:
            sleep(1)
            stack_status = [s.stack_status for s in heat.stacks.list() if s.stack_name == stack_name][0]
        if stack_status == status:
            return True
        return False

        
def create_stack(heatclient, stack_name, template):
    """ Create a stack from template and check STATUS == CREATE_COMPLETE
            :param heatclient: Heat API client connection point
            :param stack_name: Name of a new stack
            :param template:   Content of a template name
            :return uid: UID of created stack
    """
    timeout_value = 10  # Timeout in minutes to wait for stack status change
    stack = heatclient.stacks.create(
        stack_name=stack_name,
        template=template,
        parameters={})
    uid = stack['stack']['id']

    stack = heatclient.stacks.get(stack_id=uid).to_dict()
    timeout = time() + 60 * timeout_value  # default: 10 minutes of timeout to change stack status
    while stack['stack_status'] == 'CREATE_IN_PROGRESS':
        stack = heatclient.stacks.get(stack_id=uid).to_dict()
        if time() > timeout:
            break
        else:
            sleep(5)

    # Check that final status of a newly created stack is 'CREATE_COMPLETE'
    if stack['stack_status'] != 'CREATE_COMPLETE':
        raise Exception("ERROR: Stack is not in 'CREATE_COMPLETE' state:\n{0}".format(stack))
    return uid


def delete_stack(heatclient, uid):
    """ Delete stack and check STATUS == DELETE_COMPLETE
            :param heatclient: Heat API client connection point
            :param uid:        UID of stack
    """
    timeout_value = 10  # Timeout in minutes to wait for stack status change
    heatclient.stacks.delete(uid)

    stack = heatclient.stacks.get(stack_id=uid).to_dict()
    timeout = time() + 60 * timeout_value   # default: 10 minutes of timeout to change stack status
    while stack['stack_status'] == 'DELETE_IN_PROGRESS':
        stack = heatclient.stacks.get(stack_id=uid).to_dict()
        if time() > timeout:
            break
        else:
            sleep(5)

    # Check that final status of a newly deleted stack is 'DELETE_COMPLETE'
    if stack['stack_status'] != 'DELETE_COMPLETE':
        raise Exception("ERROR: Stack is not in 'DELETE_COMPLETE' state:\n{0}".format(stack))
