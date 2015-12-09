#!/bin/bash

. openrc
# Test SIGHUP signal
echo "Start testing SIGHUP signal on controller" > sighup_log
echo "
"

#
echo "__________________________________________________________________________
" >> sighup_log
screen -S l3_SIG -d -m -- sh -c 'tailf /var/log/neutron/l3-agent.log > log_l3' >> sighup_log 
if [ $1 = 'VLAN' ]; then TEST_ID='C580016'; else TEST_ID='C580017'; fi
TEST_NAME=$TEST_ID" Restart l3-agent with kill SIGHUP command"
TEST_FAILED=0
echo "Start test "$TEST_NAME >> sighup_log
echo "Get a pid of a process for l3-agent" >> sighup_log
pid_before=$(ps -aux | grep -v root | grep neutron-l3-agent | awk '{print $2}')
echo "Pid for l3-agent process is "$pid_before >> sighup_log
echo "Kill a process with HUP " >> sighup_log 
kill -SIGHUP $pid_before >> sighup_log
sleep 10
echo "Check health of l3-agent" >> sighup_log 
neutron agent-list | grep 'L3 agent' >> sighup_log
echo "Сheck status of a process after HUP restar" >> sighup_log
pid_after=$(ps -aux | grep neutron-l3-agent | grep -v root | awk '{print $2}')
echo "PID after ="$pid_after >> sighup_log
if [ $pid_before = $pid_after ]; then echo "PIDs are equal" >> sighup_log; else echo "ERROR: pids are not equal"; TEST_FAILED=1; fi 
screen -X -S l3_SIG kill
echo "Try to find ERROR in l3 log" >> sighup_log
cat log_l3 | grep ERROR >> sighup_log
echo "Try to find TRACE in l3 log" >> sighup_log
cat log_l3 | grep TRACE >> sighup_log
echo "Try to find SIGHUP command" >> sighup_log
cat log_l3 | grep SIGHUP >> sighup_log
NUMBER=$(cat log_l3 | grep SIGHUP | wc -l) >> sighup_log
if [ $NUMBER -ne 1 ]; then echo "ERROR: There was no SIGHUP command or it was sent more than 1 time" >> sighup_log; TEST_FAILED=1; fi 
if [ $TEST_FAILED = 0 ]; then echo "Test "$TEST_NAME" PASSED" >> sighup_log; else echo "Test "$TEST_NAME" FAILED" >> sighup_log; fi
rm -r log_l3


echo "__________________________________________________________________________
" >> sighup_log
screen -S DHCP_SIG -d -m -- sh -c 'tailf /var/log/neutron/dhcp-agent.log > log_dhcp' >> sighup_log
if [ $1 = 'VLAN' ]; then TEST_ID='C580018'; else TEST_ID='C580019'; fi
TEST_NAME=$TEST_ID" Restart dhcp-agent with kill SIGHUP command"
TEST_FAILED=0
echo "Start test "$TEST_NAME >> sighup_log
echo "Get a pid of a process for dhcp-agent" >> sighup_log
pid_before=$(ps -aux | grep -v root | grep neutron-dhcp-agent | awk '{print $2}')
echo "Pid for dhcp-agent process is "$pid_before >> sighup_log
echo "Kill a process with HUP " >> sighup_log
kill -SIGHUP $pid_before >> sighup_log
sleep 10
echo "Check health of dhcp-agent" >> sighup_log
neutron agent-list | grep 'DHCP agent' >> sighup_log
echo "Сheck status of a process after HUP restar" >> sighup_log
pid_after=$(ps -aux | grep neutron-dhcp-agent | grep -v root | awk '{print $2}')
echo "PID after ="$pid_after >> sighup_log
if [ $pid_before = $pid_after ]; then echo "PIDs are equal" >> sighup_log; else echo "ERROR: pids are not equal"; TEST_FAILED=1; fi
screen -X -S DHCP_SIG kill
echo "Try to find ERROR in dhcp log" >> sighup_log
cat log_dhcp | grep ERROR >> sighup_log
echo "Try to find TRACE in dhcp log" >> sighup_log
cat log_dhcp | grep TRACE >> sighup_log
echo "Try to find SIGHUP command" >> sighup_log
cat log_dhcp | grep SIGHUP >> sighup_log
NUMBER=$(cat log_dhcp | grep SIGHUP | wc -l) 
echo "Find SIGHUP "$NUMBER" times" >> sighup_log
if [ $NUMBER -ne 1 ]; then echo "ERROR: There was no SIGHUP command or it was sendt more than one time" >> sighup_log; TEST_FAILED=1; fi
if [ $TEST_FAILED = 0 ]; then echo "Test "$TEST_NAME" PASSED" >> sighup_log; else echo "Test "$TEST_NAME" FAILED" >> sighup_log; fi
rm -r log_dhcp


echo "__________________________________________________________________________
" >> sighup_log
screen -S OVS_SIG -d -m -- sh -c 'tailf /var/log/neutron/openvswitch-agent.log > log_ovs' >> sighup_log
if [ $1 = 'VLAN' ]; then TEST_ID='C580020'; else TEST_ID='C580021'; fi
TEST_NAME=$TEST_ID" Restart ovs-agent with kill SIGHUP command"
TEST_FAILED=0
echo "Start test "$TEST_NAME >> sighup_log
echo "Get a pid of a process for ovs-agent" >> sighup_log
pid_before=$(ps -aux | grep -v root | grep neutron-openvswitch-agent | awk '{print $2}')
echo "Pid for ovs-agent process is "$pid_before >> sighup_log
echo "Kill a process with HUP " >> sighup_log
kill -SIGHUP $pid_before >> sighup_log
sleep 10
echo "Check health ovs-agent" >> sighup_log
neutron agent-list | grep 'Open vSwitch agent' >> sighup_log
echo "Сheck status of a process after HUP restar" >> sighup_log
pid_after=$(ps -aux | grep  neutron-openvswitch-agent | grep -v root | awk '{print $2}')
echo "PID after ="$pid_after >> sighup_log
if [ $pid_before = $pid_after ]; then echo "PIDs are equal" >> sighup_log; else echo "ERROR: pids are not equal"; TEST_FAILED=1; fi
screen -X -S OVS_SIG kill
echo "Try to find ERROR in ovs log" >> sighup_log
cat log_ovs | grep ERROR >> sighup_log
echo "Try to find TRACE in ovs log" >> sighup_log
cat log_ovs | grep TRACE >> sighup_log
echo "Try to find SIGHUP command" >> sighup_log
cat log_ovs | grep SIGHUP >> sighup_log
NUMBER=$(cat log_ovs | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times" >> sighup_log
if [ $NUMBER -ne 1 ]; then echo "ERROR: There was no SIGHUP command or it was sendt more than one time" >> sighup_log; TEST_FAILED=1; fi
if [ $TEST_FAILED = 0 ]; then echo "Test "$TEST_NAME" PASSED" >> sighup_log; else echo "Test "$TEST_NAME" FAILED" >> sighup_log; fi
rm -r log_ovs


echo "__________________________________________________________________________
" >> sighup_log
screen -S SERVER_SIG -d -m -- sh -c 'tailf /var/log/neutron/server.log > log_server' >> sighup_log
if [ $1 = 'VLAN' ]; then TEST_ID='C580022'; else TEST_ID='C580023'; fi
TEST_NAME=$TEST_ID" Restart parent neutron-server with kill SIGHUP command"
TEST_FAILED=0
echo "Start test "$TEST_NAME >> sighup_log
echo "Get a pid of a process for neutron-server" >> sighup_log
string1=$(pstree -up | grep neutron-server | awk '{print $1}')
pid_before=$(echo $string1 | awk -F '-' '{print$3}' | awk -F '(' '{print$2}' | awk -F ',' '{print$1}')
echo "Pid for parent neutron-server process is "$pid_before >> sighup_log
echo "Kill a process with HUP " >> sighup_log
kill -SIGHUP $pid_before >> sighup_log
sleep 10
echo "Check health agents" >> sighup_log
neutron agent-list  >> sighup_log
echo "Сheck status of a process after HUP restar" >> sighup_log
string1=$(pstree -up | grep neutron-server | awk '{print $1}')
pid_after=$(echo $string1 | awk -F '-' '{print$3}' | awk -F '(' '{print$2}' | awk -F ',' '{print$1}')
#pid_after=$(ps -aux | grep  neutron-openvswitch-agent | grep -v root | awk '{print $2}')
echo "PID after ="$pid_after >> sighup_log
if [ $pid_before = $pid_after ]; then echo "PIDs are equal" >> sighup_log; else echo "ERROR: pids are not equal"; TEST_FAILED=1; fi
screen -X -S SERVER_SIG kill
echo "Try to find ERROR in server log" >> sighup_log
cat log_server | grep ERROR >> sighup_log
echo "Try to find TRACE in server log" >> sighup_log
cat log_server | grep TRACE >> sighup_log
api=$(grep 'api_workers = ' /etc/neutron/neutron.conf | grep -v '#' | awk '{print$3}')
rpc=$(grep 'rpc_workers = ' /etc/neutron/neutron.conf | grep -v '#' | awk '{print$3}')
echo "Quantity of api workers "$api >> sighup_log
echo "Quantity of rpc workers "$rpc >> sighup_log
echo "All neutron processes: " >> sighup_log
echo $(pstree -up | grep neutron-server) >> sighup_log
echo "Try to find SIGHUP command" >> sighup_log
cat log_server | grep SIGHUP >> sighup_log
NUMBER=$(cat log_server | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times" >> sighup_log
#if [ $NUMBER -ne 1 ]; then echo "ERROR: There was no SIGHUP command or it was sendt more than one time" >> sighup_log; TEST_FAILED=1; fi
if [ $TEST_FAILED = 0 ]; then echo "Test "$TEST_NAME" PASSED" >> sighup_log; else echo "Test "$TEST_NAME" FAILED" >> sighup_log; fi
rm -r log_server


echo "__________________________________________________________________________
" >> sighup_log
screen -S SERVER_SIG -d -m -- sh -c 'tailf /var/log/neutron/server.log > log_server' >> sighup_log
if [ $1 = 'VLAN' ]; then TEST_ID='C580024'; else TEST_ID='C580025'; fi
TEST_NAME=$TEST_ID" Restart child neutron-server process with kill SIGHUP command"
TEST_FAILED=0
echo "Start test "$TEST_NAME >> sighup_log
echo "Get a pid of a process for neutron-server" >> sighup_log
string1=$(pstree -up | grep neutron-server | awk '{print $1}')
pid_before=$(echo $string1 | awk -F '+' '{print$2}' | awk -F '-' '{print$3}' | awk -F '(' '{print$2}' | awk -F ')' '{print$1}')
echo "Pid for child neutron-server process is "$pid_before >> sighup_log
echo "Kill a process with HUP " >> sighup_log
kill -SIGHUP $pid_before >> sighup_log
sleep 10
echo "Check health agents" >> sighup_log
neutron agent-list  >> sighup_log
echo "Сheck status of a process after HUP restar" >> sighup_log
string1=$(pstree -up | grep neutron-server | awk '{print $1}')
pid_after=$(echo $string1 | awk -F '+' '{print$2}' | awk -F '-' '{print$3}' | awk -F '(' '{print$2}' | awk -F ')' '{print$1}')
#pid_after=$(ps -aux | grep  neutron-openvswitch-agent | grep -v root | awk '{print $2}')
echo "PID after ="$pid_after >> sighup_log
if [ $pid_before = $pid_after ]; then echo "PIDs are equal" >> sighup_log; else echo "ERROR: pids are not equal"; TEST_FAILED=1; fi
screen -X -S SERVER_SIG kill
echo "Try to find ERROR in server log" >> sighup_log
cat log_server | grep ERROR >> sighup_log
echo "Try to find TRACE in server log" >> sighup_log
cat log_server | grep TRACE >> sighup_log
api=$(grep 'api_workers = ' /etc/neutron/neutron.conf | grep -v '#' | awk '{print$3}')
rpc=$(grep 'rpc_workers = ' /etc/neutron/neutron.conf | grep -v '#' | awk '{print$3}')
echo "Quantity of api workers "$api >> sighup_log
echo "Quantity of rpc workers "$rpc >> sighup_log
echo "All neutron processes: " >> sighup_log
echo $(pstree -up | grep neutron-server) >> sighup_log
echo "Try to find SIGHUP command" >> sighup_log
cat log_server | grep SIGHUP >> sighup_log
NUMBER=$(cat log_server | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times" >> sighup_log
if [ $NUMBER -ne 1 ]; then echo "ERROR: There was no SIGHUP command or it was sendt more than one time" >> sighup_log; TEST_FAILED=1; fi
if [ $TEST_FAILED = 0 ]; then echo "Test "$TEST_NAME" PASSED" >> sighup_log; else echo "Test "$TEST_NAME" FAILED" >> sighup_log; fi
rm -r log_server


echo "__________________________________________________________________________
" >> sighup_log
screen -S META_SIG -d -m -- sh -c 'tailf /var/log/neutron/metadata-agent.log > log_metadat' >> sighup_log
if [ $1 = 'VLAN' ]; then TEST_ID='C580026'; else TEST_ID='C580027'; fi
TEST_NAME=$TEST_ID" Restart parent metada-agent with kill SIGHUP command"
TEST_FAILED=0
echo "Start test "$TEST_NAME >> sighup_log
echo "Get a pid of a process for metada-agent" >> sighup_log
string1=$(pstree -up | grep metadat | awk '{print $1}')
pid_before=$(echo $string1 | awk -F '-' '{print$3}' | awk -F '(' '{print$2}' | awk -F ',' '{print$1}')
echo "Pid for parent metada-agent process is "$pid_before >> sighup_log
echo "Kill a process with HUP " >> sighup_log
kill -SIGHUP $pid_before >> sighup_log
sleep 10
echo "Check health agents" >> sighup_log
neutron agent-list | grep "Metadata agent"  >> sighup_log
echo "Сheck status of a process after HUP restar" >> sighup_log
string1=$(pstree -up | grep metadat | awk '{print $1}')
pid_after=$(echo $string1 | awk -F '-' '{print$3}' | awk -F '(' '{print$2}' | awk -F ',' '{print$1}')
echo "PID after ="$pid_after >> sighup_log
if [ $pid_before = $pid_after ]; then echo "PIDs are equal" >> sighup_log; else echo "ERROR: pids are not equal"; TEST_FAILED=1; fi
screen -X -S META_SIG kill
echo "Try to find ERROR in metadata log" >> sighup_log
cat log_metadat | grep ERROR >> sighup_log
echo "Try to find TRACE in metadata log" >> sighup_log
cat log_metadat | grep TRACE >> sighup_log
workers=$(grep 'metadata_workers' /etc/neutron/metadata_agent.ini | awk -F '=' '{print$2}')
echo "Quantity of workers "$workers >> sighup_log
echo "All metadat processes: " >> sighup_log
echo $(pstree -up | grep metadat) >> sighup_log
echo "Try to find SIGHUP command" >> sighup_log
cat log_metadat | grep SIGHUP >> sighup_log
NUMBER=$(cat log_metadat | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times" >> sighup_log
if [ $NUMBER -ne 1 ]; then echo "ERROR: There was no SIGHUP command or it was sendt more than one time" >> sighup_log; TEST_FAILED=1; fi
if [ $TEST_FAILED = 0 ]; then echo "Test "$TEST_NAME" PASSED" >> sighup_log; else echo "Test "$TEST_NAME" FAILED" >> sighup_log; fi
rm -r log_metadat


echo "__________________________________________________________________________
" >> sighup_log
screen -S META_SIG -d -m -- sh -c 'tailf /var/log/neutron/metadata-agent.log > log_metadat' >> sighup_log
if [ $1 = 'VLAN' ]; then TEST_ID='C580028'; else TEST_ID='C580029'; fi
TEST_NAME=$TEST_ID" Restart child metada-agent with kill SIGHUP command"
TEST_FAILED=0
echo "Start test "$TEST_NAME >> sighup_log
echo "Get a pid of a process for metada-agent" >> sighup_log
string1=$(pstree -up | grep metadat | awk '{print $1}')
pid_before=$(echo $string1 | awk -F '+' '{print$2}' | awk -F '(' '{print$2}' | awk -F ')' '{print$1}')
echo "Pid for child metada-agent process is "$pid_before >> sighup_log
echo "Kill a process with HUP " >> sighup_log
kill -SIGHUP $pid_before >> sighup_log
sleep 10
echo "Check health agents" >> sighup_log
neutron agent-list | grep "Metadata agent"  >> sighup_log
echo "Сheck status of a process after HUP restar" >> sighup_log
string1=$(pstree -up | grep metadat | awk '{print $1}')
pid_after=$(echo $string1 | awk -F '+' '{print$2}' | awk -F '(' '{print$2}' | awk -F ')' '{print$1}')
echo "PID after ="$pid_after >> sighup_log
if [ $pid_before = $pid_after ]; then echo "PIDs are equal" >> sighup_log; else echo "ERROR: pids are not equal"; TEST_FAILED=1; fi
screen -X -S META_SIG kill
echo "Try to find ERROR in metadata log" >> sighup_log
cat log_metadat | grep ERROR >> sighup_log
echo "Try to find TRACE in metadata log" >> sighup_log
cat log_metadat | grep TRACE >> sighup_log
workers=$(grep 'metadata_workers' /etc/neutron/metadata_agent.ini | awk -F '=' '{print$2}')
echo "Quantity of workers "$workers >> sighup_log
echo "All metadat processes: " >> sighup_log
echo $(pstree -up | grep metadat) >> sighup_log
echo "Try to find SIGHUP command" >> sighup_log
cat log_metadat | grep SIGHUP >> sighup_log
NUMBER=$(cat log_metadat | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times" >> sighup_log
if [ $NUMBER -ne 1 ]; then echo "ERROR: There was no SIGHUP command or it was sendt more than one time" >> sighup_log; TEST_FAILED=1; fi
if [ $TEST_FAILED = 0 ]; then echo "Test "$TEST_NAME" PASSED" >> sighup_log; else echo "Test "$TEST_NAME" FAILED" >> sighup_log; fi
rm -r log_metadat


exit 0
