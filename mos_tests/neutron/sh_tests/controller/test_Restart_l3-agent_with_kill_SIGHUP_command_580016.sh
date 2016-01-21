#!/usr/bin/env bash

. openrc

screen -S l3_SIG -d -m -- sh -c 'tailf /var/log/neutron/l3-agent.log > log_l3'
TEST_FAILED=0
echo "Get a pid of a process for l3-agent"
pid_before=$(ps -aux | grep -v root | grep neutron-l3-agent | awk '{print $2}')
echo "Pid for l3-agent process is "$pid_before
echo "Kill a process with HUP "
kill -SIGHUP $pid_before
sleep 10
echo "Check health of l3-agent"
neutron agent-list | grep 'L3 agent'
echo "Check status of a process after HUP restar"
pid_after=$(ps -aux | grep neutron-l3-agent | grep -v root | awk '{print $2}')
echo "PID after ="$pid_after
if [ $pid_before = $pid_after ]; then
    echo "PIDs are equal"
else
    echo "ERROR: pids are not equal"
    TEST_FAILED=1
fi
screen -X -S l3_SIG kill
echo "Try to find ERROR in l3 log"
cat log_l3 | grep ERROR
echo "Try to find TRACE in l3 log"
cat log_l3 | grep TRACE
echo "Try to find SIGHUP command"
cat log_l3 | grep SIGHUP
NUMBER=$(cat log_l3 | grep SIGHUP | wc -l)
rm -r log_l3
if [ $NUMBER -ne 1 ]; then
    echo "ERROR: There was no SIGHUP command or it was sent more than 1 time"
    TEST_FAILED=1
fi
if [ $TEST_FAILED == 0 ]; then
    echo "Test "$TEST_NAME" PASSED"
else
    echo "Test "$TEST_NAME" FAILED"
    exit 1
fi
