#!/usr/bin/env bash

. openrc

LOG_FILE=$(find /var/log/neutron -name *server*log)
LOG_LENGTH=$(cat $LOG_FILE | wc -l)

read_log () {
    tail -n +$LOG_LENGTH $LOG_FILE
}

TEST_FAILED=0

echo "Get a pid of a process for neutron-server"
echo $(pstree -up | grep neutron-server)
pid_before=$(pstree -up | grep neutron-server | awk '{print $1}' | awk -F'[^0-9]*' '{print $2}')
echo "Pid for parent neutron-server process is "$pid_before

echo "Kill a process with HUP "
kill -SIGHUP $pid_before
sleep 10

echo "Check health agents"
neutron agent-list

echo "Check status of a process after HUP restar"
pid_after=$(pstree -up | grep neutron-server | awk '{print $1}' | awk -F'[^0-9]*' '{print $2}')
echo "PID after ="$pid_after
if [ $pid_before = $pid_after ]; then
    echo "PIDs are equal"
else
    echo "ERROR: pids are not equal"
    TEST_FAILED=1
fi

echo "Try to find ERROR in server log"
read_log | grep ERROR

echo "Try to find TRACE in server log"
read_log | grep TRACE
api=$(grep 'api_workers = ' /etc/neutron/neutron.conf | grep -v '#' | awk '{print$3}')
rpc=$(grep 'rpc_workers = ' /etc/neutron/neutron.conf | grep -v '#' | awk '{print$3}')
echo "Quantity of api workers "$api
echo "Quantity of rpc workers "$rpc
echo "All neutron processes: "
echo $(pstree -up | grep neutron-server)

echo "Try to find SIGHUP command"
read_log | grep SIGHUP
NUMBER=$(read_log | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times"

if [ $TEST_FAILED == 0 ]; then
    echo "Test "$TEST_NAME" PASSED"
else
    echo "Test "$TEST_NAME" FAILED"
    exit 1
fi
