# 빠른 시작 가이드 (5분 완성)

## 1단계: 라이브러리 설치 (1분)

```bash
pip install -r requirements.txt
```

## 2단계: YouTube API 키 발급 (2분)

1. https://console.cloud.google.com/apis/credentials 접속
2. 프로젝트 생성 (없으면)
3. "+ 사용자 인증 정보 만들기" → "API 키" 클릭
4. API 키 복사
5. "라이브러리"에서 "YouTube Data API v3" 활성화

## 3단계: Google Sheets 설정 (2분)

### 서비스 계정 생성
1. https://console.cloud.google.com/apis/credentials 접속
2. "+ 사용자 인증 정보 만들기" → "서비스 계정" 선택
3. 이름 입력 후 생성
4. "키" 탭 → "새 키 만들기" → JSON 다운로드
5. 파일을 `credentials.json`으로 저장

### API 활성화
1. "라이브러리"에서 "Google Sheets API" 활성화
2. "라이브러리"에서 "Google Drive API" 활성화

### 스프레드시트 준비
1. Google Sheets에서 새 문서 생성
2. 첫 행에 헤더 입력:
   ```
   URL | category | subcategory | type | processed | processed_date | result_index
   ```
3. credentials.json에서 `client_email` 복사
4. 스프레드시트 "공유" → 이메일 입력 → "편집자" 권한 부여
5. 스프레드시트 URL 복사

## 4단계: 프로그램 실행

```bash
python youtube_to_sheets.py
```

## 5단계: 사용

1. **YouTube API 설정**
   - API 키 입력

2. **검색 설정**
   - 키워드 입력 (예: "파이썬 강의")
   - 검색 시작 클릭

3. **카테고리 설정**
   - Category: 예) 디지털 가전
   - Subcategory: 예) 스마트폰
   - Type: 드롭다운에서 선택

4. **Google Sheets 설정**
   - 인증 파일: credentials.json 선택
   - 스프레드시트 URL: 붙여넣기

5. **업로드**
   - 원하는 영상 체크박스 선택
   - "스프레드시트에 등록" 클릭

## 완료!

스프레드시트에서 저장된 데이터 확인하세요.

---

## 트러블슈팅

**"API key not valid"**
→ YouTube Data API v3 활성화 확인

**"The caller does not have permission"**
→ 서비스 계정 이메일 스프레드시트 공유 확인

**"quotaExceeded"**
→ 내일 다시 시도 또는 새 API 키 생성

---

더 자세한 설명은 README.md와 GOOGLE_SHEETS_SETUP.md를 참조하세요.