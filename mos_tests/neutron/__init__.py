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


# suppress iso8601 and paramiko debug logging
class NoDebugMessageFilter(logging.Filter):
    def filter(self, record):
        return not record.levelno <= logging.DEBUG

logging.getLogger('paramiko.transport').addFilter(NoDebugMessageFilter())
logging.getLogger('paramiko.hostkeys').addFilter(NoDebugMessageFilter())
logging.getLogger('iso8601.iso8601').addFilter(NoDebugMessageFilter())


logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': False,

    'formatters': {
        'standart': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'filters': {
        'mos_tests': {
            'class': 'logging.Filter',
            'name': 'mos_tests',
        }
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'standart',
        },
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': 'neutron.log',
            'formatter': 'standart',
        },
    },
    'loggers': {
        '': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'mos_tests': {
            'handlers': ['console'],
            'level': 'INFO',
            'filters': ['mos_tests']
        }
    }
})
