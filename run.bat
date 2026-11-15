@echo off
setlocal
cd /d "%~dp0"
title ASTRA HEALTH - Local Demo
echo.
echo  ASTRA HEALTH - Local research prototype
echo  ----------------------------------------
where py >nul 2>nul
if %errorlevel%==0 (set "PYTHON=py -3") else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python 3.10 or newer was not found. Install Python from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
  )
  set "PYTHON=python"
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating local virtual environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto failed
)
echo Installing or checking pinned requirements...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
set "ASTRA_PORT="
for /f %%P in ('powershell -NoProfile -Command "$port=8000; while (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { $port++ }; Write-Output $port"') do set "ASTRA_PORT=%%P"
if not defined ASTRA_PORT set "ASTRA_PORT=8000"
set "ASTRA_URL=http://127.0.0.1:%ASTRA_PORT%/"
echo Starting ASTRA HEALTH at %ASTRA_URL%
echo API documentation: %ASTRA_URL%docs
start "ASTRA HEALTH API" /B .venv\Scripts\python.exe run.py
powershell -NoProfile -Command "$u='http://127.0.0.1:%ASTRA_PORT%/api/health'; for($i=0;$i -lt 40;$i++){try{$r=Invoke-RestMethod -TimeoutSec 1 $u;if($r.status -eq 'ok'){exit 0}}catch{};Start-Sleep -Milliseconds 500};exit 1"
if errorlevel 1 goto failed
echo Server is ready. Opening the website...
start "" "%ASTRA_URL%"
echo Keep this window open while using the app. Press Ctrl+C to stop the server.
pause >nul
goto end
:failed
echo.
echo Startup failed. Check the error above. The first launch needs internet access to install Python packages.
pause
:end
endlocal
