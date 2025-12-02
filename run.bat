@echo off
REM run.bat - YouTube to Sheets 프로그램 (Windows용)

echo ===================================
echo YouTube to Sheets 프로그램
echo ===================================
echo.

REM Python 버전 확인
echo Python 버전 확인 중...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python이 설치되어 있지 않습니다.
    echo Python 3.7 이상을 설치해주세요.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
echo ✓ Python 설치 확인
echo.

REM 필요한 라이브러리 확인
echo 필요한 라이브러리 확인 중...
if exist requirements.txt (
    echo ✓ requirements.txt 파일 발견
    
    REM PyQt5 설치 확인
    python -c "import PyQt5" >nul 2>&1
    if errorlevel 1 (
        echo ⚠ 라이브러리가 설치되어 있지 않습니다.
        echo 라이브러리를 설치하시겠습니까? (Y/N^)
        set /p response=
        if /i "%response%"=="Y" (
            echo 라이브러리 설치 중...
            pip install -r requirements.txt
            if errorlevel 1 (
                echo ❌ 라이브러리 설치 실패
                pause
                exit /b 1
            )
            echo ✓ 라이브러리 설치 완료
        ) else (
            echo 프로그램을 실행하려면 먼저 라이브러리를 설치해야 합니다.
            echo 다음 명령어를 실행하세요:
            echo   pip install -r requirements.txt
            pause
            exit /b 1
        )
    ) else (
        echo ✓ 라이브러리 설치 확인
    )
) else (
    echo ⚠ requirements.txt 파일을 찾을 수 없습니다.
)
echo.

REM credentials.json 파일 확인
if not exist credentials.json (
    echo ⚠ credentials.json 파일을 찾을 수 없습니다.
    echo Google Sheets API 인증 파일을 준비해주세요.
    echo 자세한 내용은 GOOGLE_SHEETS_SETUP.md를 참조하세요.
)
echo.

REM 프로그램 실행
echo 프로그램 실행 중...
echo.
python youtube_to_sheets.py

REM 종료
if errorlevel 1 (
    echo.
    echo ❌ 프로그램 실행 중 오류가 발생했습니다.
    pause
    exit /b 1
)