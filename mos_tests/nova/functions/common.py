from time import sleep, time


def check_instance(novaclient, uid):
    """ Check the presence of stack_name in stacks list
            :param novaclient: Nova API client connection point
            :param uid: UID of instance
            :return True or False
    """
    if uid in [s.id for s in novaclient.servers.list()]:
        return True
    return False


def check_inst_status(novaclient, uid, status, timeout=5):
    """ Check status if instance
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
        while inst_status != status and time() < start_time + 60*timeout:
            sleep(1)
            inst_status = [s.status for s in novaclient.servers.list() if
                           s.id == uid][0]
        if inst_status == status:
            return True
    return False

