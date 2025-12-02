import streamlit as st
import os
import json
import requests
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import pickle

# 상태 저장 파일명
STATE_FILE = 'app_state.pkl'

# 페이지 설정
st.set_page_config(
    page_title="YouTube to Sheets",
    page_icon="📺",
    layout="wide"
)

# === Helper Functions ===

def save_state(state_data):
    """상태를 파일에 저장"""
    try:
        with open(STATE_FILE, 'wb') as f:
            pickle.dump(state_data, f)
    except Exception as e:
        print(f"상태 저장 실패: {e}")

def load_state():
    """파일에서 상태 로드"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"상태 로드 실패: {e}")
    return {}

# Session State 초기화 (사이드바에서 접근하기 위해 상단으로 이동)
if 'search_results' not in st.session_state:
    # 저장된 상태 로드 시도
    saved_state = load_state()
    if saved_state:
        st.session_state.update(saved_state)
    
    if 'search_results' not in st.session_state:
        st.session_state.search_results = pd.DataFrame()

    # 기존 데이터에 새 컬럼이 없는 경우 호환성 처리
    if not st.session_state.search_results.empty:
        if 'view_sub_ratio' not in st.session_state.search_results.columns:
            st.session_state.search_results['view_sub_ratio'] = 0.0
        if 'view_diff' not in st.session_state.search_results.columns:
            st.session_state.search_results['view_diff'] = 0.0

def load_api_key():
    """api_key.txt에서 API 키 로드"""
    if os.path.exists('api_key.txt'):
        try:
            with open('api_key.txt', 'r', encoding='utf-8') as f:
                return f.read().strip()
        except:
            pass
    return ""

def get_credentials_files():
    """credentials 폴더의 JSON 파일 목록 반환"""
    creds_dir = os.path.join(os.getcwd(), 'credentials')
    if os.path.exists(creds_dir):
        return [f for f in os.listdir(creds_dir) if f.endswith('.json')]
    return []

def load_config_url():
    """config.txt에서 스프레드시트 URL 로드"""
    config_path = 'config.txt'
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith("스프레드시트 URL:"):
                        return line.split(":", 1)[1].strip()
        except Exception as e:
            print(f"설정 파일 로드 실패: {e}")
    return ""



@st.cache_data(show_spinner=False)
def search_youtube(api_key, keyword, max_results, published_after=None, published_before=None):
    """YouTube API 검색 수행"""
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        
        results = []
        next_page_token = None
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        while len(results) < max_results:
            status_text.text(f"검색 중... ({len(results)}/{max_results})")
            
            search_params = {
                'q': keyword,
                'part': "id,snippet",
                'maxResults': min(50, max_results - len(results)),
                'type': "video",
                'pageToken': next_page_token,
                'order': "relevance"
            }
            
            if published_after:
                search_params['publishedAfter'] = published_after
            if published_before:
                search_params['publishedBefore'] = published_before
                
            search_response = youtube.search().list(**search_params).execute()
            
            # 채널 ID 수집
            channel_ids = []
            video_ids = []
            for item in search_response.get('items', []):
                channel_ids.append(item['snippet']['channelId'])
                video_ids.append(item['id']['videoId'])
            
            # 채널 정보 조회 (통계)
            channel_stats_map = {}
            if channel_ids:
                channels_response = youtube.channels().list(
                    part="statistics",
                    id=','.join(list(set(channel_ids))) # 중복 제거
                ).execute()
                
                for channel in channels_response.get('items', []):
                    stats = channel['statistics']
                    channel_stats_map[channel['id']] = {
                        'subscriberCount': int(stats.get('subscriberCount', 0)),
                        'viewCount': int(stats.get('viewCount', 0)),
                        'videoCount': int(stats.get('videoCount', 0))
                    }

            if video_ids:
                videos_response = youtube.videos().list(
                    part="snippet,statistics,contentDetails",
                    id=','.join(video_ids)
                ).execute()
                
                for video in videos_response.get('items', []):
                    video_id = video['id']
                    snippet = video['snippet']
                    statistics = video.get('statistics', {})
                    channel_id = snippet.get('channelId')
                    
                    view_count = int(statistics.get('viewCount', 0))
                    comment_count = int(statistics.get('commentCount', 0))
                    
                    # 채널 통계 가져오기
                    ch_stats = channel_stats_map.get(channel_id, {'subscriberCount': 0, 'viewCount': 0, 'videoCount': 0})
                    subscriber_count = ch_stats['subscriberCount']
                    channel_total_views = ch_stats['viewCount']
                    channel_video_count = ch_stats['videoCount']
                    
                    # 지표 1: 조회수 / 구독자수 비율 (영상 조회수/구독)
                    view_sub_ratio = 0.0
                    if subscriber_count > 0:
                        view_sub_ratio = view_count / subscriber_count
                        
                    # 지표 2: 조회수 - 평균조회수
                    avg_views = 0
                    if channel_video_count > 0:
                        avg_views = channel_total_views / channel_video_count
                    view_diff = view_count - avg_views
                    
                    video_data = {
                        'selected': False, # 체크박스용
                        'thumbnail': snippet.get('thumbnails', {}).get('medium', {}).get('url', ''),
                        'url': f"https://youtube.com/watch?v={video_id}",
                        'title': snippet.get('title', ''),
                        'channel': snippet.get('channelTitle', ''),
                        'channel': snippet.get('channelTitle', ''),
                        'view_count': view_count,
                        'subscriber_count': subscriber_count, # 조회수와 댓글수 사이에 배치
                        'comment_count': comment_count,
                        'published_at': snippet.get('publishedAt', ''),
                        'view_sub_ratio': view_sub_ratio,
                        'view_diff': view_diff,
                        # 'subscriber_count': subscriber_count # (제거: 위로 이동)
                    }
                    results.append(video_data)
            
            progress_bar.progress(min(len(results) / max_results, 1.0))
            
            next_page_token = search_response.get('nextPageToken')
            if not next_page_token:
                break
                
        progress_bar.empty()
        status_text.empty()
        return results
        
    except HttpError as e:
        st.error(f"YouTube API 오류: {e}")
        return []
    except Exception as e:
        st.error(f"오류 발생: {e}")
        return []

def upload_to_sheets(creds_file, sheet_url, data_list, category, subcategory, type_text, sheet_name="source_urls"):
    """Google Sheets 업로드"""
    try:
        scope = ['https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive']
        
        creds = Credentials.from_service_account_file(creds_file, scopes=scope)
        client = gspread.authorize(creds)
        
        # 시트 열기
        try:
            sheet = client.open_by_url(sheet_url).worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            st.error(f"'{sheet_name}' 시트를 찾을 수 없습니다.")
            return 0, 0
            
        # 기존 데이터 읽기
        existing_data = sheet.get_all_values()
        
        # 헤더 처리
        headers = []
        if existing_data:
            headers = existing_data[0]
        else:
            # 헤더가 없는 경우 기본 헤더 생성 및 추가
            headers = ['URL', 'title', 'category', 'subcategory', 'type', 'processed', 'processed_date', 'result_index']
            sheet.append_row(headers)
            existing_data = [headers]
            
        # 헤더 매핑 (소문자로 변환하여 인덱스 저장)
        header_map = {h.lower().strip(): i for i, h in enumerate(headers)}
        
        # 필수 컬럼 인덱스 찾기
        url_idx = -1
        index_idx = -1
        
        # URL 컬럼 찾기 (url, link, 주소 등)
        for key in ['url', 'link', '주소']:
            if key in header_map:
                url_idx = header_map[key]
                break
                
        # Index 컬럼 찾기 (result_index, index, 인덱스 등)
        for key in ['result_index', 'index', '인덱스']:
            if key in header_map:
                index_idx = header_map[key]
                break
        
        existing_urls = set()
        max_index = 0
        
        # 기존 데이터 분석 (중복 체크 및 Max Index)
        if len(existing_data) > 1:
            for row in existing_data[1:]: # 헤더 제외
                if not row: continue
                
                # URL 수집
                if url_idx != -1 and len(row) > url_idx:
                    existing_urls.add(row[url_idx])
                elif url_idx == -1 and len(row) > 0: # 매핑 실패 시 첫 번째 컬럼 가정
                    existing_urls.add(row[0])
                    
                # Max Index 계산
                if index_idx != -1 and len(row) > index_idx:
                    val = row[index_idx]
                    if val.isdigit():
                        max_index = max(max_index, int(val))
                elif index_idx == -1 and len(row) > 6: # 매핑 실패 시 7번째(인덱스 6) 컬럼 가정 (기존 로직 호환)
                    val = row[6]
                    if val.isdigit():
                        max_index = max(max_index, int(val))
        
        # 데이터 준비
        rows_to_append = []
        duplicate_count = 0
        current_index = max_index + 1
        
        for data in data_list:
            if data['url'] in existing_urls:
                duplicate_count += 1
                continue
            
            # 헤더에 맞춰 행 데이터 생성 (기본값 빈 문자열)
            row = [''] * len(headers)
            
            def set_col(keys, value):
                for key in keys:
                    if key.lower() in header_map:
                        row[header_map[key.lower()]] = str(value)
                        return
            
            # 데이터 매핑
            set_col(['url', 'link', '주소'], data['url'])
            set_col(['title', '제목'], data['title'])
            set_col(['category', '카테고리'], category)
            set_col(['subcategory', '서브카테고리'], subcategory)
            set_col(['type', '유형', 'post_type'], type_text)
            set_col(['processed', '처리여부', 'posted'], '✓')
            set_col(['processed_date', '처리일', 'posted_date', 'posted_time'], datetime.now().strftime('%Y-%m-%d'))
            set_col(['result_index', 'index', '인덱스'], str(current_index))
            
            # 매핑되지 않은 필수 데이터 처리 (헤더가 없거나 매핑 실패 시 기본 위치에 할당 시도)
            # 주의: 동적 매핑을 사용하므로, 헤더가 명확하지 않으면 데이터가 누락될 수 있음.
            # 호환성을 위해 URL이 매핑되지 않았으면 첫 번째에 넣는 등의 처리는 하지 않음 (헤더가 있을 것이라 가정)
            
            rows_to_append.append(row)
            current_index += 1
            
        if rows_to_append:
            sheet.append_rows(rows_to_append)
            
        return len(rows_to_append), duplicate_count
        
    except Exception as e:
        st.error(f"업로드 중 오류 발생: {e}")
        return 0, 0

def run_self_test(api_key, creds_file, sheet_url, sheet_name="source_urls"):
    """설정 자가 진단 실행"""
    results = []
    
    # 1. YouTube API 테스트
    try:
        if not api_key:
            results.append(("❌", "YouTube API: 키가 입력되지 않았습니다."))
        else:
            youtube = build("youtube", "v3", developerKey=api_key)
            youtube.search().list(q="test", part="id", maxResults=1).execute()
            results.append(("✅", "YouTube API: 연결 성공"))
    except HttpError as e:
        results.append(("❌", f"YouTube API: 오류 ({e.resp.status}) - {e.content.decode('utf-8')}"))
    except Exception as e:
        results.append(("❌", f"YouTube API: 오류 - {str(e)}"))
        
    # 2. Google Sheets 인증 파일 테스트
    creds = None
    try:
        if not creds_file or creds_file == "파일 없음":
            results.append(("❌", "Google Sheets: 인증 파일이 선택되지 않았습니다."))
        elif not os.path.exists(creds_file):
            results.append(("❌", f"Google Sheets: 파일이 존재하지 않습니다 ({creds_file})"))
        else:
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = Credentials.from_service_account_file(creds_file, scopes=scope)
            results.append(("✅", "Google Sheets: 인증 파일 로드 성공"))
    except Exception as e:
        results.append(("❌", f"Google Sheets: 인증 파일 오류 - {str(e)}"))
        
    # 3. Spreadsheet 접근 테스트
    if creds and sheet_url:
        try:
            client = gspread.authorize(creds)
            sheet = client.open_by_url(sheet_url)
            try:
                sheet.worksheet(sheet_name)
                results.append(("✅", f"Google Sheets: '{sheet_name}' 시트 확인됨"))
            except gspread.exceptions.WorksheetNotFound:
                results.append(("⚠️", f"Google Sheets: '{sheet_name}' 시트가 없습니다."))
        except Exception as e:
            results.append(("❌", f"Google Sheets: 접근 실패 - {str(e)}"))
    elif not sheet_url:
        results.append(("⚠️", "Google Sheets: URL이 입력되지 않아 접근 테스트를 건너뜁니다."))
        
    return results


def update_card_selection(idx):
    """카드 뷰에서 체크박스 변경 시 DataFrame 업데이트"""
    st.session_state.search_results.at[idx, 'selected'] = st.session_state[f"card_chk_{idx}"]

# === UI Layout ===

st.title("YouTube URL 수집기 📺")

# --- Sidebar ---
with st.sidebar:
    st.header("설정")
    
    # API Key
    api_key = st.text_input("YouTube API Key", value=load_api_key(), type="password")
    
    # Group 1: Search Settings
    st.header("1. 검색 설정")
    keyword = st.text_input("검색 키워드", value=st.session_state.get('keyword', "파이썬 강의"))
    max_results = st.number_input("최대 검색 결과", min_value=10, max_value=100, value=st.session_state.get('max_results', 50))
    
    # Date Range
    period_option = st.selectbox("검색 기간", ["전체 기간", "최근 7일", "최근 15일", "최근 30일", "직접 입력"], index=["전체 기간", "최근 7일", "최근 15일", "최근 30일", "직접 입력"].index(st.session_state.get('period_option', "전체 기간")))
    
    published_after = None
    published_before = None
    today = datetime.now()
    
    if period_option == "최근 7일":
        published_after = (today - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
    elif period_option == "최근 15일":
        published_after = (today - timedelta(days=15)).strftime("%Y-%m-%dT00:00:00Z")
    elif period_option == "최근 30일":
        published_after = (today - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    elif period_option == "직접 입력":
        col1, col2 = st.columns(2)
        start_date = col1.date_input("시작일", today - timedelta(days=7))
        end_date = col2.date_input("종료일", today)
        published_after = start_date.strftime("%Y-%m-%dT00:00:00Z")
        published_before = (end_date + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

    # 검색 버튼 (사이드바)
    if st.button("🔍 검색 시작", type="primary"):
        if not api_key:
            st.warning("API 키를 입력해주세요.")
        elif not keyword:
            st.warning("검색 키워드를 입력해주세요.")
        else:
            # 검색 로직은 메인 컨텍스트에서 실행 결과를 session_state에 저장하거나
            # 여기서 바로 실행하고 결과를 session_state에 저장
            # (기존 로직이 사이드바 버튼 클릭 시 실행되므로 구조 유지)
            st.session_state.trigger_search = True

    st.divider()
    
    st.divider()
    
    # Self Test 및 Upload Settings를 위한 컨테이너 (렌더링 순서 제어)
    # 메인 컨텐츠에서 데이터가 업데이트된 후 내용을 채우기 위해 빈 컨테이너만 미리 생성
    self_test_container = st.container()
    upload_settings_container = st.container()




# --- Main Content ---

# (Session State 초기화는 상단으로 이동됨)

# 검색 로직 실행
if st.session_state.get('trigger_search', False):
    st.session_state.trigger_search = False # Reset trigger
    results = search_youtube(api_key, keyword, max_results, published_after, published_before)
    if results:
        st.session_state.search_results = pd.DataFrame(results)
        
        # 검색 성공 시 상태 저장
        state_to_save = {
            'search_results': st.session_state.search_results,
            'keyword': keyword,
            'max_results': max_results,
            'period_option': period_option,
            'sheet_name': st.session_state.get('sheet_name', "source_urls"),
            # 필요한 다른 설정값들도 저장 가능
        }
        save_state(state_to_save)
        
        st.success(f"{len(results)}개의 영상을 찾았습니다.")
    else:
        st.warning("검색 결과가 없습니다.")

# 결과 표시 및 선택
if not st.session_state.search_results.empty:
    st.divider()
    
    # 뷰 모드 선택
    col_view, col_action = st.columns([1, 4])
    with col_view:
        view_mode = st.radio("보기 모드", ["리스트", "카드"], horizontal=True, label_visibility="collapsed")
    
    # 전체 선택/해제 버튼
    with col_action:
        sub_c1, sub_c2, _ = st.columns([1, 1, 4])
        if sub_c1.button("전체 선택"):
            st.session_state.search_results['selected'] = True
            st.rerun()
        if sub_c2.button("전체 해제"):
            st.session_state.search_results['selected'] = False
            st.rerun()
        
    if view_mode == "리스트":
        # 데이터 에디터 (테이블)
        edited_df = st.data_editor(
            st.session_state.search_results,
            column_config={
                "selected": st.column_config.CheckboxColumn(
                    "선택",
                    help="업로드할 영상을 선택하세요",
                    default=False,
                ),
                "thumbnail": st.column_config.ImageColumn(
                    "썸네일", help="영상 썸네일"
                ),
                "url": st.column_config.LinkColumn(
                    "URL", help="영상 링크"
                ),
                "view_count": st.column_config.NumberColumn(
                    "조회수", format="%d"
                ),
                "subscriber_count": st.column_config.NumberColumn(
                    "구독자수", format="%d"
                ),
                "comment_count": st.column_config.NumberColumn(
                    "댓글수", format="%d"
                ),
                "view_sub_ratio": st.column_config.NumberColumn(
                    "조회/구독 비율", format="%.4f", help="영상 조회수 / 구독자수"
                ),
                "view_diff": st.column_config.NumberColumn(
                    "조회수 차이", format="%d", help="조회수 - 채널 평균 조회수"
                ),
            },
            disabled=["thumbnail", "url", "title", "channel", "view_count", "subscriber_count", "comment_count", "published_at", "view_sub_ratio", "view_diff"],
            hide_index=True,
            width='stretch',
            height=600
        )
        # 상태 업데이트 (사용자 선택 반영)
        st.session_state.search_results = edited_df
        
    else: # 카드 보기
        # 그리드 레이아웃 (4열)
        cols = st.columns(4)
        for idx, row in st.session_state.search_results.iterrows():
            with cols[idx % 4]:
                with st.container(border=True):
                    # 썸네일
                    st.image(row['thumbnail'], width='stretch')
                    
                    # 제목 (링크 포함)
                    st.markdown(f"**[{row['title']}]({row['url']})**")
                    
                    # 채널 및 통계
                    st.caption(f"{row['channel']}")
                    st.caption(f"👁️ {row['view_count']:,} | 💬 {row['comment_count']:,}")
                    st.caption(f"Ratio: {row['view_sub_ratio']:.4f} | Diff: {row['view_diff']:,.0f}")
                    
                    # 선택 체크박스
                    st.checkbox(
                        "선택", 
                        value=row['selected'], 
                        key=f"card_chk_{idx}",
                        on_change=update_card_selection,
                        args=(idx,)
                    )
    
    edited_df = st.session_state.search_results # 카드 뷰에서도 edited_df 참조를 위해
    
    # 선택된 항목 수 표시
    selected_rows = edited_df[edited_df['selected']]
    st.write(f"선택된 항목: {len(selected_rows)}개")
    
    st.divider()

    # (Self Test는 사이드바로 이동됨)

    
    st.divider()

# --- Sidebar Content Filling (After Main Content Update) ---
# 메인 컨텐츠(st.data_editor 등)가 실행된 후 업데이트된 session_state를 기반으로 사이드바 렌더링

# 1. Upload Settings 렌더링
# 기본값 설정
selected_creds = "파일 없음"
sheet_url = load_config_url()
sheet_name = st.session_state.get('sheet_name', "source_urls")

# 검색 결과 및 선택 항목 확인
has_results = not st.session_state.search_results.empty
has_selection = False
if has_results and 'selected' in st.session_state.search_results.columns:
    has_selection = st.session_state.search_results['selected'].any()

with upload_settings_container:
    if has_selection:
        st.divider()
        st.header("2. 업로드 설정")
        
        # Category Settings
        st.subheader("카테고리")
        category = st.text_input("Category", "디지털 가전")
        subcategory = st.text_input("Subcategory", keyword) # 기본값을 검색 키워드로 설정
        post_type = st.selectbox("Type", ['중격정보형', '비교분석형', '꿀팁공유형', '정보공유형'])
        
        # Google Sheets Settings
        st.subheader("Google Sheets")
        creds_files = get_credentials_files()
        selected_creds = st.selectbox("인증 파일", creds_files if creds_files else ["파일 없음"])
        sheet_url = st.text_input("스프레드시트 URL", value=sheet_url)
        sheet_name = st.text_input("시트 이름", value=sheet_name)
        
        st.divider()
        
        # 선택된 항목 계산
        selected_rows = st.session_state.search_results[st.session_state.search_results['selected']]
        
        if st.button("📤 스프레드시트에 업로드", type="primary", disabled=len(selected_rows) == 0):
            if not selected_creds or selected_creds == "파일 없음":
                st.error("인증 파일을 선택해주세요.")
            elif not sheet_url:
                st.error("스프레드시트 URL을 입력해주세요.")
            else:
                creds_path = os.path.join(os.getcwd(), 'credentials', selected_creds)
                
                # DataFrame을 딕셔너리 리스트로 변환
                data_to_upload = selected_rows.to_dict('records')
                
                with st.spinner("업로드 중..."):
                    success_count, duplicate_count = upload_to_sheets(
                        creds_path, 
                        sheet_url, 
                        data_to_upload, 
                        category, 
                        subcategory, 
                        post_type,
                        sheet_name
                    )
                    
                if success_count > 0:
                    st.balloons()
                    msg = f"{success_count}개 항목이 성공적으로 업로드되었습니다!"
                    if duplicate_count > 0:
                        msg += f" ({duplicate_count}개 중복 제외)"
                    st.success(msg)
                elif duplicate_count > 0:
                    st.warning(f"업로드할 항목이 없습니다. (선택된 {duplicate_count}개 모두 이미 존재함)")
                else:
                    st.error("업로드에 실패했거나 추가할 항목이 없습니다.")

# 2. Self Test 렌더링 (Upload Settings에서 설정된 변수 사용 가능)
with self_test_container:
    with st.expander("🛠️ 설정 및 진단"):
        if st.button("연결 테스트 실행"):
            creds_path = os.path.join(os.getcwd(), 'credentials', selected_creds) if selected_creds != "파일 없음" else None
            test_results = run_self_test(api_key, creds_path, sheet_url, sheet_name)
            
            for icon, msg in test_results:
                if icon == "✅":
                    st.success(f"{icon} {msg}")
                elif icon == "⚠️":
                    st.warning(f"{icon} {msg}")
                else:
                    st.error(f"{icon} {msg}")
