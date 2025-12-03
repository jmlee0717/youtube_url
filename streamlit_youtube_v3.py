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

# === [1] 기본 설정 및 시크릿 로드 ===
st.set_page_config(
    page_title="유튜브 떡상 채굴기",
    page_icon="⛏️",
    layout="wide"
)

# Secrets에서 접두어 가져오기 (기본값: donjjul)
SECRET_PREFIX = st.secrets.get("SUB_PREFIX", "donjjul")
# 이번 달 정답 생성 (예: donjjul12)
CURRENT_MONTH_PW = f"{SECRET_PREFIX}{datetime.now().strftime('%m')}"

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
def search_youtube(api_key, keyword, limit_count, _p_after, _p_before):
    if not api_key: return []
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        results = []
        token = None
        target = min(limit_count, 50)
        
        pb = st.progress(0); st_text = st.empty()
        
        while len(results) < target:
            st_text.text(f"채굴 중... ({len(results)}/{target})")
            params = {'q':keyword, 'part':"id,snippet", 'maxResults':min(50, target-len(results)), 'type':"video", 'pageToken':token, 'order':"relevance"}
            if _p_after: params['publishedAfter'] = _p_after
            if _p_before: params['publishedBefore'] = _p_before
            
            res = youtube.search().list(**params).execute()
            v_ids = [i['id']['videoId'] for i in res.get('items', [])]; ch_ids = [i['snippet']['channelId'] for i in res.get('items', [])]
            if not v_ids: break
            
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
                    
                results.append({
                    'video_id': vid, 'selected': False,
                    'thumbnail': sn.get('thumbnails',{}).get('medium',{}).get('url',''),
                    'url': f"https://youtube.com/watch?v={vid}",
                    'title': sn.get('title',''), 'channel': sn.get('channelTitle',''),
                    'view_count': vc, 'subscriber_count': sub, 'comment_count': int(stt.get('commentCount',0)),
                    'published_at': convert_to_kst(sn.get('publishedAt','')),
                    'view_sub_ratio': vc/sub if sub>0 else 0, 'view_diff': vc-avg,
                    'performance': perf, 'duration_sec': parse_iso_duration(cnt.get('duration',''))
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

st.title("⛏️ 유튜브 떡상 채굴기")
st.markdown("""
### 👉 알고리즘 깊은 곳에 숨겨진 '황금 키워드'와 '대본'을 캐내는 도구
*"맨땅에 헤딩하지 마세요. 떡상 영상은 **채굴**하는 것입니다."*
""")

# --- Sidebar UI (이미지와 동일하게 구성) ---
with st.sidebar:
    st.header("🔑 기본 설정")
    #st.caption("API Key 입력 (필수)")
    #u_key = st.text_input("API Key", type="password", label_visibility="collapsed").strip()

    # 👇👇 [아래 코드로 교체하세요] 👇👇
    
    st.caption("API Key 입력 (필수)")
    
    # 1. URL(주소창)에 저장된 키가 있는지 확인
    # (새로고침 해도 URL에 남아있는 정보를 가져옵니다)
    query_params = st.query_params
    saved_key = query_params.get("api_key", "")
    
    # 2. 입력창 생성 (저장된 키를 기본값으로 채워넣음)
    u_key = st.text_input("API Key", value=saved_key, type="password", label_visibility="collapsed", key="api_key_input").strip()
    
    # 3. 입력값이 바뀌면 URL 업데이트 (새로고침 대비 저장)
    if u_key != saved_key:
        st.query_params["api_key"] = u_key


    # 👇👇 [여기부터 추가하세요] 👇👇
    # ---------------------------------------------------------
    # API 연결 확인 기능 (Expander)
    # ---------------------------------------------------------
    if u_key: # 키가 입력되었을 때만 표시
        with st.expander("🛠️ API 연결 확인"):
            if st.button("접속 테스트 실행", use_container_width=True):
                # run_api_test 함수 호출 (코드 상단에 정의됨)
                results = run_api_test(u_key)
                for icon, msg in results:
                    if icon == "✅":
                        st.success(f"{icon} {msg}")
                    else:
                        st.error(f"{icon} {msg}")
    # ---------------------------------------------------------
    # 👆👆 [여기까지 추가] 👆👆    
    
    st.divider()
    
    st.header("🎁 구독자 혜택")
    
    # Expander: 구독자 인증
    with st.expander("🔐 모든 기능 무료로 풀기!", expanded=not usage_mgr.is_pro()):
        st.markdown(f"""
        **돈쭐파파 구독자**라면 제한 없이 사용하세요!
        
        비밀번호는 [제 유튜브 채널](https://www.youtube.com/@%EC%9B%94%EC%B2%9C%EC%95%8C%EA%B3%A0%EB%A6%AC%EC%A6%98)의 최신 영상 더보기란에 있습니다.
        """)
        
        st.caption("구독자 비밀번호")
        pw_input = st.text_input("Password", type="password", label_visibility="collapsed", key="pw_sub")
        
        if pw_input == CURRENT_MONTH_PW:
            st.session_state.is_subscriber = True
            st.success("🎉 인증 성공! 무제한 모드 ON")
        elif pw_input:
            st.error("비밀번호가 틀렸습니다.")
            st.session_state.is_subscriber = False
            
    # 상태 표시 파란 박스
    if usage_mgr.is_pro():
        st.info("💎 현재 **구독자(무제한)** 모드입니다.")
    else:
        stt = usage_mgr.get_status()
        st.warning(f"📅 체험판: 검색 {stt['search_count']}/10회 | 스크립트 {stt['script_count']}/5회")

    st.divider()
    
    # 검색 조건
    st.header("검색 조건")
    st.caption("키워드")
    kw = st.text_input("키워드", value="쇼츠 수익", label_visibility="collapsed")
    
    limit_cnt = 50 if usage_mgr.is_pro() else 30
    st.caption(f"최대 검색 결과: {limit_cnt}개")
    
    st.caption("기간")
    prd = st.selectbox("기간", ["전체","최근 7일","최근 30일"], label_visibility="collapsed")
    
    p_after = None
    if prd=="최근 7일": p_after=(datetime.now()-timedelta(7)).strftime("%Y-%m-%dT00:00:00Z")
    elif prd=="최근 30일": p_after=(datetime.now()-timedelta(30)).strftime("%Y-%m-%dT00:00:00Z")
    
    st.write("") # 간격
    if st.button("🔍 검색 시작", type="primary", use_container_width=True):
        if not u_key: st.toast("API Key를 입력해주세요!", icon="🚨")
        elif not usage_mgr.can_search(): st.error("🔒 일일 검색 한도 초과!"); st.info("구독자 비밀번호를 입력하세요!")
        else:
            st.session_state.trigger = True
            st.session_state.comments_map = {}
            st.session_state.scripts_map = {}
            usage_mgr.increment_search()

# --- Main Content ---
if st.session_state.get('trigger', False):
    st.session_state.trigger = False
    limit_cnt = 50 if usage_mgr.is_pro() else 30
    res = search_youtube(u_key, kw, limit_cnt, p_after, None)
    if res:
        st.session_state.search_results = pd.DataFrame(res)
        save_state({'search_results':st.session_state.search_results})
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
    if filter_opt == "숏폼": df = df[df['duration_sec'] < 60]
    elif filter_opt == "롱폼": df = df[df['duration_sec'] >= 60]
    
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

    # 4. CSV 다운로드 (우측 끝) - 리스트 뷰에서는 숨김 처리
    with c_top[3]:
        # [수정됨] 뷰 모드가 '카드'일 때만 다운로드 버튼 표시
        if view == "카드":
            sel_count = len(st.session_state.search_results[st.session_state.search_results['selected']])
            st.caption(f"선택: {sel_count}개")
            
            if usage_mgr.is_pro():
                sel_rows = st.session_state.search_results[st.session_state.search_results['selected']]
                if not sel_rows.empty:
                    csv = sel_rows[['title', 'url', 'view_count', 'published_at']].to_csv(index=False).encode('utf-8-sig')
                    st.download_button("📥 CSV 다운로드", csv, "youtube_data.csv", "text/csv", use_container_width=True)
                else:
                    st.button("📥 CSV 다운로드", disabled=True, use_container_width=True)
            else:
                st.button("🔒 CSV (구독자용)", disabled=True, use_container_width=True, help="비밀번호 입력 시 활성화")
        else:
            # 리스트 뷰일 때는 아무것도 표시하지 않음
            st.empty()

    # === [리스트 뷰] ===
    if view == "리스트":
        st.data_editor(
            df, key="list_view_editor",
            column_order=["selected", "url", "title", "view_count", "subscriber_count", "comment_count", "published_at", "performance"],
            column_config={
                "selected": st.column_config.CheckboxColumn("선택", width="small"),
                "url": st.column_config.LinkColumn("URL", max_chars=40, width="small"),
                "title": st.column_config.TextColumn("제목", width="large"),
                "view_count": st.column_config.NumberColumn("조회수", format="%d"),
                "subscriber_count": st.column_config.NumberColumn("구독자수", format="%d"),
                "comment_count": st.column_config.NumberColumn("댓글수", format="%d"),
                "published_at": st.column_config.TextColumn("발행시간"),
                "performance": st.column_config.TextColumn("성과지표"),
            },
            disabled=["url", "title", "view_count", "subscriber_count", "comment_count", "published_at", "performance"],
            hide_index=True, use_container_width=True, height=600, on_change=save_editor_changes
        )

    # === [카드 뷰] ===
    else:
        cols = st.columns(4)
        for i, (idx, row) in enumerate(df.iterrows()):
            with cols[i % 4]:
                with st.container(border=True, height=520):
                    st.image(row['thumbnail'], use_container_width=True)
                    st.markdown(f"**[{row['title']}]({row['url']})**", unsafe_allow_html=True)
                    st.caption(f"{row['channel']}")
                    
                    # 통계 및 성과
                    c_stat1, c_stat2 = st.columns(2)
                    c_stat1.caption(f"👁️ {row['view_count']:,}")
                    c_stat2.caption(f"💬 {row['comment_count']:,}")
                    
                    st.caption(f"Ratio: {row['view_sub_ratio']:.4f} | Diff: {row['view_diff']:,.0f}")
                    if row['performance'] != "- ": st.markdown(f"🚀 **{row['performance']}**")
                    else: st.write("") # 줄맞춤용

                    # 하단 버튼 (체크박스, 스크립트, 댓글)
                    c_b1, c_b2, c_b3 = st.columns([0.6, 2, 1.4])
                    if f"chk_{idx}" not in st.session_state: st.session_state[f"chk_{idx}"] = row['selected']
                    
                    c_b1.checkbox("선택", key=f"chk_{idx}", on_change=update_sel, args=(df.at[idx, "_original_index"],), label_visibility="collapsed")
                    
                    if c_b2.button("📜 스크립트", key=f"s_{idx}", use_container_width=True):
                        open_script_modal(row['video_id'], row['title'])
                    
                    if c_b3.button("💬 댓글", key=f"c_{idx}", use_container_width=True):
                        open_comment_modal(row['video_id'], row['title'], u_key)