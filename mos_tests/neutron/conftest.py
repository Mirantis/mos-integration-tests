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


def pytest_addoption(parser):
    parser.addoption("--fuel-ip", '-I', action="store",
                     help="Fuel master server ip address")
    parser.addoption("--env", '-E', action="store",
                     help="Fuel devops env name")
    parser.addoption("--snapshot", '-S', action="store",
                     help="Fuel devops snapshot name")
