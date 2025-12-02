# YouTube URL 수집 → Google Sheets 업로드 프로그램

## 주요 기능

1. **키워드로 YouTube 검색**: YouTube Data API를 사용하여 키워드 검색
2. **시각적 결과 표시**: 썸네일, URL, 제목, 채널, 조회수, 댓글 수 표시
3. **체크박스 선택**: 업로드할 영상을 체크박스로 선택
4. **카테고리 입력**: Category, Subcategory, Type 설정
5. **Google Sheets 자동 업로드**: 선택한 항목을 스프레드시트에 자동 저장

## 설치 방법

### 1. 필요한 라이브러리 설치

```bash
pip install PyQt5
pip install google-api-python-client
pip install gspread
pip install google-auth
pip install requests
```

또는 requirements.txt 사용:

```bash
pip install -r requirements.txt
```

### 2. YouTube Data API v3 키 발급

1. [Google Cloud Console](https://console.cloud.google.com/) 접속
2. 새 프로젝트 생성 또는 기존 프로젝트 선택
3. "API 및 서비스" → "라이브러리" 이동
4. "YouTube Data API v3" 검색 후 사용 설정
5. "사용자 인증 정보" → "사용자 인증 정보 만들기" → "API 키" 선택
6. 생성된 API 키 복사

### 3. Google Sheets API 설정

#### 3-1. 서비스 계정 생성

1. [Google Cloud Console](https://console.cloud.google.com/) 접속
2. "API 및 서비스" → "사용자 인증 정보" 이동
3. "사용자 인증 정보 만들기" → "서비스 계정" 선택
4. 서비스 계정 이름 입력 (예: youtube-sheets-uploader)
5. "완료" 클릭

#### 3-2. JSON 키 파일 다운로드

1. 생성된 서비스 계정 클릭
2. "키" 탭 → "키 추가" → "새 키 만들기"
3. "JSON" 선택 후 "만들기"
4. 다운로드된 JSON 파일 저장 (예: credentials.json)

#### 3-3. Google Sheets API 활성화

1. "API 및 서비스" → "라이브러리" 이동
2. "Google Sheets API" 검색 후 사용 설정
3. "Google Drive API"도 검색 후 사용 설정

#### 3-4. 스프레드시트 공유 설정

1. Google Sheets에서 새 스프레드시트 생성
2. 첫 번째 시트에 다음 헤더 추가:
   ```
   URL | category | subcategory | type | processed | processed_date | result_index
   ```
3. "공유" 버튼 클릭
4. JSON 파일에서 `client_email` 값 복사 (예: xxx@xxx.iam.gserviceaccount.com)
5. 해당 이메일 주소를 편집자로 추가
6. 스프레드시트 URL 복사

## 사용 방법

### 1. 프로그램 실행

```bash
python youtube_to_sheets.py
```

### 2. 설정 입력

#### YouTube API 설정
- **API 키**: YouTube Data API v3 키 입력

#### 검색 설정
- **검색 키워드**: 검색할 키워드 입력 (예: "파이썬 강의")
- **최대 검색 결과**: 10~100개 설정 (기본값: 50)
- **🔍 검색 시작** 버튼 클릭

#### 카테고리 설정
- **Category**: 대분류 입력 (예: "디지털 가전")
- **Subcategory**: 소분류 입력 (예: "스마트폰")
- **Type**: 드롭다운에서 선택 (중격정보형, 비교분석형, 꿀팁공유형, 정보공유형)

#### Google Sheets 설정
- **인증 파일 (JSON)**: 다운로드한 credentials.json 파일 선택
- **스프레드시트 URL**: Google Sheets URL 입력

### 3. 영상 선택 및 업로드

1. 검색 결과에서 원하는 영상의 체크박스 선택
   - "전체 선택" / "전체 해제" 버튼 사용 가능
2. **📤 스프레드시트에 등록** 버튼 클릭
3. 업로드 완료 메시지 확인

## 스프레드시트 데이터 형식

업로드된 데이터는 다음 형식으로 저장됩니다:

| URL | category | subcategory | type | processed | processed_date | result_index |
|-----|----------|-------------|------|-----------|----------------|--------------|
| https://youtube.com/watch?v=xxx | 디지털 가전 | 스마트폰 | 중격정보형 | ✓ | 2025-11-23 | 1 |

## 주의사항

### API 할당량
- YouTube Data API v3는 일일 할당량이 있습니다 (기본 10,000 units)
- 검색 1회당 약 100 units 사용
- 할당량 초과 시 다음날까지 대기 또는 새 API 키 사용

### 네트워크 연결
- 썸네일 이미지 로딩에 인터넷 연결 필요
- 느린 네트워크에서는 썸네일 로딩이 지연될 수 있음

### Google Sheets 권한
- 서비스 계정 이메일이 스프레드시트에 편집 권한이 있어야 함
- 스프레드시트가 삭제되거나 권한이 변경되면 업로드 실패

## 문제 해결

### "API 키가 유효하지 않습니다"
- YouTube Data API v3가 활성화되어 있는지 확인
- API 키를 올바르게 복사했는지 확인
- API 키 제한 설정 확인

### "인증 파일을 찾을 수 없습니다"
- credentials.json 파일 경로 확인
- 파일이 존재하고 읽기 권한이 있는지 확인

### "스프레드시트에 접근할 수 없습니다"
- 서비스 계정 이메일이 스프레드시트에 공유되었는지 확인
- 스프레드시트 URL이 올바른지 확인
- Google Sheets API와 Google Drive API가 활성화되어 있는지 확인

### 썸네일이 표시되지 않음
- 인터넷 연결 확인
- 방화벽 설정 확인

## 추가 기능 개발 아이디어

- [ ] 검색 필터 추가 (조회수, 날짜 범위 등)
- [ ] 여러 스프레드시트 시트 지원
- [ ] CSV/Excel 내보내기 기능
- [ ] 영상 상세 정보 표시 (길이, 좋아요 수 등)
- [ ] 중복 URL 체크 기능
- [ ] 검색 히스토리 저장

## 라이선스

MIT License

## 문의

버그 리포트나 기능 제안은 이슈로 등록해주세요.