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

from mos_tests.functions.common import wait


logger = logging.getLogger(__name__)


def run_and_check_job(sahara, template_id, cluster_id, input_id, output_id):
    def is_job_succeeded(job_id):
        job = sahara.job_executions.get(job_id)
        assert job.info['status'] not in ['KILLED', 'FAILED'], (
            "job is {0}".format(job.info['status']))
        return job.info['status'] == 'SUCCEEDED'

    logger.info('Execute job on existing cluster')
    job = sahara.job_executions.create(job_id=template_id,
                                       cluster_id=cluster_id,
                                       input_id=input_id,
                                       output_id=output_id)
    wait(lambda: is_job_succeeded(job.id), timeout_seconds=10 * 60,
         sleep_seconds=10, waiting_for='job success')


@pytest.mark.check_env_('is_sahara_enabled')
@pytest.mark.testrail_id('1295481')
def test_restart_all_sahara_services(env, data_sources, cluster, job_template,
                                     sahara):
    """Restart all Sahara services

    Scenario:
        1. Register vanilla 2.7.1 image for sahara
        2. Create vanilla cluster based on default template for vanilla
        3. Create job template and run job on cluster
        4. Check that job is finished successfully
        5. Restart sahara services on controllers
        6. Re-run job and check that it's finished successfully again
    """

    input_id, output_id1, output_id2 = data_sources
    run_and_check_job(sahara, job_template, cluster, input_id, output_id1)

    for node in env.get_nodes_by_role('controller'):
        with node.ssh() as remote:
            remote.check_call("service sahara-api restart && "
                              "service sahara-engine restart")

    run_and_check_job(sahara, job_template, cluster, input_id, output_id2)
