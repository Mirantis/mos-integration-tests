#!/usr/bin/env bash

. openrc

screen -S META_SIG -d -m -- sh -c 'tailf /var/log/neutron/metadata-agent.log > log_metadat'
TEST_FAILED=0
echo "Get a pid of a process for metada-agent"
pid_before=$( pstree -up | grep neutron-metadat | awk '{print $1}' | awk -F'[^0-9]*' '{print $2}')
echo "Pid for parent metada-agent process is "$pid_before
echo "Kill a process with HUP "
kill -SIGHUP $pid_before
sleep 10
echo "Check health agents"
neutron agent-list | grep "Metadata agent"
echo "Check status of a process after HUP restar"
pid_after=$( pstree -up | grep neutron-metadat | awk '{print $1}' | awk -F'[^0-9]*' '{print $2}')
echo "PID after ="$pid_after
if [ $pid_before = $pid_after ]; then
    echo "PIDs are equal"
else
    echo "ERROR: pids are not equal"
    TEST_FAILED=1
fi
screen -X -S META_SIG kill
echo "Try to find ERROR in metadata log"
cat log_metadat | grep ERROR
echo "Try to find TRACE in metadata log"
cat log_metadat | grep TRACE
workers=$(grep 'metadata_workers' /etc/neutron/metadata_agent.ini | awk -F '=' '{print$2}')
echo "Quantity of workers "$workers
echo "All metadat processes: "
echo $(pstree -up | grep metadat)
echo "Try to find SIGHUP command"
cat log_metadat | grep SIGHUP
NUMBER=$(cat log_metadat | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times"
if [ $NUMBER -ne $((workers + 1)) ]; then
    echo "ERROR: Expected SIGHUP command was sent $workers + 1 times"
    TEST_FAILED=1
fi
rm -r log_metadat


if [ $TEST_FAILED == 0 ]; then
    echo "Test "$TEST_NAME" PASSED"
else
    echo "Test "$TEST_NAME" FAILED"
    exit 1
fi
