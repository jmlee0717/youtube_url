import streamlit as st
import os
import requests
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd
import pickle
import io
import yt_dlp
import glob
import re
import json
import uuid

# 상태 저장 파일명
STATE_FILE = 'app_state.pkl'

# 페이지 설정
st.set_page_config(
    page_title="YouTube Search Tool",
    page_icon="📺",
    layout="wide"
)

# === 로그인(비밀번호) 인증 기능 ===
def check_password():
    """비밀번호 확인 함수"""
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"] 
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input(
        "비밀번호를 입력하세요", type="password", on_change=password_entered, key="password"
    )
    if "password_correct" in st.session_state:
        st.error("😕 비밀번호가 틀렸습니다.")
    return False

if not check_password():
    st.stop()
# =================================


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

def parse_iso_duration(duration_str):
    """ISO 8601 지속 시간 문자열(PT#H#M#S)을 초 단위(int)로 변환"""
    if not duration_str:
        return 0
    # 정규표현식으로 시, 분, 초 추출
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return 0
    
    hours, minutes, seconds = match.groups()
    total_seconds = 0
    if hours: total_seconds += int(hours) * 3600
    if minutes: total_seconds += int(minutes) * 60
    if seconds: total_seconds += int(seconds)
    
    return total_seconds

# Session State 초기화
if 'search_results' not in st.session_state:
    saved_state = load_state()
    if saved_state:
        st.session_state.update(saved_state)
    
    if 'search_results' not in st.session_state:
        st.session_state.search_results = pd.DataFrame()

    # 댓글 저장소 초기화 {video_id: [comments]}
    if 'comments_map' not in st.session_state:
        st.session_state.comments_map = {}
        
    # 스크립트 저장소 초기화 {video_id: full_text}
    if 'scripts_map' not in st.session_state:
        st.session_state.scripts_map = {}

    # 기존 데이터 호환성 처리
    if not st.session_state.search_results.empty:
        if 'view_sub_ratio' not in st.session_state.search_results.columns:
            st.session_state.search_results['view_sub_ratio'] = 0.0
        if 'view_diff' not in st.session_state.search_results.columns:
            st.session_state.search_results['view_diff'] = 0.0
        if 'duration_sec' not in st.session_state.search_results.columns:
            st.session_state.search_results['duration_sec'] = 0

def load_api_key():
    """Secrets 또는 api_key.txt에서 API 키 로드"""
    # 1순위: Streamlit Secrets 확인 (클라우드 배포용)
    if "YOUTUBE_API_KEY" in st.secrets:
        return st.secrets["YOUTUBE_API_KEY"]
        
    # 2순위: 로컬 파일 확인 (내 컴퓨터 테스트용)
    if os.path.exists('api_key.txt'):
        try:
            with open('api_key.txt', 'r', encoding='utf-8') as f:
                return f.read().strip()
        except:
            pass
    return "" 

# === 기능 1: 스크립트(자막) 추출 (yt-dlp 기반) ===
def get_youtube_transcript(video_id):
    """
    [yt-dlp] 자막 파일 다운로드 방식 (main.py 로직 이식)
    **수정사항: 5000자 길이 제한 제거 (전체 스크립트 추출)**
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    unique_id = str(uuid.uuid4())[:8]
    temp_filename = f"temp_sub_{unique_id}"
    
    # 기존 임시 파일 청소
    for f in glob.glob(f"{temp_filename}*"):
        try: os.remove(f)
        except: pass
    
    try:
        # yt-dlp 설정
        ydl_opts = {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['ko'],
            'outtmpl': temp_filename,
            'quiet': True,
            'no_warnings': True,
        }
        
        # cookies.txt가 있으면 사용 (안전성 향상)
        if os.path.exists('cookies.txt'):
            ydl_opts['cookiefile'] = 'cookies.txt'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # 다운로드된 파일 찾기
        downloaded_files = glob.glob(f"{temp_filename}*")
        downloaded_files = [f for f in downloaded_files if not f.endswith('.part')]
        
        if not downloaded_files:
            return None, "자막 파일을 다운로드하지 못했습니다."
            
        target_file = downloaded_files[0]
        
        # 파일 읽기 및 파싱
        full_text = ""
        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # JSON 포맷 우선 파싱
            if target_file.endswith('.json3') or target_file.endswith('.json'):
                try:
                    data = json.loads(content)
                    events = data.get('events', [])
                    full_text = " ".join(["".join([s.get('utf8', '') for s in e.get('segs', [])]) for e in events])
                except:
                    pass
            
            # 텍스트가 없으면 VTT/General 파싱
            if not full_text:
                lines = content.splitlines()
                text_lines = []
                for line in lines:
                    if '-->' in line: continue
                    if line.strip() == 'WEBVTT': continue
                    if line.strip().isdigit(): continue
                    
                    # 태그 제거
                    clean_line = re.sub(r'<[^>]+>', '', line).strip()
                    if clean_line:
                        text_lines.append(clean_line)
                
                # 중복 제거 (순서 유지)
                full_text = " ".join(list(dict.fromkeys(text_lines)))

        # 뒷정리
        for f in glob.glob(f"{temp_filename}*"):
            try: os.remove(f)
            except: pass

        # [중요] 길이 제한 코드(5000자) 제거됨
        
        if not full_text.strip():
             return None, "자막 내용이 비어있습니다."
             
        return full_text, None

    except Exception as e:
        # 에러 시 파일 정리
        for f in glob.glob(f"{temp_filename}*"):
            try: os.remove(f)
            except: pass
        return None, f"다운로드 실패: {str(e)}"

# === 기능 2: 댓글 추출 (YouTube API 기반) ===
def get_video_comments(api_key, video_id, max_results=20):
    """특정 비디오의 댓글 수집"""
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        response = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=max_results,
            order="relevance", # 관련성 순
            textFormat="plainText"
        ).execute()

        comments = []
        for item in response.get("items", []):
            comment = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "author": comment["authorDisplayName"],
                "text": comment["textDisplay"],
                "likes": comment["likeCount"],
                "date": comment["publishedAt"][:10] # YYYY-MM-DD
            })
        return comments

    except HttpError as e:
        if e.resp.status == 403 and "quotaExceeded" in str(e):
            st.error("🚨 일일 사용량 초과로 댓글을 불러올 수 없습니다. 내일 다시 시도해주세요.")
            return [{"author": "System", "text": "⛔ 일일 사용량 초과 (내일 오후 5시 리셋)", "likes": 0, "date": ""}]
        
        return [{"author": "System", "text": "댓글을 가져올 수 없습니다. (댓글 사용 중지됨)", "likes": 0, "date": ""}]

    except Exception as e:
        return [{"author": "Error", "text": str(e), "likes": 0, "date": ""}]

# === 팝업 (Dialogs) ===

@st.dialog("댓글 내용 확인 및 저장")
def open_comment_modal(video_id, video_title, api_key):
    if video_id not in st.session_state.comments_map:
        with st.spinner("댓글을 가져오는 중입니다..."):
            comments = get_video_comments(api_key, video_id)
            st.session_state.comments_map[video_id] = comments
    
    comments = st.session_state.comments_map.get(video_id, [])

    txt_output = io.StringIO()
    txt_output.write(f"영상 제목: {video_title}\n")
    txt_output.write(f"수집 일자: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    txt_output.write("=" * 50 + "\n\n")
    
    for c in comments:
        txt_output.write(f"작성자: {c['author']} ({c['date']}) [좋아요: {c['likes']}]\n")
        txt_output.write(f"내용: {c['text']}\n")
        txt_output.write("-" * 30 + "\n")
    
    txt_data = txt_output.getvalue()

    col1, col2 = st.columns([2, 1])
    with col1:
        st.write(f"총 **{len(comments)}**개의 댓글이 조회되었습니다.")
    with col2:
        st.download_button(
            label="💾 댓글 저장 (TXT)",
            data=txt_data,
            file_name=f"comments_{video_id}.txt",
            mime="text/plain",
            use_container_width=True,
            type="primary"
        )
    
    st.divider()

    if not comments:
        st.info("표시할 댓글이 없습니다.")
    else:
        with st.container(height=400):
            for c in comments:
                st.markdown(f"**{c['author']}** <span style='color:grey; font-size:0.8em'>({c['date']})</span> 👍 {c['likes']}", unsafe_allow_html=True)
                st.text(c['text'])
                st.markdown("---")

@st.dialog("스크립트 내용 확인 및 저장")
def open_script_modal(video_id, video_title):
    # 스크립트 데이터 확인 및 수집
    if video_id not in st.session_state.scripts_map:
        with st.spinner("자막(스크립트)을 추출하는 중입니다... (시간이 조금 걸릴 수 있습니다)"):
            script_text, error = get_youtube_transcript(video_id)
            if error:
                st.error(f"오류 발생: {error}")
                return
            st.session_state.scripts_map[video_id] = script_text
    
    script_content = st.session_state.scripts_map.get(video_id, "")

    # TXT 생성
    txt_output = io.StringIO()
    txt_output.write(f"영상 제목: {video_title}\n")
    txt_output.write(f"추출 일자: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    txt_output.write("=" * 50 + "\n\n")
    txt_output.write(script_content)
    
    txt_data = txt_output.getvalue()

    col1, col2 = st.columns([2, 1])
    with col1:
        st.write(f"스크립트 길이: **{len(script_content):,}**자")
    with col2:
        st.download_button(
            label="💾 스크립트 저장 (TXT)",
            data=txt_data,
            file_name=f"script_{video_id}.txt",
            mime="text/plain",
            use_container_width=True,
            type="primary"
        )
    
    st.divider()
    
    # [수정] 불필요한 st.container(height=...) 제거
    # 이제 텍스트 상자가 전체 높이를 사용하며 자체 스크롤을 가집니다.
    st.text_area("스크립트 내용", value=script_content, height=600, label_visibility="collapsed")


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
            
            # 채널 ID 및 비디오 ID 수집
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
                    content_details = video.get('contentDetails', {})
                    channel_id = snippet.get('channelId')
                    
                    view_count = int(statistics.get('viewCount', 0))
                    comment_count = int(statistics.get('commentCount', 0))
                    duration_str = content_details.get('duration', '')
                    duration_sec = parse_iso_duration(duration_str)
                    
                    # 채널 통계 가져오기
                    ch_stats = channel_stats_map.get(channel_id, {'subscriberCount': 0, 'viewCount': 0, 'videoCount': 0})
                    subscriber_count = ch_stats['subscriberCount']
                    channel_total_views = ch_stats['viewCount']
                    channel_video_count = ch_stats['videoCount']
                    
                    # 지표 계산
                    view_sub_ratio = 0.0
                    if subscriber_count > 0:
                        view_sub_ratio = view_count / subscriber_count
                        
                    avg_views = 0
                    if channel_video_count > 0:
                        avg_views = channel_total_views / channel_video_count
                    view_diff = view_count - avg_views

                    # ✅ [추가] 떡상 판독 로직 (평균 조회수 0일 경우 대비)
                    performance = "- "
                    if avg_views > 0:
                        ratio = (view_count - avg_views) / avg_views * 100 # 백분율 계산
                        
                        if ratio >= 200:      # 평균보다 3배 이상 (차이 200% 이상)
                            performance = "🔥🔥 초대박"
                        elif ratio >= 100:    # 평균보다 2배 이상 (차이 100% 이상)
                            performance = "🔥 떡상"
                        elif ratio >= 50:     # 평균보다 1.5배 이상 (차이 50% 이상)
                            performance = "👍 양호"                    
                    
                    video_data = {
                        'video_id': video_id, # ID 보존
                        'selected': False,
                        'thumbnail': snippet.get('thumbnails', {}).get('medium', {}).get('url', ''),
                        'url': f"https://youtube.com/watch?v={video_id}",
                        'title': snippet.get('title', ''),
                        'channel': snippet.get('channelTitle', ''),
                        'view_count': view_count,
                        'subscriber_count': subscriber_count,
                        'comment_count': comment_count,
                        'published_at': snippet.get('publishedAt', ''),
                        'view_sub_ratio': view_sub_ratio,
                        'view_diff': view_diff,
                        'avg_views': int(avg_views),  # [추가됨] 평균 조회수 저장
                        'performance': performance, # ✅ [추가] 성과 지표 저장
                        'duration_sec': duration_sec, # 영상 길이(초) 저장
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
        # 에러 코드가 403이고, 메시지에 quotaExceeded가 포함된 경우
        if e.resp.status == 403 and "quotaExceeded" in str(e):
            st.error(
                "🚨 **오늘의 유튜브 데이터 사용량(10,000 unit)이 모두 소진되었습니다!** 😢\n\n"
                "구글 정책에 따라 **매일 오후 5시(한국시간)**에 사용량이 초기화됩니다.\n"
                "내일 다시 방문해 주세요!", 
                icon="🚫"
            )
        else:
            st.error(f"YouTube API 오류: {e}")
        return []
    except Exception as e:
        st.error(f"알 수 없는 오류 발생: {e}")
        return []


def run_api_test(api_key):
    """API 키 테스트"""
    results = []
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
    return results

def update_card_selection(idx):
    """카드 뷰에서 체크박스 변경 시 DataFrame 업데이트"""
    st.session_state.search_results.at[idx, 'selected'] = st.session_state[f"card_chk_{idx}"]

# === UI Layout ===

st.title("YouTube 영상 검색기 📺")

# --- Sidebar ---
with st.sidebar:
    st.header("설정")
    
    # API Key
    #api_key = st.text_input("YouTube API Key", value=load_api_key(), type="password")


    # API Key (UI 숨김 처리)
    api_key = load_api_key() 
    
    # 연결 상태만 살짝 표시 (선택 사항)
    if api_key:
        st.caption("✅ YouTube API 연동됨")
    else:
        st.error("API 키 설정이 필요합니다.")

    
    # Search Settings
    st.header("검색 조건")
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

    # 검색 버튼
    if st.button("🔍 검색 시작", type="primary"):
        if not api_key:
            st.warning("API 키를 입력해주세요.")
        elif not keyword:
            st.warning("검색 키워드를 입력해주세요.")
        else:
            st.session_state.trigger_search = True
            # 새 검색 시 댓글/스크립트 데이터 초기화
            st.session_state.comments_map = {}
            st.session_state.scripts_map = {}

    st.divider()
    
    # API 연결 테스트
    with st.expander("🛠️ API 연결 확인"):
        if st.button("테스트 실행"):
            test_results = run_api_test(api_key)
            for icon, msg in test_results:
                if icon == "✅":
                    st.success(f"{icon} {msg}")
                else:
                    st.error(f"{icon} {msg}")

# --- Main Content ---

# 검색 로직 실행
if st.session_state.get('trigger_search', False):
    st.session_state.trigger_search = False # Reset trigger
    results = search_youtube(api_key, keyword, max_results, published_after, published_before)
    if results:
        st.session_state.search_results = pd.DataFrame(results)
        
        # 검색 성공 시 상태 저장
        state_to_save = {
            'search_results': st.session_state.search_results,
            'comments_map': st.session_state.comments_map, 
            'scripts_map': st.session_state.scripts_map,
            'keyword': keyword,
            'max_results': max_results,
            'period_option': period_option,
        }
        save_state(state_to_save)
        
        st.success(f"{len(results)}개의 영상을 찾았습니다.")
    else:
        st.warning("검색 결과가 없습니다.")

# 결과 표시 및 선택
if not st.session_state.search_results.empty:
    st.divider()
    
    # 뷰 모드 및 필터 선택
    col_view, col_filter, col_action = st.columns([1, 1.5, 3])
    
    with col_view:
        view_mode = st.radio("보기 모드", ["리스트", "카드"], horizontal=True, label_visibility="collapsed")
    
    with col_filter:
        # 필터링 옵션 (전체 / 숏폼 / 롱폼)
        filter_option = st.radio("필터", ["전체보기", "숏폼보기", "롱폼보기"], horizontal=True, index=0, label_visibility="collapsed")

    # 필터링 로직
    filtered_df = st.session_state.search_results
    if filter_option == "숏폼보기":
        filtered_df = st.session_state.search_results[st.session_state.search_results['duration_sec'] < 60]
    elif filter_option == "롱폼보기":
        filtered_df = st.session_state.search_results[st.session_state.search_results['duration_sec'] >= 60]

    # 전체 선택/해제 버튼 및 CSV 다운로드 (필터링된 항목 대상)
    with col_action:
        sub_c1, sub_c2, sub_c3, sub_c4 = st.columns([1, 1, 1.5, 1.5])
        with sub_c1:
            if st.button("✅ 전체 선택", key="select_all_btn", use_container_width=True):
                # 현재 필터링된 항목들의 인덱스를 찾아 원본 데이터프레임 업데이트
                for idx in filtered_df.index:
                    st.session_state.search_results.loc[idx, 'selected'] = True
                    # 카드 뷰 체크박스 키값도 함께 업데이트
                    st.session_state[f"card_chk_{idx}"] = True
                st.rerun()
        with sub_c2:
            if st.button("❌ 전체 해제", key="deselect_all_btn", use_container_width=True):
                for idx in filtered_df.index:
                    st.session_state.search_results.loc[idx, 'selected'] = False
                    # 카드 뷰 체크박스 키값도 함께 업데이트
                    st.session_state[f"card_chk_{idx}"] = False
                st.rerun()
        with sub_c3:
            # 현재 선택 상태 표시
            selected_count = len(st.session_state.search_results[st.session_state.search_results['selected']])
            filtered_count = len(filtered_df)
            st.caption(f"선택: **{selected_count}**개 / 표시: {filtered_count}개")
        with sub_c4:
            # [수정] 리스트 모드가 아닐 때만(카드 모드 등) CSV 다운로드 버튼 표시
            if view_mode != "리스트":
                # CSV 다운로드 버튼
                selected_rows = st.session_state.search_results[st.session_state.search_results['selected']]
                if len(selected_rows) > 0:
                    # CSV 데이터 생성
                    csv_columns = ['title', 'channel', 'url', 'view_count', 'subscriber_count', 
                                'comment_count', 'published_at', 'view_sub_ratio', 'view_diff', 'duration_sec']
                    download_df = selected_rows[csv_columns].copy()
                    
                    # CSV 변환 (Excel 한글 완벽 호환)
                    csv_buffer = io.BytesIO()
                    download_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig', sep=',')
                    csv_data = csv_buffer.getvalue()
                    
                    # 다운로드 버튼
                    st.download_button(
                        label="📥 CSV 다운로드",
                        data=csv_data,
                        file_name=f"youtube_selected_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True,
                        type="primary"
                    )
                else:
                    st.button("📥 CSV 다운로드", disabled=True, use_container_width=True)
        
    if view_mode == "리스트":
        # 데이터 에디터 (테이블) - 필터링된 데이터프레임 사용

        # ✅ [추가] 화면에 표시할 컬럼 순서 지정 (여기에 없는 컬럼은 숨겨집니다)
        display_columns = [
            "selected",         # 선택 체크박스
            "url",              # 영상 링크
            "title",            # 영상 제목
            "view_count",       # 조회수
            "subscriber_count", # 구독자수
            "comment_count",    # 댓글수
            "published_at",     # 게시일
            "performance"       # 성과지표 (불꽃 아이콘)
        ]

        # 주의: 필터링된 DF를 편집하면 원본에 반영해야 함.
        edited_df = st.data_editor(
            filtered_df,
            # ✅ [추가] 컬럼 순서 적용
            column_order=display_columns,
            column_config={
                "selected": st.column_config.CheckboxColumn(
                    "선택",
                    default=False,
                    width="small" # 체크박스 열 너비 최소화
                ),
                "thumbnail": st.column_config.ImageColumn(
                    "썸네일", help="영상 썸네일"
                ),
                "url": st.column_config.LinkColumn(
                    "URL", help="영상 링크",
                    max_chars=100 # 링크 텍스트가 너무 길면 잘라서 표시
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
                # [추가됨] 평균 조회수 컬럼 설정
                "avg_views": st.column_config.NumberColumn(
                    "평균 조회수", format="%d", help="채널 영상들의 평균 조회수"
                ),   
                "performance": st.column_config.TextColumn(
                    "성과지표", help="평균 조회수 대비 성과 (🔥: 2배 이상, 🔥🔥: 3배 이상)"
                ),             
                "duration_sec": st.column_config.NumberColumn(
                    "길이(초)", format="%d"
                )
            },
            # [수정됨] disabled 리스트에도 "avg_views" 추가 (수정 방지)
            #disabled=["thumbnail", "url", "title", "channel", "view_count", "subscriber_count", "comment_count", "published_at", "view_sub_ratio", "view_diff", "avg_views", "duration_sec"],
            disabled=["url", "title", "channel", "view_count", "subscriber_count", "comment_count", "published_at", "performance"],
            hide_index=True,
            width='stretch',
            height=600
        )
        # 상태 업데이트: 편집된(체크박스) 내용을 원본 session_state에 병합
        st.session_state.search_results.update(edited_df)
        
    else: # 카드 보기
        # 그리드 레이아웃 (4열)
        cols = st.columns(4)
        
        # [수정] 순차적인 인덱스(i)를 사용하여 빈 공간 없이 채우도록 enumerate 사용
        for i, (idx, row) in enumerate(filtered_df.iterrows()):
            vid = row['video_id']
            with cols[i % 4]: # i (화면 순서)를 기준으로 배치하여 빈 칸 방지
                # 카드 높이를 550으로 증가시켜 버튼 짤림 방지
                with st.container(border=True, height=550):
                    # 썸네일
                    st.image(row['thumbnail'], use_container_width=True)
                    
                    # 제목 (링크 포함)
                    st.markdown(f"**[{row['title']}]({row['url']})**")
                    
                    # 채널 및 통계
                    st.caption(f"{row['channel']}")
                    st.caption(f"👁️ {row['view_count']:,} | 💬 {row['comment_count']:,}")
                    st.caption(f"Ratio: {row['view_sub_ratio']:.4f} | Diff: {row['view_diff']:,.0f}")
                    # 만약 성과 지표(불꽃)도 있다면 여기에 포함
                    if 'performance' in row:
                        st.caption(row['performance'])
                    
                    # 하단 버튼 그룹 (선택 | 스크립트 | 댓글)
                    # 스크립트 버튼의 가로 사이즈를 확보하기 위해 비율 조절 (1단 텍스트 유지를 위해)
                    c1, c2, c3 = st.columns([0.6, 2.0, 1.4])
                    with c1:
                        st.checkbox(
                            "선택", 
                            value=row['selected'], 
                            key=f"card_chk_{idx}", # 키는 고유한 idx 사용 유지
                            on_change=update_card_selection,
                            args=(idx,),
                            label_visibility="collapsed"
                        )
                    
                    with c2:
                        if st.button("📜 스크립트", key=f"btn_script_{idx}", use_container_width=True):
                            open_script_modal(vid, row['title'])

                    with c3:
                        if st.button("💬 댓글", key=f"btn_comm_{idx}", use_container_width=True):
                            open_comment_modal(vid, row['title'], api_key)

    # 선택된 항목 수 표시
    selected_rows = st.session_state.search_results[st.session_state.search_results['selected']]
    if view_mode == "카드":
        st.divider()
        st.info(f"✅ 총 **{len(selected_rows)}**개 항목이 선택되었습니다.")
    elif len(selected_rows) > 0:
        st.info(f"✅ 총 **{len(selected_rows)}**개 항목이 선택되었습니다.")