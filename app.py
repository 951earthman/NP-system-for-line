import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json
import os
import re
import random
import requests
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# --- 頁面基本設定 ---
st.set_page_config(page_title="急診專師協助派發系統", page_icon="🏥", layout="wide")

# ==========================================
# 🛑 LINE Bot 設定區
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = "YOUR_LINE_CHANNEL_ACCESS_TOKEN" 
TARGET_LINE_ID = "YOUR_LINE_USER_ID" 

def send_line_notification(task_data):
    """發送 LINE 推播訊息"""
    if LINE_CHANNEL_ACCESS_TOKEN == "YOUR_LINE_CHANNEL_ACCESS_TOKEN":
        return 
        
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    msg_text = (
        f"🚨【新任務派發】{task_data['priority']}\n"
        f"📍 位置: {task_data['bed']}\n"
        f"📝 任務: {task_data['task_type']}\n"
        f"📋 備註: {task_data['details']}\n"
        f"👨‍⚕️ 派發人: {task_data['requester']} ({task_data['requester_role']})\n"
        f"⏱️ 時間: {task_data['time'][11:16]}"
    )
    
    payload = {
        "to": TARGET_LINE_ID,
        "messages": [{"type": "text", "text": msg_text}]
    }
    
    try:
        response = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload)
        response.raise_for_status() 
    except requests.exceptions.RequestException as e:
        print(f"LINE 推播失敗: {e}")

# ==========================================

# --- 初始化 Session State ---
# 1. 登入狀態與網址記憶
if "is_logged_in" not in st.session_state:
    if "nickname" in st.query_params and "role" in st.query_params:
        st.session_state.nickname = st.query_params["nickname"]
        st.session_state.role = st.query_params["role"]
        st.session_state.is_logged_in = True
    else:
        st.session_state.nickname = ""
        st.session_state.role = ""
        st.session_state.is_logged_in = False

if "success_message" not in st.session_state:
    st.session_state.success_message = ""

# 2. 雙模式切換狀態 (待命 vs 操作)
if "is_standby" not in st.session_state:
    st.session_state.is_standby = True  
if "op_mode_start" not in st.session_state:
    st.session_state.op_mode_start = None

# 3. 動態表單金鑰 (用於送出後完美重置表單)
if "form_id" not in st.session_state:
    st.session_state.form_id = 0

# --- 台灣時間轉換函數 ---
def get_tw_time():
    return datetime.utcnow() + timedelta(hours=8)

# --- 5 分鐘操作逾時自動回歸機制 ---
if not st.session_state.is_standby and st.session_state.op_mode_start:
    if (get_tw_time() - st.session_state.op_mode_start).total_seconds() >= 295:
        st.session_state.is_standby = True
        st.session_state.op_mode_start = None
        st.toast("⏳ 您已停留操作模式超過 5 分鐘，系統已自動切回【待命模式】以確保接收新任務！", icon="🔄")

# --- 動態高頻率心跳機制 (Heartbeat) ---
refresh_interval = 10000 if st.session_state.is_standby else 300000
count = st_autorefresh(interval=refresh_interval, limit=None, key="data_sync_refresh")

# --- 檔案與資料庫操作 ---
DATA_FILE = "task_data.json"
ONLINE_FILE = "online_users.json"

BED_DATA_COMPLEX = {
    "留觀(OBS)": {
        "OBS 1": ["1", "2", "3", "5", "6", "7", "8", "9", "10", "35", "36", "37", "38"],
        "OBS 2": ["11", "12", "13", "15", "16", "17", "18", "19", "20", "21", "22", "23"],
        "OBS 3": ["25", "26", "27", "28", "29", "30", "31", "32", "33", "39"]
    },
    "診間": {
        "第一診間": ["11", "12", "13", "15", "21", "22", "23", "25"],
        "第二診間": ["16", "17", "18", "19", "20", "36", "37", "38"],
        "第三診間": ["5", "6", "27", "28", "29", "30", "31", "32", "33", "39"]
    },
    "兒科": {
        "兒科床位": ["501", "502", "503", "505", "506", "507", "508", "509"]
    },
    "急救區": {},
    "檢傷": {},
    "縫合室": {},
    "超音波室": {}
}

def load_data():
    if not os.path.exists(DATA_FILE): 
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for t in data:
                if 'priority' not in t: t['priority'] = '🟢 一般'
            return data
    except Exception as e:
        print(f"警告：讀取 task_data.json 時發生錯誤 ({e})，系統將自動重置狀態。")
        return []

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_online_users():
    if not os.path.exists(ONLINE_FILE): 
        return {}
    try:
        with open(ONLINE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"警告：讀取 online_users.json 時發生錯誤 ({e})，系統將自動重置狀態。")
        return {}

def save_online_users(data):
    with open(ONLINE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def update_online_status(nickname, role):
    users = load_online_users()
    users[nickname] = {"role": role, "last_seen": get_tw_time().strftime("%Y-%m-%d %H:%M:%S")}
    save_online_users(users)

def remove_online_status(nickname):
    users = load_online_users()
    if nickname in users:
        del users[nickname]
        save_online_users(users)

def check_pii(*texts):
    for t in texts:
        if t and re.search(r'[A-Za-z][1289]\d{8}', str(t)): return True
    return False

if "known_task_ids" not in st.session_state:
    st.session_state.known_task_ids = set([t['id'] for t in load_data()])

def check_for_new_alerts():
    tasks = load_data()
    current_ids = set([t['id'] for t in tasks])
    new_ids = current_ids - st.session_state.known_task_ids
    
    if new_ids:
        latest_new_task = next((t for t in tasks if t['id'] in new_ids), None)
        is_self_dispatched = latest_new_task and latest_new_task.get('requester') == st.session_state.nickname
        
        if not is_self_dispatched:
            st.toast("🚨 系統有新的協助任務派發！請查看列表。", icon="🔔")
            alert_js = """
            <script>
                let audio = new Audio("https://actions.google.com/sounds/v1/alarms/beep_short.ogg");
                audio.play().catch(e => console.log("Audio play prevented:", e));
                
                if ('speechSynthesis' in window) {
                    let msg = new SpeechSynthesisUtterance("急診專師請注意，有新任務派發！");
                    msg.lang = 'zh-TW';
                    msg.rate = 1.0;
                    window.speechSynthesis.speak(msg);
                }
                
                let originalTitle = document.title;
                let isFlashing = false;
                let flashInterval;
                
                function startFlashing() {
                    if (isFlashing) return;
                    isFlashing = true;
                    let showAlert = true;
                    flashInterval = setInterval(() => {
                        document.title = showAlert ? "🚨 新任務來囉！" : "🏥 趕快切換回來！";
                        showAlert = !showAlert;
                    }, 1000);
                }
                
                function stopFlashing() {
                    clearInterval(flashInterval);
                    document.title = "🏥 急診專師協助派發系統";
                    isFlashing = false;
                }
                
                if (document.hidden) {
                    startFlashing();
                } else {
                    startFlashing();
                    setTimeout(stopFlashing, 4000);
                }
                
                document.addEventListener("visibilitychange", () => {
                    if (!document.hidden) stopFlashing();
                });
                document.addEventListener("click", stopFlashing);
            </script>
            """
            components.html(alert_js, width=0, height=0)
        
    st.session_state.known_task_ids = current_ids

def reset_to_standby():
    st.session_state.is_standby = True
    st.session_state.op_mode_start = None

# --- UI 輔助函數：展開式複選框矩陣 ---
def checkbox_matrix(options, key_prefix, num_columns=4):
    """將選項攤平為 checkbox 矩陣，並利用 form_id 確保能自動重置"""
    selected = []
    cols = st.columns(num_columns)
    for i, option in enumerate(options):
        with cols[i % num_columns]:
            # 動態 Key 綁定 form_id，送出後自動失效重置
            if st.checkbox(option, key=f"matrix_{key_prefix}_{option}_{st.session_state.form_id}"):
                selected.append(option)
    return selected

# --- 動態 Key 產生器 ---
def k(name):
    """根據當前 form_id 產生唯一的 key，用於表單送出後自動清空"""
    return f"{name}_{st.session_state.form_id}"

# --- 確認彈出視窗 ---
@st.dialog("⚠️ 確認派發任務")
def confirm_dispatch_dialog(new_task, require_prep=False, require_hd_consent=False):
    st.write(f"即將派發：**{new_task['priority']}** | **{new_task['bed']}** 的 **{new_task['task_type']}** 請求。")
    
    consent = "是"
    reason = ""
    
    if require_prep:
        st.warning("護理師提醒：請問是否已完成相關備物？")
    
    if require_hd_consent:
        st.warning("請問是否已完成洗腎同意書？")
        consent = st.radio("同意書狀態", ["是", "否"], horizontal=True, label_visibility="collapsed")
        if consent == "否":
            reason = st.text_input("請填寫未完成原因 (必填)", placeholder="例如：家屬尚未抵達...")
            
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🚀 確認送出", type="primary", use_container_width=True):
            if require_hd_consent and consent == "否" and not reason.strip():
                st.error("⚠️ 選擇「否」時，必須填寫未完成原因！")
            else:
                if require_hd_consent:
                    if consent == "否":
                        new_task['details'] += f" | 同意書: 未完成 ({reason})"
                    else:
                        new_task['details'] += f" | 同意書: 已完成"
                        
                tasks = load_data()
                tasks.append(new_task)
                save_data(tasks)
                send_line_notification(new_task)
                
                # 【關鍵邏輯】觸發表單重置與回歸待命
                st.session_state.form_id += 1  
                st.session_state.success_message = f"✅ 已成功送出 【 {new_task['bed']} 】 的 【{new_task['task_type']}】 請求！"
                reset_to_standby() 
                st.rerun() 
    with col2:
        if st.button("❌ 返回修改", use_container_width=True):
            st.rerun()

# --- 專科護理師專用：任務回報彈出視窗 ---
@st.dialog("📝 執行任務回報與結案")
def np_feedback_dialog(task_id, is_doc_assisted=False):
    tasks = load_data()
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        st.error("找不到該任務資料！")
        return

    st.write(f"**位置/病患：** {task['bed']} | **任務：** {task['task_type']}")
    st.write(f"**派發者：** {task['requester']} ({task['requester_role']})")
    st.markdown("---")
    
    feedback_text = ""
    if is_doc_assisted:
        st.info("💡 目前為「醫師已協助完成」模式")
        feedback_text = st.text_input("處理結果備註", value="醫師已於現場協助處理完畢")
    else:
        if task['task_type'] == "Suture (縫合)":
            thread_choice = st.radio("實際使用縫線", ["Nylon 1-0", "Nylon 2-0", "Nylon 3-0", "Nylon 4-0", "Nylon 5-0", "Nylon 6-0", "其他 (自行輸入)"], horizontal=True)
            if thread_choice == "其他 (自行輸入)":
                thread = st.text_input("請輸入自訂縫線", placeholder="例如: Prolene 4-0")
                if not thread: thread = "未填寫"
            else:
                thread = thread_choice
            stitches = st.number_input("縫合針數", min_value=1, max_value=50, value=3, step=1)
            feedback_text = f"縫線: {thread} | 針數: {stitches} 針"
            
        elif task['task_type'] == "on Foley":
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                material = st.radio("材質", ["一般 (Latex)", "矽質 (Silicone)"], horizontal=True)
            with col_f2:
                size = st.radio("尺寸 (Fr)", ["14", "16", "18", "20", "22"], horizontal=True)
            feedback_text = f"材質: {material} | 尺寸: {size} Fr"
            
        elif task['task_type'] == "on NG":
            col_n1, col_n2 = st.columns(2)
            with col_n1:
                nostril = st.radio("固定鼻孔", ["左鼻孔", "右鼻孔"], horizontal=True)
                material = st.radio("材質", ["一般 (PVC)", "矽質 (Silicone)"], horizontal=True)
            with col_n2:
                fix_cm = st.number_input("固定刻度 (公分數)", min_value=10, max_value=100, value=55, step=1)
            feedback_text = f"鼻孔: {nostril} | 材質: {material} | 固定刻度: {fix_cm} cm"
            
        else:
            feedback_text = st.text_input("處理結果備註 (選填)", placeholder="例如：已完成採集、已處理完畢...")
            if not feedback_text: feedback_text = "已處理完畢"

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("💾 儲存回報並結案", type="primary", use_container_width=True):
        latest_tasks = load_data()
        for i in range(len(latest_tasks)):
            if latest_tasks[i]['id'] == task_id:
                latest_tasks[i]['status'] = '已完成'
                latest_tasks[i]['complete_time'] = get_tw_time().strftime("%Y-%m-%d %H:%M:%S")
                if is_doc_assisted:
                    latest_tasks[i]['handler'] = f"{st.session_state.nickname} (註記醫師完成)"
                else:
                    latest_tasks[i]['handler'] = st.session_state.nickname
                latest_tasks[i]['feedback'] = feedback_text
        save_data(latest_tasks)
        st.session_state.success_message = "✅ 任務結案與回報完成！"
        reset_to_standby() 
        st.rerun()

@st.dialog("⚠️ 警告：刪除選取的紀錄")
def delete_selected_dialog(ids_to_delete):
    st.error(f"您即將刪除選取的 {len(ids_to_delete)} 筆紀錄！此動作無法復原。")
    pwd = st.text_input("請輸入系統密碼以確認", type="password")
    if st.button("🚨 確認刪除選取項目", type="primary", use_container_width=True):
        if pwd == "6155":
            tasks = load_data()
            tasks = [t for t in tasks if t['id'] not in ids_to_delete]
            save_data(tasks)
            st.session_state.known_task_ids = set([t['id'] for t in tasks])
            st.session_state.success_message = f"✅ 已成功刪除 {len(ids_to_delete)} 筆紀錄！"
            st.rerun()
        else:
            st.error("密碼錯誤，拒絕刪除！")

@st.dialog("💥 警告：清除全部紀錄")
def clear_records_dialog():
    st.error("您即將清除系統中的「所有」任務紀錄！此動作無法復原。")
    pwd = st.text_input("請輸入系統密碼以確認", type="password")
    if st.button("🚨 確認清空資料庫", type="primary", use_container_width=True):
        if pwd == "6155":
            save_data([]) 
            st.session_state.known_task_ids = set()
            st.session_state.success_message = "✅ 系統內所有紀錄已成功清除！"
            st.rerun()
        else:
            st.error("密碼錯誤，拒絕清除！")

def login_interface():
    st.header("🔑 系統登入")
    
    with st.container(border=True):
        st.subheader("1. 輸入您的綽號")
        nickname_input = st.text_input("手動輸入新綽號 (必填)")
        
        st.markdown("---")
        st.subheader("2. 選擇您的身分")
        role_input = st.radio("身分選擇", ["護理師", "醫師", "專科護理師"], horizontal=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 登入系統", use_container_width=True, type="primary"):
            final_nickname = nickname_input.strip()
            if not final_nickname: st.error("請輸入綽號！")
            else:
                st.session_state.nickname = final_nickname
                st.session_state.role = role_input
                st.session_state.is_logged_in = True
                st.query_params["nickname"] = final_nickname
                st.query_params["role"] = role_input
                st.rerun()

# --- 派發任務介面 (醫師/護理師) ---
def assigner_interface(view_role="護理師"):
    st.header(f"👋 {view_role} 派發介面")
    
    if st.session_state.success_message:
        st.success(st.session_state.success_message)
        st.session_state.success_message = "" 
        
    st.markdown("---")
    
    st.subheader("📍 步驟 1：選擇位置")
    area_options = list(BED_DATA_COMPLEX.keys()) + ["病患無床位"]
    area = st.radio("【 1. 先選大區域 】", area_options, horizontal=True, key=k("area"))
    final_bed = ""; bed_note = ""; patient_name = ""
    
    if area in ["留觀(OBS)", "診間"]:
        sub_area = st.radio(f"【 2. 選擇 {area} 區域 】", list(BED_DATA_COMPLEX[area].keys()), horizontal=True, key=k("sub_area"))
        bed_num = st.radio(f"【 3. 選擇 {sub_area} 床號 】", BED_DATA_COMPLEX[area][sub_area], horizontal=True, key=k("bed_num"))
        final_bed = f"{sub_area} {bed_num}床"
    elif area == "兒科":
        bed_num = st.radio("【 2. 選擇床號 】", BED_DATA_COMPLEX[area]["兒科床位"], horizontal=True, key=k("peds_bed"))
        final_bed = f"兒科 {bed_num}床"
    elif area == "病患無床位":
        patient_name = st.text_input("【 2. 填寫病患姓名 (必填) 】", placeholder="請在此貼上或輸入病患姓名...", key=k("patient_name"))
        if patient_name: final_bed = f"無床位 (病患: {patient_name})"
        else: final_bed = "無床位"
    else:
        bed_note = st.text_input(f"【 2. {area} 備註 (選填) 】", placeholder="例如：等待推床...", key=k("bed_note"))
        final_bed = area
        if bed_note: final_bed += f" ({bed_note})"

    st.markdown("---")
    st.subheader("📋 步驟 2：選擇協助項目與優先級")
    priority = st.radio("優先級別", ["🟢 一般", "🔴 緊急"], horizontal=True, key=k("priority"))
    
    task_options = [
        "on Foley", "on NG", "Suture (縫合)", "會診", "藥物開立", 
        "檢體採集", "安排洗腎", "訂ICU", "開診斷書", "拍照", "追蹤", "其他"
    ]
    task_type = st.radio("協助項目", task_options, horizontal=True, key=k("task_type"))
    
    details = ""
    med_details = ""; consult_dept_str = ""; hd_days = []; spec_type = ""; wound_sub = []
    wound_part_sub = []; diag_lang = ""; photo_part = ""; other_desc = ""; icu_type = ""
    
    actual_s_parts = []
    actual_s_lines = []
    actual_consult_depts = []
    actual_wound_parts = []
    actual_wounds = []
    actual_tracks = []
    
    with st.container(border=True):
        st.markdown("##### 填寫詳細設定")
        if task_type == "on Foley":
            f_type = st.radio("Foley 種類", ["一般", "矽質"], horizontal=True, key=k("f_type"))
            f_sample = st.checkbox("需留取檢體", key=k("f_sample"))
            details = f"種類: {f_type} | 檢體: {'是' if f_sample else '否'}"
            
        elif task_type == "on NG":
            ng_type_choice = st.radio("NG 目的", ["Re-on", "Decompression", "IRRI (沖洗)", "其他 (自行輸入)"], horizontal=True, key=k("ng_type"))
            if ng_type_choice == "其他 (自行輸入)":
                custom_ng = st.text_input("請輸入自訂目的", key=k("custom_ng"))
                actual_ng = custom_ng if custom_ng else "未填寫"
            else: actual_ng = ng_type_choice
            details = f"目的: {actual_ng}"
            
        elif task_type == "Suture (縫合)":
            st.write("縫合部位 (可複選):")
            s_parts = ["左手", "左腳", "右手", "右腳", "胸口", "肚子", "背後", "頭皮", "臉", "脖子"]
            selected_s_parts = checkbox_matrix(s_parts, "s_part", num_columns=5)
            custom_s_part = st.text_input("其他縫合部位 (自行輸入)", key=k("custom_s_part"))
            if custom_s_part: selected_s_parts.append(custom_s_part)
            s_part_str = " + ".join(selected_s_parts) if selected_s_parts else "未選擇部位"
            actual_s_parts = selected_s_parts 
            
            st.write("縫線選擇 (可複選):")
            s_lines = ["Nylon 1-0", "Nylon 2-0", "Nylon 3-0", "Nylon 4-0", "Nylon 5-0", "Nylon 6-0", "由專科護理師自行評估"]
            selected_s_lines = checkbox_matrix(s_lines, "s_line", num_columns=4)
            custom_s_line = st.text_input("其他縫線 (自行輸入)", key=k("custom_s_line"))
            if custom_s_line: selected_s_lines.append(custom_s_line)
            s_line_str = " + ".join(selected_s_lines) if selected_s_lines else "未選擇縫線"
            actual_s_lines = selected_s_lines 
            
            details = f"部位: {s_part_str} | 縫線: {s_line_str}"
            
        elif task_type == "會診":
            st.write("會診科別 (可複選):")
            depts = [
                "ENT (耳鼻喉科)", "OPH (眼科)", "PS (整形外科)", "GS (一般外科)", 
                "CVS (心臟血管外科)", "GU (泌尿科)", "Ortho (骨科)", "NS (神經外科)",
                "GYN (婦產科)", "CV (心臟內科)", "Hospice (安寧/家醫科)", "INF (感染科)"
            ]
            selected_depts = checkbox_matrix(depts, "dept", num_columns=4)
            custom_dept = st.text_input("其他會診科別 (自行輸入)", key=k("custom_dept"))
            if custom_dept: selected_depts.append(custom_dept)
            actual_consult_depts = selected_depts 
            
            consult_dept_str = " + ".join(selected_depts) if selected_depts else "未選擇科別"
            details = f"科別: {consult_dept_str}"
            
        elif task_type == "藥物開立":
            med_details = st.text_input("藥物/說明 (必填)", key=k("med_details"))
            details = f"說明: {med_details}"
            
        elif task_type == "安排洗腎":
            if view_role == "醫師": st.info("💡 醫師提醒：請務必完成「洗腎同意書」！")
            st.write("平常洗腎日 (可複選):")
            hd_day_opts = ["週一", "週二", "週三", "週四", "週五", "週六", "初次洗腎"]
            hd_days = checkbox_matrix(hd_day_opts, "hd_day", num_columns=4)
            
            hd_location = st.radio("地點", ["本院", "外院", "不明"], horizontal=True, key=k("hd_location"))
            days_str = ",".join(hd_days) if hd_days else "未勾選"
            details = f"洗腎日: {days_str} | 地點: {hd_location}"
            
        elif task_type == "檢體採集":
            spec_type = st.radio("採集內容", ["鼻口腔黏膜", "傷口"], horizontal=True, key=k("spec_type"))
            if spec_type == "傷口":
                st.write("傷口部位 (可複選):")
                wp_opts = ["頭頸部", "軀幹", "上肢", "下肢", "臀部/會陰"]
                selected_wps = checkbox_matrix(wp_opts, "wp", num_columns=5)
                custom_wp = st.text_input("其他傷口部位 (自行輸入)", key=k("custom_wp"))
                if custom_wp: selected_wps.append(custom_wp)
                actual_wound_parts = selected_wps
                wound_part_str = " + ".join(selected_wps) if selected_wps else "未選擇部位"
                
                st.write("傷口培養類別 (可複選):")
                w_opts = ["嗜氧", "厭氧"]
                selected_ws = checkbox_matrix(w_opts, "ws", num_columns=2)
                custom_w = st.text_input("其他培養類別 (自行備註)", key=k("custom_w"))
                if custom_w: selected_ws.append(custom_w)
                actual_wounds = selected_ws
                wound_str = " + ".join(selected_ws) if selected_ws else "未選擇培養"
                
                details = f"內容: 傷口 | 部位: {wound_part_str} | 培養: {wound_str}"
            else:
                details = f"內容: 鼻口腔黏膜"
                if view_role == "護理師":
                    st.info("💡 護理師提醒：請印好條碼貼上採檢棒，並放於待採檢區。")
                    
        elif task_type == "訂ICU":
            icu_type = st.radio("ICU 類別", ["MICU (內科加護)", "CCU (心臟加護)", "PICU (兒科加護)", "其他"], horizontal=True, key=k("icu_type"))
            if icu_type == "其他":
                icu_actual = st.text_input("輸入其他 ICU 單位", key=k("custom_icu"))
            else:
                icu_actual = icu_type
            details = f"類別: {icu_actual}"
            
        elif task_type == "開診斷書":
            diag_lang = st.radio("診斷書版本 (必選)", ["中文版", "英文版", "中英雙語"], horizontal=True, key=k("diag_lang"))
            details = f"版本: {diag_lang}"
            
        elif task_type == "拍照":
            photo_part = st.text_input("拍照部位 (必填)", placeholder="例如：右小腿撕裂傷、臉部擦傷...", key=k("photo_part"))
            details = f"部位: {photo_part}"
            
        elif task_type == "追蹤":
            st.write("追蹤項目 (可複選):")
            track_opts = ["會診回復", "消化道檢查報告", "放射科檢查報告", "心電圖", "Lab data"]
            selected_tracks = checkbox_matrix(track_opts, "track", num_columns=5)
            custom_track = st.text_input("追蹤項目說明 / 其他 (自行輸入)", placeholder="例如：GS的會診回復、胃鏡檢查報告、ileus追蹤...", key=k("custom_track"))
            
            actual_tracks = list(selected_tracks)
            if custom_track.strip():
                actual_tracks.append(custom_track.strip())
                
            track_str = " + ".join(actual_tracks) if actual_tracks else "未填寫"
            details = f"項目: {track_str}"
            
        elif task_type == "其他":
            other_desc = st.text_input("請輸入協助事項 (必填)", placeholder="請簡述需要專師協助的內容...", key=k("other_desc"))
            details = f"事項: {other_desc}"
            
        st.markdown("---")
        global_memo = st.text_input("✍️ 通用補充說明 / 自行輸入 (選填)", placeholder="有任何特殊需求或注意事項請在此填寫...", key=k("global_memo"))
        if global_memo:
            details += f" | 補充: {global_memo}"

    st.markdown("<br>", unsafe_allow_html=True)
    
    # 判斷是否需要備物確認 (護理師專用邏輯)
    no_prep_tasks = ["會診", "藥物開立", "訂ICU", "開診斷書", "追蹤"]
    
    if st.button("🚀 準備派發任務", use_container_width=True, type="primary"):
        # 防呆檢查 
        if check_pii(patient_name, details, bed_note, consult_dept_str, med_details, global_memo, other_desc):
            st.error("⚠️ 資安警告：偵測到疑似身分證字號！已攔截派發。"); st.stop()
            
        if area == "病患無床位" and not patient_name.strip(): st.warning("⚠️ 請填寫病患姓名！")
        elif task_type == "Suture (縫合)" and not actual_s_parts: st.warning("⚠️ 請至少選擇一個縫合部位！")
        elif task_type == "Suture (縫合)" and not actual_s_lines: st.warning("⚠️ 請至少選擇一種縫線！")
        elif task_type == "會診" and not actual_consult_depts: st.warning("⚠️ 請至少選擇一個會診科別！")
        elif task_type == "藥物開立" and not med_details.strip(): st.warning("⚠️ 請填寫藥物說明！")
        elif task_type == "檢體採集" and spec_type == "傷口" and (not actual_wounds or not actual_wound_parts): st.warning("⚠️ 傷口採集請務必勾選「部位」與「培養類別」！")
        elif task_type == "拍照" and not photo_part.strip(): st.warning("⚠️ 請填寫拍照部位！")
        elif task_type == "追蹤" and not actual_tracks: st.warning("⚠️ 請至少勾選或填寫一項追蹤內容！")
        elif task_type == "其他" and not other_desc.strip(): st.warning("⚠️ 請填寫協助事項！")
        else:
            new_task = {
                "id": str(get_tw_time().timestamp()), 
                "time": get_tw_time().strftime("%Y-%m-%d %H:%M:%S"), 
                "priority": priority, 
                "bed": final_bed, 
                "task_type": task_type, 
                "details": details, 
                "requester": st.session_state.nickname, 
                "requester_role": view_role, 
                "status": "待處理", 
                "handler": "", 
                "start_time": "", 
                "complete_time": "", 
                "feedback": ""
            }
            if view_role == "護理師":
                if task_type in no_prep_tasks:
                    confirm_dispatch_dialog(new_task, require_prep=False, require_hd_consent=False)
                elif task_type == "安排洗腎":
                    confirm_dispatch_dialog(new_task, require_prep=False, require_hd_consent=True)
                else:
                    confirm_dispatch_dialog(new_task, require_prep=True, require_hd_consent=False)
            else:
                confirm_dispatch_dialog(new_task, require_prep=False, require_hd_consent=False)

def np_interface():
    st.header(f"👩‍⚕️ 專科護理師接收介面")
    
    check_for_new_alerts()
    
    tasks = load_data()
    pending = [t for t in tasks if t['status'] == '待處理']
    in_prog = [t for t in tasks if t['status'] == '執行中' and t['handler'] == st.session_state.nickname]
    
    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"🔔 待接單 ({len(pending)})")
        if pending:
            for t in pending:
                task_time = datetime.strptime(t['time'], "%Y-%m-%d %H:%M:%S")
                overdue_time = task_time + timedelta(hours=1)
                is_overdue = get_tw_time() > overdue_time
                
                status_icon = "🔴" if is_overdue else "🟡"
                overdue_text = " ⚠️ (已超時)" if is_overdue else ""
                
                with st.container(border=True):
                    st.markdown(f"**{t['priority']}** | **{status_icon} {t['time'][11:16]} | {t['bed']} - {t['task_type']}**{overdue_text}")
                    st.markdown(f"📞 **派發者：{t['requester']} ({t['requester_role']})**")
                    st.write(f"📝 內容：{t['details']}")
                    
                    if t['task_type'] == "檢體採集" and "鼻口腔黏膜" in t['details']:
                        st.warning("🛡️ **防護提醒：** 執行鼻口腔黏膜採集，請務必配戴**護目鏡與口罩**，保護自身安全！")
                    
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button(f"👉 點我接單", key=f"tk_{t['id']}", use_container_width=True):
                            latest_tasks = load_data()
                            for i in range(len(latest_tasks)):
                                if latest_tasks[i]['id'] == t['id']:
                                    latest_tasks[i]['status'] = '執行中'
                                    latest_tasks[i]['handler'] = st.session_state.nickname
                                    latest_tasks[i]['start_time'] = get_tw_time().strftime("%Y-%m-%d %H:%M:%S")
                            save_data(latest_tasks)
                            reset_to_standby() 
                            st.rerun() 
                    with b2:
                        if st.button(f"👨‍⚕️ 醫師已完成", key=f"dd_{t['id']}", use_container_width=True):
                            np_feedback_dialog(t['id'], is_doc_assisted=True)
        else:
            empty_pending_msgs = [
                "目前急診前線暫時和平，先去喝口水、喘口氣吧！☕",
                "待辦清單清空啦！辛苦了，趁現在稍微拉個筋休息一下吧！✨",
                "現在沒有新任務喔！難得的平靜時刻，讓自己放空三分鐘吧～",
                "您真的很棒！趁著空檔趕快去上個洗手間，照顧病患也要照顧自己喔！💪"
            ]
            st.info(random.choice(empty_pending_msgs))

    with c2:
        st.subheader(f"🏃 我的執行中 ({len(in_prog)})")
        if in_prog:
            for t in in_prog:
                with st.container(border=True):
                    st.markdown(f"**{t['priority']}** | **🔵 {t['bed']} - {t['task_type']}**")
                    st.markdown(f"📞 **派發者：{t['requester']} ({t['requester_role']})**")
                    st.write(f"📝 內容：{t['details']}")
                    st.write(f"⏱️ 接單時間：{t['start_time'][11:16]}")
                    if t['task_type'] == "檢體採集" and "鼻口腔黏膜" in t['details']:
                        st.warning("🛡️ **防護提醒：** 請配戴護目鏡與口罩！")
                    if st.button(f"✅ 標記完成", key=f"dn_{t['id']}", use_container_width=True, type="primary"):
                        np_feedback_dialog(t['id'], is_doc_assisted=False)
        else:
            empty_prog_msgs = [
                "手邊暫時沒有正在執行的處置，可以稍微喘息一下！",
                "完美結案！現在是您的短暫 off-time，辛苦了！🎉",
                "目前沒有處理中的任務，隨時準備迎接下一個挑戰！"
            ]
            st.success(random.choice(empty_prog_msgs))

def whiteboard_interface():
    st.header("📊 系統動態白板")
    
    check_for_new_alerts()
    
    tasks = load_data()
    
    tab_realtime, tab_completed = st.tabs(["🚀 即時動態看板", "✅ 歷史完成紀錄"])
    
    with tab_realtime:
        pending = [t for t in tasks if t['status'] == '待處理']
        in_prog = [t for t in tasks if t['status'] == '執行中']
        online_users = load_online_users()
        active_nps = []
        now = get_tw_time()
        
        for name, info in online_users.items():
            if info['role'] == "專科護理師":
                last_seen = datetime.strptime(info['last_seen'], "%Y-%m-%d %H:%M:%S")
                if (now - last_seen).total_seconds() < 900: active_nps.append(name)
                
        busy_nps = list(set([t['handler'] for t in in_prog if t['handler']]))
        idle_nps = [np for np in active_nps if np not in busy_nps]
        
        col1, col2, col3 = st.columns(3)
        col1.metric("🔴 待處理任務", len(pending), "未接單", delta_color="inverse")
        col2.metric("🔵 執行中任務", len(in_prog), "處理中", delta_color="off")
        col3.metric("👨‍⚕️ 值班專師", len(active_nps), "上線中")
        if active_nps:
            col3.caption(f"🏃 **執行中:** {', '.join(busy_nps) if busy_nps else '無'}")
            col3.caption(f"☕ **待命中:** {', '.join(idle_nps) if idle_nps else '無'}")
        
        st.markdown("---")
        w1, w2 = st.columns(2)
        with w1:
            st.subheader("🚨 未接單清單")
            if pending:
                dfp = pd.DataFrame(pending)[['time', 'priority', 'bed', 'task_type', 'requester']]
                dfp['time'] = dfp['time'].str[11:16]; dfp.columns = ['發布時間', '優先級', '位置/病患', '任務', '發布者']
                st.dataframe(dfp, use_container_width=True, hide_index=True)
            else:
                st.success("目前無積壓任務！")
                
        with w2:
            st.subheader("⚡ 專師執行動態")
            if in_prog:
                dfg = pd.DataFrame(in_prog)[['handler', 'priority', 'bed', 'task_type', 'start_time']]
                dfg['start_time'] = dfg['start_time'].str[11:16]; dfg.columns = ['專師', '優先級', '位置/病患', '任務', '接單時間']
                st.dataframe(dfg, use_container_width=True, hide_index=True)
            else:
                st.info("目前無正在執行的任務。")
                
    with tab_completed:
        st.subheader("📅 查詢已完成任務")
        selected_date = st.date_input("選擇日期", value=get_tw_time().date())
        
        completed_tasks = []
        for t in tasks:
            if t['status'] == '已完成':
                time_str = t.get('complete_time') or t.get('time')
                if time_str and time_str.startswith(str(selected_date)):
                    completed_tasks.append(t)
                    
        if completed_tasks:
            st.success(f"🎉 {selected_date} 總計完成 **{len(completed_tasks)}** 件任務！")
            
            dfc = pd.DataFrame(completed_tasks)[['complete_time', 'priority', 'bed', 'task_type', 'handler', 'requester', 'feedback']]
            dfc['complete_time'] = dfc['complete_time'].str[11:16]
            dfc.columns = ['完成時間', '優先級', '位置/病患', '任務', '處理專師', '派發者', '回報內容']
            
            dfc = dfc.sort_values(by='完成時間', ascending=False)
            st.dataframe(dfc, use_container_width=True, hide_index=True)
        else:
            st.info(f"查無 {selected_date} 的完成紀錄。")

def backend_interface():
    st.header("📂 後台紀錄與管理")
    tasks = load_data()
    if not tasks: st.info("目前無紀錄。"); return
    df = pd.DataFrame(tasks)
    df.insert(0, "選取", False)
    st.markdown("### 📋 檢視與排序")
    sort_by = st.radio("🔃 排序依據", ["最新到最舊", "最舊到最新", "依處理專師", "依任務類型"], horizontal=True)
    if "最新" in sort_by: df = df.sort_values(by='time', ascending=False)
    elif "最舊" in sort_by: df = df.sort_values(by='time', ascending=True)
    elif "專師" in sort_by: df = df.sort_values(by='handler')
    elif "任務" in sort_by: df = df.sort_values(by='task_type')

    edited_df = st.data_editor(df, column_config={"選取": st.column_config.CheckboxColumn("選取", default=False), "id": None}, hide_index=True, use_container_width=True)
    sel_rows = edited_df[edited_df["選取"] == True]
    
    c1, c2, c3 = st.columns(3)
    with c1:
        if not sel_rows.empty:
            csv = sel_rows.drop(columns=["選取", "id"]).to_csv(index=False, encoding='utf-8-sig')
            st.download_button(label=f"📥 匯出選取 ({len(sel_rows)})", data=csv, file_name=f"ER_Tasks_{get_tw_time().strftime('%Y%m%d')}.csv", mime="text/csv", use_container_width=True)
    with c2:
        if st.button(f"🗑️ 刪除選取 ({len(sel_rows)})", disabled=sel_rows.empty, use_container_width=True):
            delete_selected_dialog(sel_rows['id'].tolist())
    with c3:
        if st.button("🚨 清除全部", use_container_width=True, type="primary"): clear_records_dialog()

def main():
    if st.session_state.is_logged_in: 
        update_online_status(st.session_state.nickname, st.session_state.role)
        
    if not st.session_state.is_logged_in:
        with st.sidebar:
            st.markdown("### 📍 系統導航")
            page = st.radio("前往頁面", ["🔑 系統登入", "📊 動態白板 (免登入)"], label_visibility="collapsed")
            st.markdown("---")
            st.caption("© 2026 護理師 吳智弘 版權所有"); st.caption("請遵守個資法，勿填真實身分證字號。")
        if page == "🔑 系統登入": login_interface()
        else: whiteboard_interface()
    else:
        with st.sidebar:
            st.markdown(f"### 👤 **{st.session_state.nickname}** ({st.session_state.role})")
            
            st.markdown("---")
            st.markdown("### ⚙️ 畫面更新模式")
            if st.session_state.is_standby:
                st.success("🟢 **待命模式** (即時接收推播)")
                if st.button("⏸️ 切換為 操作模式 (暫停更新)", use_container_width=True):
                    st.session_state.is_standby = False
                    st.session_state.op_mode_start = get_tw_time()
                    st.rerun()
            else:
                st.warning("🔴 **操作模式** (畫面暫停更新中...)")
                st.caption("為避免漏接任務，5 分鐘後將自動切回待命")
                if st.button("▶️ 切換為 待命模式 (恢復更新)", use_container_width=True):
                    reset_to_standby()
                    st.rerun()
            st.markdown("---")
            
            if st.button("🚪 下班登出", use_container_width=True):
                remove_online_status(st.session_state.nickname)
                if "nickname" in st.query_params: del st.query_params["nickname"]
                if "role" in st.query_params: del st.query_params["role"]
                
                tasks = load_data()
                for t in tasks:
                    if t['status'] == '執行中' and t['handler'] == st.session_state.nickname:
                        t['status'] = '待處理'; t['handler'] = ''; t['start_time'] = ''
                save_data(tasks); st.session_state.is_logged_in = False; st.rerun()
            st.markdown("""<a href="." target="_blank" style="display:block;text-align:center;padding:0.45rem;margin-top:0.5rem;background-color:transparent;color:inherit;border-radius:0.5rem;border:1px solid rgba(128,128,128,0.5);text-decoration:none;">➕ 開啟新身分</a>""", unsafe_allow_html=True)
            st.markdown("---")
            
            pages = ["👩‍⚕️ 護理師派發", "👨‍⚕️ 醫師派發", "🧑‍⚕️ 專師接收任務", "📊 動態白板", "📂 後台紀錄"]
            
            default_index = 0
            if st.session_state.role == "醫師": default_index = 1
            elif st.session_state.role == "專科護理師": default_index = 2
                
            page = st.radio("系統選單", pages, index=default_index, label_visibility="collapsed")
            st.markdown("---")
            st.caption("© 2026 護理師 吳智弘 版權所有")
            
        if page == "👩‍⚕️ 護理師派發": assigner_interface(view_role="護理師")
        elif page == "👨‍⚕️ 醫師派發": assigner_interface(view_role="醫師")
        elif page == "🧑‍⚕️ 專師接收任務": np_interface()
        elif page == "📊 動態白板": whiteboard_interface()
        elif page == "📂 後台紀錄": backend_interface()

if __name__ == "__main__":
    main()
