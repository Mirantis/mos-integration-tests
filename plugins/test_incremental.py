
pytest_plugins = "pytester"


def test_xfail_after_fail(testdir):
    testdir.makepyfile("""
        import pytest
        pytest_plugins = "plugins.incremental"

        @pytest.mark.incremental
        class TestSmth(object):

            def test_a(self):
                assert False

            def test_b(self):
                assert True
    """)
    result = testdir.runpytest("--verbose")
    result.stdout.fnmatch_lines("*::test_b xfail")


def test_class_parametrization(testdir):
    testdir.makepyfile("""
        import pytest
        pytest_plugins = "plugins.incremental"

        @pytest.mark.incremental
        class TestSmth(object):

            @pytest.fixture(scope='class', params=['bar', 'baz'])
            def foo(self, request):
                return request.param

            def test_a(self, foo):
                assert foo == 'baz'

            def test_b(self, foo):
                assert True
    """)
    result = testdir.runpytest("--verbose")
    result.stdout.fnmatch_lines([
        "*::test_b?bar? xfail",
        "*::test_b?baz? PASSED",
    ])


def test_class_indirect_parametrization(testdir):
    testdir.makepyfile("""
        import pytest
        pytest_plugins = "plugins.incremental"

        @pytest.mark.incremental
        class TestSmth(object):

            @classmethod
            @pytest.fixture(scope='class', params=['bar', 'baz'], autouse=True)
            def foo(cls, request):
                cls.foo_val = request.param

            def test_a(self):
                assert self.foo_val == 'baz'

            def test_b(self):
                assert True
    """)
    result = testdir.runpytest("--verbose")
    result.stdout.fnmatch_lines([
        "*::test_b?bar? xfail",
        "*::test_b?baz? PASSED",
    ])


def test_parametrized_fixture_error(testdir):
    testdir.makepyfile("""
        import pytest
        pytest_plugins = "plugins.incremental"

        @pytest.mark.incremental
        class TestSmth(object):

            @classmethod
            @pytest.fixture(scope='class', params=['bar', 'baz'], autouse=True)
            def foo(cls, request):
                assert request.param == 'baz'

            def test_a(self):
                assert True

            def test_b(self):
                assert True
    """)
    result = testdir.runpytest("--verbose")
    result.stdout.fnmatch_lines([
        "*::test_b?bar? xfail",
        "*::test_b?baz? PASSED",
    ])


def test_external_fixture_error(testdir):
    testdir.makeconftest("""
        import pytest

        @pytest.fixture
        def broken():
            raise Exception()
    """)
    testdir.makepyfile("""
        import pytest
        pytest_plugins = "plugins.incremental"

        @pytest.mark.incremental
        class TestSmth(object):

            @classmethod
            @pytest.fixture(scope='class', params=['bar', 'baz'], autouse=True)
            def foo(cls, request):
                return request.param

            def test_a(self, broken):
                assert True

            def test_b(self, broken):
                assert True
    """)
    result = testdir.runpytest("--verbose")
    result.stdout.fnmatch_lines([
        "*::test_b?bar? xfail",
        "*::test_b?baz? xfail",
    ])
