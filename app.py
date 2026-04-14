import streamlit as st
import pandas as pd
import json
import os
import random
import requests
import urllib.parse
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# --- 頁面基本設定 ---
st.set_page_config(page_title="急診專師協助派發系統", page_icon="🏥", layout="wide")

# ==========================================
# 🛑 LINE 設定區 (精準私訊版)
# ==========================================
LIFF_ID = "請貼上您的_LIFF_ID"
LINE_CLIENT_ID = "請貼上您的_Channel_ID"          
LINE_CLIENT_SECRET = "請貼上您的_Channel_Secret"  
REDIRECT_URI = "請貼上您的_Streamlit_網址"        

LINE_CHANNEL_ACCESS_TOKEN = "請貼上您的_Channel_Access_Token"
# ==========================================

# --- 檔案庫設定 ---
DATA_FILE = "task_data.json"
ONLINE_FILE = "online_users.json"
USER_ID_MAP_FILE = "user_id_map.json"

BED_DATA_COMPLEX = {
    "留觀(OBS)": {"OBS 1": ["1", "2", "3", "5", "6", "7", "8", "9", "10", "35", "36", "37", "38"], "OBS 2": ["11", "12", "13", "15", "16", "17", "18", "19", "20", "21", "22", "23"], "OBS 3": ["25", "26", "27", "28", "29", "30", "31", "32", "33", "39"]},
    "診間": {"第一診間": ["11", "12", "13", "15", "21", "22", "23", "25"], "第二診間": ["16", "17", "18", "19", "20", "36", "37", "38"], "第三診間": ["5", "6", "27", "28", "29", "30", "31", "32", "33", "39"]},
    "兒科": {"兒科床位": ["501", "502", "503", "505", "506", "507", "508", "509"]},
    "急救區": {}, "檢傷": {}, "縫合室": {}, "超音波室": {}
}

# --- 初始化 Session State ---
if "is_logged_in" not in st.session_state:
    st.session_state.nickname = ""
    st.session_state.role = ""
    st.session_state.line_userId = ""
    st.session_state.is_logged_in = False

if "success_message" not in st.session_state: st.session_state.success_message = ""
if "is_standby" not in st.session_state: st.session_state.is_standby = True  
if "op_mode_start" not in st.session_state: st.session_state.op_mode_start = None

def get_tw_time(): return datetime.utcnow() + timedelta(hours=8)

if not st.session_state.is_standby and st.session_state.op_mode_start:
    if (get_tw_time() - st.session_state.op_mode_start).total_seconds() >= 295:
        st.session_state.is_standby = True; st.session_state.op_mode_start = None
        st.toast("⏳ 停留超過5分鐘，已自動切回待命模式！", icon="🔄")

refresh_interval = 10000 if st.session_state.is_standby else 300000
count = st_autorefresh(interval=refresh_interval, limit=None, key="data_sync_refresh")

def load_data(file_path, default_empty):
    if not os.path.exists(file_path): return default_empty
    try:
        with open(file_path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default_empty

def save_data(data, file_path):
    with open(file_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

def update_online_status(nickname, role):
    users = load_data(ONLINE_FILE, {})
    users[nickname] = {"role": role, "last_seen": get_tw_time().strftime("%Y-%m-%d %H:%M:%S")}
    save_data(users, ONLINE_FILE)

def remove_online_status(nickname):
    users = load_data(ONLINE_FILE, {})
    if nickname in users: del users[nickname]; save_data(users, ONLINE_FILE)

# --- 核心：LINE 雙向推播與零點擊登入功能 ---
def send_line_push(target_id, message_text):
    if not LINE_CHANNEL_ACCESS_TOKEN or LINE_CHANNEL_ACCESS_TOKEN.startswith("請貼上"): return
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"to": target_id, "messages": [{"type": "text", "text": message_text}]}
    try: requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload)
    except Exception as e: print(f"LINE 推播失敗: {e}")

def notify_np_new_task(task):
    # 深層連結：標記這是一個任務連結，並將登入身分強制帶入為「專科護理師」
    auth_params = {
        "response_type": "code", "client_id": LINE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI, "state": f"task_{task['id']}_role_專科護理師", "scope": "profile"
    }
    direct_link = f"https://access.line.me/oauth2/v2.1/authorize?{urllib.parse.urlencode(auth_params)}"
    
    msg = (
        f"🚨 【新任務派發】 {task['priority']}\n"
        f"📍 位置: {task['bed']}\n"
        f"📝 任務: {task['task_type']}\n"
        f"📋 說明: {task['details']}\n"
        f"👨‍⚕️ 派發: {task['requester']} ({task['requester_role']})\n"
        f"🔗 點此一鍵登入並接單:\n{direct_link}"
    )
    
    # 🎯【亮點更新】：找出所有在線上的專科護理師，並發送私訊給他們！
    online_users = load_data(ONLINE_FILE, {})
    user_map = load_data(USER_ID_MAP_FILE, {})
    
    for nickname, info in online_users.items():
        if info.get("role") == "專科護理師":
            # 找到這位專師的 LINE ID
            line_id = user_map.get(nickname)
            if line_id:
                send_line_push(line_id, msg)

def notify_doctor_task_completed(task):
    user_map = load_data(USER_ID_MAP_FILE, {})
    doc_line_id = user_map.get(task['requester'])
    
    if doc_line_id:
        # 深層連結：將登入身分設定回原本派單的醫師/護理師
        auth_params = {
            "response_type": "code", "client_id": LINE_CLIENT_ID,
            "redirect_uri": REDIRECT_URI, "state": f"task_{task['id']}_role_{task['requester_role']}", "scope": "profile"
        }
        direct_link = f"https://access.line.me/oauth2/v2.1/authorize?{urllib.parse.urlencode(auth_params)}"
        
        msg = (
            f"✅ 【任務已完成】\n"
            f"📍 位置: {task['bed']}\n"
            f"📝 任務: {task['task_type']}\n"
            f"🧑‍⚕️ 執行專師: {task['handler']}\n"
            f"💬 回報內容: {task['feedback']}\n"
            f"🔗 點此一鍵登入查看:\n{direct_link}"
        )
        send_line_push(doc_line_id, msg)

if "known_task_ids" not in st.session_state: st.session_state.known_task_ids = set([tk['id'] for tk in load_data(DATA_FILE, [])])

def check_for_new_alerts():
    tasks = load_data(DATA_FILE, []); current_ids = set([tk['id'] for tk in tasks]); new_ids = current_ids - st.session_state.known_task_ids
    if new_ids:
        latest_new_task = next((tk for tk in tasks if tk['id'] in new_ids), None)
        if latest_new_task and latest_new_task.get('requester') != st.session_state.nickname:
            st.toast("🚨 系統有新的任務！", icon="🔔")
            st.html("""<script>new Audio("https://actions.google.com/sounds/v1/alarms/beep_short.ogg").play();</script>""")
    st.session_state.known_task_ids = current_ids

def reset_to_standby(): st.session_state.is_standby = True; st.session_state.op_mode_start = None

def checkbox_matrix(options, num_columns=4):
    selected = []; cols = st.columns(num_columns)
    for i, option in enumerate(options):
        with cols[i % num_columns]:
            if st.checkbox(option, key=f"matrix_{option}"): selected.append(option)
    return selected

# --- 🚀 正式版登入介面 ---
def login_interface():
    st.header("🔑 系統登入")
    with st.container(border=True):
        st.subheader("💡 方式一：LINE 快速登入 (正式環境)")
        st.caption("請先選擇您的身分，再點擊下方按鈕進行安全驗證登入。")
        
        # 動態選擇 LINE 登入身分
        line_role_input = st.radio("👇 請先選擇您的身分", ["護理師", "醫師", "專科護理師"], horizontal=True, key="line_role_selector")
        
        if LINE_CLIENT_ID.startswith("請貼上"):
            st.error("⚠️ 開發者請先在程式碼上方填入 LINE 的相關金鑰！")
        else:
            # 將選擇的身分包裝在 state 參數裡傳送
            auth_params = {
                "response_type": "code", "client_id": LINE_CLIENT_ID,
                "redirect_uri": REDIRECT_URI, "state": f"login_role_{line_role_input}", "scope": "profile"
            }
            auth_url = f"https://access.line.me/oauth2/v2.1/authorize?{urllib.parse.urlencode(auth_params)}"
            btn_html = f"""<a href="{auth_url}" target="_blank" style="text-decoration: none;"><div style="background-color: #06C755; color: white; padding: 15px; border-radius: 10px; text-align: center; font-weight: bold; font-size: 18px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">🟢 點我使用 LINE 一鍵登入</div></a>"""
            st.markdown(btn_html, unsafe_allow_html=True)

        st.markdown("---")
        st.subheader("⌨️ 方式二：手動輸入 (傳統登入)")
        nickname_input = st.text_input("手動輸入新綽號 (必填)")
        role_input = st.radio("傳統登入身分選擇", ["護理師", "醫師", "專科護理師"], horizontal=True)
        if st.button("🚀 手動登入", use_container_width=True, type="primary"):
            if not nickname_input.strip(): st.error("請輸入綽號！")
            else:
                st.session_state.nickname = nickname_input.strip(); st.session_state.role = role_input; st.session_state.is_logged_in = True
                st.rerun()

# --- 模擬 AI 解析功能 ---
def parse_nlp_to_task(text):
    parsed = {"bed": "未知", "type": "其他", "priority": "🟢 一般", "details": text}
    if "急" in text or "快" in text: parsed["priority"] = "🔴 緊急"
    if "foley" in text.lower() or "尿管" in text: parsed["type"] = "on Foley"
    elif "ng" in text.lower() or "鼻胃管" in text: parsed["type"] = "on NG"
    elif "會診" in text: parsed["type"] = "會診"
    elif "縫" in text: parsed["type"] = "Suture (縫合)"
    import re
    bed_match = re.search(r'(診間|留觀|兒科|急救區).*?(\d+)床?', text)
    if bed_match: parsed["bed"] = f"{bed_match.group(1)} {bed_match.group(2)}床"
    return parsed

# --- 派發介面 ---
def assigner_interface(view_role="護理師"):
    st.header(f"👋 {view_role} 派發介面")
    if st.session_state.success_message: st.success(st.session_state.success_message); st.session_state.success_message = "" 
    
    with st.expander("✨ AI 語音/文字智能建單 (Beta)", expanded=False):
        st.caption("📱 請點擊下方輸入框，使用手機鍵盤的「麥克風」用語音說出任務。")
        nlp_input = st.text_area("語音/文字輸入區", placeholder="例如：診間二區16床要on Foley，這是急件。")
        if st.button("🤖 讓系統幫我填表"):
            if nlp_input:
                ai_result = parse_nlp_to_task(nlp_input)
                st.info(f"**AI 解析結果**：\n📍 位置: {ai_result['bed']}\n📝 項目: {ai_result['type']}\n🚨 優先級: {ai_result['priority']}")
            else: st.warning("請先輸入內容")
            
    st.markdown("---")
    
    st.subheader("📍 步驟 1：選擇位置")
    area = st.radio("【 1. 先選大區域 】", list(BED_DATA_COMPLEX.keys()) + ["病患無床位"], horizontal=True)
    final_bed = ""; bed_note = ""; patient_name = ""
    if area in ["留觀(OBS)", "診間"]:
        sub_area = st.radio(f"【 2. 選擇 {area} 區域 】", list(BED_DATA_COMPLEX[area].keys()), horizontal=True)
        bed_num = st.radio(f"【 3. 選擇 {sub_area} 床號 】", BED_DATA_COMPLEX[area][sub_area], horizontal=True)
        final_bed = f"{sub_area} {bed_num}床"
    elif area == "兒科":
        bed_num = st.radio("【 2. 選擇床號 】", BED_DATA_COMPLEX[area]["兒科床位"], horizontal=True)
        final_bed = f"兒科 {bed_num}床"
    elif area == "病患無床位":
        patient_name = st.text_input("【 2. 填寫病患姓名 (必填) 】")
        final_bed = f"無床位 (病患: {patient_name})" if patient_name else "無床位"
    else:
        bed_note = st.text_input(f"【 2. {area} 備註 (選填) 】")
        final_bed = area + (f" ({bed_note})" if bed_note else "")

    st.markdown("---")
    st.subheader("📋 步驟 2：選擇協助項目與優先級")
    priority = st.radio("優先級別", ["🟢 一般", "🔴 緊急"], horizontal=True)
    task_type = st.radio("協助項目", ["on Foley", "on NG", "Suture (縫合)", "會診", "藥物開立", "檢體採集", "安排洗腎", "訂ICU", "開診斷書", "拍照", "其他"], horizontal=True)
    
    details = ""
    with st.container(border=True):
        if task_type == "on Foley": details = f"種類: {st.radio('Foley 種類', ['一般', '矽質'], horizontal=True)} | 檢體: {'是' if st.checkbox('需留取檢體') else '否'}"
        elif task_type == "on NG": details = f"目的: {st.radio('NG 目的', ['Re-on', 'Decompression', 'IRRI', '其他'], horizontal=True)}"
        elif task_type == "Suture (縫合)": details = "需縫合處置"
        elif task_type == "藥物開立": details = f"說明: {st.text_input('藥物/說明 (必填)')}"
        else: details = st.text_input("細節說明 (必填)")
            
    if st.button("🚀 確認並派發任務", use_container_width=True, type="primary"):
        new_task = {
            "id": str(get_tw_time().timestamp()), "time": get_tw_time().strftime("%Y-%m-%d %H:%M:%S"), 
            "priority": priority, "bed": final_bed, "task_type": task_type, "details": details, 
            "requester": st.session_state.nickname, "requester_role": view_role, "status": "待處理", 
            "handler": "", "start_time": "", "complete_time": "", "feedback": ""
        }
        tasks = load_data(DATA_FILE, []); tasks.append(new_task); save_data(tasks, DATA_FILE)
        
        notify_np_new_task(new_task)
        
        st.session_state.success_message = f"✅ 已成功送出 【 {final_bed} 】 的 【{task_type}】 請求！"
        reset_to_standby(); st.rerun() 

@st.dialog("📝 執行回報")
def np_feedback_dialog(task_id):
    tasks = load_data(DATA_FILE, []); task = next((t for t in tasks if t['id'] == task_id), None)
    if not task: return st.error("找不到資料！")
    st.write(f"**{task['bed']}** | **{task['task_type']}**\n派發者: {task['requester']} ({task['requester_role']})")
    feedback_text = st.text_input("回報內容 / 備註", placeholder="已處理完畢...")

    if st.button("💾 儲存結案", type="primary", use_container_width=True):
        latest_tasks = load_data(DATA_FILE, [])
        for i in range(len(latest_tasks)):
            if latest_tasks[i]['id'] == task_id:
                latest_tasks[i]['status'] = '已完成'; latest_tasks[i]['complete_time'] = get_tw_time().strftime("%Y-%m-%d %H:%M:%S")
                latest_tasks[i]['handler'] = st.session_state.nickname
                latest_tasks[i]['feedback'] = feedback_text if feedback_text else "已處理完畢"
                
                notify_doctor_task_completed(latest_tasks[i])
                
        save_data(latest_tasks, DATA_FILE); reset_to_standby(); st.rerun()

def np_interface():
    st.header("👩‍⚕️ 專科護理師接收介面")
    check_for_new_alerts()
    tasks = load_data(DATA_FILE, [])
    
    target_task_id = st.query_params.get("target_task_id")
    if target_task_id:
        target_task = next((t for t in tasks if t['id'] == target_task_id), None)
        if target_task:
            st.warning(f"🎯 **您從 LINE 點擊了任務連結！**\n📍 {target_task['bed']} - {target_task['task_type']} ({target_task['status']})")
    
    pending = [t for t in tasks if t['status'] == '待處理']
    in_prog = [t for t in tasks if t['status'] == '執行中' and t['handler'] == st.session_state.nickname]
    
    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"🔔 待接單 ({len(pending)})")
        if pending:
            for t in pending:
                is_target = (t['id'] == target_task_id)
                with st.container(border=True):
                    if is_target: st.markdown("🌟 **[LINE 指定任務]**")
                    st.markdown(f"**{t['priority']}** | **{t['time'][11:16]} | {t['bed']} - {t['task_type']}**")
                    st.write(f"📝 {t['details']}")
                    if st.button("👉 接單", key=f"tk_{t['id']}", use_container_width=True):
                        latest = load_data(DATA_FILE, [])
                        for i in range(len(latest)):
                            if latest[i]['id'] == t['id']: latest[i]['status'] = '執行中'; latest[i]['handler'] = st.session_state.nickname; latest[i]['start_time'] = get_tw_time().strftime("%Y-%m-%d %H:%M:%S")
                        save_data(latest, DATA_FILE); reset_to_standby(); st.rerun()
        else: st.info("目前無待辦任務！☕")

    with c2:
        st.subheader(f"🏃 執行中 ({len(in_prog)})")
        if in_prog:
            for t in in_prog:
                is_target = (t['id'] == target_task_id)
                with st.container(border=True):
                    if is_target: st.markdown("🌟 **[LINE 指定任務]**")
                    st.markdown(f"**{t['priority']}** | **🔵 {t['bed']} - {t['task_type']}**")
                    if st.button("✅ 標記完成", key=f"dn_{t['id']}", use_container_width=True, type="primary"): np_feedback_dialog(t['id'])
        else: st.success("無執行中任務。")

def whiteboard_interface():
    st.header("📊 系統動態白板")
    check_for_new_alerts()
    tasks = load_data(DATA_FILE, [])
    
    target_task_id = st.query_params.get("target_task_id")
    if target_task_id:
        target_task = next((t for t in tasks if t['id'] == target_task_id), None)
        if target_task:
            st.info(f"🔍 **正在查看任務**：{target_task['bed']} - {target_task['task_type']} (狀態: {target_task['status']})")
    
    tab_r, tab_c = st.tabs(["🚀 即時動態看板", "✅ 歷史完成紀錄"])
    with tab_r:
        pending = [t for t in tasks if t['status'] == '待處理']
        in_prog = [t for t in tasks if t['status'] == '執行中']
        c1, c2, c3 = st.columns(3)
        c1.metric("🔴 待處理任務", len(pending)); c2.metric("🔵 執行中任務", len(in_prog))
        st.markdown("---")
        w1, w2 = st.columns(2)
        with w1:
            st.subheader("🚨 未接單清單")
            if pending:
                dfp = pd.DataFrame(pending)[['time', 'priority', 'bed', 'task_type', 'requester']]
                dfp['time'] = dfp['time'].str[11:16]; dfp.columns = ['時間', '優先級', '位置', '任務', '發布者']; st.dataframe(dfp, use_container_width=True, hide_index=True)
        with w2:
            st.subheader("⚡ 執行動態")
            if in_prog:
                dfg = pd.DataFrame(in_prog)[['handler', 'priority', 'bed', 'task_type', 'start_time']]
                dfg['start_time'] = dfg['start_time'].str[11:16]; dfg.columns = ['專師', '優先級', '位置', '任務', '接單時間']; st.dataframe(dfg, use_container_width=True, hide_index=True)
                
    with tab_c:
        selected_date = st.date_input("選擇日期", value=get_tw_time().date())
        comp_tasks = [t for t in tasks if t['status'] == '已完成' and (t.get('complete_time') or t.get('time')).startswith(str(selected_date))]
        if comp_tasks:
            dfc = pd.DataFrame(comp_tasks)[['complete_time', 'bed', 'task_type', 'handler', 'requester', 'feedback']]
            dfc['complete_time'] = dfc['complete_time'].str[11:16]; dfc.columns = ['完成時間', '位置', '任務', '專師', '派發者', '回報']
            st.dataframe(dfc.sort_values(by='完成時間', ascending=False), use_container_width=True, hide_index=True)

# --- 主程式入口 (處理 OAuth 重新導向與動態身分) ---
def main():
    # 攔截 LINE OAuth 的回傳 Code
    if "code" in st.query_params and not st.session_state.is_logged_in:
        code = st.query_params["code"]
        state = st.query_params.get("state", "") # 抓取暗號 (包含任務ID與身分)
        
        token_url = "https://api.line.me/oauth2/v2.1/token"
        data = {
            "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
            "client_id": LINE_CLIENT_ID, "client_secret": LINE_CLIENT_SECRET
        }
        res = requests.post(token_url, data=data)
        if res.status_code == 200:
            access_token = res.json().get("access_token")
            profile_res = requests.get("https://api.line.me/v2/profile", headers={"Authorization": f"Bearer {access_token}"})
            if profile_res.status_code == 200:
                profile_data = profile_res.json()
                st.session_state.nickname = profile_data.get("displayName")
                st.session_state.line_userId = profile_data.get("userId") 
                
                # 預設身分，並嘗試從暗號中解析出正確身分
                assigned_role = "護理師" 
                target_task_id = None
                
                if "_role_" in state:
                    parts = state.split("_role_")
                    action_part = parts[0]
                    assigned_role = parts[1]
                    if action_part.startswith("task_"):
                        target_task_id = action_part.replace("task_", "")
                elif state.startswith("task_"):
                    target_task_id = state.replace("task_", "")
                elif state.startswith("login_role_"):
                    assigned_role = state.replace("login_role_", "")
                
                st.session_state.role = assigned_role
                st.session_state.is_logged_in = True
                
                # 登入成功後，把名字和 LINE ID 綁定存起來
                user_map = load_data(USER_ID_MAP_FILE, {})
                user_map[st.session_state.nickname] = st.session_state.line_userId
                save_data(user_map, USER_ID_MAP_FILE)
                
                st.query_params.clear()
                if target_task_id: st.query_params["target_task_id"] = target_task_id
                st.rerun()
            else: st.error("取得 LINE 檔案失敗，請重新登入")
        else: st.error("LINE 登入驗證失敗，請檢查金鑰或 Callback URL")

    if st.session_state.is_logged_in: update_online_status(st.session_state.nickname, st.session_state.role)
        
    if not st.session_state.is_logged_in:
        with st.sidebar:
            page = st.radio("前往頁面", ["🔑 登入", "📊 白板"], label_visibility="collapsed")
        if "登入" in page: login_interface()
        else: whiteboard_interface()
    else:
        with st.sidebar:
            st.markdown(f"### 👤 **{st.session_state.nickname}** ({st.session_state.role})")
            st.markdown("---")
            if st.button("🚪 登出", use_container_width=True):
                remove_online_status(st.session_state.nickname)
                st.session_state.is_logged_in = False; st.rerun()
            st.markdown("---")
            page = st.radio("選單", ["👩‍⚕️ 護理師派發", "👨‍⚕️ 醫師派發", "🧑‍⚕️ 專師接收", "📊 動態白板"], index=2 if st.session_state.role == "專科護理師" else 0, label_visibility="collapsed")
            
        if "護理師" in page: assigner_interface("護理師")
        elif "醫師" in page: assigner_interface("醫師")
        elif "接收" in page: np_interface()
        elif "白板" in page: whiteboard_interface()

if __name__ == "__main__":
    main()
