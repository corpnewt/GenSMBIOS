@echo off
REM Get our local path before delayed expansion - allows ! in path
set "thisDir=%~dp0"

setlocal enableDelayedExpansion
REM Setup initial vars
set "script_name=%~n0.py"
set /a tried=0
set "toask=yes"
set "pause_on_error=yes"
set "py3v="
set "py3path="
set "pypath="
set "just_installing=FALSE"

REM Get the system32 (or equivalent) path
call :getsyspath "syspath"

REM Make sure the syspath exists
if "!syspath!" == "" (
    if exist "%SYSTEMROOT%\system32\cmd.exe" (
        if exist "%SYSTEMROOT%\system32\reg.exe" (
            if exist "%SYSTEMROOT%\system32\where.exe" (
                REM Fall back on the default path if it exists
                set "ComSpec=%SYSTEMROOT%\system32\cmd.exe"
                set "syspath=%SYSTEMROOT%\system32\"
            )
        )
    )
    if "!syspath!" == "" (
        cls
        echo   ###     ###
        echo  # Warning #
        echo ###     ###
        echo.
        echo Could not locate cmd.exe, reg.exe, or where.exe
        echo.
        echo Please ensure your ComSpec environment variable is properly configured and
        echo points directly to cmd.exe, then try again.
        echo.
        echo Current CompSpec Value: "%ComSpec%"
        echo.
        echo Press [enter] to quit.
        pause > nul
        exit /b 1
    )
)

if "%~1" == "--install-python" (
    set "just_installing=TRUE"
    goto installpy
)

goto checkscript

:checkscript
REM Check for our script
if not exist "!thisDir!\!script_name!" (
    cls
    echo   ###              ###
    echo  # Script Not Found #
    echo ###              ###
    echo.
    echo Could not find !script_name!.
    echo Please make sure to run this script from the same directory
    echo as !script_name!.
    echo.
    echo Press [enter] to quit.
    pause > nul
    exit /b 1
)
goto checkpy

:checkpy
call :updatepath
for /f "USEBACKQ tokens=*" %%x in (`!syspath!where.exe python3 2^> nul`) do ( call :checkpyversion "%%x" "py3v" "py3path" )
if not "!py3path!" == "" (
    set "pypath=!py3path!"
    goto setupvenv
)
if !tried! lss 1 (
    if /i "!toask!"=="yes" (
        goto askinstall
    ) else (
        goto installpy
    )
) else (
    cls
    echo   ###              ###
    echo  # Python Not Found #
    echo ###              ###
    echo.
    echo Python 3 is not installed or not found in your PATH.
    echo Please install it from https://www.python.org/downloads/windows/
    echo.
    echo Make sure you check the box labeled:
    echo "Add Python 3.X to PATH"
    echo.
    echo Press [enter] to quit.
    pause > nul
    exit /b 1
)

:checkpyversion <path> <py3v> <py3path>
set "version="&for /f "tokens=2* USEBACKQ delims= " %%a in (`"%~1" -V 2^>^&1`) do (
    REM Ensure we have a version number
    call :isnumber "%%a"
    if not "!errorlevel!" == "0" goto :EOF
    set "version=%%a"
)
if not defined version goto :EOF
if "!version:~0,1!" == "3" (
    REM Python 3
    call :comparepyversion "!version!" "!%~2!"
    if "!errorlevel!" == "1" (
        set "%~2=!version!"
        set "%~3=%~1"
    )
)
goto :EOF

:isnumber <check_value>
set "var="&for /f "delims=0123456789." %%i in ("%~1") do set var=%%i
if defined var (exit /b 1)
exit /b 0

:comparepyversion <version1> <version2>
REM Exits with status 0 if equal, 1 if v1 gtr v2, 2 if v1 lss v2
for /f "tokens=1,2,3 delims=." %%a in ("%~1") do (
    set a1=%%a
    set a2=%%b
    set a3=%%c
)
for /f "tokens=1,2,3 delims=." %%a in ("%~2") do (
    set b1=%%a
    set b2=%%b
    set b3=%%c
)
if not defined a1 set a1=0
if not defined a2 set a2=0
if not defined a3 set a3=0
if not defined b1 set b1=0
if not defined b2 set b2=0
if not defined b3 set b3=0
if %a1% gtr %b1% exit /b 1
if %a1% lss %b1% exit /b 2
if %a2% gtr %b2% exit /b 1
if %a2% lss %b2% exit /b 2
if %a3% gtr %b3% exit /b 1
if %a3% lss %b3% exit /b 2
exit /b 0

:askinstall
cls
echo   ###              ###
echo  # Python Not Found #
echo ###              ###
echo.
echo Python 3 was not found on the system or in the PATH.
echo.
set /p "menu=Would you like to install it now? [y/n]: "
if /i "!menu!"=="y" (
    goto installpy
) else if "!menu!"=="n" (
    set /a tried=!tried!+1
    goto checkpy
)
goto askinstall

:installpy
set /a tried=!tried!+1
cls
echo   ###               ###
echo  # Installing Python #
echo ###               ###
echo.
echo Gathering info from https://www.python.org/downloads/windows/...
powershell -command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;(new-object System.Net.WebClient).DownloadFile('https://www.python.org/downloads/windows/','%TEMP%\pyurl.txt')"
if not exist "%TEMP%\pyurl.txt" (
    if /i "!just_installing!" == "TRUE" (
        echo Failed to get info
        exit /b 1
    ) else (
        goto checkpy
    )
)
echo Parsing for latest...
pushd "%TEMP%"
for /f "tokens=9 delims=< " %%x in ('findstr /i /c:"Latest Python 3 Release" pyurl.txt') do ( set "release=%%x" )
popd
if "!release!" == "" (
    if /i "!just_installing!" == "TRUE" (
        echo Failed to get python version
        exit /b 1
    ) else (
        goto checkpy
    )
)
echo Found Python !release! - Downloading...
del "%TEMP%\pyurl.txt"
set "url=https://www.python.org/ftp/python/!release!/python-!release!-amd64.exe"
set "pytype=exe"
powershell -command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (new-object System.Net.WebClient).DownloadFile('!url!','%TEMP%\pyinstall.!pytype!')"
if not exist "%TEMP%\pyinstall.!pytype!" (
    if /i "!just_installing!" == "TRUE" (
        echo Failed to download installer
        exit /b 1
    ) else (
        goto checkpy
    )
)
echo Installing...
pushd "%TEMP%"
echo pyinstall.exe /quiet PrependPath=1 Include_test=0 Shortcuts=0 Include_launcher=0
pyinstall.exe /quiet PrependPath=1 Include_test=0 Shortcuts=0 Include_launcher=0
popd
echo Installer finished with %ERRORLEVEL% status.
del "%TEMP%\pyinstall.!pytype!"
call :updatepath
if /i "!just_installing!" == "TRUE" (
    echo.
    echo Done.
    pause > nul
    exit /b 0
) else (
    goto checkpy
)

:setupvenv
REM Create virtual environment if it doesn't exist
set "venv_dir=!thisDir!.venv"
if not exist "!venv_dir!\Scripts\python.exe" (
    echo Creating virtual environment...
    "!pypath!" -m venv "!venv_dir!"
    if not !ERRORLEVEL! == 0 (
        echo Failed to create virtual environment. Falling back to base Python.
        set "venv_python=!pypath!"
    ) else (
        set "venv_python=!venv_dir!\Scripts\python.exe"
    )
) else (
    set "venv_python=!venv_dir!\Scripts\python.exe"
)
REM Upgrade pip in venv
"!venv_python!" -m pip install --upgrade pip >nul 2>&1
REM Check and install required modules in venv
echo Checking Python modules...
"!venv_python!" -c "import tqdm" >nul 2>&1
if not !ERRORLEVEL! == 0 (
    echo tqdm not found. Attempting to install in venv...
    "!venv_python!" -m pip install tqdm >nul 2>&1
    if not !ERRORLEVEL! == 0 (
        echo Failed to install tqdm. Continuing without it...
    )
)
"!venv_python!" -c "import requests" >nul 2>&1
if not !ERRORLEVEL! == 0 (
    echo requests not found. Attempting to install in venv...
    "!venv_python!" -m pip install requests >nul 2>&1
    if not !ERRORLEVEL! == 0 (
        echo Failed to install requests. The script may not run without it...
    )
)
"!venv_python!" -c "import tkinter" >nul 2>&1
if not !ERRORLEVEL! == 0 (
    echo tkinter module not found.
    echo Python on Windows typically includes tkinter. Continuing without it...
)
goto runscript

:runscript
REM Run the Python script
cls
set "args=%*"
set "args=!args:"=!"
if "!args!"=="" (
    "!venv_python!" "!thisDir!!script_name!"
) else (
    "!venv_python!" "!thisDir!!script_name!" %*
)
if /i "!pause_on_error!" == "yes" (
    if not "%ERRORLEVEL%" == "0" (
        echo.
        echo Script exited with error code: %ERRORLEVEL%
        echo.
        echo Press [enter] to exit...
        pause > nul
    )
)
goto :EOF

:undouble <string_name> <string_value> <character>
REM Helper function to strip doubles of a single character out of a string recursively
set "string_value=%~2"
:undouble_continue
set "check=!string_value:%~3%~3=%~3!"
if not "!check!" == "!string_value!" (
    set "string_value=!check!"
    goto :undouble_continue
)
set "%~1=!check!"
goto :EOF

:updatepath
set "spath="
set "upath="
for /f "USEBACKQ tokens=2* delims= " %%i in (`!syspath!reg.exe query "HKCU\Environment" /v "Path" 2^> nul`) do ( if not "%%j" == "" set "upath=%%j" )
for /f "USEBACKQ tokens=2* delims= " %%i in (`!syspath!reg.exe query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v "Path" 2^> nul`) do ( if not "%%j" == "" set "spath=%%j" )
if not "%spath%" == "" (
    set "PATH=%spath%"
    if not "%upath%" == "" (
        set "PATH=%PATH%;%upath%"
    )
) else if not "%upath%" == "" (
    set "PATH=%upath%"
)
call :undouble "PATH" "%PATH%" ";"
goto :EOF

:getsyspath <variable_name>
REM Helper method to return a valid path to cmd.exe, reg.exe, and where.exe
call :undouble "temppath" "%ComSpec%" ";"
(set LF=^
%=this line is empty=%
)
set "testpath=%temppath:;=!LF!%"
set /a found=0
for /f "tokens=* delims=" %%i in ("!testpath!") do (
    if not "%%i" == "" (
        if !found! lss 1 (
            set "checkpath=%%i"
            if /i "!checkpath:~-7!" == "cmd.exe" (
                set "checkpath=!checkpath:~0,-7!"
            )
            if not "!checkpath:~-1!" == "\" (
                set "checkpath=!checkpath!\"
            )
            if EXIST "!checkpath!cmd.exe" (
                if EXIST "!checkpath!reg.exe" (
                    if EXIST "!checkpath!where.exe" (
                        set /a found=1
                        set "ComSpec=!checkpath!cmd.exe"
                        set "%~1=!checkpath!"
                    )
                )
            )
        )
    )
)
goto :EOF