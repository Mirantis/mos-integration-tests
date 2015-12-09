from time import sleep


def check_stack(stack_name, heat):
    if stack_name in [s.stack_name for s in heat.stacks.list()]:
        return True
    return False


def clean_stack(stack_name, heat):
    if stack_name in [s.stack_name for s in heat.stacks.list()]:
        heat.stacks.delete(stack_name)
        while check_stack(stack_name, heat):
            sleep(1)


def check_stack_status(stack_name, heat, status):
    if check_stack(stack_name, heat):
        stack_status = [s.stack_status for s in heat.stacks.list() if s.stack_name == stack_name][0]
        while stack_status.find('IN_PROGRESS') != -1:
            sleep(1)
            stack_status = [s.stack_status for s in heat.stacks.list() if s.stack_name == stack_name][0]
        if stack_status == status:
            return True
        return False

        




