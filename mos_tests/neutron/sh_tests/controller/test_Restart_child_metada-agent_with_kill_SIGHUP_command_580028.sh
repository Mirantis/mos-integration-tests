#!/usr/bin/env bash

. openrc

LOG_FILE=$(find /var/log/neutron -name *metadata-agent*log)
LOG_LENGTH=$(cat $LOG_FILE | wc -l)

read_log () {
    tail -n +$LOG_LENGTH $LOG_FILE
}

TEST_FAILED=0
echo "Get a pid of a process for metada-agent"
echo $(pstree -up | grep metadat)
pid_before=$(pstree -up | grep metadat | awk '{print $1}' | awk -F'[^0-9]*' '{print $3}')
echo "Pid for child metada-agent process is "$pid_before

echo "Kill a process with HUP "
kill -SIGHUP $pid_before
sleep 10

echo "Check health agents"
neutron agent-list | grep "Metadata agent"

echo "Check status of a process after HUP restar"
pid_after=$(pstree -up | grep metadat | awk '{print $1}' | awk -F'[^0-9]*' '{print $3}')
echo "PID after ="$pid_after
if [ $pid_before = $pid_after ]; then
    echo "PIDs are equal"
else
    echo "ERROR: pids are not equal"
    TEST_FAILED=1
fi

echo "Try to find ERROR in metadata log"
read_log | grep ERROR

echo "Try to find TRACE in metadata log"
read_log | grep TRACE

workers=$(grep 'metadata_workers' /etc/neutron/metadata_agent.ini | awk -F '=' '{print$2}')
echo "Quantity of workers "$workers
echo "All metadat processes: "
echo $(pstree -up | grep metadat)
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
