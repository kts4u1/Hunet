@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem 처음 실행할 때만 .venv 폴더에 필요한 파이썬 패키지를 설치합니다.
if not exist ".venv\Scripts\python.exe" (
    echo 처음 실행: 필요한 프로그램을 설치합니다. 1~2분 정도 걸립니다...
    py -3 -m venv .venv 2> nul || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Python 이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요.
    echo 설치 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
    pause
    exit /b 1
)
if not exist ".venv\installed.txt" (
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo 설치에 실패했습니다. 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
    echo ok> ".venv\installed.txt"
)

start "" ".venv\Scripts\pythonw.exe" main.py
