"""
app.py
------
Instagram Relations & Automation Dashboard for @darsal1a.
Built with Streamlit, SQLite, and authenticated browser session requests.
"""

import html
import sys
import time
import random
import subprocess
import streamlit as st
from datetime import datetime

import instagram_service
import instagram_actions

# ---------------------------------------------------------------------------
# Page Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="@darsal1a | Instagram Relations Tracker",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------------------------
# Dark / Glassmorphic Custom Styling
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap');

/* Base page styles */
html, body, [class*="css"], .stApp {
    font-family: 'Plus Jakarta Sans', sans-serif;
    background-color: #0b0c10;
    color: #e2e8f0;
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Outfit', sans-serif;
    font-weight: 700;
    letter-spacing: -0.5px;
}

/* Glassmorphic card container */
.glass-card {
    background: rgba(22, 27, 38, 0.65);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 18px;
    padding: 22px 26px;
    backdrop-filter: blur(14px);
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.4);
    margin-bottom: 20px;
    transition: border-color 0.3s ease, box-shadow 0.3s ease;
}

.glass-card:hover {
    border-color: rgba(139, 92, 246, 0.25);
    box-shadow: 0 12px 36px 0 rgba(139, 92, 246, 0.08);
}

/* Metric boxes */
.metric-box {
    text-align: center;
    padding: 20px 14px;
    border-radius: 16px;
    background: linear-gradient(135deg, rgba(26, 31, 46, 0.85) 0%, rgba(17, 21, 31, 0.85) 100%);
    border: 1px solid rgba(255, 255, 255, 0.06);
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    transition: transform 0.3s ease, border-color 0.3s ease;
}

.metric-box:hover {
    transform: translateY(-3px);
    border-color: rgba(168, 85, 247, 0.35);
    box-shadow: 0 10px 25px rgba(168, 85, 247, 0.12);
}

.metric-val {
    font-size: 2.6rem;
    font-weight: 800;
    font-family: 'Outfit', sans-serif;
    background: linear-gradient(135deg, #c084fc 0%, #f472b6 50%, #fb7185 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 2px;
    line-height: 1.1;
}

.metric-lbl {
    font-size: 0.8rem;
    font-weight: 600;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 1.5px;
}

/* Gradient accents */
.gradient-text {
    background: linear-gradient(135deg, #a855f7 0%, #ec4899 50%, #f43f5e 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800;
}

/* Target profile badge */
.target-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(168, 85, 247, 0.15);
    border: 1px solid rgba(168, 85, 247, 0.35);
    padding: 6px 16px;
    border-radius: 9999px;
    font-size: 0.85rem;
    font-weight: 600;
    color: #e9d5ff;
}

/* Badges */
.badge-new {
    background-color: rgba(16, 185, 129, 0.15);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.3);
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
}

.badge-lost {
    background-color: rgba(239, 68, 68, 0.15);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.3);
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
}

.badge-unfollowed {
    background-color: rgba(168, 85, 247, 0.15);
    color: #c084fc;
    border: 1px solid rgba(168, 85, 247, 0.3);
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
}

.user-tag {
    display: inline-block;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 0.88rem;
    font-weight: 500;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: #cbd5e1;
    margin: 4px;
    transition: all 0.2s ease;
    text-decoration: none;
}

.user-tag:hover {
    background: rgba(168, 85, 247, 0.18);
    border-color: rgba(168, 85, 247, 0.4);
    color: #f3e8ff;
    transform: translateY(-1px);
}

/* Custom button styling */
.stButton>button {
    background: linear-gradient(135deg, #8b5cf6 0%, #ec4899 100%) !important;
    color: white !important;
    border: none !important;
    padding: 9px 20px !important;
    border-radius: 12px !important;
    font-weight: 600 !important;
    transition: all 0.3s ease !important;
    box-shadow: 0 4px 15px rgba(139, 92, 246, 0.25) !important;
}

.stButton>button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 22px rgba(139, 92, 246, 0.45) !important;
}

/* Bulk unfollow prominent red button */
div[data-testid="stButton"] button:has(div:contains("Unfollow Selected")),
div[data-testid="stButton"] button:has(span:contains("Unfollow Selected")),
div[data-testid="stButton"] button:has(p:contains("Unfollow Selected")) {
    background: linear-gradient(135deg, #ef4444 0%, #dc2626 50%, #991b1b 100%) !important;
    color: #ffffff !important;
    font-size: 1.08rem !important;
    font-weight: 800 !important;
    padding: 12px 24px !important;
    border-radius: 14px !important;
    box-shadow: 0 6px 25px rgba(239, 68, 68, 0.5) !important;
    border: 1px solid rgba(255, 255, 255, 0.2) !important;
}
div[data-testid="stButton"] button:has(div:contains("Unfollow Selected")):hover,
div[data-testid="stButton"] button:has(span:contains("Unfollow Selected")):hover,
div[data-testid="stButton"] button:has(p:contains("Unfollow Selected")):hover {
    transform: translateY(-2px) scale(1.01) !important;
    box-shadow: 0 10px 32px rgba(239, 68, 68, 0.7) !important;
}

/* Input fields */
.stTextInput>div>div>input {
    background-color: #171b26 !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    color: #f1f5f9 !important;
    border-radius: 10px !important;
}

/* Scrollbar */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}
::-webkit-scrollbar-track {
    background: #0b0c10;
}
::-webkit-scrollbar-thumb {
    background: #1e293b;
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: #334155;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Database & Relationship State
# ---------------------------------------------------------------------------
TARGET = instagram_service.TARGET_USERNAME

@st.cache_data(show_spinner=False)
def load_data():
    """Load relationship dataset. Cached: Streamlit reruns the whole script on
    every checkbox click, so the DB is only re-read after load_data.clear()
    (called after sync, session import and unfollow batches)."""
    return instagram_service.load_relationship_data()

data = load_data()
followers = data["followers"]
following = data["following"]
mutuals = data["mutuals"]
not_following_back = data["not_following_back"]
fans = data["fans"]
events = data["events"]
event_count = data.get("event_count", len(events))
last_checked = data["last_checked"]
user_id_map = data["user_id_map"]

# Format Last Checked Timestamp
if last_checked:
    try:
        dt = datetime.fromisoformat(last_checked)
        last_checked_formatted = dt.strftime("%b %d, %Y at %I:%M %p UTC")
    except Exception:
        last_checked_formatted = last_checked
else:
    last_checked_formatted = "Never"

# ---------------------------------------------------------------------------
# Sidebar: Target & Automation Controls
# ---------------------------------------------------------------------------
st.sidebar.markdown(
    '<div style="text-align: center; margin-bottom: 25px;">'
    '<h2 class="gradient-text" style="font-size: 1.9rem; margin: 0;">IG Automation</h2>'
    '<p style="color: #64748b; font-size: 0.85rem; margin-top: 4px;">Single-Account Intelligence & Relations</p>'
    '</div>', 
    unsafe_allow_html=True
)

st.sidebar.markdown(
    f'<div class="glass-card" style="padding: 16px; margin-bottom: 20px;">'
    f'<div style="font-size: 0.75rem; text-transform: uppercase; color: #94a3b8; letter-spacing: 1px; margin-bottom: 6px;">Target Account</div>'
    f'<div style="font-size: 1.15rem; font-weight: 700; color: #f8fafc;">@{TARGET}</div>'
    f'<div style="font-size: 0.78rem; color: #10b981; margin-top: 4px;">● Sole Root Profile Active</div>'
    f'</div>',
    unsafe_allow_html=True
)

# Session Status Check
session_exists = instagram_service.SESSION_FILE.exists()
st.sidebar.markdown("### 🔐 Session Status")
if session_exists:
    st.sidebar.success("Session file (`.session`) active")
else:
    st.sidebar.warning("Session file missing! Import browser cookies below.")

# Live Data Sync
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Sync Live Instagram Data")
st.sidebar.caption(f"Executes stealth fetch of followers and following for @{TARGET} into SQLite.")

if st.sidebar.button("Run Live Sync Now", use_container_width=True):
    with st.spinner(f"Connecting to Instagram and syncing @{TARGET}..."):
        try:
            sync_script = instagram_service.BASE_DIR / "sync_accurate_data.py"
            result = subprocess.run(
                [sys.executable, str(sync_script), TARGET],
                capture_output=True,
                text=True,
                check=True,
                timeout=300
            )
            st.sidebar.success("Sync completed successfully!")
            load_data.clear()
            st.rerun()
        except subprocess.CalledProcessError as err:
            st.sidebar.error("Sync failed!")
            with st.sidebar.expander("Error Details"):
                st.code(err.stderr or err.stdout)
        except Exception as e:
            st.sidebar.error(f"Execution error: {e}")

# Browser Session Re-import
st.sidebar.markdown("---")
st.sidebar.markdown("### 🍪 Browser Cookie Importer")
st.sidebar.caption("Extracts fresh cookies from Chrome, Edge, or Firefox when session expires.")

if st.sidebar.button("Import Browser Session", use_container_width=True):
    with st.spinner("Extracting browser cookies... (Please ensure browser is closed)"):
        try:
            import_script = instagram_service.BASE_DIR / "import_browser_session.py"
            res = subprocess.run(
                [sys.executable, str(import_script)],
                capture_output=True,
                text=True,
                timeout=45
            )
            if res.returncode == 0:
                st.sidebar.success("Session imported and saved!")
                load_data.clear()
                st.rerun()
            else:
                st.sidebar.warning("Cookie extraction failed. Check browser lock.")
                with st.sidebar.expander("Output"):
                    st.code(res.stdout or res.stderr)
        except Exception as e:
            st.sidebar.error(f"Error importing session: {e}")

st.sidebar.markdown("<br><br>", unsafe_allow_html=True)
st.sidebar.markdown(
    f'<div style="text-align: center; color: #475569; font-size: 0.75rem;">'
    f'Targeted Exclusively for @{TARGET}<br>Python 3.14 • SQLite • Streamlit'
    f'</div>',
    unsafe_allow_html=True
)

# ---------------------------------------------------------------------------
# Main Dashboard Header
# ---------------------------------------------------------------------------
st.markdown(
    f'<div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 25px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 16px;">'
    f'<div>'
    f'<div class="target-badge">🔒 ROOT PROFILE EXCLUSIVE</div>'
    f'<h1 style="margin: 8px 0 0 0; font-size: 2.5rem;">Profile Intelligence: <span class="gradient-text">@{TARGET}</span></h1>'
    f'<p style="color: #64748b; margin: 4px 0 0 0;">Relationship insights, reciprocal status, and stealth bulk automation</p>'
    f'</div>'
    f'<div style="text-align: right;">'
    f'<span style="font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 1px;">Last Database Sync</span><br>'
    f'<span style="font-size: 0.95rem; color: #cbd5e1; font-weight: 600;">{last_checked_formatted}</span>'
    f'</div>'
    f'</div>',
    unsafe_allow_html=True
)

# ---------------------------------------------------------------------------
# Top Metrics Cards
# ---------------------------------------------------------------------------
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.markdown(
        f'<div class="metric-box">'
        f'<div class="metric-val">{len(followers)}</div>'
        f'<div class="metric-lbl">Followers</div>'
        f'</div>',
        unsafe_allow_html=True
    )
with col2:
    st.markdown(
        f'<div class="metric-box">'
        f'<div class="metric-val">{len(following)}</div>'
        f'<div class="metric-lbl">Following</div>'
        f'</div>',
        unsafe_allow_html=True
    )
with col3:
    st.markdown(
        f'<div class="metric-box">'
        f'<div class="metric-val">{len(mutuals)}</div>'
        f'<div class="metric-lbl">Mutuals</div>'
        f'</div>',
        unsafe_allow_html=True
    )
with col4:
    st.markdown(
        f'<div class="metric-box">'
        f'<div class="metric-val">{len(not_following_back)}</div>'
        f'<div class="metric-lbl">Not Following Back</div>'
        f'</div>',
        unsafe_allow_html=True
    )
with col5:
    st.markdown(
        f'<div class="metric-box">'
        f'<div class="metric-val">{len(fans)}</div>'
        f'<div class="metric-lbl">Fans (Followers Only)</div>'
        f'</div>',
        unsafe_allow_html=True
    )

st.markdown("<br>", unsafe_allow_html=True)

if len(followers) == 0 and len(following) == 0:
    st.markdown(
        f'<div class="glass-card" style="text-align: center; padding: 45px 25px; border-left: 4px solid #a855f7;">'
        f'<h3 style="margin-top: 0; color: #f8fafc;">✨ Database Initialized for @{TARGET}</h3>'
        f'<p style="color: #94a3b8; max-width: 650px; margin: 10px auto 25px auto; font-size: 0.95rem;">'
        f'The database has been sanitized and prepared exclusively for <strong>@{TARGET}</strong>. '
        f'All legacy records have been completely purged. Click the <strong>"Run Live Sync Now"</strong> button in the sidebar '
        f'to fetch your active followers and following lists directly from Instagram.'
        f'</p>'
        f'</div>',
        unsafe_allow_html=True
    )

# ---------------------------------------------------------------------------
# Main Tabs: Relation Filtering & Diff History
# ---------------------------------------------------------------------------
tab_relations, tab_history = st.tabs([
    "🎯 Relationship Explorer & Bulk Actions",
    "📈 Follower Diff & Activity History"
])

# ---------------------------------------------------------------------------
# Tab 1: Categorized Dropdown Filtering & Interactive Bulk Actions
# ---------------------------------------------------------------------------
with tab_relations:
    # Requirement 2: Categorized Dropdown Filtering
    st.markdown(
        '<div class="glass-card" style="padding: 16px 20px; margin-bottom: 20px;">'
        '<div style="font-weight: 700; font-size: 1.1rem; color: #f1f5f9; margin-bottom: 8px;">'
        '📂 Categorized Relationship Filter'
        '</div>'
        '<p style="color: #94a3b8; font-size: 0.85rem; margin: 0;">'
        'Toggle between relationship groups to inspect connections and execute targeted bulk unfollow actions.'
        '</p>'
        '</div>',
        unsafe_allow_html=True
    )

    # key -> (label, users, description, can_unfollow)
    CATEGORIES = {
        "not_following_back": ("Not Following Back", not_following_back,
                               f"Accounts that @{TARGET} follows who do NOT follow back.", True),
        "mutuals": ("Mutuals", mutuals,
                    f"Reciprocal connections: accounts @{TARGET} follows who follow back.", True),
        "all_following": ("All Following", following,
                          f"Complete list of all accounts followed by @{TARGET}.", True),
        "all_followers": ("All Followers", followers,
                          f"Complete list of accounts following @{TARGET}.", False),
    }

    current_category = st.selectbox(
        "Select Relationship Category",
        list(CATEGORIES),
        index=0,
        format_func=lambda k: f"{CATEGORIES[k][0]} ({len(CATEGORIES[k][1])})",
        help="Filter user list by reciprocal relationship status"
    )
    category_name, category_set, category_desc, can_unfollow = CATEGORIES[current_category]
    current_users = sorted(category_set)
    selected_category_label = category_name

    # Search filter
    search_col, count_col = st.columns([3, 1])
    with search_col:
        search_term = st.text_input(
            f"🔍 Search within {category_name}",
            placeholder="Type to filter usernames...",
            key=f"search_{current_category}"
        )
    with count_col:
        needle = search_term.strip().lower()
        filtered_users = [u for u in current_users if needle in u.lower()] if needle else current_users
        st.markdown(
            f'<div style="text-align: right; padding-top: 30px; font-weight: 600; color: #94a3b8; font-size: 0.9rem;">'
            f'Showing {len(filtered_users)} of {len(current_users)}'
            f'</div>',
            unsafe_allow_html=True
        )

    st.caption(category_desc)

    # Initialize dictionary in st.session_state for selection management
    if "selected_users" not in st.session_state:
        st.session_state.selected_users = {}

    # Filter signature detection to reset page when search or category changes
    filter_sig = f"{current_category}_{search_term}"
    if st.session_state.get("prev_filter_sig") != filter_sig:
        st.session_state.prev_filter_sig = filter_sig
        st.session_state.page_num = 1

    total_items = len(filtered_users)
    page_size = 50
    total_pages = max(1, (total_items + page_size - 1) // page_size)

    if "page_num" not in st.session_state:
        st.session_state.page_num = 1
    if st.session_state.page_num > total_pages:
        st.session_state.page_num = 1
    if st.session_state.page_num < 1:
        st.session_state.page_num = 1

    curr_page = st.session_state.page_num

    # 1. Identify the paginated slice of users currently rendered on screen
    start_idx = (curr_page - 1) * page_size
    end_idx = min(start_idx + page_size, total_items)
    current_page_users = filtered_users[start_idx:end_idx] if filtered_users else []
    page_count = len(current_page_users)

    # 2. Callbacks for Paginated Selection Scope & Page Navigation
    def on_select_page(users):
        for u in users:
            st.session_state.selected_users[u] = True
            st.session_state[f"chk_{u}"] = True

    def on_deselect_page(users):
        for u in users:
            st.session_state.selected_users[u] = False
            st.session_state[f"chk_{u}"] = False

    def on_deselect_all_pages():
        for u in list(st.session_state.selected_users.keys()):
            st.session_state.selected_users[u] = False
            st.session_state[f"chk_{u}"] = False

    def on_prev_page():
        if st.session_state.page_num > 1:
            st.session_state.page_num -= 1

    def on_next_page():
        if st.session_state.page_num < total_pages:
            st.session_state.page_num += 1

    # Sync checkbox widget state into selected_users BEFORE counting. The rows
    # (and their checkboxes) render further down, so without this the counters
    # and the Unfollow button lagged one click behind.
    for u in current_page_users:
        if f"chk_{u}" in st.session_state:
            st.session_state.selected_users[u] = st.session_state[f"chk_{u}"]

    # Compute counters: selection on active page and total selection across all pages
    selected_on_page = sum(1 for u in current_page_users if st.session_state.selected_users.get(u, False))
    # Only users in the CURRENT category (and still followed) count. Previously a
    # selection made under "Mutuals" stayed active after switching to "Not
    # Following Back", so mutuals could be unfollowed without being visible.
    selected_to_unfollow = sorted(
        u for u, is_sel in st.session_state.selected_users.items()
        if is_sel and u in category_set and u in following
    ) if can_unfollow else []
    total_selected = len(selected_to_unfollow)

    # Paginated Bulk Selection Controls
    if can_unfollow and filtered_users:
        btn_col1, btn_col2, counter_col = st.columns([1.5, 1.3, 3.2], vertical_alignment="center")
        with btn_col1:
            st.button(
                f"☑️ Select Current Page ({page_count})",
                key=f"select_page_{current_category}_{curr_page}",
                on_click=on_select_page,
                args=(current_page_users,),
                use_container_width=True
            )
        with btn_col2:
            st.button(
                "✖️ Deselect Page",
                key=f"deselect_page_{current_category}_{curr_page}",
                on_click=on_deselect_page,
                args=(current_page_users,),
                use_container_width=True
            )
        with counter_col:
            st.markdown(
                f"""
                <div style="background: rgba(30, 41, 59, 0.45); padding: 8px 14px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.06); font-size: 0.88rem; display: flex; align-items: center; justify-content: space-between;">
                    <div>
                        <span>Selected on this page: <strong style="color: #38bdf8;">{selected_on_page} / {page_count}</strong></span>
                        &nbsp;&bull;&nbsp;
                        <span>Total Selected: <strong style="color: #ec4899;">{total_selected}</strong></span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

        if total_selected > selected_on_page:
            st.button(
                f"🧹 Clear All Selected Across All Pages ({total_selected})",
                key=f"clear_all_pages_{current_category}",
                on_click=on_deselect_all_pages,
            )

    # -----------------------------------------------------------------------
    # Requirement 2 & 3: Prominent Bulk Unfollow Action Bar & Live Execution
    # -----------------------------------------------------------------------
    if can_unfollow and total_selected > 0:
        st.markdown(
            f"""
            <div style="background: linear-gradient(135deg, rgba(239, 68, 68, 0.18) 0%, rgba(185, 28, 28, 0.08) 100%);
                        border: 1px solid rgba(239, 68, 68, 0.45); border-radius: 14px; padding: 18px 22px;
                        margin: 16px 0 16px 0;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
                    <div>
                        <div style="font-weight: 800; font-size: 1.18rem; color: #fca5a5; display: flex; align-items: center; gap: 10px;">
                            <span>🚨 Bulk Action Ready</span>
                            <span style="background: #ef4444; color: white; padding: 2px 12px; border-radius: 9999px; font-size: 0.85rem; font-weight: 700;">
                                {total_selected} Selected
                            </span>
                        </div>
                        <div style="color: #cbd5e1; font-size: 0.85rem; margin-top: 4px;">
                            Authenticated unfollow with automated safety jitter delays (3.0s – 5.5s) to avoid Instagram rate limits.
                        </div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        unfollow_btn = st.button(
            f"🔴 Unfollow Selected ({total_selected}) Users",
            key=f"bulk_unfollow_btn_{current_category}",
            use_container_width=True
        )

        if unfollow_btn:
            users_to_unfollow = list(selected_to_unfollow)
            total_unfollow = len(users_to_unfollow)

            st.markdown("---")
            st.markdown("#### ⚡ Live Unfollow Execution")
            progress_bar = st.progress(0.0)
            status_text = st.empty()
            log_expander = st.expander("📋 Detailed Live Action Log", expanded=True)
            log_placeholder = log_expander.empty()
            logs = []

            # Authenticated session via instagram_actions.py
            sess, csrf, auth_err = instagram_actions.load_session()
            if not sess:
                st.error(f"Cannot execute unfollow: {auth_err}. Please re-import browser session cookies.")
            else:
                completed = 0
                failed = 0
                halted = False

                for idx, uname in enumerate(users_to_unfollow, start=1):
                    # Live status message displaying username currently being processed
                    status_text.markdown(f"⏳ **[{idx}/{total_unfollow}]** Processing unfollow for **@{uname}**...")
                    
                    # unfollow_user resolves the ID itself when it is not in the map
                    success, message, is_fatal = instagram_actions.unfollow_user(
                        uname,
                        user_id=user_id_map.get(uname),
                        session=sess,
                        csrftoken=csrf
                    )

                    if success:
                        completed += 1
                        logs.append(f"✅ [{idx}/{total_unfollow}] Successfully unfollowed @{uname}")
                        # Upon successful unfollow of each user:
                        # - Record removed from following table in instagram_tracker.db (performed inside unfollow_user)
                        # - Remove the user from st.session_state
                        st.session_state.selected_users.pop(uname, None)
                        if f"chk_{uname}" in st.session_state:
                            st.session_state[f"chk_{uname}"] = False
                    else:
                        failed += 1
                        logs.append(f"❌ [{idx}/{total_unfollow}] Failed @{uname}: {message}")

                    log_placeholder.code("\n".join(logs))
                    progress_bar.progress(idx / total_unfollow)

                    # If rate limit (HTTP 429) or checkpoint occurs, halt immediately and notify user
                    if is_fatal:
                        halted = True
                        status_text.error(f"🛑 **Execution Halted:** {message}")
                        st.error(f"⚠️ Instagram rate limit/checkpoint encountered on @{uname}: {message}. Process stopped immediately to safeguard your account.")
                        break

                    # Safety jitter delay between ALL requests (3.0 to 5.5 seconds).
                    # Previously failures skipped the delay, so a run of errors
                    # fired requests back-to-back — the fastest way to get rate-limited.
                    if idx < total_unfollow:
                        jitter = round(random.uniform(3.0, 5.5), 2)
                        verb = "Unfollowed" if success else "Failed"
                        status_text.markdown(f"⏳ **[{idx}/{total_unfollow}]** {verb} **@{uname}**. Sleeping for **{jitter}s** (safety jitter delay)...")
                        time.sleep(jitter)

                # DB changed (rows removed) — drop the cached dataset.
                load_data.clear()
                if halted:
                    st.warning(f"Batch halted early. Successfully unfollowed {completed} user(s) before stopping. Refresh to update counters.")
                else:
                    status_text.markdown("✨ **Batch execution complete!**")
                    st.success(f"🎉 Unfollowed {completed} account(s), {failed} failed. Database updated immediately.")
                    time.sleep(1.5)
                    # Call st.rerun() only after the entire batch finishes to refresh the UI and counters
                    st.rerun()

    # -----------------------------------------------------------------------
    # Interactive Account List & Checkbox Grid
    # -----------------------------------------------------------------------
    if filtered_users:
        # Table Header
        if can_unfollow:
            st.markdown("""
            <div style="display: grid; grid-template-columns: 48px 1fr 180px 110px; padding: 10px 14px; background: rgba(30, 41, 59, 0.45); border-radius: 12px; font-weight: 700; color: #94a3b8; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.5px; margin: 12px 0 8px 0; border: 1px solid rgba(255, 255, 255, 0.05);">
                <div>Select</div>
                <div>Account</div>
                <div>Status</div>
                <div style="text-align: right;">Profile</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="display: grid; grid-template-columns: 1fr 180px 110px; padding: 10px 14px; background: rgba(30, 41, 59, 0.45); border-radius: 12px; font-weight: 700; color: #94a3b8; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.5px; margin: 12px 0 8px 0; border: 1px solid rgba(255, 255, 255, 0.05);">
                <div>Account</div>
                <div>Status</div>
                <div style="text-align: right;">Profile</div>
            </div>
            """, unsafe_allow_html=True)

        # User Rows for Current Page
        for u in current_page_users:
            if u in mutuals:
                badge_html = '<span class="badge-new">Mutual Follow</span>'
            elif u in following:
                badge_html = '<span class="badge-lost">Not Following Back</span>'
            else:
                badge_html = '<span class="badge-unfollowed">Fan (Follower)</span>'

            if can_unfollow:
                c_chk, c_usr, c_sts, c_lnk = st.columns([0.65, 4.35, 2.5, 1.5], vertical_alignment="center")
                with c_chk:
                    # Sync dynamic key from session state dictionary
                    if f"chk_{u}" not in st.session_state:
                        st.session_state[f"chk_{u}"] = st.session_state.selected_users.get(u, False)
                    
                    # Direct dynamic key checkbox WITHOUT callback (no st.rerun inside handler)
                    chk_val = st.checkbox(
                        f"Select @{u}",
                        key=f"chk_{u}",
                        label_visibility="collapsed"
                    )
                    st.session_state.selected_users[u] = chk_val

                with c_usr:
                    st.markdown(f'<span style="font-weight: 600; color: #f1f5f9; font-size: 0.95rem;">@{u}</span>', unsafe_allow_html=True)
                with c_sts:
                    st.markdown(badge_html, unsafe_allow_html=True)
                with c_lnk:
                    st.markdown(f'<a href="https://instagram.com/{u}" target="_blank" style="color: #c084fc; font-size: 0.85rem; font-weight: 600; text-decoration: none;">View Profile ↗</a>', unsafe_allow_html=True)
            else:
                c_usr, c_sts, c_lnk = st.columns([5, 2.5, 1.5], vertical_alignment="center")
                with c_usr:
                    st.markdown(f'<span style="font-weight: 600; color: #f1f5f9; font-size: 0.95rem;">@{u}</span>', unsafe_allow_html=True)
                with c_sts:
                    st.markdown(badge_html, unsafe_allow_html=True)
                with c_lnk:
                    st.markdown(f'<a href="https://instagram.com/{u}" target="_blank" style="color: #c084fc; font-size: 0.85rem; font-weight: 600; text-decoration: none;">View Profile ↗</a>', unsafe_allow_html=True)

        # Pagination controls when multiple pages exist
        if total_pages > 1:
            st.markdown("<br>", unsafe_allow_html=True)
            col_prev, col_pg_info, col_next = st.columns([1.2, 2.6, 1.2], vertical_alignment="center")
            with col_prev:
                st.button(
                    "⬅️ Previous Page",
                    key=f"prev_btn_{current_category}",
                    on_click=on_prev_page,
                    disabled=(curr_page <= 1),
                    use_container_width=True
                )
            with col_pg_info:
                st.markdown(
                    f"<div style='text-align: center; color: #94a3b8; font-weight: 600; font-size: 0.9rem;'>"
                    f"Page <span style='color: #c084fc;'>{curr_page}</span> of {total_pages} "
                    f"<span style='color: #64748b;'>({start_idx + 1}–{end_idx} of {total_items})</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )
            with col_next:
                st.button(
                    "Next Page ➡️",
                    key=f"next_btn_{current_category}",
                    on_click=on_next_page,
                    disabled=(curr_page >= total_pages),
                    use_container_width=True
                )
    else:
        st.markdown(
            f'<div class="glass-card" style="text-align: center; padding: 40px; color: #94a3b8;">'
            f'No accounts match the current filter or category.'
            f'</div>',
            unsafe_allow_html=True
        )

# ---------------------------------------------------------------------------
# Tab 2: Follower Diff & Activity History
# ---------------------------------------------------------------------------
with tab_history:
    st.markdown("<h3 style='margin-top: 10px; margin-bottom: 15px;'>Historical Follower Changes & Diffs</h3>", unsafe_allow_html=True)
    st.caption(f"Activity snapshots and automated diff events recorded for @{TARGET}.")

    if not events:
        st.markdown(
            '<div class="glass-card" style="text-align: center; padding: 40px; color: #64748b;">'
            'No events recorded yet. Run live syncs or execute unfollow actions to track historical diffs.'
            '</div>',
            unsafe_allow_html=True
        )
    else:
        st.write(f"Total events recorded: **{event_count}**")
        for ev in events[:60]:
            event_type = ev["event_type"]
            uname = html.escape(ev["username"])
            ts = ev["detected_at"]
            
            try:
                dt = datetime.fromisoformat(ts)
                time_str = dt.strftime("%b %d, %Y • %I:%M:%S %p UTC")
            except Exception:
                time_str = ts

            if event_type == "new_follower":
                badge = '<span class="badge-new">NEW FOLLOWER</span>'
                border_color = "#10b981"
            elif event_type == "unfollower":
                badge = '<span class="badge-lost">LOST FOLLOWER</span>'
                border_color = "#ef4444"
            else:
                badge = '<span class="badge-unfollowed">UNFOLLOWED BY YOU</span>'
                border_color = "#a855f7"

            st.markdown(
                f'<div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 18px; background: rgba(22, 27, 38, 0.6); border-radius: 12px; margin-bottom: 8px; border-left: 4px solid {border_color};">'
                f'<div style="display: flex; align-items: center; gap: 14px;">'
                f'{badge}'
                f'<a href="https://instagram.com/{uname}" target="_blank" style="color: #f1f5f9; font-weight: 600; text-decoration: none;">@{uname}</a>'
                f'</div>'
                f'<div style="color: #64748b; font-size: 0.8rem; font-family: monospace;">{time_str}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
