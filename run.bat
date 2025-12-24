@echo off
echo Starting Network Test Tool...
python main.py
if %errorlevel% neq 0 (
    echo.
    echo Application exited with error code %errorlevel%
    pause
)
