apt-get install -y git libffi-dev libssl-dev python-tox
source openrc
git clone --branch 0.7.1 https://github.com/openstack/python-muranoclient
cd python-muranoclient
tox -e functional -- --with-xunit
