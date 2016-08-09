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

import os
import yaml


def _parse_obj(obj):
    target = lambda: None
    if isinstance(obj, dict):
        for key, value in obj.items():
            setattr(target, key, _parse_obj(value))
    elif isinstance(obj, list):
        target = [_parse_obj(x) for x in obj]
    else:
        target = obj
    return target

commands_path = os.path.dirname(os.path.abspath(__file__)) + "/commands.yaml"
BashCommand = _parse_obj(yaml.load(open(commands_path).read()))
