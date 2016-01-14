#!/usr/bin/env bash

rm -rf $1
git clone --branch 0.7.2 https://github.com/openstack/python-muranoclient $1
cd $1
source $VENV_PATH/bin/activate
pip install -r $1/requirements.txt
pip install -r $1/test-requirements.txt
