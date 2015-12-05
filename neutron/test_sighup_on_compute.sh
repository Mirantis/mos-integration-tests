#!/bin/bash
# Test SIGHUP signal
echo "Start testing SIGHUP signal on controller" > sighup_log_on_compute
echo "
" >>sighup_log_on_compute 

#
echo $1 >> sighup_log_on_compute

echo "__________________________________________________________________________
" >> sighup_log_on_compute
screen -S l3_SIG -d -m -- sh -c 'tailf /var/log/neutron/neutron-l3-agent.log > log_l3' >> sighup_log_on_compute 
if [ $1 = 'VLAN' ]; then TEST_ID='C580030'; else TEST_ID='C580031'; fi
TEST_NAME=$TEST_ID" [ DVR] Restart l3-agent with kill SIGHUP command"
TEST_FAILED=0
echo "Start test "$TEST_NAME >> sighup_log_on_compute
echo "Get a pid of a process for l3-agent" >> sighup_log_on_compute
pid_before=$(ps -aux | grep -v root | grep neutron-l3-agent | awk '{print $2}')
echo "Pid for l3-agent process is "$pid_before >> sighup_log_on_compute
echo "Kill a process with HUP " >> sighup_log_on_compute 
kill -SIGHUP $pid_before >> sighup_log_on_compute
sleep 10
echo "Check health of l3-agent" >> sighup_log_on_compute 
neutron agent-list | grep 'L3 agent' >> sighup_log_on_compute
echo "Сheck status of a process after HUP restar" >> sighup_log_on_compute
pid_after=$(ps -aux | grep neutron-l3-agent | grep -v root | awk '{print $2}')
echo "PID after ="$pid_after >> sighup_log_on_compute
if [ $pid_before = $pid_after ]; then echo "PIDs are equal" >> sighup_log_on_compute; else echo "ERROR: pids are not equal"; TEST_FAILED=1; fi 
screen -X -S l3_SIG kill
echo "Try to find ERROR in l3 log" >> sighup_log_on_compute
cat log_l3 | grep ERROR >> sighup_log_on_compute
echo "Try to find TRACE in l3 log" >> sighup_log_on_compute
cat log_l3 | grep TRACE >> sighup_log_on_compute
echo "Try to find SIGHUP command" >> sighup_log_on_compute
cat log_l3 | grep SIGHUP >> sighup_log_on_compute
NUMBER=$(cat log_l3 | grep SIGHUP | wc -l) >> sighup_log_on_compute
if [ $NUMBER -ne 1 ]; then echo "ERROR: There was no SIGHUP command or it was sent more than 1 time" >> sighup_log_on_compute; TEST_FAILED=1; fi 
if [ $TEST_FAILED = 0 ]; then echo "Test "$TEST_NAME" PASSED" >> sighup_log_on_compute; else echo "Test "$TEST_NAME" FAILED" >> sighup_log_on_compute; fi
rm -r log_l3

echo "__________________________________________________________________________
" >> sighup_log_on_compute
screen -S META_SIG -d -m -- sh -c 'tailf /var/log/neutron/neutron-metadata-agent.log > log_metadat' >> sighup_log_on_compute
if [ $1 = 'VLAN' ]; then TEST_ID='C580032'; else TEST_ID='C580033'; fi
TEST_NAME=$TEST_ID" [DVR] Restart parent metada-agent with kill SIGHUP command"
TEST_FAILED=0
echo "Start test "$TEST_NAME >> sighup_log_on_compute
echo "Get a pid of a process for metada-agent" >> sighup_log_on_compute
string1=$(pstree -up | grep metadat | awk '{print $1}')
pid_before=$(echo $string1 | awk -F '-' '{print$3}' | awk -F '(' '{print$2}' | awk -F ',' '{print$1}')
echo "Pid for parent metada-agent process is "$pid_before >> sighup_log_on_compute
echo "Kill a process with HUP " >> sighup_log_on_compute
kill -SIGHUP $pid_before >> sighup_log_on_compute
sleep 10
echo "Check health agents" >> sighup_log_on_compute
neutron agent-list | grep "Metadata agent"  >> sighup_log_on_compute
echo "Сheck status of a process after HUP restar" >> sighup_log_on_compute
string1=$(pstree -up | grep metadat | awk '{print $1}')
pid_after=$(echo $string1 | awk -F '-' '{print$3}' | awk -F '(' '{print$2}' | awk -F ',' '{print$1}')
echo "PID after ="$pid_after >> sighup_log_on_compute
if [ $pid_before = $pid_after ]; then echo "PIDs are equal" >> sighup_log_on_compute; else echo "ERROR: pids are not equal" >> sighup_log_on_compute; TEST_FAILED=1; fi
screen -X -S META_SIG kill
echo "Try to find ERROR in metadata log" >> sighup_log_on_compute
cat log_metadat | grep ERROR >> sighup_log_on_compute
echo "Try to find TRACE in metadata log" >> sighup_log_on_compute
cat log_metadat | grep TRACE >> sighup_log_on_compute
workers=$(grep 'metadata_workers' /etc/neutron/metadata_agent.ini | awk -F '=' '{print$2}')
echo "Quantity of workers "$workers >> sighup_log_on_compute
echo "All metadat processes: " >> sighup_log_on_compute
echo $(pstree -up | grep metadat) >> sighup_log_on_compute
echo "Try to find SIGHUP command" >> sighup_log_on_compute
cat log_metadat | grep SIGHUP >> sighup_log_on_compute
NUMBER=$(cat log_metadat | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times" >> sighup_log_on_compute
if [ $NUMBER -ne 1 ]; then echo "ERROR: There was no SIGHUP command or it was sendt more than one time" >> sighup_log_on_compute; TEST_FAILED=1; fi
if [ $TEST_FAILED = 0 ]; then echo "Test "$TEST_NAME" PASSED" >> sighup_log_on_compute; else echo "Test "$TEST_NAME" FAILED" >> sighup_log_on_compute; fi
rm -r log_metadat


echo "__________________________________________________________________________
" >> sighup_log_on_compute
screen -S META_SIG -d -m -- sh -c 'tailf /var/log/neutron/neutron-metadata-agent.log > log_metadat' >> sighup_log_on_compute
if [ $1 = 'VLAN' ]; then TEST_ID='C580034'; else TEST_ID='C580035'; fi
TEST_NAME=$TEST_ID" [DVR] Restart child metada-agent with kill SIGHUP command"
TEST_FAILED=0
echo "Start test "$TEST_NAME >> sighup_log_on_compute
echo "Get a pid of a process for metada-agent" >> sighup_log_on_compute
string1=$(pstree -up | grep metadat | awk '{print $1}')
pid_before=$(echo $string1 | awk -F '(' '{print$3}' | awk -F ')' '{print$1}')
echo "Pid for child metada-agent process is "$pid_before >> sighup_log_on_compute
echo "Kill a process with HUP " >> sighup_log_on_compute
kill -SIGHUP $pid_before >> sighup_log_on_compute
sleep 10
echo "Check health agents" >> sighup_log_on_compute
neutron agent-list | grep "Metadata agent"  >> sighup_log_on_compute
echo "Сheck status of a process after HUP restar" >> sighup_log_on_compute
string1=$(pstree -up | grep metadat | awk '{print $1}')
pid_after=$(echo $string1 | awk -F '(' '{print$3}' | awk -F ')' '{print$1}')
echo "PID after ="$pid_after >> sighup_log_on_compute
if [ $pid_before = $pid_after ]; then echo "PIDs are equal" >> sighup_log_on_compute; else echo "ERROR: pids are not equal"; TEST_FAILED=1; fi
screen -X -S META_SIG kill
echo "Try to find ERROR in metadata log" >> sighup_log_on_compute
cat log_metadat | grep ERROR >> sighup_log_on_compute
echo "Try to find TRACE in metadata log" >> sighup_log_on_compute
cat log_metadat | grep TRACE >> sighup_log_on_compute
workers=$(grep 'metadata_workers' /etc/neutron/metadata_agent.ini | awk -F '=' '{print$2}')
echo "Quantity of workers "$workers >> sighup_log_on_compute
echo "All metadat processes: " >> sighup_log_on_compute
echo $(pstree -up | grep metadat) >> sighup_log_on_compute
echo "Try to find SIGHUP command" >> sighup_log_on_compute
cat log_metadat | grep SIGHUP >> sighup_log_on_compute
NUMBER=$(cat log_metadat | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times" >> sighup_log_on_compute
if [ $NUMBER -ne 1 ]; then echo "ERROR: There was no SIGHUP command or it was sendt more than one time" >> sighup_log_on_compute; TEST_FAILED=1; fi
if [ $TEST_FAILED = 0 ]; then echo "Test "$TEST_NAME" PASSED" >> sighup_log_on_compute; else echo "Test "$TEST_NAME" FAILED" >> sighup_log_on_compute; fi
rm -r log_metadat


exit 0

