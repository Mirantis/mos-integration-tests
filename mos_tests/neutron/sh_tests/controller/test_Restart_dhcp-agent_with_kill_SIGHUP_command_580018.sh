#!/usr/bin/env bash

. openrc

LOG_FILE=$(find /var/log/neutron -name *dhcp-agent*log)
LOG_LENGTH=$(cat $LOG_FILE | wc -l)

read_log () {
    tail -n +$LOG_LENGTH $LOG_FILE
}

TEST_FAILED=0

echo "Get a pid of a process for dhcp-agent"
PID_BEFORE=$(ps -aux | grep -v root | grep neutron-dhcp-agent | awk '{print $2}')
echo "Pid for dhcp-agent process is "$PID_BEFORE

echo "Kill a process with HUP "
kill -SIGHUP $PID_BEFORE
sleep 10

echo "Check health of dhcp-agent"
neutron agent-list | grep 'DHCP agent'

echo "Check status of a process after HUP restar"
PID_AFTER=$(ps -aux | grep neutron-dhcp-agent | grep -v root | awk '{print $2}')
echo "PID after ="$PID_AFTER
if [ $PID_BEFORE = $PID_AFTER ]; then
    echo "PIDs are equal"
else
    echo "ERROR: pids are not equal"
    TEST_FAILED=1
fi

echo "Try to find ERROR in dhcp log"
read_log | grep ERROR

echo "Try to find TRACE in dhcp log"
read_log | grep TRACE

echo "Try to find SIGHUP command"
read_log | grep SIGHUP

SIGHUP_COUNT=$(read_log | grep SIGHUP | wc -l)
echo "Find SIGHUP "$SIGHUP_COUNT" times"
if [ $SIGHUP_COUNT -ne 1 ]; then
    echo "ERROR: There was no SIGHUP command or it was sent more than one time"
    TEST_FAILED=1
fi

if [ $TEST_FAILED == 0 ]; then
    echo "Test "$TEST_NAME" PASSED"
else
    read_log
    echo "Test "$TEST_NAME" FAILED"
    exit 1
fi
