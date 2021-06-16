#!/bin/sh

workingDir=/home/bot/balancer
scriptName=mayer.py

cd ${workingDir}
find -name "*.mid" -type f 2>/dev/null | while read file; do
  read pid instance <${file}
  kill -0 ${pid} 2>/dev/null
  if [ $? -eq 1 ]; then
    echo resurrecting ${instance}
    tmux has-session -t ${instance} 2>/dev/null
    if [ $? -eq 1 ]; then
      tmux new -d -s ${instance}
    fi
    sleep 2
    tmux send-keys -t "$instance" C-z "$workingDir/$scriptName $instance" C-m
  else
    echo ${instance} is alive
  fi
done
