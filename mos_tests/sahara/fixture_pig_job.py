#    Copyright 2016 Mirantis, Inc.
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

import logging

import pytest

from mos_tests.functions.common import gen_random_resource_name
from mos_tests.functions.common import wait


logger = logging.getLogger(__name__)

CONTAINER_NAME = 'container'
INPUT_FILE_NAME = 'input_for_job'
OUTPUT_FILE_NAME = 'output_for_job'
PIG_FILE_NAME = 'example_pig'
TEMPLATE_NAME = 'template_for_pig_job'

PIG_SCRIPT = '''
A = load '$INPUT';
B = foreach A generate flatten(TOKENIZE((chararray)$0)) as word;
C = filter B by word matches '\\\\w+';
D = group C by word;
E = foreach D generate COUNT(C), group;
store E INTO '$OUTPUT' USING PigStorage();
'''

INPUT_CONTENT = "Input file for word count calculation"


@pytest.yield_fixture
def files_for_pig_job(swift):
    logger.info('Create container and put files')
    swift.put_container(CONTAINER_NAME)
    swift.put_object(container=CONTAINER_NAME, obj=INPUT_FILE_NAME,
                     contents=INPUT_CONTENT)
    swift.put_object(container=CONTAINER_NAME, obj=PIG_FILE_NAME,
                     contents=PIG_SCRIPT)

    yield

    logger.info('Remove container')
    objects = swift.get_container(CONTAINER_NAME)[1]
    objects_to_remove = [obj['name'] for obj in objects]
    for obj in objects_to_remove:
        swift.delete_object(CONTAINER_NAME, obj)
    swift.delete_container(CONTAINER_NAME)


@pytest.yield_fixture
def data_sources(os_conn, files_for_pig_job, sahara):
    user = os_conn.session.auth.username
    password = os_conn.session.auth.password

    logger.info('Creating input data source')
    input_url = "swift://{0}/{1}".format(CONTAINER_NAME, INPUT_FILE_NAME)
    src_input = sahara.data_sources.create(name=INPUT_FILE_NAME,
                                           description="input_file",
                                           data_source_type='swift',
                                           url=input_url,
                                           credential_user=user,
                                           credential_pass=password)

    logger.info('Creating output data source with random name')
    output_name1 = gen_random_resource_name(prefix=OUTPUT_FILE_NAME)
    output_url1 = "swift://{0}/{1}".format(CONTAINER_NAME, output_name1)
    src_output1 = sahara.data_sources.create(name=output_name1,
                                             description="output_file1",
                                             data_source_type='swift',
                                             url=output_url1,
                                             credential_user=user,
                                             credential_pass=password)

    logger.info('Creating output data source to use after restart')
    output_name2 = gen_random_resource_name(prefix=OUTPUT_FILE_NAME)
    output_url2 = "swift://{0}/{1}".format(CONTAINER_NAME, output_name2)
    src_output2 = sahara.data_sources.create(name=output_name2,
                                             description="output_file2",
                                             data_source_type='swift',
                                             url=output_url2,
                                             credential_user=user,
                                             credential_pass=password)

    yield src_input.id, src_output1.id, src_output2.id

    sahara.data_sources.delete(src_input.id)
    sahara.data_sources.delete(src_output1.id)
    sahara.data_sources.delete(src_output2.id)


@pytest.yield_fixture
def job_binary(os_conn, sahara):
    pig_url = "swift://{0}/{1}".format(CONTAINER_NAME, PIG_FILE_NAME)
    extra = {'user': os_conn.session.auth.username,
             'password': os_conn.session.auth.password}
    job_binary = sahara.job_binaries.create(name=PIG_FILE_NAME,
                                            url=pig_url,
                                            extra=extra)
    yield job_binary.id
    sahara.job_binaries.delete(job_binary.id)


@pytest.yield_fixture
def job_template(job_binary, sahara):
    template = sahara.jobs.create(name=TEMPLATE_NAME, type='Pig',
                                  mains=[job_binary])
    yield template.id
    jobs = sahara.job_executions.list()
    for job in jobs:
        sahara.job_executions.delete(job.id)
    wait(lambda: len(sahara.job_executions.list()) == 0,
         timeout_seconds=2 * 60, waiting_for='jobs deletion')
    sahara.jobs.delete(template.id)
