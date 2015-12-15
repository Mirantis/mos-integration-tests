# Introduction

Neutron python tests

## System requirements

`sudo apt-get install tshark`

## Running

### Arguments

* `-I FUEL_IP, --fuel-ip=FUEL_IP`      Fuel master server ip address
* `-E ENV, --env=ENV`                  Fuel devops env name
* `-S SNAPSHOT, --snapshot=SNAPSHOT`   Fuel devops snapshot name


### Local

For run test on local machine just execute from this project root:

`$ py.test mos_tests/neutron`
`$ py.test test_l3_agent.py/test_l3_agent.py::TestL3Agent::test_ban_one_l3_agent # check this ability
`$ py.test mos_tests/neutron -k test_ban_one_dhcp_agent # run a single test`


### Remote


To execute tests on remote execute next from this project root:

`$ py.test -d --tx ssh=mirantis-lab//python=~/fuel-devops-venv/bin/python \
    --rsyncdir . mos_tests/neutron`

where:

* `mirantis-lab` - remote server
* `~/fuel-devops-venv` - virtualenv path on remote server

**NOTE**

You should create virtualenv on remote server and install all requirements
(from requirements.txt)

