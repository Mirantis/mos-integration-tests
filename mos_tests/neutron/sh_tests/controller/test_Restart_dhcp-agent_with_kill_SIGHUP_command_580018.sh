#!/usr/bin/env bash

. openrc

screen -S DHCP_SIG -d -m -- sh -c 'tailf /var/log/neutron/dhcp-agent.log > log_dhcp'
TEST_FAILED=0
echo "Get a pid of a process for dhcp-agent"
pid_before=$(ps -aux | grep -v root | grep neutron-dhcp-agent | awk '{print $2}')
echo "Pid for dhcp-agent process is "$pid_before
echo "Kill a process with HUP "
kill -SIGHUP $pid_before
sleep 10
echo "Check health of dhcp-agent"
neutron agent-list | grep 'DHCP agent'
echo "Check status of a process after HUP restar"
pid_after=$(ps -aux | grep neutron-dhcp-agent | grep -v root | awk '{print $2}')
echo "PID after ="$pid_after
if [ $pid_before = $pid_after ]; then
    echo "PIDs are equal"
else
    echo "ERROR: pids are not equal"
    TEST_FAILED=1
fi
screen -X -S DHCP_SIG kill
echo "Try to find ERROR in dhcp log"
cat log_dhcp | grep ERROR
echo "Try to find TRACE in dhcp log"
cat log_dhcp | grep TRACE
echo "Try to find SIGHUP command"
cat log_dhcp | grep SIGHUP
NUMBER=$(cat log_dhcp | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times"
if [ $NUMBER -ne 1 ]; then
    echo "ERROR: There was no SIGHUP command or it was sent more than one time"
    TEST_FAILED=1
fi
rm -r log_dhcp

if [ $TEST_FAILED == 0 ]; then
    echo "Test "$TEST_NAME" PASSED"
else
    echo "Test "$TEST_NAME" FAILED"
    exit 1
fi
