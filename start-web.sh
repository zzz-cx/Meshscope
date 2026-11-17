#!/bin/bash
cd /root/Meshscope
export PATH=/opt/python311/bin:$PATH
exec /opt/python311/bin/python3.11 -m configpilot web --port 8080
