@echo off
setlocal
py -3 -m PyInstaller --noconfirm --clean --distpath release MinPaint.spec
if errorlevel 1 goto failed
echo.
echo Built release\MinPaint.exe
pause
exit /b 0

:failed
echo.
echo Build failed. Install the build dependency with:
echo py -3 -m pip install -r requirements-build.txt
pause
exit /b 1
