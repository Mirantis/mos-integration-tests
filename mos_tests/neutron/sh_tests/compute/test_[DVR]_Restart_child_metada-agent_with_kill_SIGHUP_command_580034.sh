#!/usr/bin/env bash

screen -S META_SIG -d -m -- sh -c 'tailf /var/log/neutron/neutron-metadata-agent.log > log_metadat'
TEST_FAILED=0
echo "Get a pid of a process for metada-agent"
pid_before=$(pstree -up | grep metadat | awk '{print $1}'| awk -F'[^0-9]*' '{print $3}')
echo "Pid for child metada-agent process is "$pid_before
echo "Kill a process with HUP "
kill -SIGHUP $pid_before
sleep 10
echo "Check health agents"
neutron agent-list | grep "Metadata agent"
echo "Check status of a process after HUP restar"
pid_after=$(pstree -up | grep metadat | awk '{print $1}'| awk -F'[^0-9]*' '{print $3}')
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
rm -r log_metadat
if [ $NUMBER -ne 1 ]; then
    echo "ERROR: There was no SIGHUP command or it was sendt more than one time";
    TEST_FAILED=1
fi
if [ $TEST_FAILED == 0 ]; then
    echo "Test "$TEST_NAME" PASSED"
else
    echo "Test "$TEST_NAME" FAILED"
    exit 1
fi
