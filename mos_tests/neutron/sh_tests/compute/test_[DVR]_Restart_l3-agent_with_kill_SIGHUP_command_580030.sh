#!/usr/bin/env bash

LOG_FILE=$(find /var/log/neutron -name *l3-agent*log)
LOG_LENGTH=$(cat $LOG_FILE | wc -l)

read_log () {
    tail -n +$LOG_LENGTH $LOG_FILE
}

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

echo "Try to find ERROR in l3 log"
read_log | grep ERROR

echo "Try to find TRACE in l3 log"
read_log | grep TRACE

echo "Try to find SIGHUP command"
read_log | grep SIGHUP
NUMBER=$(read_log | grep SIGHUP | wc -l)
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
