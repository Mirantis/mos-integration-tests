import logging
import pytest

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption("--log-fixtures",
                     '-L',
                     action="store_true",
                     dest='log_fixtures',
                     help="Log fixtures setup/teardown")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    """Mark start test in log"""
    logger.info('<#### {2} ({0}:{1}) ####>'.format(*item.location))
    yield


def _log_fixture(fixturedef, action, config):
    if fixturedef.has_location and config.getoption('log_fixtures'):
        logger.debug('{action} {fixturedef!r} '
                     '({code.co_filename}:{code.co_firstlineno})'.format(
                         action=action,
                         fixturedef=fixturedef,
                         code=fixturedef.func.func_code))


def pytest_fixture_setup(fixturedef, request):
    _log_fixture(fixturedef, "Setup", fixturedef._fixturemanager.config)


def pytest_fixture_post_finalizer(fixturedef):
    _log_fixture(fixturedef, "Finalized", fixturedef._fixturemanager.config)
