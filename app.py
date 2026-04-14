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
st.set_page_config(page_title="Emergency Orderly System", page_icon="🏥", layout="wide")

# ==========================================
# 🛑 LINE OAuth 2.0 登入設定區
# ==========================================
LINE_CLIENT_ID = "2009793049"          # 例如: "1234567890"
LINE_CLIENT_SECRET = "330e5ad65f39f344b419d75e2e94405f"  # 例如: "abcdef1234567890abcdef"
REDIRECT_URI = "https://np-system-for-line-26ht3v7pgusawfcswn2ykb.streamlit.app/"        # 例如: "https://np-system-for-line.streamlit.app/" (要跟後台的 Callback URL 一模一樣)
# ==========================================

# --- 語系切換輔助函數 ---
if "lang" not in st.session_state:
    st.session_state.lang = "中文"

def t(zh_text, en_text):
    return zh_text if st.session_state.lang == "中文" else en_text

# --- 初始化 Session State ---
if "is_logged_in" not in st.session_state:
    st.session_state.nickname = ""
    st.session_state.role = ""
    st.session_state.is_logged_in = False

if "success_message" not in st.session_state: st.session_state.success_message = ""
if "is_standby" not in st.session_state: st.session_state.is_standby = True  
if "op_mode_start" not in st.session_state: st.session_state.op_mode_start = None
if "form_id" not in st.session_state: st.session_state.form_id = 0

def get_tw_time():
    return datetime.utcnow() + timedelta(hours=8)

# --- 逾時回歸機制 ---
if not st.session_state.is_standby and st.session_state.op_mode_start:
    if (get_tw_time() - st.session_state.op_mode_start).total_seconds() >= 295:
        st.session_state.is_standby = True; st.session_state.op_mode_start = None
        st.toast(t("⏳ 停留超過5分鐘，已自動切回待命模式！", "⏳ Timeout. Switched to Standby Mode!"), icon="🔄")

refresh_interval = 10000 if st.session_state.is_standby else 300000
count = st_autorefresh(interval=refresh_interval, limit=None, key="data_sync_refresh")

# --- 檔案庫設定 ---
DATA_FILE = "orderly_tasks_v5.json"
ONLINE_FILE = "orderly_online_v5.json"
ROUTINE_FILE = "orderly_routines_v5.json"

BED_DATA_COMPLEX = {
    "OBS (留觀)": {"OBS 1": ["1", "2", "3", "5", "6", "7", "8", "9", "10", "35", "36", "37", "38"], "OBS 2": ["11", "12", "13", "15", "16", "17", "18", "19", "20", "21", "22", "23"], "OBS 3": ["25", "26", "27", "28", "29", "30", "31", "32", "33", "39"]},
    "Clinic (診間)": {"Clinic 1": ["11", "12", "13", "15", "21", "22", "23", "25"], "Clinic 2": ["16", "17", "18", "19", "20", "36", "37", "38"], "Clinic 3": ["5", "6", "27", "28", "29", "30", "31", "32", "33", "39"]},
    "Pediatrics (兒科)": {"Peds Bed": ["501", "502", "503", "505", "506", "507", "508", "509"]},
    "Resuscitation (急救區)": {}, "Triage (檢傷)": {}, "Suture Room (縫合室)": {}, "Ultrasound (超音波室)": {}, "Others (其他)": {}
}

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

if "known_task_ids" not in st.session_state: st.session_state.known_task_ids = set([tk['id'] for tk in load_data(DATA_FILE, [])])

def check_and_trigger_routines():
    routines = load_data(ROUTINE_FILE, []); tasks = load_data(DATA_FILE, [])
    now = get_tw_time(); hour = now.hour; date_hour_str = now.strftime("%Y-%m-%d-%H")
    triggered_any = False
    
    for rt in routines:
        trigger = False
        r_type = rt.get("routine_type", "odd_hours")
        if r_type == "odd_hours" and hour % 2 != 0: trigger = True
        elif r_type == "q4h" and hour in [1, 5, 9, 13, 17, 21]: trigger = True
            
        if trigger and rt.get("last_triggered_date_hour") != date_hour_str:
            new_task = {
                "id": str(get_tw_time().timestamp() + random.random()), "time_created": now.strftime("%Y-%m-%d %H:%M:%S"),
                "time_received": "", "time_completed": "", "priority": False, "location": rt["location"],
                "task_type": "Patient Care", "details": f"Action: {rt['action']} [Routine/常規]",
                "requested_reports": rt.get("requested_reports", []), "dispatched_by": f"{rt['dispatched_by']} (System)",
                "status": "Pending", "assigned_to": "", "nursing_note": ""
            }
            tasks.append(new_task)
            rt["last_triggered_date_hour"] = date_hour_str
            triggered_any = True
            
    if triggered_any: save_data(tasks, DATA_FILE); save_data(routines, ROUTINE_FILE)

check_and_trigger_routines()

def check_for_new_alerts():
    tasks = load_data(DATA_FILE, []); current_ids = set([tk['id'] for tk in tasks]); new_ids = current_ids - st.session_state.known_task_ids
    if new_ids:
        latest_new_task = next((tk for tk in tasks if tk['id'] in new_ids), None)
        if latest_new_task and latest_new_task.get('dispatched_by') != st.session_state.nickname:
            st.toast(t("🚨 有新任務！", "🚨 New Task!"), icon="🔔")
            st.html("""<script>new Audio("https://actions.google.com/sounds/v1/alarms/beep_short.ogg").play();</script>""")
    st.session_state.known_task_ids = current_ids

def reset_to_standby(): st.session_state.is_standby = True; st.session_state.op_mode_start = None

def k(name): return f"{name}_{st.session_state.form_id}"

def checkbox_matrix(options, key_prefix, num_columns=4):
    selected = []; cols = st.columns(num_columns)
    for i, option in enumerate(options):
        with cols[i % num_columns]:
            if st.checkbox(option, key=f"matrix_{key_prefix}_{option}_{st.session_state.form_id}"): selected.append(option)
    return selected

# --- 🚀 穩定的 LINE OAuth 登入介面 ---
def login_interface():
    st.header(t("🔑 系統登入", "🔑 Login System"))
    
    with st.container(border=True):
        st.subheader(t("💡 方式一：LINE 快速登入 (推薦)", "💡 Method 1: LINE Login"))
        st.caption(t("點擊下方按鈕，將引導至 LINE 進行安全驗證。測試期間將預設登入為『Nurse (護理師)』。", "Redirects to LINE for secure login."))
        
        # 建立 LINE 授權網址
        if LINE_CLIENT_ID == "請貼上您的_Channel_ID":
            st.error("⚠️ 開發者請先在程式碼上方填入 LINE 的相關金鑰！")
        else:
            auth_params = {
                "response_type": "code",
                "client_id": LINE_CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "state": "login_test",
                "scope": "profile"
            }
            auth_url = f"https://access.line.me/oauth2/v2.1/authorize?{urllib.parse.urlencode(auth_params)}"
            
            # 製作精美的跳轉按鈕 (強制破框 _top，避開 Streamlit 沙盒阻擋)
            btn_html = f"""
            <a href="{auth_url}" target="_top" style="text-decoration: none;">
                <div style="background-color: #06C755; color: white; padding: 15px; border-radius: 10px; text-align: center; font-weight: bold; font-size: 18px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                    🟢 點我使用 LINE 一鍵登入
                </div>
            </a>
            """
            st.markdown(btn_html, unsafe_allow_html=True)

        st.markdown("---")
        st.subheader(t("⌨️ 方式二：手動輸入 (傳統登入)", "⌨️ Method 2: Manual Login"))
        nickname_input = st.text_input(t("手動輸入新綽號 (必填)", "Nickname (Required)"))
        role_input = st.radio(t("身分選擇", "Role"), ["Nurse", "Orderly"], format_func=lambda x: t("👩‍⚕️ 護理師 (派發)", "👩‍⚕️ Nurse") if x == "Nurse" else t("🧑‍⚕️ 護佐 (接收)", "🧑‍⚕️ Orderly"), horizontal=True)
        
        if st.button(t("🚀 手動登入", "🚀 Login"), use_container_width=True, type="primary"):
            final_nickname = nickname_input.strip()
            if not final_nickname: st.error(t("請輸入綽號！", "Please enter nickname!"))
            else:
                st.session_state.nickname = final_nickname; st.session_state.role = role_input; st.session_state.is_logged_in = True
                st.rerun()

# --- 派發介面 ---
def assigner_interface(is_orderly=False):
    st.header(t(f"➕ 主動建單 ({st.session_state.nickname})", f"➕ Create Task ({st.session_state.nickname})") if is_orderly else t(f"👋 派發介面 ({st.session_state.nickname})", f"👋 Dispatch Panel ({st.session_state.nickname})"))
    if st.session_state.success_message: st.success(st.session_state.success_message); st.session_state.success_message = "" 
    st.markdown("---")
    
    st.subheader(t("📍 步驟 1：選擇位置", "📍 Step 1: Location"))
    area = st.radio(t("【 1. 大區域 】", "【 1. Area 】"), list(BED_DATA_COMPLEX.keys()), horizontal=True, key=k(f"area_{is_orderly}"))
    final_bed = ""
    if area in ["OBS (留觀)", "Clinic (診間)"]:
        sub_area = st.radio(t("【 2. 次區域 】", "【 2. Sub-Area 】"), list(BED_DATA_COMPLEX[area].keys()), horizontal=True, key=k(f"sub_area_{is_orderly}"))
        bed_num = st.radio(t("【 3. 床號 】", "【 3. Bed Number 】"), BED_DATA_COMPLEX[area][sub_area], horizontal=True, key=k(f"bed_num_{is_orderly}"))
        final_bed = f"{sub_area} - Bed {bed_num}"
    elif area == "Pediatrics (兒科)":
        bed_num = st.radio(t("【 2. 床號 】", "【 2. Bed Number 】"), BED_DATA_COMPLEX[area]["Peds Bed"], horizontal=True, key=k(f"peds_bed_{is_orderly}"))
        final_bed = f"Peds - Bed {bed_num}"
    elif area in ["Resuscitation (急救區)", "Triage (檢傷)", "Suture Room (縫合室)", "Ultrasound (超音波室)"]:
        final_bed = area.split(" ")[0] 
    else:
        custom_loc = st.text_input(t("【 2. 手動輸入位置 】", "【 2. Specify Location 】"), key=k(f"custom_loc_{is_orderly}"))
        final_bed = custom_loc if custom_loc else "Others"

    st.markdown("---")
    st.subheader(t("📋 步驟 2：任務細節", "📋 Step 2: Task Details"))
    priority = st.toggle(t("🚨 急件 (優先處理)", "🚨 URGENT (Priority Task)"), value=False, key=k(f"priority_{is_orderly}"))
    
    task_status = "Pending"
    if is_orderly:
        task_status_opt = st.radio(t("目前狀態", "Task Status"), [t("剛開始 (執行中)", "Just Started (In Progress)"), t("已處理完 (已完成)", "Already Finished (Completed)")], horizontal=True, key=k("status_opt"))
        task_status = "Completed" if "Already Finished" in task_status_opt or "已處理完" in task_status_opt else "In Progress"

    task_categories = ["🧑‍🤝‍🧑 Patient Care (病人照護)", "🧹 Environment (環境與儀器)", "📦 Supplies & Others (撥補與其他)", "🩸 Specimen/Blood (檢體/血品)", "🛏️ Transfer (推床/傳送)"]
    task_category = st.radio(t("任務類別", "Task Category"), task_categories, horizontal=True, key=k(f"task_cat_{is_orderly}"))
    
    details = ""; task_type_str = task_category.split(" ")[1] 
    is_turn_routine = False; is_feed_routine = False; clothes_purpose = ""; requested_reports = []
    actual_cares = []; actual_envs = []; actual_sups = []; actual_specs = []; actual_dests = []; custom_sup = ""
    
    with st.container(border=True):
        if task_category.startswith("🧑‍🤝‍🧑"):
            care_opts = ["Turn Over / Position (翻身/擺位)", "Change Clothes (換衣)", "Toileting / Empty Urine (大小便/倒尿)", "Body Clean / Change Diaper (身體清潔/換尿布墊)", "Feeding / Tube Feeding (餵食/灌食)", "Assist Transfer / Wheelchair (協助移位/坐輪椅)", "Assist Restraint (協助約束)", "Postmortem Care (遺體護理)"]
            selected_cares = checkbox_matrix(care_opts, f"care_{is_orderly}", num_columns=2)
            custom_care = st.text_input(t("其他照護事項", "Other Care Actions"), key=k(f"custom_care_{is_orderly}"))
            actual_cares = [c.split(" (")[0] for c in selected_cares]
            if custom_care: actual_cares.append(custom_care)
            care_str = " + ".join(actual_cares) if actual_cares else t("未指定", "Not Specified")
            
            st.markdown("---")
            if any("Turn Over" in c for c in actual_cares) and not is_orderly:
                st.write(t("🔀 **[翻身/擺位] 子項目:**", "🔀 **[Turn Over] Sub-settings:**"))
                is_turn_routine = st.checkbox(t("🔁 設為常規任務 (每奇數小時自動派發)", "🔁 Set as Routine (Every odd hour)"), key=k("turn_routine"))
            if any("Feeding" in c for c in actual_cares):
                st.write(t("🥣 **[餵食/灌食] 子項目:**", "🥣 **[Feeding] Sub-settings:**"))
                if not is_orderly: is_feed_routine = st.checkbox(t("🔁 設為常規任務 (Q4H: 1,5,9,13,17,21)", "🔁 Set as Routine (Q4H)"), key=k("feed_routine"))
                if st.checkbox(t("⚠️ 要求回報 (反抽量/灌入量)", "⚠️ Require Report (Residual/Feeding)"), value=True, key=k("feed_report")): requested_reports.append("Feeding")
            if any("Change Clothes" in c for c in actual_cares):
                st.write(t("👕 **[換衣] 子項目:**", "👕 **[Change Clothes] Sub-settings:**"))
                clothes_purpose = st.radio(t("換衣目的:", "Purpose:"), [t("一般換衣 (General)", "General"), t("手術準備 (Surgery prep)", "Surgery prep"), t("MRI 準備 (MRI prep)", "MRI prep")], horizontal=True, key=k("clothes_purpose"))
                requested_reports.append("Clothes")
            if any("Toileting" in c for c in actual_cares):
                st.write(t("🚽 **[大小便/倒尿] 子項目:**", "🚽 **[Toileting] Sub-settings:**"))
                if st.checkbox(t("⚠️ 要求回報 (尿量與顏色)", "⚠️ Require Report (Urine)"), value=True, key=k("urine_report")): requested_reports.append("Urine")
            if any("Diaper" in c for c in actual_cares):
                st.write(t("🧻 **[身體清潔/換尿布墊] 子項目:**", "🧻 **[Diaper] Sub-settings:**"))
                if st.checkbox(t("⚠️ 要求回報 (重量與性狀)", "⚠️ Require Report (Weight/Appearance)"), value=True, key=k("diaper_report")): requested_reports.append("Diaper")

            details = f"Action: {care_str}"
            if clothes_purpose and "一般" not in clothes_purpose and "General" not in clothes_purpose: details += f" [{clothes_purpose}]"
            
        elif task_category.startswith("🧹"):
            env_opts = ["Make Bed / Change Linens (鋪床/換單)", "Empty Suction Bottle (清理抽痰瓶)", "Change O2 Tank (更換氧氣筒)", "Clean Area / Resus Room (清理病房/急救室)"]
            selected_envs = checkbox_matrix(env_opts, f"env_{is_orderly}", num_columns=2)
            actual_envs = [e.split(" (")[0] for e in selected_envs]
            env_str = " + ".join(actual_envs) if actual_envs else t("未指定", "Not Specified")
            
            if any("Suction" in e for e in actual_envs):
                st.markdown("---")
                st.write(t("🫧 **[清理抽痰瓶] 子項目:**", "🫧 **[Suction] Sub-settings:**"))
                if st.checkbox(t("⚠️ 要求回報 (抽痰量/色/黏稠度)", "⚠️ Require Report (Amount/Color/Viscosity)"), value=True, key=k("suction_report")): requested_reports.append("Suction")
            details = f"Action: {env_str}"
            
        elif task_category.startswith("📦"):
            sup_opts = ["Restock Cart / IV (工作車/點滴撥補)", "Restock Linens (被服撥補)", "Sterilization (器械/甦醒球寄換消)", "Pharmacy / Supply Room (去藥局/庫房)", "Temporary Task (臨時交辦事項)"]
            selected_sups = checkbox_matrix(sup_opts, f"sup_{is_orderly}", num_columns=2)
            custom_sup = st.text_input(t("指定物品或說明 (必填)", "Specify items or details (Required)"), key=k(f"custom_sup_{is_orderly}"))
            actual_sups = [s.split(" (")[0] for s in selected_sups]
            sup_str = " + ".join(actual_sups) if actual_sups else t("未指定", "Not Specified")
            details = f"Action: {sup_str} | Notes: {custom_sup}"
            
        elif task_category.startswith("🩸"):
            specimen_opts = ["General Specimen (送一般檢體)", "Urgent Specimen (送緊急/隔離檢體)", "Pick up Blood (領血)"]
            selected_specs = checkbox_matrix(specimen_opts, f"spec_{is_orderly}", num_columns=3)
            actual_specs = [s.split(" (")[0] for s in selected_specs]
            spec_str = " + ".join(actual_specs) if actual_specs else t("未指定", "Not Specified")
            details = f"Items: {spec_str}"
            
        elif task_category.startswith("🛏️"):
            dest_opts = ["X-Ray (X光)", "CT (電腦斷層)", "MRI (核磁共振)", "Ultrasound (超音波)", "Ward (病房)", "ICU (加護病房)", "Discharge (協助出院)", "Hemodialysis (洗腎室)"]
            selected_dests = checkbox_matrix(dest_opts, f"dest_{is_orderly}", num_columns=4)
            actual_dests = [d.split(" ")[0] for d in selected_dests]
            dest_str = " + ".join(actual_dests) if actual_dests else t("未指定", "Not Specified")
            method = st.radio(t("傳送方式:", "Method:"), ["Bed (推床)", "Wheelchair (輪椅)", "Walk (步行)"], horizontal=True, key=k(f"method_{is_orderly}"))
            details = f"To: {dest_str} | Via: {method.split(' ')[0]}"

        st.markdown("---")
        global_memo = st.text_input(t("✍️ 備註說明", "✍️ Additional Notes"), key=k(f"global_memo_{is_orderly}"))
        if global_memo: details += f" | Extra: {global_memo}"

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button(t("🚀 確認建單", "🚀 Create Task") if is_orderly else t("🚀 確認送出", "🚀 Dispatch Task"), use_container_width=True, type="primary"):
        if task_category.startswith("🧑‍🤝‍🧑") and not actual_cares: st.warning(t("⚠️ 請選擇照護項目！", "⚠️ Please select Care actions!"))
        elif task_category.startswith("🧹") and not actual_envs: st.warning(t("⚠️ 請選擇環境整理項目！", "⚠️ Please select an Environment action!"))
        elif task_category.startswith("📦") and not actual_sups and not custom_sup.strip(): st.warning(t("⚠️ 請填寫事項！", "⚠️ Please specify action!"))
        elif task_category.startswith("🩸") and not actual_specs: st.warning(t("⚠️ 請選擇檢體項目！", "⚠️ Please select Specimen/Blood items!"))
        elif task_category.startswith("🛏️") and not actual_dests: st.warning(t("⚠️ 請選擇目的地！", "⚠️ Please select a Destination!"))
        else:
            time_str = get_tw_time().strftime("%Y-%m-%d %H:%M:%S")
            new_task = {
                "id": str(get_tw_time().timestamp()), "time_created": time_str, "time_received": time_str if is_orderly else "",
                "time_completed": time_str if task_status == "Completed" else "", "priority": priority, "location": final_bed, 
                "task_type": task_type_str, "details": details, "requested_reports": requested_reports, 
                "dispatched_by": f"{st.session_state.nickname} (Orderly)" if is_orderly else st.session_state.nickname, 
                "status": task_status, "assigned_to": st.session_state.nickname if is_orderly else "", "nursing_note": ""
            }
            tasks = load_data(DATA_FILE, []); tasks.append(new_task); save_data(tasks, DATA_FILE)
            
            if not is_orderly:
                routines = load_data(ROUTINE_FILE, [])
                if is_turn_routine:
                    routines.append({"id": str(get_tw_time().timestamp() + 1), "location": final_bed, "action": "Turn Over / Position", "routine_type": "odd_hours", "requested_reports": [], "dispatched_by": st.session_state.nickname, "last_triggered_date_hour": get_tw_time().strftime("%Y-%m-%d-%H") if get_tw_time().hour % 2 != 0 else ""})
                if is_feed_routine:
                    routines.append({"id": str(get_tw_time().timestamp() + 2), "location": final_bed, "action": "Feeding / Tube Feeding", "routine_type": "q4h", "requested_reports": ["Feeding"] if "Feeding" in requested_reports else [], "dispatched_by": st.session_state.nickname, "last_triggered_date_hour": get_tw_time().strftime("%Y-%m-%d-%H") if get_tw_time().hour in [1,5,9,13,17,21] else ""})
                if is_turn_routine or is_feed_routine: save_data(routines, ROUTINE_FILE); st.toast(t("🔁 已加入常規任務排程！", "🔁 Added to Routine Schedule!"), icon="🔄")
            
            st.session_state.form_id += 1; st.session_state.success_message = t(f"✅ 任務已登錄: {final_bed}", f"✅ Task Logged: {final_bed}"); reset_to_standby(); st.rerun()

# --- 接收與回報介面 ---
@st.dialog(t("📝 任務回報與結案", "📝 Task Feedback & Finish"))
def orderly_feedback_dialog(task_id):
    tasks = load_data(DATA_FILE, []); task = next((tk for tk in tasks if tk['id'] == task_id), None)
    if not task: return st.error("Task not found!")
    st.write(f"**📍 {task['location']}** | **{task['task_type']}**\nDetails: {task['details']}")
    st.markdown("---")
    
    req_reports = task.get('requested_reports', []); needs_review = len(req_reports) > 0; nursing_note_parts = []
    
    if "Clothes" in req_reports:
        st.write(t("👕 換衣任務確認", "👕 Change Clothes Confirmation"))
        if "手術準備" in task['details'] or "Surgery" in task['details']: nursing_note_parts.append("為手術準備更換衣物")
        elif "MRI" in task['details']: nursing_note_parts.append("為MRI檢查更換衣物")
        else: nursing_note_parts.append("協助更換衣物")
    if "Urine" in req_reports:
        st.write(t("🚽 排泄回報：", "🚽 Urine Report:"))
        c_amt = st.text_input(t("尿量 (cc)", "Amount (cc)"), key="u_amt"); c_col = st.text_input(t("顏色與性狀", "Color/Appearance"), key="u_col")
        if c_amt or c_col: nursing_note_parts.append(f"協助倒尿/大小便 ➔ 量: {c_amt}cc, 顏色: {c_col}")
    if "Diaper" in req_reports:
        st.write(t("🧻 尿布墊回報：", "🧻 Diaper Report:"))
        d_wt = st.text_input(t("重量 (g)", "Weight (g)"), key="d_wt"); d_col = st.text_input(t("顏色與性狀", "Color/Appearance"), key="d_col")
        if d_wt or d_col: nursing_note_parts.append(f"更換尿布/墊 ➔ 重量: {d_wt}g, 顏色/性狀: {d_col}")
    if "Feeding" in req_reports:
        st.write(t("🥣 灌食回報：", "🥣 Feeding Report:"))
        f_res = st.text_input(t("反抽量 (cc) / 消化狀況", "Residual Amount / Digestion"), key="f_res"); f_amt = st.text_input(t("實際灌食量 (cc)", "Feeding Amount (cc)"), key="f_amt")
        if f_res or f_amt: nursing_note_parts.append(f"協助餵食/灌食 ➔ 反抽量: {f_res}, 灌入: {f_amt}cc")
    if "Suction" in req_reports:
        st.write(t("🫧 抽痰瓶回報：", "🫧 Suction Bottle Report:"))
        s_amt = st.text_input(t("總量 (cc)", "Amount (cc)"), key="s_amt"); s_col = st.text_input(t("顏色", "Color"), key="s_col"); s_vis = st.text_input(t("黏稠度", "Viscosity"), key="s_vis")
        if s_amt or s_col or s_vis: nursing_note_parts.append(f"清理抽痰瓶 ➔ 量: {s_amt}cc, 顏色: {s_col}, 黏稠度: {s_vis}")

    if needs_review: st.markdown("---")
    feedback_text = st.text_input(t("✍️ 其他文字備註 (選填)", "✍️ Other Notes (Optional)"))
    if feedback_text: nursing_note_parts.append(f"備註: {feedback_text}")
    stop_routine = False
    if "Patient Care" in task['task_type']: stop_routine = st.checkbox(t("🛑 取消此床位的後續常規任務", "🛑 Stop future routines for this bed"), value=False)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button(t("💾 送出與結案", "💾 Submit & Finish"), type="primary", use_container_width=True):
        latest_tasks = load_data(DATA_FILE, [])
        for i in range(len(latest_tasks)):
            if latest_tasks[i]['id'] == task_id:
                if needs_review or feedback_text:
                    latest_tasks[i]['status'] = 'Awaiting Review'
                    latest_tasks[i]['nursing_note'] = f"[{get_tw_time().strftime('%H:%M')} 護佐 {st.session_state.nickname} 執行] " + "；".join(nursing_note_parts)
                else: latest_tasks[i]['status'] = 'Completed'
                latest_tasks[i]['time_completed'] = get_tw_time().strftime("%Y-%m-%d %H:%M:%S")
                if stop_routine: feedback_text += t(" [已手動取消常規]", " [Routine Stopped]")
                latest_tasks[i]['details'] += f" | Report: {feedback_text}" if feedback_text else ""
        save_data(latest_tasks, DATA_FILE)
        if stop_routine:
            routines = load_data(ROUTINE_FILE, []); routines = [r for r in routines if r["location"] != task["location"]]; save_data(routines, ROUTINE_FILE)
        reset_to_standby(); st.rerun()

def orderly_interface():
    st.header(t(f"🧑‍⚕️ 護佐接收端 ({st.session_state.nickname})", f"🧑‍⚕️ Orderly Panel ({st.session_state.nickname})"))
    check_for_new_alerts()
    tasks = load_data(DATA_FILE, []); pending = [tk for tk in tasks if tk['status'] == 'Pending']
    in_prog = [tk for tk in tasks if tk['status'] == 'In Progress' and tk['assigned_to'] == st.session_state.nickname]
    
    with st.expander(t("➕ 主動建單 / 廣播動態", "➕ Create Task / Broadcast")): assigner_interface(is_orderly=True)
    st.markdown("---")
    
    c1, c2 = st.columns(2)
    with c1:
        st.subheader(t(f"🔔 待接單 ({len(pending)})", f"🔔 Pending ({len(pending)})"))
        if pending:
            pending.sort(key=lambda x: (not x["priority"], x["time_created"]))
            for tk in pending:
                with st.container(border=True):
                    st.markdown(f"**{t('🚨 急件', '🚨 URGENT') if tk['priority'] else t('🟢 一般', '🟢 Routine')}** | **{tk['time_created'][11:16]}**")
                    st.markdown(f"### 📍 {tk['location']}\n📝 {tk['details']}")
                    if tk.get('requested_reports'): st.caption(f"⚠️ {t('需回報數據', 'Data Report Required')}")
                    if st.button(t("👉 點我接單", "👉 Take Order"), key=f"tk_{tk['id']}", use_container_width=True):
                        latest = load_data(DATA_FILE, [])
                        for i in range(len(latest)):
                            if latest[i]['id'] == tk['id']: latest[i]['status'] = 'In Progress'; latest[i]['assigned_to'] = st.session_state.nickname; latest[i]['time_received'] = get_tw_time().strftime("%Y-%m-%d %H:%M:%S")
                        save_data(latest, DATA_FILE); reset_to_standby(); st.rerun() 
        else: st.info(t("目前無任務。☕", "No pending tasks. ☕"))

    with c2:
        st.subheader(t(f"🏃 我的執行中 ({len(in_prog)})", f"🏃 My Tasks ({len(in_prog)})"))
        if in_prog:
            for tk in in_prog:
                with st.container(border=True):
                    st.markdown(f"**{t('🚨 急件', '🚨 URGENT') if tk['priority'] else t('🟢 一般', '🟢 Routine')}** | **🔵 {t('執行中', 'In Progress')}**")
                    st.markdown(f"### 📍 {tk['location']}\n📝 {tk['details']}")
                    if tk.get('requested_reports'): st.caption(f"⚠️ {t('需回報數據', 'Data Report Required')}")
                    if st.button(t("✅ 標記完成", "✅ Finish Task"), key=f"dn_{tk['id']}", use_container_width=True, type="primary"): orderly_feedback_dialog(tk['id'])
        else: st.success(t("無執行中任務。", "No active tasks."))

def whiteboard_interface():
    st.header(t("📊 動態白板", "📊 Dashboard"))
    check_for_new_alerts(); tasks = load_data(DATA_FILE, [])
    tab_r, tab_c = st.tabs([t("🚀 即時看板", "🚀 Real-time"), t("✅ 完成紀錄", "✅ Completed")])
    
    with tab_r:
        pending = [tk for tk in tasks if tk['status'] == 'Pending']; in_prog = [tk for tk in tasks if tk['status'] == 'In Progress']; aw_rev = [tk for tk in tasks if tk['status'] == 'Awaiting Review'] 
        online_users = load_data(ONLINE_FILE, {})
        active_os = [n for n, info in online_users.items() if info['role'] == "Orderly" and (get_tw_time() - datetime.strptime(info['last_seen'], "%Y-%m-%d %H:%M:%S")).total_seconds() < 900]
        busy_os = list(set([tk['assigned_to'] for tk in in_prog if tk['assigned_to']])); idle_os = [o for o in active_os if o not in busy_os]
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(t("🔴 待處理", "🔴 Pending"), len(pending)); c2.metric(t("🔵 執行中", "🔵 In Progress"), len(in_prog)); c3.metric(t("👀 待回報", "👀 Awaiting Review"), len(aw_rev)); c4.metric(t("🧑‍⚕️ 線上護佐", "🧑‍⚕️ Online"), len(active_os))
        st.markdown("---")
        w1, w2 = st.columns(2)
        with w1:
            st.subheader(t("🚨 待接單清單", "🚨 Pending List"))
            if pending:
                pending.sort(key=lambda x: (not x["priority"], x["time_created"]))
                dfp = pd.DataFrame(pending)[['time_created', 'priority', 'location', 'task_type', 'dispatched_by']]
                dfp['time_created'] = dfp['time_created'].str[11:16]; dfp['priority'] = dfp['priority'].apply(lambda x: "🚨" if x else "")
                dfp.columns = [t('時間', 'Time'), t('急件', 'Urgent'), t('位置', 'Location'), t('任務', 'Task'), t('發布者', 'From')]; st.dataframe(dfp, use_container_width=True, hide_index=True)
            else: st.success(t("目前無積壓任務！", "All clear!"))
        with w2:
            st.subheader(t("⚡ 執行中動態", "⚡ Active Tasks"))
            if in_prog:
                dfg = pd.DataFrame(in_prog)[['assigned_to', 'location', 'task_type']]
                dfg.columns = [t('護佐', 'Orderly'), t('位置', 'Location'), t('任務', 'Task')]; st.dataframe(dfg, use_container_width=True, hide_index=True)
            else: st.info(t("目前無正在執行的任務。", "No active tasks."))
                
    with tab_c:
        selected_date = st.date_input(t("選擇日期", "Date"), value=get_tw_time().date())
        comp_tasks = [tk for tk in tasks if tk['status'] == 'Completed' and (tk.get('time_completed') or tk.get('time_created')).startswith(str(selected_date))]
        if comp_tasks:
            dfc = pd.DataFrame(comp_tasks)[['time_completed', 'location', 'task_type', 'assigned_to', 'dispatched_by', 'nursing_note']]
            dfc['time_completed'] = dfc['time_completed'].str[11:16]
            dfc.columns = [t('完成時間', 'Time'), t('位置', 'Location'), t('任務', 'Task'), t('護佐', 'Orderly'), t('發布者', 'From'), t('護理紀錄', 'Nursing Note')]
            st.dataframe(dfc.sort_values(by=t('完成時間', 'Time'), ascending=False), use_container_width=True, hide_index=True)
        else: st.info(t("查無紀錄。", "No records found."))

def backend_interface():
    st.header(t("📂 後台數據紀錄", "📂 Backend Data Records"))
    tasks = load_data(DATA_FILE, [])
    if not tasks: return st.info(t("目前無任何紀錄。", "No records available."))
    df = pd.DataFrame(tasks); cols = ['id', 'priority', 'status', 'location', 'task_type', 'details', 'dispatched_by', 'assigned_to', 'time_created', 'time_received', 'time_completed', 'nursing_note']
    df = df[[c for c in cols if c in df.columns]]
    st.markdown(t("### 📋 完整任務資料表", "### 📋 Full Task Database"))
    st.dataframe(df.sort_values(by='time_created', ascending=False), use_container_width=True)
    st.download_button(t("📥 匯出為 CSV 檔案 (可供 Excel/Power BI 使用)", "📥 Export as CSV"), data=df.to_csv(index=False, encoding='utf-8-sig'), file_name=f"ER_Orderly_Records_{get_tw_time().strftime('%Y%m%d')}.csv", mime="text/csv", use_container_width=True, type="primary")

# --- 主程式入口 (處理 OAuth 重新導向) ---
def main():
    # 攔截 LINE OAuth 的回傳 Code
    if "code" in st.query_params and not st.session_state.is_logged_in:
        code = st.query_params["code"]
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
                st.session_state.nickname = profile_res.json().get("displayName")
                st.session_state.role = "Nurse" # 測試期間預設為護理師
                st.session_state.is_logged_in = True
                st.query_params.clear() # 清除網址列參數保持乾淨
                st.rerun()
            else: st.error("取得 LINE 檔案失敗，請重新登入")
        else: st.error("LINE 登入驗證失敗，請檢查金鑰或 Callback URL")

    with st.sidebar:
        st.session_state.lang = st.radio("🌐 Language / 語言", ["中文", "English"], horizontal=True, key="lang_selector")
        st.markdown("---")

    if st.session_state.is_logged_in: update_online_status(st.session_state.nickname, st.session_state.role)
        
    if not st.session_state.is_logged_in:
        with st.sidebar:
            page = st.radio(t("前往頁面", "Page"), [t("🔑 登入", "🔑 Login"), t("📊 白板 (免登入)", "📊 Dashboard (No)")], label_visibility="collapsed")
        if t("🔑 登入", "🔑 Login") in page: login_interface()
        else: whiteboard_interface()
    else:
        with st.sidebar:
            st.markdown(f"### 👤 **{st.session_state.nickname}**")
            st.caption(t("👩‍⚕️ 護理師", "👩‍⚕️ Nurse") if st.session_state.role == "Nurse" else t("🧑‍⚕️ 護佐", "🧑‍⚕️ Orderly"))
            st.markdown("---")
            
            if st.session_state.role == "Nurse":
                tasks = load_data(DATA_FILE, []); aw_rev = [tk for tk in tasks if tk.get('status') == 'Awaiting Review']
                if aw_rev:
                    st.markdown(f"### 👀 {t('待確認回報', 'Awaiting Review')} ({len(aw_rev)})")
                    for tk in aw_rev:
                        with st.expander(f"{tk['location']} - 🧑‍⚕️{tk['assigned_to']}", expanded=True):
                            st.code(tk['nursing_note'], language="text")
                            if st.button(t("✅ 歸檔", "✅ Archive"), key=f"rev_sb_{tk['id']}", use_container_width=True):
                                for i in range(len(tasks)):
                                    if tasks[i]['id'] == tk['id']: tasks[i]['status'] = 'Completed'
                                save_data(tasks, DATA_FILE); st.rerun()
                    st.markdown("---")
                
                archived = [tk for tk in tasks if tk.get('status') == 'Completed' and tk.get('nursing_note')]
                if archived:
                    archived.sort(key=lambda x: x.get('time_completed', ''), reverse=True)
                    with st.expander(t("✅ 最近歸檔紀錄 (找回)", "✅ Recently Archived (Recovery)")):
                        for tk in archived[:10]:
                            st.markdown(f"**{tk['location']}** ({tk['time_completed'][11:16]})")
                            st.code(tk['nursing_note'], language="text")
                    st.markdown("---")

            with st.expander(t("⚙️ 管理員專區 (強制下線)", "⚙️ Admin Area (Force Logout)")):
                admin_pwd = st.text_input(t("輸入管理員密碼", "Admin Password"), type="password", key="admin_pwd")
                if admin_pwd == "6155":
                    online_users = load_data(ONLINE_FILE, {})
                    if online_users:
                        target_user = st.selectbox(t("選擇要強制下線的人員", "Select user to logout"), list(online_users.keys()))
                        if st.button(t("🚨 強制下線", "🚨 Force Logout"), use_container_width=True):
                            remove_online_status(target_user); st.success(f"{target_user} 已強制下線！"); st.rerun()
                    else: st.info(t("目前無人上線", "No users online"))
                elif admin_pwd: st.error("密碼錯誤")
            st.markdown("---")

            if st.session_state.is_standby:
                st.success(t("🟢 **待命模式**", "🟢 **Standby**"))
                if st.button(t("⏸️ 暫停更新 (操作)", "⏸️ Switch to Input"), use_container_width=True): st.session_state.is_standby = False; st.session_state.op_mode_start = get_tw_time(); st.rerun()
            else:
                st.warning(t("🔴 **操作模式**", "🔴 **Input Mode**"))
                if st.button(t("▶️ 回復 待命模式", "▶️ Switch to Standby"), use_container_width=True): reset_to_standby(); st.rerun()
            st.markdown("---")
            
            if st.button(t("🚪 登出", "🚪 Logout"), use_container_width=True):
                remove_online_status(st.session_state.nickname)
                tasks = load_data(DATA_FILE, [])
                for tk in tasks:
                    if tk['status'] == 'In Progress' and tk['assigned_to'] == st.session_state.nickname: tk['status'] = 'Pending'; tk['assigned_to'] = ''
                save_data(tasks, DATA_FILE); st.session_state.is_logged_in = False; st.rerun()
            
            st.markdown("""<a href="." target="_blank" style="display:block;text-align:center;padding:0.45rem;margin-top:0.5rem;background-color:transparent;color:inherit;border-radius:0.5rem;border:1px solid rgba(128,128,128,0.5);text-decoration:none;">➕ 開啟新分頁 (切換角色)</a>""", unsafe_allow_html=True)
            st.markdown("---")
            
            pages = [t("👩‍⚕️ 護理師派發", "👩‍⚕️ Dispatch (Nurse)"), t("🧑‍⚕️ 護佐接收", "🧑‍⚕️ Receive (Orderly)"), t("📊 動態白板", "📊 Dashboard"), t("📂 後台紀錄", "📂 Backend Data")]
            page = st.radio(t("選單", "Menu"), pages, index=0 if st.session_state.role == "Nurse" else 1, label_visibility="collapsed")
            
        if t("派發", "Dispatch") in page: assigner_interface(is_orderly=False)
        elif t("接收", "Receive") in page: orderly_interface()
        elif t("白板", "Dashboard") in page: whiteboard_interface()
        elif t("後台", "Backend") in page: backend_interface()

if __name__ == "__main__":
    main()
