## Introduction

This repository contains automated tests for Mirantis OpenStack.


### Packages requirements

```bash
$ sudo apt-get install libpq-dev \
    python-dev \
    libffi-dev \
    libvirt-dev
```

### Python requirements

    $ virtualenv venv
    $ source venv/bin/activate
    $ pip install -U pip
    $ pip install tox


### Running tests with tox

To run tests you need to deploy some cloud with MOS, then install `tox` and run on server:

    $ tox -e <test group> -- -E <devops env name> -S <devops snapshot name>

**IMPORTANT:** some tests will fail, if they ran from root user.

### Available test groups

* neutron
* glance
* murano-cli
* murano
* ceilometer
* ironic


### Running with py.test directly

To launch tests with py.test directly:

    $ pip install -r requirements.txt

Next you can run tests:

    $ py.test mos_tests/<path_to_tests> -E <devops env name> -S <devops snapshot name>


### Py.test arguments

This arguments can be used with tox or with py.test directly. In first case all arguments should be passed after `--`

* `-s` don't capture stdout, stderr. This parameter required, if you want to use debugger like `import pdb; pdb.set_trace()`
* `-k <some filter>` filter tests to run by test name, class name, file name, etc.
* `--collectonly` - show list of tests, with all filters, which py.test will execute. May be helpful to check that `-k` parameter is passed correctly.
* `-ra` print extended information about failed and skipped tests. May be helpful, if you want to know, why some tests was skipped
* `-x` exit after first fail
* `-I <fuel master ip>` If this parameter passed, and `-S` is not passed - py.test will non do revert before tests. May be helpful during debugging or writing new tests.
* `-v` be more verbose (show test name instead of dots)
* `--help` - py.test help. Contains other possible arguments


### Troubleshooting

Some times, during installing python requirements, you can see next error:

    Traceback (most recent call last):
    File "/home/sandriichenko/venv/bin/pip", line 11, in <module>
    sys.exit(main())
    File "/home/sandriichenko/venv/local/lib/python2.7/site-packages/pip/_init_.py", line 215, in main
    locale.setlocale(locale.LC_ALL, '')
    File "/home/sandriichenko/venv/lib/python2.7/locale.py", line 579, in setlocale
    return _setlocale(category, locale)
    locale.Error: unsupported locale setting

To fix it, execute next commands:

    export LANGUAGE=en_US.UTF-8
    export LANG=en_US.UTF-8
    export LC_ALL=en_US.UTF-8
    locale-gen en_US.UTF-8
    sudo dpkg-reconfigure locales

## Documentation

To build docs:

    $ cd doc && make html
