#!/usr/bin/env bash
CONTR_ID=$(fuel node | grep controller | head -1 | awk '{print$1}')
scp -rp ./../../mos_tests/ node-$CONTR_ID:~/

ssh node-$CONTR_ID "export PYTHONPATH=.:$PYTHONPATH && source ~/openrc && nosetests mos_tests/nova/windows_compatibility_tests.py --with-xunit --xunit-file=windows_compatibility_tests_report.xml"
scp node-$CONTR_ID:~/windows_compatibility_tests_report.xml ~/

ssh node-$CONTR_ID "export PYTHONPATH=.:$PYTHONPATH && source ~/openrc && nosetests mos_tests/nova/nova_tests.py --with-xunit --xunit-file=nova_tests_report.xml"
scp node-$CONTR_ID:~/nova_tests_report.xml ~/

# CleanUp
ssh node-$CONTR_ID "\rm -rf ~/mos_tests"

# Show command to view results
echo -e "For test results see:\n\t# less ~/nova_tests_report.xml\n\t# xmllint --format ~/nova_tests_report.xml"
