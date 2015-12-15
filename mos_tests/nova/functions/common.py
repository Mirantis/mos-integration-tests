from time import sleep, time


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
        while inst_status != status and time() < start_time + 60 * timeout:
            sleep(1)
            inst_status = [s.status for s in novaclient.servers.list() if
                           s.id == uid][0]
        if inst_status == status:
            return True
    return False


def check_ip(novaclient, uid, ip, timeout=1):
    """ Check floating ip address adding to instance
            :param novaclient: Nova API client connection point
            :param uid: UID of instance
            :param ip: Floating ip
            :param timeout: Timeout for check operation
            :return True or False
    """
    if check_instance(novaclient, uid):
        start_time = time()
        ips = [ip['addr'] for ip in novaclient.servers.ips(uid)[
                'admin_internal_net']]
        while ip not in ips and time() < start_time + 10 * timeout:
            sleep(1)
            ips = [ip['addr'] for ip in novaclient.servers.ips(uid)[
                'admin_internal_net']]
        if ip in ips:
            return True
        return False


def delete_instance(novaclient, uid):
    """ Delete stack and check STATUS == DELETE_COMPLETE
            :param novaclient: Nova API client connection point
            :param uid: UID of instance
    """
    if check_instance(novaclient, uid):
        novaclient.servers.delete(uid)
        while check_instance(novaclient, uid):
            sleep(1)
