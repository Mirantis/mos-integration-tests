from settings import logger


class TestResult(object):
    """TestResult."""  # TODO documentation

    def __init__(self, name, group, status, duration, url=None,
                 version=None, description=None, comments=None,
                 launchpad_bug=None, steps=None):
        self.name = name
        self.group = group
        self._status = status
        self.duration = duration
        self.url = url
        self._version = version
        self.description = description
        self.comments = comments
        self.launchpad_bug = launchpad_bug
        self.launchpad_bug_status = None
        self.launchpad_bug_importance = None
        self.launchpad_bug_title = None
        self.available_statuses = {
            'passed': ['passed', 'fixed'],
            'failed': ['failed', 'regression'],
            'skipped': ['skipped'],
            'blocked': ['blocked'],
            'custom_status2': ['in_progress']
        }
        self._steps = steps

    @property
    def version(self):
        # Version string length is limited by 250 symbols because field in
        # TestRail has type 'String'. This limitation can be removed by
        # changing field type to 'Text'
        return (self._version or '')[:250]

    @version.setter
    def version(self, value):
        self._version = value[:250]

    @property
    def status(self):
        for s in self.available_statuses.keys():
            if self._status in self.available_statuses[s]:
                return s
        logger.error('Unsupported result status: "{0}"!'.format(self._status))
        return self._status

    @status.setter
    def status(self, value):
        self._status = value

    @property
    def steps(self):
        return self._steps

    def __str__(self):
        result_dict = {
            'name': self.name,
            'group': self.group,
            'status': self.status,
            'duration': self.duration,
            'url': self.url,
            'version': self.version,
            'description': self.description,
            'comments': self.comments
        }
        return str(result_dict)
