#!/usr/bin/env bash

. openrc

screen -S SERVER_SIG -d -m -- sh -c 'tailf /var/log/neutron/server.log > log_server'
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
screen -X -S SERVER_SIG kill
echo "Try to find ERROR in server log"
cat log_server | grep ERROR
echo "Try to find TRACE in server log"
cat log_server | grep TRACE
api=$(grep 'api_workers = ' /etc/neutron/neutron.conf | grep -v '#' | awk '{print$3}')
rpc=$(grep 'rpc_workers = ' /etc/neutron/neutron.conf | grep -v '#' | awk '{print$3}')
echo "Quantity of api workers "$api
echo "Quantity of rpc workers "$rpc
echo "All neutron processes: "
echo $(pstree -up | grep neutron-server)
echo "Try to find SIGHUP command"
cat log_server | grep SIGHUP
NUMBER=$(cat log_server | grep SIGHUP | wc -l)
echo "Find SIGHUP "$NUMBER" times"
rm -r log_server

if [ $TEST_FAILED == 0 ]; then
    echo "Test "$TEST_NAME" PASSED"
else
    echo "Test "$TEST_NAME" FAILED"
    exit 1
fi
