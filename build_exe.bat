@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem Python 이 없는 PC 에서도 실행되는 HunetAutoStudy.exe 를 만듭니다. (결과: dist\HunetAutoStudy.exe)
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv 2> nul || python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name HunetAutoStudy --icon hunet_auto/assets/app.ico --collect-data customtkinter --collect-data hunet_auto main.py
if errorlevel 1 goto fail
echo.
echo 완료: dist\HunetAutoStudy.exe
pause
exit /b 0

:fail
echo 빌드에 실패했습니다.
pause
exit /b 1
