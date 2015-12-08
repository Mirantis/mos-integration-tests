#!/usr/bin/env bash
CONTR_ID=$(fuel node | grep controller | head -1 | awk '{print$1}')
scp heat_tests.py node-$CONTR_ID:~/

ssh node-$CONTR_ID "source ~/openrc && nosetests heat_tests.py --with-xunit --xunit-file=heat_tests_report.xml"
scp node-$CONTR_ID:~/heat_tests_report.xml ~/
echo -e "For test results see:\n\t# less ~/heat_tests_report.xml\n\t# xmllint --format ~/heat_tests_report.xml"
