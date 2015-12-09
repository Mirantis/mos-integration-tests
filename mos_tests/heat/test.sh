#!/usr/bin/env bash
CONTR_ID=$(fuel node | grep controller | head -1 | awk '{print$1}')
scp -rp ./../../mos_tests/ node-$CONTR_ID:~/

ssh node-$CONTR_ID "export PYTHONPATH=.:$PYTHONPATH && source ~/openrc && nosetests mos_tests/heat/heat_tests.py --with-xunit --xunit-file=heat_tests_report.xml"
scp node-$CONTR_ID:~/heat_tests_report.xml ~/
echo -e "For test results see:\n\t# less ~/heat_tests_report.xml\n\t# xmllint --format ~/heat_tests_report.xml"
