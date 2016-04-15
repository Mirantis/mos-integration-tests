# https://github.com/vitalygusev/ceilo-scripts/blob/master/mongo-generator.py

import argparse
import copy
import datetime
import itertools
import multiprocessing
import random
import uuid

from oslo_config import cfg
from six.moves import range

from ceilometer.storage import impl_mongodb


metadata = {"state_description": "scheduling",
            "event_type": "compute.instance.create.start",
            "availability_zone": None,
            "terminated_at": "", "ephemeral_gb": 0,
            "instance_type_id": 18, "message": "",
            "deleted_at": "",
            "reservation_id": "r-ccujk2n0",
            "memory_mb": 64,
            "user_id": "ba597f03542d4609bda1698b25222dc2",
            "hostname": "ost1-test-ceilo-instance-310303725",
            "state": "building", "launched_at": "",
            "node": None, "ramdisk_id": "",
            "access_ip_v6": None, "disk_gb": 1,
            "access_ip_v4": None, "kernel_id": "",
            "image_name": "TestVM",
            "host": "compute.node-4.domain.tld",
            "display_name": "ost1-test-ceilo-instance-310303725",
            "image_ref_url": "http://10.20.0.6:9292/images/"
                             "146e9b37-c922-45c6-9d7d-477fec54bc59",
            "root_gb": 1,
            "tenant_id": "373127a00dd34e1c9b753cde9bca5395",
            "created_at": "2015-03-19T11:09:06.000000",
            "instance_id": "3a55a1c0-52b1-4deb-a6d4-c9a6093fc0eb",
            "instance_type": "ost1_test-flavor-nano15708668",
            "vcpus": 1,
            "image_meta": {"container_format": "bare",
                           "min_ram": "64",
                           "murano_image_info": "{\"title\": \"Murano Demo\", "
                                                "\"type\": \"cirros.demo\"}",
                           "disk_format": "qcow2",
                           "min_disk": "1",
                           "base_image_ref":
                               "146e9b37-c922-45c6-9d7d-477fec54bc59"},
            "architecture": None, "os_type": None,
            "instance_flavor_id": "5306"}

sample_dict = {"counter_name": "instance",
               "user_id": "ba597f03542d4609bda1698b25222dc2",
               "message_signature": "c8f7c5a127931cd7cc7a99d24f51751"
                                    "a46ab343a2cba246a613e8c56644500a1",
               "timestamp": "2015-03-19T11:09:06.822Z",
               "resource_id": "3a55a1c0-52b1-4deb-a6d4-c9a6093fc0eb",
               "source": "openstack", "counter_unit": "instance",
               "counter_volume": 1,
               "recorded_at": ("2015-03-19T11:09:06.906Z"),
               "project_id": "373127a00dd34e1c9b753cde9bca5395",
               "message_id": "5c30ef42-ce28-11e4-a3a9-eec7d5e8f742",
               "counter_type": "gauge"}


def create_resources(resources_count=5000):
    return [str(uuid.uuid4()) for _ in range(resources_count)]


def record_samples(samples_count=50000, resources_count=5000,
                   conf=None):
    print('%s. %s. Start record samples' % (
        datetime.datetime.utcnow(),
        multiprocessing.current_process().name))
    cfg.CONF(["--config-file", "/etc/ceilometer/ceilometer.conf"],
             project='ceilometer')

    cl = impl_mongodb.Connection(cfg.CONF.database.connection)
    db = cl.db
    one_second = datetime.timedelta(seconds=1) * (conf.get('interval') or 1)
    timestamp = datetime.datetime.utcnow() - one_second * (samples_count + 1)
    sample = copy.deepcopy(sample_dict)
    resource_ids = create_resources(resources_count)
    resources_timestamps = {}
    resource_metadatas = {}
    batch = []
    for i in range(samples_count):
        m = copy.deepcopy(metadata)
        sample['_id'] = uuid.uuid4().hex
        sample['message_id'] = uuid.uuid4().hex
        sample['timestamp'] = timestamp
        sample['counter_name'] = conf.get('name') or 'cpu_util'
        sample['counter_volume'] = random.randint(0, 1600)
        sample['counter_unit'] = conf.get('unit') or '%'
        sample['recorded_at'] = timestamp
        sample['project_id'] = conf.get('project')
        sample['user_id'] = conf.get('user')
        timestamp += one_second
        timestamp = timestamp.replace(microsecond=0)

        resource_index = random.randint(0, resources_count - 1)
        resource_id = resource_ids[resource_index]
        sample['resource_id'] = resource_id
        m['host'] = "host.%s" % resource_index
        sample['resource_metadata'] = m
        if resource_id not in resource_metadatas:
            resource_metadatas[resource_id] = m
        batch.append(copy.deepcopy(sample))
        if len(batch) >= 5000:
            db.meter.insert(batch)
            batch = []
        if not resources_timestamps.get(resource_id):
            resources_timestamps[resource_id] = [timestamp, timestamp]
        resources_timestamps[resource_id][1] = timestamp

    resource_batch = []
    for resource, timestamps in resources_timestamps.items():
        resource_dict = {"_id": resource,
                         "first_sample_timestamp": timestamps[0],
                         "last_sample_timestamp":
                             timestamps[0] +
                             datetime.timedelta(
                                 seconds=random.randint(0, 1000)),
                         "metadata": resource_metadatas[resource],
                         "user_id": conf.get('user'),
                         "project_id": conf.get('project'),
                         "source": "jira",
                         "meter": [{"counter_name": conf.get('name',
                                                             'cpu_util'),
                                    "counter_unit": conf.get('unit', '%'),
                                    "counter_type": 'gauge'}, ]}
        resource_batch.append(resource_dict)
    if batch:
        db.meter.insert(batch)
    if resource_batch:
        db.resource.insert(resource_batch)
    print("%s. %s. Writed %s samples and %s resources" % (
        datetime.datetime.utcnow(),
        multiprocessing.current_process().name,
        samples_count, resources_count))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--users",
                        type=int,
                        default=2)
    parser.add_argument("--projects",
                        type=int,
                        default=2)
    parser.add_argument("--samples_per_user_project",
                        type=int,
                        default=30000,
                        dest="samples")
    parser.add_argument("--resources_per_user_project",
                        type=int,
                        default=4,
                        dest="resources")
    parser.add_argument("--meter",
                        type=str,
                        default="cpu_util")
    args = parser.parse_args()
    users = [uuid.uuid4().hex for _ in range(args.users)]
    projects = [uuid.uuid4().hex for _ in range(args.projects)]
    meters = [args.meter]
    interval = 30
    for user, project, meter in itertools.product(users, projects, meters):
        conf = {"name": meter,
                "user": user,
                "project": project,
                "interval": interval}
        record_samples(args.samples, args.resources, conf)

if __name__ == '__main__':
    main()
