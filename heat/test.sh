CONTR_ID=$(fuel node | grep controller | head -1 | awk '{print$1}')
scp test_heat.sh node-$CONTR_ID:~/
scp -r Templates node-$CONTR_ID:~/

ssh node-$CONTR_ID "source ~/openrc && nosetests heat_tests.py --with-xunit --xunit-file=heat_tests_report.xml"
scp node-$CONTR_ID:~/heat_tests_report.xml ~/
