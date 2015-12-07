#!/usr/bin/env python
#
#    Copyright 2015 Mirantis, Inc.
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

import optparse


from settings import logger
from settings import TestRailSettings
from testrail_client import TestRailProject
from testrail import APIError
from test_result import TestResult


LOG = logger


def report_test_results_for_run(client, run_name, suite_id, case_name, case_status):
    the_case = client.get_case_by_name(suite_id, case_name)
    the_run = client.add_run(client.test_run_struct(name=run_name,
                                                    suite_id=int(suite_id),
                                                    milestone_id=client.get_milestone_by_name("8.0")['id'],
                                                    description=run_name,
                                                    config_ids=None,
                                                    include_all=True,
                                                    assignedto=None,
                                                    case_ids=[the_case['id']]))
    client.add_results_for_cases(the_run['id'], suite_id, [TestResult(case_name, None, case_status, 0)])


def main():
    parser = optparse.OptionParser(
        description='Publish the results of Automated Cloud Tests in TestRail')
    parser.add_option('-r', '--run-name', dest='run_name',
                      help='The name of a test run. '
                           'The name should describe the configuration '
                           'of the environment where Tempest tests were run')
    parser.add_option('-i', '--id', dest='test_suite_id', default="1595",
                      help='The id of test suite that should be updated with results of'
                           'the test run')
    parser.add_option('-n', '--case_name', dest='test_case_name', default="SimpleTestCase",
                      help='Name of the test case')

    (options, args) = parser.parse_args()

    if options.run_name is None:
        raise optparse.OptionValueError('No run name was specified!')

    # STEP #1
    # Initialize TestRail project client
    LOG.info('Initializing TestRail project client...')
    client = TestRailProject(url=TestRailSettings.url,
                             user="user@domain",
                             password="",
                             project=TestRailSettings.project)
    LOG.info('TestRail project client has been initialized.')

    the_suite = client.get_suite(int(options.test_suite_id))
    LOG.info('Tests suite is "{0}".'.format(the_suite['name']))

    try:
        report_test_results_for_run(client, options.run_name, options.test_suite_id, options.test_case_name, 'passed')
    except APIError as api_error:
        LOG.exception(api_error)

if __name__ == "__main__":
    main()
