#!/bin/bash

#NEUTRON_TYPE_SEGMENTATION=global parametr
NEUTRON_TYPE_SEGMENTATION='VxLAN'

#DVR_ENV - if env with DVR - true, else - false
DVR_ENV=false

CONTR_ID=$(fuel node | grep controller | head -1 | awk '{print$1}')
scp test_sighup_on_controller.sh node-$CONTR_ID:~/
command="bash test_sighup_on_controller.sh $NEUTRON_TYPE_SEGMENTATION"
ssh node-$CONTR_ID "$command"
ssh node-$CONTR_ID "$command"
scp node-$CONTR_ID:~/sighup_log ~/

if [ $DVR_ENV = true ]; then
COMP_ID=$(fuel node | grep compute | head -1 | awk '{print$1}')
scp test_sighup_on_compute.sh node-$COMP_ID:~/
#ssh node-$COMP_ID 'bash test_sighup_on_compute.sh'
command="bash test_sighup_on_compute.sh $NEUTRON_TYPE_SEGMENTATION"
ssh node-$COMP_ID "$command"
ssh node-$COMP_ID "$command"
scp node-$COMP_ID:~/sighup_log_on_compute ~/
fi

echo "PASSED"
cat sighup_log | grep PASSED
if [ $DVR_ENV = true ]; then cat sighup_log_on_compute | grep PASSED; fi
echo "FAILED"
cat sighup_log | grep FAILED
if [ $DVR_ENV = true ]; then cat sighup_log_on_compute | grep FAILED; fi
