@echo off 
chcp 65001 > nul 
title NetMonitor Agent 
cd /d "C:\Users\newnew\Desktop\网络检测\" 
python agent\agent.py 
pause 
