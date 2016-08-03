#!/usr/bin/env bash

. openrc

LOG_FILE=$(find /var/log/neutron -name *openvswitch-agent*log)
LOG_LENGTH=$(cat $LOG_FILE | wc -l)

read_log () {
    tail -n +$LOG_LENGTH $LOG_FILE
}

TEST_FAILED=0

echo "Get a pid of a process for ovs-agent"
pid_before=$(ps -aux | grep -v root | grep neutron-openvswitch-agent | awk '{print $2}')
echo "Pid for ovs-agent process is "$pid_before

echo "Kill a process with HUP "
kill -SIGHUP $pid_before
sleep 10

echo "Check health ovs-agent"
neutron agent-list | grep 'Open vSwitch agent'

echo "Check status of a process after HUP restar"
pid_after=$(ps -aux | grep  neutron-openvswitch-agent | grep -v root | awk '{print $2}')
echo "PID after ="$pid_after
if [ $pid_before = $pid_after ]; then
    echo "PIDs are equal"
else
    echo "ERROR: pids are not equal"
    TEST_FAILED=1
fi

echo "Try to find ERROR in ovs log"
read_log | grep ERROR

echo "Try to find TRACE in ovs log"
read_log | grep TRACE

echo "Try to find SIGHUP command"
read_log | grep SIGHUP
NUMBER=$(read_log | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times"
if [ $NUMBER -ne 1 ]; then
    echo "ERROR: There was no SIGHUP command or it was sent more than one time"
    TEST_FAILED=1
fi

if [ $TEST_FAILED == 0 ]; then
    echo "Test "$TEST_NAME" PASSED"
else
    echo "Test "$TEST_NAME" FAILED"
    exit 1
fi
