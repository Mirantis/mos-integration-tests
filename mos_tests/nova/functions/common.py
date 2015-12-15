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
