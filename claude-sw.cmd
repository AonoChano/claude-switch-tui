@echo off
setlocal
set "CSW_HOME=%~dp0"
"%CSW_HOME%.venv\Scripts\python.exe" "%CSW_HOME%claude_switch.py" %*
exit /b %ERRORLEVEL%
