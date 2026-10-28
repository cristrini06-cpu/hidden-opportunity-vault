@echo off
setlocal
cd /d "%~dp0"
echo.
echo Hidden Opportunity Vault - Daily Discovery Monitor
 echo ================================================
echo.
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 agent\monitor.py
    goto :done
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python agent\monitor.py
    goto :done
)
echo Python is not installed or cannot be found.
echo Read AGENT_SETUP.txt to activate daily automatic scans on GitHub.
goto :end
:done
echo.
echo The results are in agent\data\discoveries.json.
echo Open the Vault, choose DAILY AGENT, then IMPORT AGENT REPORT.
:end
echo.
pause
