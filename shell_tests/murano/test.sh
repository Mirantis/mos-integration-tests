CONTR_ID=$(fuel node | grep controller | head -1 | awk '{print$1}')
scp test_murano_cli.sh node-$CONTR_ID:~/

ssh node-$CONTR_ID "bash test_murano_cli.sh"
scp node-$CONTR_ID:~/murano_cli_tests_log ~/
