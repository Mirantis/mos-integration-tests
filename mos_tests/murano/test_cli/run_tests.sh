#!/usr/bin/env bash

set -ex

if [[ -f ~/.ssh/known_hosts ]]; then
    mv ~/.ssh/known_hosts{,.backup}
fi
KEY_FILE=./fuel_key
FUEL_MASTER_IP=${1:?"Fuel master IP expected as first argument"}
CONTROLLER_IP=$(sshpass -pr00tme ssh -o 'StrictHostKeyChecking no' root@$FUEL_MASTER_IP 'fuel node | grep controller | head -n1 | awk "{ print \$9 }"')
sshpass -pr00tme scp -o 'StrictHostKeyChecking no' root@$FUEL_MASTER_IP:.ssh/id_rsa $KEY_FILE

ssh -i $KEY_FILE -o 'StrictHostKeyChecking no' root@$CONTROLLER_IP << EOF

    set -ex

    source openrc
    apt-get install -y git virtualenv libffi-dev libssl-dev
    rm -rf python-muranoclient
    MURANO_VERSION=$(murano --version)
    git clone --branch $MURANO_VERSION https://github.com/openstack/python-muranoclient

    cd python-muranoclient
    virtualenv .venv
    source .venv/bin/activate
    MURANO_BIN=$(which murano)
    export OS_MURANOCLIENT_EXEC_DIR=$(dirname $MURANO_BIN)
    pip install -r requirements.txt -r test-requirements.txt pytest
    py.test muranoclient/tests/functional -v --junit-xml=report.xml

EOF

scp -i $KEY_FILE -o 'StrictHostKeyChecking no' root@$CONTROLLER_IP:python-muranoclient/report.xml .
rm $KEY_FILE
if [[ -f ~/.ssh/known_hosts.backup ]]; then
    mv ~/.ssh/known_hosts{.backup,}
fi
