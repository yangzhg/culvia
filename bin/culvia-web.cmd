@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT=%%~fI"

if defined CULVIA_VENV (
  set "VENV=%CULVIA_VENV%"
) else (
  set "VENV=%USERPROFILE%\.venvs\culvia"
)

if exist "%VENV%\Scripts\python.exe" (
  set "PY=%VENV%\Scripts\python.exe"
) else if exist "%VENV%\bin\python" (
  set "PY=%VENV%\bin\python"
) else if defined PYTHON (
  set "PY=%PYTHON%"
) else (
  set "PY=python"
)

pushd "%ROOT%"
"%PY%" -c "from culvia.server import main; import sys; sys.argv[0] = 'bin/culvia-web.cmd'; raise SystemExit(main(sys.argv[1:]))" %*
set "STATUS=%ERRORLEVEL%"
popd
exit /b %STATUS%
