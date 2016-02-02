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

import logging
import logging.config

from mos_tests.settings import CONSOLE_LOG_LEVEL

logging.getLogger("paramiko.transport").setLevel(logging.WARNING)
logging.getLogger("paramiko.hostkeys").setLevel(logging.INFO)
logging.getLogger("iso8601.iso8601").setLevel(logging.INFO)

logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': False,

    'formatters': {
        'standart': {
            'format':
                '%(asctime)s [%(levelname)s] %(name)s:%(lineno)s: %(message)s'
        },
    },
    'handlers': {
        'console': {
            'level': CONSOLE_LOG_LEVEL,
            'class': 'logging.StreamHandler',
            'formatter': 'standart',
            'stream': 'ext://sys.stdout',
        },
        'file': {
            'level': logging.DEBUG,
            'class': 'logging.FileHandler',
            'filename': 'test.log',
            'formatter': 'standart',
        },
    },
    'loggers': {
        '': {
            'handlers': ['file'],
            'level': logging.DEBUG,
        },
        'mos_tests': {
            'handlers': ['console'],
            'level': logging.DEBUG,
        },
    }
})
