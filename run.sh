#!/bin/bash
# run.sh - YouTube to Sheets 프로그램 실행 스크립트

echo "==================================="
echo "YouTube to Sheets 프로그램"
echo "==================================="
echo ""

# Python 버전 확인
echo "Python 버전 확인 중..."
python --version
if [ $? -ne 0 ]; then
    echo "❌ Python이 설치되어 있지 않습니다."
    echo "Python 3.7 이상을 설치해주세요."
    exit 1
fi
echo "✓ Python 설치 확인"
echo ""

# 필요한 라이브러리 확인
echo "필요한 라이브러리 확인 중..."
if [ -f "requirements.txt" ]; then
    echo "✓ requirements.txt 파일 발견"
    
    # 라이브러리가 설치되어 있는지 확인
    python -c "import PyQt5" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "⚠ 라이브러리가 설치되어 있지 않습니다."
        echo "라이브러리를 설치하시겠습니까? (y/n)"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            echo "라이브러리 설치 중..."
            pip install -r requirements.txt
            if [ $? -ne 0 ]; then
                echo "❌ 라이브러리 설치 실패"
                exit 1
            fi
            echo "✓ 라이브러리 설치 완료"
        else
            echo "프로그램을 실행하려면 먼저 라이브러리를 설치해야 합니다."
            echo "다음 명령어를 실행하세요:"
            echo "  pip install -r requirements.txt"
            exit 1
        fi
    else
        echo "✓ 라이브러리 설치 확인"
    fi
else
    echo "⚠ requirements.txt 파일을 찾을 수 없습니다."
fi
echo ""

# credentials.json 파일 확인
if [ ! -f "credentials.json" ]; then
    echo "⚠ credentials.json 파일을 찾을 수 없습니다."
    echo "Google Sheets API 인증 파일을 준비해주세요."
    echo "자세한 내용은 GOOGLE_SHEETS_SETUP.md를 참조하세요."
fi
echo ""

# 프로그램 실행
echo "프로그램 실행 중..."
echo ""
python youtube_to_sheets.py

# 종료 코드 확인
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ 프로그램 실행 중 오류가 발생했습니다."
    exit 1
fi