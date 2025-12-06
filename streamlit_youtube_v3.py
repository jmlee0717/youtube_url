# ============================================================================
# [유튜브 떡상 채굴기] - UI/UX & Bug Fixed Version
# ============================================================================

import streamlit as st
import os
from datetime import datetime, timedelta, date
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
import time
import random
import unicodedata  # <--- 이 줄을 추가하세요 (한글 자소 합치기용)

# === [1] 기본 설정 및 시크릿 로드 ===
st.set_page_config(
    page_title="유튜브 떡상 채굴기 v0.1(베타)",
    page_icon="⛏️",
    layout="wide"
)


# [최종판] Fullscreen 클릭 이벤트 강제 차단
hide_elements = """
    <style>
    /* 1. 헤더/푸터 숨김 */
    header {visibility: hidden !important; height: 0px !important;}
    footer {visibility: hidden !important; display: none !important;}
    
    /* 2. 툴바 숨김 */
    [data-testid="stToolbar"],
    [data-testid="stStatusWidget"],
    .stAppDeployButton,
    .viewerBadge_container__1QSob,
    div[class*="viewerBadge"],
    a[href*="streamlit.io"] {
        display: none !important;
    }
    
    /* 3. Fullscreen 버튼 스타일 */
    button[title*="ullscreen"],
    button[title*="Fullscreen"],
    button[kind="header"],
    button[kind="headerNoPadding"],
    [data-testid="StyledFullScreenButton"],
    [data-testid="stBaseButton-header"] {
        pointer-events: none !important;
        opacity: 0.3 !important;
        cursor: not-allowed !important;
    }
    </style>
    
    <script>
    // JavaScript로 Fullscreen 클릭 이벤트 완전 차단
    function blockFullscreen() {
        const selectors = [
            'button[title*="ullscreen"]',
            'button[title*="Fullscreen"]', 
            'button[kind="header"]',
            'button[kind="headerNoPadding"]',
            '[data-testid="StyledFullScreenButton"]',
            '[data-testid="stBaseButton-header"]'
        ];
        
        selectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(button => {
                // 모든 클릭 이벤트 차단
                button.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    return false;
                }, true);
                
                // 마우스 이벤트도 차단
                button.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    return false;
                }, true);
                
                // 터치 이벤트 차단
                button.addEventListener('touchstart', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    return false;
                }, true);
                
                // 스타일 강제 적용
                button.style.pointerEvents = 'none';
                button.style.opacity = '0.3';
                button.style.cursor = 'not-allowed';
            });
        });
    }
    
    // 즉시 실행
    blockFullscreen();
    
    // 0.5초마다 재실행 (동적 생성 대응)
    setInterval(blockFullscreen, 500);
    
    // DOM 변경 감지
    const observer = new MutationObserver(blockFullscreen);
    observer.observe(document.body, {childList: true, subtree: true});
    </script>
    """
st.markdown(hide_elements, unsafe_allow_html=True)

# 이번 달 암호
CURRENT_MONTH_PW = st.secrets.get("MONTHLY_PW", "donjjul0717")

# === [2] 상태 관리 및 속도 제한 ===
STATE_FILE = 'app_state.pkl'

@st.cache_resource
class RateLimiter:
    def __init__(self):
        self.last_called = 0
    def try_acquire(self, min_interval=10):
        now = time.time()
        elapsed = now - self.last_called
        if elapsed < min_interval:
            return False, int(min_interval - elapsed) + 1
        self.last_called = now
        return True, 0

limiter = RateLimiter()

class UsageManager:
    def __init__(self):
        if 'usage_data' not in st.session_state:
            st.session_state.usage_data = {'date': str(date.today()), 'search_count': 0, 'script_count': 0}
            
    def check_reset(self):
        today = str(date.today())
        if st.session_state.usage_data['date'] != today:
            st.session_state.usage_data = {'date': today, 'search_count': 0, 'script_count': 0}
            
    def is_pro(self):
        return st.session_state.get("is_subscriber", False)

    def can_search(self):
        self.check_reset()
        if self.is_pro(): return True
        return st.session_state.usage_data['search_count'] < 10

    def increment_search(self):
        if not self.is_pro(): st.session_state.usage_data['search_count'] += 1

    def can_download_script(self):
        self.check_reset()
        if self.is_pro(): return True
        return st.session_state.usage_data['script_count'] < 5

    def increment_script(self):
        if not self.is_pro(): st.session_state.usage_data['script_count'] += 1
    
    # [수정] 누락되었던 함수 추가됨
    def get_status(self):
        self.check_reset()
        return st.session_state.usage_data

usage_mgr = UsageManager()

# === [3] 헬퍼 함수 ===
def save_editor_changes():
    """리스트 뷰 변경사항 반영"""
    state = st.session_state["list_view_editor"]
    current_df = st.session_state.get("_current_filtered_df", None)
    for display_idx, changes in state["edited_rows"].items():
        if current_df is not None and "_original_index" in current_df.columns:
            original_idx = current_df.at[int(display_idx), "_original_index"]
        else:
            original_idx = int(display_idx)
        for col, val in changes.items():
            st.session_state.search_results.at[original_idx, col] = val

def save_state(state_data):
    try:
        with open(STATE_FILE, 'wb') as f: pickle.dump(state_data, f)
    except: pass

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'rb') as f: return pickle.load(f)
        except: pass
    return {}

def parse_iso_duration(duration_str):
    if not duration_str: return 0
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match: return 0
    h, m, s = match.groups()
    return (int(h or 0)*3600) + (int(m or 0)*60) + int(s or 0)

def convert_to_kst(utc_str):
    if not utc_str: return ""
    try:
        dt_utc = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ")
        return (dt_utc + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")
    except: return utc_str

# 세션 초기화
if 'search_results' not in st.session_state:
    saved = load_state()
    if saved: st.session_state.update(saved)
    if 'search_results' not in st.session_state: st.session_state.search_results = pd.DataFrame()
    if 'comments_map' not in st.session_state: st.session_state.comments_map = {}
    if 'scripts_map' not in st.session_state: st.session_state.scripts_map = {}
    if not st.session_state.search_results.empty:
        for c in ['view_sub_ratio', 'view_diff', 'duration_sec']:
            if c not in st.session_state.search_results.columns:
                st.session_state.search_results[c] = 0
        # is_shorts 컬럼 추가 (기존 데이터 호환, 180초 기준)
        if 'is_shorts' not in st.session_state.search_results.columns:
            st.session_state.search_results['is_shorts'] = st.session_state.search_results['duration_sec'] < 180

# === [4] 핵심 기능 함수 (검색, 스크립트, 댓글) ===
def get_youtube_transcript(video_id):
    success, wait = limiter.try_acquire(10)
    if not success: return None, f"🚦 잠시 대기 ({wait}초)"
    time.sleep(random.uniform(0.5, 1.5))
    
    url = f"https://www.youtube.com/watch?v={video_id}"
    uid = str(uuid.uuid4())[:8]
    temp = f"temp_{uid}"
    
    # 청소
    for f in glob.glob(f"{temp}*"): 
        try: os.remove(f)
        except: pass

    try:
        ydl_opts = {'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True, 'subtitleslangs': ['ko'], 'outtmpl': temp, 'quiet': True, 'no_warnings': True}
        if os.path.exists('cookies.txt'): ydl_opts['cookiefile'] = 'cookies.txt'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])
        
        files = [f for f in glob.glob(f"{temp}*") if not f.endswith('.part')]
        if not files: return None, "자막 없음"
        
        full_text = ""
        with open(files[0], 'r', encoding='utf-8') as f:
            content = f.read()
            # JSON/VTT 파싱 로직 간소화
            lines = [re.sub(r'<[^>]+>', '', l).strip() for l in content.splitlines()]
            full_text = " ".join([l for l in lines if l and '-->' not in l and l != 'WEBVTT' and not l.isdigit()])
            
        for f in glob.glob(f"{temp}*"): os.remove(f)
        return full_text if full_text.strip() else None, "내용 없음" if not full_text.strip() else None
    except Exception as e:
        for f in glob.glob(f"{temp}*"): 
            try: os.remove(f)
            except: pass
        return None, "추출 실패"

def get_video_comments(api_key, video_id):
    if not api_key: return []
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        all_c = []
        token = None
        pages = 0
        max_pages = 10 if usage_mgr.is_pro() else 3
        
        while pages < max_pages:
            res = youtube.commentThreads().list(part="snippet,replies", videoId=video_id, maxResults=50, order="relevance", textFormat="plainText", pageToken=token).execute()
            for item in res.get("items", []):
                c = item["snippet"]["topLevelComment"]["snippet"]
                all_c.append({"author": c["authorDisplayName"], "text": c["textDisplay"], "likes": c["likeCount"], "date": c["publishedAt"][:10]})
                if "replies" in item:
                    for r in item["replies"]["comments"]:
                        rs = r["snippet"]
                        all_c.append({"author": rs["authorDisplayName"], "text": f"[대댓글] {rs['textDisplay']}", "likes": rs["likeCount"], "date": rs["publishedAt"][:10]})
            token = res.get("nextPageToken")
            pages += 1
            if not token: break
        all_c.sort(key=lambda x: x["likes"], reverse=True)
        return all_c
    except: return []

def run_api_test(api_key):
    """API 키 연결 테스트 함수"""
    if not api_key: return [("❌", "키를 입력해주세요.")]
    try:
        # 가벼운 쿼리로 테스트
        build("youtube", "v3", developerKey=api_key).search().list(q="test", part="id", maxResults=1).execute()
        return [("✅", "정상 연결되었습니다!")]
    except HttpError as e:
        if e.resp.status == 403:
            return [("❌", "연결 실패: 할당량 초과 또는 권한 없음")]
        return [("❌", f"연결 실패 (코드 {e.resp.status})")]
    except Exception as e:
        return [("❌", f"오류 발생: {str(e)}")]

# 👆👆 [여기까지 추가] 👆👆

@st.cache_data(show_spinner=False)
def search_youtube(api_key, keyword, limit_count, _p_after, _p_before, _duration_mode="전체"):
    if not api_key: return []
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        results = []
        token = None
        target = min(limit_count, 50)
        
        pb = st.progress(0); st_text = st.empty()
        
        while len(results) < target:
            st_text.text(f"채굴 중... ({len(results)}/{target})")

            # 기본 파라미터 설정
            params = {
                'q': keyword, 
                'part': "id,snippet", 
                'maxResults': min(50, target-len(results)), 
                'type': "video", 
                'pageToken': token, 
                'order': "relevance"
            }
            if _p_after: params['publishedAfter'] = _p_after
            if _p_before: params['publishedBefore'] = _p_before

            # [최적화] 숏폼 모드일 때는 API 차원에서 4분 미만만 가져오도록 1차 필터링 (속도 향상)
            if _duration_mode == "숏폼 (3분 이하)":
                params['videoDuration'] = 'short' 
            
            res = youtube.search().list(**params).execute()
            v_ids = [i['id']['videoId'] for i in res.get('items', [])]
            
            # 검색 결과가 없으면 종료
            if not v_ids: break
            
            ch_ids = [i['snippet']['channelId'] for i in res.get('items', [])]
            
            # 채널 통계
            ch_stats = {}
            if ch_ids:
                c_res = youtube.channels().list(part="statistics", id=','.join(set(ch_ids))).execute()
                for c in c_res.get('items',[]): ch_stats[c['id']] = {'sub': int(c['statistics'].get('subscriberCount',0)), 'view': int(c['statistics'].get('viewCount',0)), 'vid': int(c['statistics'].get('videoCount',0))}
            
            # 영상 통계
            v_res = youtube.videos().list(part="snippet,statistics,contentDetails", id=','.join(v_ids)).execute()
            for v in v_res.get('items',[]):
                vid = v['id']; sn = v['snippet']; stt = v.get('statistics',{}); cnt = v.get('contentDetails',{})
                vc = int(stt.get('viewCount',0)); cid = sn.get('channelId'); cst = ch_stats.get(cid, {'sub':0, 'view':0, 'vid':0})
                sub = cst['sub']; avg = cst['view']/cst['vid'] if cst['vid']>0 else 0
                
                perf = "- "
                if avg > 0:
                    r = (vc - avg)/avg * 100
                    if r >= 200: perf = "🔥🔥 초대박"
                    elif r >= 100: perf = "🔥 떡상"
                    elif r >= 50: perf = "👍 양호"
                
                # [중요] 길이 계산 (ISO -> 초 단위)
                duration_sec = parse_iso_duration(cnt.get('duration',''))
                is_shorts = duration_sec <= 180  # 3분(180초) 기준
                
                # 👇👇 [핵심 필터링] 3분 기준 엄격 필터링 로직 👇👇
                if _duration_mode == "숏폼 (3분 이하)" and duration_sec > 180:
                    continue # 3분 초과면 버림 (API는 4분까지 가져오므로 여기서 한번 더 자름)
                
                if _duration_mode == "롱폼 (3분 초과)" and duration_sec <= 180:
                    continue # 3분 이하면 버림
                # 👆👆 ------------------------------------- 👆👆
                
                results.append({
                    'video_id': vid, 'selected': False,
                    'thumbnail': sn.get('thumbnails',{}).get('medium',{}).get('url',''),
                    'url': f"https://youtube.com/watch?v={vid}",
                    # 👇👇 [핵심 수정] 가져올 때부터 'NFC'로 강력 접착! 👇👇
                    'title': unicodedata.normalize('NFC', sn.get('title','')), 
                    'channel': unicodedata.normalize('NFC', sn.get('channelTitle','')),
                    # 👆👆 ------------------------------------------- 👆👆
                    'view_count': vc, 'subscriber_count': sub, 'comment_count': int(stt.get('commentCount',0)),
                    'published_at': convert_to_kst(sn.get('publishedAt','')),
                    'view_sub_ratio': vc/sub if sub>0 else 0, 'view_diff': vc-avg,
                    'performance': perf, 'duration_sec': duration_sec, 'is_shorts': is_shorts
                })  
            
            pb.progress(min(len(results)/target, 1.0)); token = res.get('nextPageToken')
            if not token: break
        
        pb.empty(); st_text.empty()
        return results
    except Exception as e:
        st.error(f"검색 오류: {e}")
        return []

# === [5] 팝업 (모달) ===
@st.dialog("스크립트 확인")
def open_script_modal(video_id, title):
    limit = 5
    is_cached = video_id in st.session_state.scripts_map
    
    if not usage_mgr.is_pro() and not is_cached and not usage_mgr.can_download_script():
        st.error(f"🔒 일일 스크립트 추출 한도({limit}회) 초과!"); return

    if not is_cached:
        with st.spinner("⛏️ 대본 채굴 중..."):
            text, err = get_youtube_transcript(video_id)
            if err: st.error(err); return
            st.session_state.scripts_map[video_id] = text
            if not usage_mgr.is_pro(): usage_mgr.increment_script()

    content = st.session_state.scripts_map.get(video_id, "")
    c1, c2 = st.columns([2,1])
    c1.write(f"길이: {len(content):,}자")
    c2.download_button("💾 저장 (TXT)", content, f"script_{video_id}.txt", use_container_width=True)
    st.text_area("내용", content, height=500)

@st.dialog("댓글 확인")
def open_comment_modal(video_id, title, key):
    if not key: st.error("키 필요"); return
    if video_id not in st.session_state.comments_map:
        with st.spinner("댓글 로딩..."):
            st.session_state.comments_map[video_id] = get_video_comments(key, video_id)
    
    comments = st.session_state.comments_map.get(video_id, [])
    txt = io.StringIO()
    for c in comments: txt.write(f"[{c['author']}] {c['likes']}👍\n{c['text']}\n---\n")
    
    c1, c2 = st.columns([2,1])
    limit = "500개" if usage_mgr.is_pro() else "150개"
    c1.write(f"수집: {len(comments)}개 (최대 {limit})")

    # 👇 [추가] 해명 문구 삽입 (여기에 코드를 추가하세요)
    c1.caption("💡 유튜브 정책상 '스팸/검토대기/삭제' 댓글은 수집되지 않아 표시된 숫자와 다를 수 있습니다.")

    c2.download_button("💾 저장", txt.getvalue(), f"comments_{video_id}.txt", use_container_width=True)
    st.divider()
    for c in comments[:30]:
        st.markdown(f"**{c['author']}** 👍{c['likes']}")
        st.text(c['text'])
        st.markdown("---")

def update_sel(idx): st.session_state.search_results.at[idx, 'selected'] = st.session_state[f"chk_{idx}"]

# ============================================================================
# [6] 메인 UI 레이아웃
# ============================================================================

st.title("⛏️ 유튜브 떡상 채굴기 V0.1(베타)")
st.markdown("""
### 👉 알고리즘 깊은 곳에 숨겨진 '황금 키워드'와 '대본'을 캐내는 도구
*"맨땅에 헤딩하지 마세요. 떡상 영상은 **채굴**하는 것입니다."*
*"베타 버전인 만큼 버그가 있을 수 있습니다. 우리가 함께 이 프로그램을 완성해 나가는 겁니다."*
""")

# --- Sidebar UI ---
with st.sidebar:
    st.header("🔑 기본 설정")
    
    # 1. API Key 관리
    st.markdown("""
    *유튜브 API Key 입력*
    """)
    query_params = st.query_params
    saved_key = query_params.get("api_key", "")
    u_key = st.text_input("API Key", value=saved_key, type="password", label_visibility="collapsed", key="api_key_input").strip()
    
    if u_key != saved_key:
        st.query_params["api_key"] = u_key

    # API 연결 확인
    if u_key:
        with st.expander("🛠️ API 연결 확인"):
            if st.button("접속 테스트 실행", use_container_width=True):
                results = run_api_test(u_key)
                for icon, msg in results:
                    if icon == "✅": st.success(f"{icon} {msg}")
                    else: st.error(f"{icon} {msg}")
    
    st.divider()
    
    # 2. 구독자 인증
    st.header("🎁 구독자 혜택")
    with st.expander("🔐 모든 기능 무료로 풀기!", expanded=not usage_mgr.is_pro()):
        st.caption("구독자 비밀번호")
        pw_input = st.text_input("Password", value="", type="password", label_visibility="collapsed", key="pw_sub")
        
        if pw_input == CURRENT_MONTH_PW:
            if not st.session_state.get("is_subscriber", False):
                st.session_state.is_subscriber = True
                st.toast("🎉 인증 성공! 무제한 모드 ON")
                st.balloons()
            st.success("✅ 인증됨 (무제한 모드)")
        elif pw_input:
            st.error("⛔ 암호가 틀렸습니다!")
            st.session_state.is_subscriber = False

    if usage_mgr.is_pro():
        st.info("💎 현재 **구독자(무제한)** 모드입니다.")
    else:
        stt = usage_mgr.get_status()
        st.warning(f"📅 체험판: 검색 {stt['search_count']}/10회 | 스크립트 {stt['script_count']}/5회")

    st.divider()
    
    # 3. 검색 조건 (여기가 중요합니다!)
    st.header("검색 조건")
    st.caption("키워드")
    kw = st.text_input("키워드", value="60대 후회 사연", label_visibility="collapsed") # 추천 키워드 기본값 적용
    
    limit_cnt = 50 if usage_mgr.is_pro() else 30
    st.caption(f"최대 검색 결과: {limit_cnt}개")
    
    # [날짜 계산 로직 복구]
    st.caption("기간")
    prd = st.selectbox("기간", ["전체","최근 7일","최근 30일","사용자 지정"], label_visibility="collapsed")
    
    p_after = None
    p_before = None
    
    if prd=="최근 7일": 
        p_after=(datetime.now()-timedelta(7)).strftime("%Y-%m-%dT00:00:00Z")
    elif prd=="최근 30일": 
        p_after=(datetime.now()-timedelta(30)).strftime("%Y-%m-%dT00:00:00Z")
    elif prd=="사용자 지정":
        c_d1, c_d2 = st.columns(2)
        with c_d1: s_d = st.date_input("시작일", value=datetime.now()-timedelta(30))
        with c_d2: e_d = st.date_input("종료일", value=datetime.now())
        if s_d and e_d:
            p_after = s_d.strftime("%Y-%m-%dT00:00:00Z")
            p_before = e_d.strftime("%Y-%m-%dT23:59:59Z")

    # [영상 길이 필터 (3분 기준)]
    st.caption("영상 길이 필터")
    dur_option = st.radio(
        "영상 길이 선택", 
        ["전체", "숏폼 (3분 이하)", "롱폼 (3분 초과)"],
        index=2, # 기본값을 롱폼으로 설정 (시연 편의상)
        horizontal=True,
        label_visibility="collapsed"
    )

    st.write("") 
    if st.button("🔍 검색 시작", type="primary", use_container_width=True):
        if not u_key: st.toast("API Key를 입력해주세요!", icon="🚨")
        elif not usage_mgr.can_search(): st.error("🔒 일일 검색 한도 초과!"); st.info("구독자 비밀번호를 입력하세요!")
        else:
            st.session_state.trigger = True
            st.session_state.comments_map = {}
            st.session_state.scripts_map = {}
            usage_mgr.increment_search()

# --- Main Content (함수 호출부) ---
if st.session_state.get('trigger', False):
    st.session_state.trigger = False
    
    # 검색 함수 호출 (수정된 인자 전달)
    res = search_youtube(u_key, kw, limit_cnt, p_after, p_before, dur_option)
    
    if res:
        st.session_state.search_results = pd.DataFrame(res)
        save_state({'search_results':st.session_state.search_results})
        st.toast(f"🎉 채굴 성공! {len(res)}개의 영상을 찾았습니다.", icon="⛏️")
        st.balloons()        
    else: st.warning("결과가 없습니다.")

# 결과 화면
if not st.session_state.search_results.empty:
    st.divider()
    
    # 상단 컨트롤 바 (리스트/카드, 필터, 버튼)
    c_top = st.columns([1.5, 3, 2, 1.5])
    
    # 1. 뷰 모드
    with c_top[0]:
        view = st.radio("뷰 모드", ["리스트", "카드"], horizontal=True, label_visibility="collapsed")
    
    # 2. 필터 및 정렬
    with c_top[1]:
        c_f1, c_f2 = st.columns([2, 2])
        filter_opt = c_f1.radio("필터", ["전체", "숏폼", "롱폼"], horizontal=True, label_visibility="collapsed")
        sort_opt = c_f2.selectbox("정렬", ["기본순 (최신날짜)", "조회수 높은순", "구독자 대비 조회수(떡상순)", "성과지표순"], label_visibility="collapsed")
    
    # 데이터 필터링 & 정렬 적용
    df = st.session_state.search_results.copy()
    if filter_opt == "숏폼": 
        df = df[df['is_shorts'] == True]
    elif filter_opt == "롱폼": 
        df = df[df['is_shorts'] == False]
    
    if "조회수" in sort_opt: df = df.sort_values('view_count', ascending=False)
    elif "떡상" in sort_opt: df = df.sort_values('view_sub_ratio', ascending=False)
    elif "성과" in sort_opt: df = df.sort_values('performance', ascending=False)
    else: df = df.sort_values('published_at', ascending=False) # 기본
    
    df["_original_index"] = df.index
    df = df.reset_index(drop=True)
    st.session_state["_current_filtered_df"] = df

    # 3. 전체 선택/해제
    with c_top[2]:
        bt1, bt2 = st.columns(2)
        if bt1.button("✅ 전체 선택", use_container_width=True):
            for i in df.index:
                st.session_state.search_results.loc[df.at[i,"_original_index"],'selected']=True
                st.session_state[f"chk_{i}"]=True
            st.rerun()
        if bt2.button("❌ 전체 해제", use_container_width=True):
            for i in df.index:
                st.session_state.search_results.loc[df.at[i,"_original_index"],'selected']=False
                st.session_state[f"chk_{i}"]=False
            st.rerun()

    # 4. CSV 다운로드 (우측 끝)
    with c_top[3]:
        # 1. 체크된 항목만 가져오기
        sel_rows = st.session_state.search_results[st.session_state.search_results['selected']].copy()
        sel_count = len(sel_rows)
        
        st.caption(f"선택: {sel_count}개")
        
        if usage_mgr.is_pro():
            if sel_count > 0:
                # 👇👇 [핵심 추가] 화면에 보이는 '정렬 옵션'을 그대로 적용 👇👇
                if "조회수" in sort_opt: 
                    sel_rows = sel_rows.sort_values('view_count', ascending=False)
                elif "조회구독비율" in sort_opt: 
                    sel_rows = sel_rows.sort_values('view_sub_ratio', ascending=False)
                elif "성과" in sort_opt: 
                    sel_rows = sel_rows.sort_values('performance', ascending=False) # 문자열 정렬이라 완벽하진 않지만 근사치 제공
                elif "평균대비차이" in sort_opt: 
                    sel_rows = sel_rows.sort_values('view_diff', ascending=False)
                elif "영상길이" in sort_opt: 
                    sel_rows = sel_rows.sort_values('duration_sec', ascending=False)
                else: 
                    sel_rows = sel_rows.sort_values('published_at', ascending=False) # 기본값
                # 👆👆 ---------------------------------------------------- 👆👆

                export_df = sel_rows
                
                # 한글 자소 분리 방지 (NFC 정규화)
                for col in ['title', 'channel']: 
                    if col in export_df.columns:
                        export_df[col] = export_df[col].apply(
                            lambda x: unicodedata.normalize('NFC', str(x)) if isinstance(x, str) else x
                        )

                # CSV 변환 (사용자가 보기 편한 컬럼 순서로 배치)
                csv = export_df[['thumbnail','title', 'url', 'view_count', 'published_at', 'view_sub_ratio', 'performance', 'duration_sec', 'view_diff', 'subscriber_count', 'comment_count', 'is_shorts', 'channel', 'video_id']].to_csv(index=False).encode('utf-8-sig')
                
                st.download_button(
                    label="📥 CSV 다운로드", 
                    data=csv, 
                    file_name="youtube_selected_data.csv", 
                    mime="text/csv", 
                    use_container_width=True
                )
            else:
                st.button("📥 CSV 다운로드", disabled=True, use_container_width=True, help="리스트에서 영상을 먼저 선택해주세요.")
        else:
            st.button("🔒 CSV (구독자용)", disabled=True, use_container_width=True, help="구독자 전용 기능입니다.")
# === [리스트 뷰 옵션 설정] ===
    # 1. [설정] 전체 옵션 컬럼 정의
    optional_cols = [
        "view_count", "subscriber_count", "comment_count", 
        "published_at", "performance", "duration_sec", 
        "view_sub_ratio", "view_diff"
    ]
    
    # 2. [초기화] 세션 상태 안전 초기화
    if "view_options_selected" not in st.session_state:
        st.session_state.view_options_selected = [
            "view_count", "subscriber_count", "comment_count", 
            "published_at", "performance"
        ]

    # 3. [UI] 컬럼 선택 기능 - 리스트 뷰일 때만 표시
    if view == "리스트":
        # 오른쪽 여백 확보 (아이콘과 겹치지 않도록)
        col_multi, col_space = st.columns([0.88, 0.12])
        with col_multi:
            selected_cols = st.multiselect(
                "📊 리스트 표시 항목:",
                options=optional_cols,
                default=st.session_state.view_options_selected,
                format_func=lambda x: {
                    "view_count": "조회수", "subscriber_count": "구독자수", 
                    "comment_count": "댓글수", "published_at": "발행시간", 
                    "performance": "성과지표", "duration_sec": "영상길이",
                    "view_sub_ratio": "조회/구독 비율", "view_diff": "조회수 차이"
                }.get(x, x)
            )
        
        # 4. 선택값을 session_state에 저장 (뷰 전환 시에도 유지)
        st.session_state.view_options_selected = selected_cols
    else:
        # 카드 뷰일 때는 저장된 값 사용
        selected_cols = st.session_state.view_options_selected

# === [리스트 뷰] ===
    if view == "리스트":
        # 4. [적용] 고정 컬럼 + 사용자 선택 컬럼 합치기
        fixed_cols = ["selected", "thumbnail", "url", "title"]
        final_col_order = fixed_cols + selected_cols

        # 5. [표시] 데이터 에디터

        # Show/hide columns 아이콘 숨기기
        st.markdown("""
            <style>
            /* Show/hide columns 버튼 숨기기 */
            [data-testid="stDataFrameToolbarButton"]:first-of-type,
            button[kind="icon"][title*="column"],
            button[kind="icon"][title*="Column"],
            button[aria-label*="column"],
            button[aria-label*="Column"],
            div[data-testid="stDataFrameToolbar"] button:first-child {
                display: none !important;
                visibility: hidden !important;
            }
            </style>
        """, unsafe_allow_html=True)


        st.data_editor(
            df, 
            key="list_view_editor",
            column_order=final_col_order, 
            column_config={
                "selected": st.column_config.CheckboxColumn("선택", width="small"),
                "thumbnail": st.column_config.ImageColumn("썸네일", help="클릭하여 확대"),
                "url": st.column_config.LinkColumn("URL", max_chars=40, width="small"),
                "title": st.column_config.TextColumn("제목", width="large"),
                
                # --- 동적 컬럼 설정 ---
                "view_count": st.column_config.NumberColumn("조회수", format="%d"),
                "subscriber_count": st.column_config.NumberColumn("구독자수", format="%d"),
                "comment_count": st.column_config.NumberColumn("댓글수", format="%d"),
                "published_at": st.column_config.TextColumn("발행시간"),
                "performance": st.column_config.TextColumn("성과지표"),
                "duration_sec": st.column_config.NumberColumn("길이(초)", format="%d초"),
                "view_sub_ratio": st.column_config.NumberColumn("조회/구독비", format="%.2f"),
                "view_diff": st.column_config.NumberColumn("평균대비 차이", format="%d")
            },
            disabled=["url", "title"] + optional_cols,
            hide_index=True, 
            use_container_width=True, 
            height=600, 
            on_change=save_editor_changes
        )

# === [카드 뷰] ===
    else:
        # [수정] 4개씩 끊어서 로우(Row) 단위로 렌더링하여 줄맞춤 강제
        # 이렇게 하면 윗줄 카드의 높이가 달라도 다음 줄은 항상 수평이 맞습니다.
        for i in range(0, len(df), 4):
            # 4개씩 데이터 슬라이싱
            batch = df.iloc[i : i+4]
            cols = st.columns(4) # 매 줄마다 새로운 컬럼 생성
            
            for j, (idx, row) in enumerate(batch.iterrows()):
                with cols[j]:
                    # 버튼이 추가되었으므로 카드 높이를 520 -> 580 정도로 늘려주세요
                    with st.container(border=True, height=580):
                        # 1. 썸네일
                        st.image(row['thumbnail'], use_container_width=True)
                        
                        # 2. 제목
                        st.markdown(f"**[{row['title']}]({row['url']})**", unsafe_allow_html=True)
                        
                        # 3. 채널명
                        st.caption(f"{row['channel']}")
                        
                        # 4. 통계 정보
                        c_stat1, c_stat2 = st.columns(2)
                        c_stat1.caption(f"👁️ {row['view_count']:,}")
                        c_stat2.caption(f"💬 {row['comment_count']:,}")
                        
                        st.caption(f"Ratio: {row['view_sub_ratio']:.4f} | Diff: {row['view_diff']:,.0f}")
                        
                        # 5. 성과 지표
                        if row['performance'] != "- ": 
                            st.markdown(f"🚀 **{row['performance']}**")
                        else: 
                            st.write("") # 줄맞춤용 공백

                        # 6. 하단 버튼 그룹 (체크박스 | 스크립트 | 썸네일/댓글)
                        # 공간 확보를 위해 ratio 조정
                        c_b1, c_b2, c_b3 = st.columns([0.6, 2, 1.4])
                        
                        # (1) 선택 체크박스
                        if f"chk_{idx}" not in st.session_state: 
                            st.session_state[f"chk_{idx}"] = row['selected']
                        
                        c_b1.checkbox("선택", key=f"chk_{idx}", on_change=update_sel, args=(df.at[idx, "_original_index"],), label_visibility="collapsed")
                        
                        # (2) 스크립트 & 썸네일 버튼 (가운데 컬럼에 세로로 배치)
                        with c_b2:
                            if st.button("📜 스크립트", key=f"s_{idx}", use_container_width=True):
                                open_script_modal(row['video_id'], row['title'])
                            
                            # [추가됨] 썸네일 다운로드 버튼
                            thumb_url = f"https://img.youtube.com/vi/{row['video_id']}/maxresdefault.jpg"
                            st.link_button("🖼️ 썸네일", thumb_url, use_container_width=True, help="고화질 썸네일 보기")
                        
                        # (3) 댓글 버튼
                        if c_b3.button("💬 댓글", key=f"c_{idx}", use_container_width=True):
                            open_comment_modal(row['video_id'], row['title'], u_key)