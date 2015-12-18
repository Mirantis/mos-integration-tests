#!/usr/bin/env bash
CONTR_ID=$(fuel node | grep controller | head -1 | awk '{print$1}')
scp -rp ./../../mos_tests/ node-$CONTR_ID:~/

# Launch of Windows Compatibility tests
ssh node-$CONTR_ID "export PYTHONPATH=.:$PYTHONPATH && source ~/openrc && nosetests mos_tests/nova/windows_compatibility_tests.py --with-xunit --xunit-file=windows_compatibility_tests_report.xml"
scp node-$CONTR_ID:~/windows_compatibility_tests_report.xml ~/
# Launch of Nova tests
ssh node-$CONTR_ID "export PYTHONPATH=.:$PYTHONPATH && source ~/openrc && nosetests mos_tests/nova/nova_tests.py --with-xunit --xunit-file=nova_tests_report.xml"
scp node-$CONTR_ID:~/nova_tests_report.xml ~/

# CleanUp
ssh node-$CONTR_ID "\rm -rf ~/mos_tests"

# Show command(s) to view results
# For nova tests
echo -e "For Nova test results see:\n\t# less ~/nova_tests_report.xml\n\t# xmllint --format ~/nova_tests_report.xml"
# For windows compatibility tests
echo -e "For Windows Compatibility test results see:\n\t# less ~/windows_compatibility_tests_report.xml\n\t# xmllint --format ~/windows_compatibility_tests_report.xml"
