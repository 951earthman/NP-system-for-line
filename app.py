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
# 🛑 LIFF 與 LINE Bot 設定區
# ==========================================
LIFF_ID = "2009793049-K0kqE1ou"  # <--- 注意：請替換成您申請的 LIFF ID

LINE_CHANNEL_ACCESS_TOKEN = "YOUR_LINE_CHANNEL_ACCESS_TOKEN" 
TARGET_LINE_ID = "YOUR_LINE_USER_ID" 

def send_line_notification(task_data):
    if LINE_CHANNEL_ACCESS_TOKEN == "YOUR_LINE_CHANNEL_ACCESS_TOKEN": return 
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}", "Content-Type": "application/json"}
    msg_text = (
        f"🚨【新任務派發】{task_data['priority']}\n"
        f"📍 位置: {task_data['bed']}\n"
        f"📝 任務: {task_data['task_type']}\n"
        f"📋 備註: {task_data['details']}\n"
        f"👨‍⚕️ 派發人: {task_data['requester']} ({task_data['requester_role']})\n"
        f"⏱️ 時間: {task_data['time'][11:16]}"
    )
    payload = {"to": TARGET_LINE_ID, "messages": [{"type": "text", "text": msg_text}]}
    try: requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload)
    except Exception as e: print(f"LINE 推播失敗: {e}")

# ==========================================

# --- 初始化 Session State ---
if "is_logged_in" not in st.session_state:
    if "nickname" in st.query_params and "role" in st.query_params:
        st.session_state.nickname = st.query_params["nickname"]
        st.session_state.role = st.query_params["role"]
        st.session_state.is_logged_in = True
    else:
        st.session_state.nickname = ""
        st.session_state.role = ""
        st.session_state.is_logged_in = False

if "success_message" not in st.session_state: st.session_state.success_message = ""
if "is_standby" not in st.session_state: st.session_state.is_standby = True  
if "op_mode_start" not in st.session_state: st.session_state.op_mode_start = None

def get_tw_time(): return datetime.utcnow() + timedelta(hours=8)

if not st.session_state.is_standby and st.session_state.op_mode_start:
    if (get_tw_time() - st.session_state.op_mode_start).total_seconds() >= 295:
        st.session_state.is_standby = True; st.session_state.op_mode_start = None
        st.toast("⏳ 您已停留操作模式超過 5 分鐘，系統已自動切回【待命模式】！", icon="🔄")

refresh_interval = 10000 if st.session_state.is_standby else 300000
count = st_autorefresh(interval=refresh_interval, limit=None, key="data_sync_refresh")

DATA_FILE = "task_data.json"
ONLINE_FILE = "online_users.json"

BED_DATA_COMPLEX = {
    "留觀(OBS)": {"OBS 1": ["1", "2", "3", "5", "6", "7", "8", "9", "10", "35", "36", "37", "38"], "OBS 2": ["11", "12", "13", "15", "16", "17", "18", "19", "20", "21", "22", "23"], "OBS 3": ["25", "26", "27", "28", "29", "30", "31", "32", "33", "39"]},
    "診間": {"第一診間": ["11", "12", "13", "15", "21", "22", "23", "25"], "第二診間": ["16", "17", "18", "19", "20", "36", "37", "38"], "第三診間": ["5", "6", "27", "28", "29", "30", "31", "32", "33", "39"]},
    "兒科": {"兒科床位": ["501", "502", "503", "505", "506", "507", "508", "509"]},
    "急救區": {}, "檢傷": {}, "縫合室": {}, "超音波室": {}
}

def load_data():
    if not os.path.exists(DATA_FILE): return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

def load_online_users():
    if not os.path.exists(ONLINE_FILE): return {}
    try:
        with open(ONLINE_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return {}

def save_online_users(data):
    with open(ONLINE_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

def update_online_status(nickname, role):
    users = load_online_users()
    users[nickname] = {"role": role, "last_seen": get_tw_time().strftime("%Y-%m-%d %H:%M:%S")}
    save_online_users(users)

def remove_online_status(nickname):
    users = load_online_users()
    if nickname in users: del users[nickname]; save_online_users(users)

def check_pii(*texts):
    for t in texts:
        if t and re.search(r'[A-Za-z][1289]\d{8}', str(t)): return True
    return False

if "known_task_ids" not in st.session_state: st.session_state.known_task_ids = set([t['id'] for t in load_data()])

def check_for_new_alerts():
    tasks = load_data()
    current_ids = set([t['id'] for t in tasks])
    new_ids = current_ids - st.session_state.known_task_ids
    if new_ids:
        latest_new_task = next((t for t in tasks if t['id'] in new_ids), None)
        if latest_new_task and latest_new_task.get('requester') != st.session_state.nickname:
            st.toast("🚨 系統有新的協助任務派發！", icon="🔔")
            components.html("""<script>new Audio("https://actions.google.com/sounds/v1/alarms/beep_short.ogg").play();</script>""", width=0, height=0)
    st.session_state.known_task_ids = current_ids

def reset_to_standby():
    st.session_state.is_standby = True; st.session_state.op_mode_start = None

def checkbox_matrix(options, num_columns=4):
    selected = []
    cols = st.columns(num_columns)
    for i, option in enumerate(options):
        with cols[i % num_columns]:
            if st.checkbox(option, key=f"matrix_{option}"): selected.append(option)
    return selected

# --- 🚀 全新 LIFF 與 登入介面 ---
def login_interface():
    st.header("🔑 系統登入")
    
    # 檢查是否被按下了 LINE 登入按鈕
    if "liff_trigger" in st.session_state and st.session_state.liff_trigger:
        st.info("🔄 正在連接 LINE 驗證，請稍候...")
        # 注入 LIFF JS 腳本
        liff_js = f"""
        <script charset="utf-8" src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
        <script>
            document.addEventListener("DOMContentLoaded", function() {{
                liff.init({{ liffId: "{LIFF_ID}" }}).then(() => {{
                    if (liff.isLoggedIn()) {{
                        liff.getProfile().then(profile => {{
                            // 將名字轉換成 URL 參數回傳給 Streamlit
                            let url = new URL(window.parent.location.href);
                            url.searchParams.set("nickname", profile.displayName);
                            // 為了方便測試，用 LINE 登入的人預設直接給「專科護理師」身分
                            url.searchParams.set("role", "專科護理師"); 
                            window.parent.location.href = url.toString();
                        }}).catch(err => console.error(err));
                    }} else {{
                        // 如果沒有登入，呼叫 LINE 登入畫面
                        liff.login();
                    }}
                }}).catch(err => console.error(err));
            }});
        </script>
        """
        components.html(liff_js, height=0, width=0)
        st.session_state.liff_trigger = False
        st.stop()
    
    with st.container(border=True):
        st.subheader("💡 方式一：LINE 快速登入 (推薦)")
        st.caption("使用 LINE 開啟時，點擊下方按鈕將自動抓取您的名字並以「專科護理師」身分登入。")
        
        if st.button("🟢 點我使用 LINE 一鍵登入", use_container_width=True):
            if LIFF_ID == "請在這裡貼上您的_LIFF_ID":
                st.error("⚠️ 開發者請先在程式碼上方填入 LIFF_ID！")
            else:
                st.session_state.liff_trigger = True
                st.rerun()

        st.markdown("---")
        st.subheader("⌨️ 方式二：手動輸入 (傳統登入)")
        nickname_input = st.text_input("手動輸入新綽號 (必填)")
        role_input = st.radio("身分選擇", ["護理師", "醫師", "專科護理師"], horizontal=True)
        
        if st.button("🚀 手動登入", use_container_width=True, type="primary"):
            final_nickname = nickname_input.strip()
            if not final_nickname: st.error("請輸入綽號！")
            else:
                st.session_state.nickname = final_nickname
                st.session_state.role = role_input
                st.session_state.is_logged_in = True
                st.query_params["nickname"] = final_nickname
                st.query_params["role"] = role_input
                st.rerun()

# --- 以下為原本的專師系統派發與接收介面 (無更動，保持 Phase 2 完整版) ---

@st.dialog("⚠️ 確認派發任務")
def confirm_dispatch_dialog(new_task, require_prep=False, require_hd_consent=False):
    st.write(f"即將派發：**{new_task['priority']}** | **{new_task['bed']}** 的 **{new_task['task_type']}** 請求。")
    consent = "是"; reason = ""
    if require_prep: st.warning("護理師提醒：請問是否已完成相關備物？")
    if require_hd_consent:
        st.warning("請問是否已完成洗腎同意書？")
        consent = st.radio("同意書狀態", ["是", "否"], horizontal=True, label_visibility="collapsed")
        if consent == "否": reason = st.text_input("請填寫未完成原因 (必填)", placeholder="例如：家屬尚未抵達...")
            
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 確認送出", type="primary", use_container_width=True):
            if require_hd_consent and consent == "否" and not reason.strip(): st.error("⚠️ 選擇「否」時，必須填寫未完成原因！")
            else:
                if require_hd_consent:
                    if consent == "否": new_task['details'] += f" | 同意書: 未完成 ({reason})"
                    else: new_task['details'] += f" | 同意書: 已完成"
                tasks = load_data()
                tasks.append(new_task)
                save_data(tasks)
                send_line_notification(new_task)
                st.session_state.success_message = f"✅ 已成功送出 【 {new_task['bed']} 】 的 【{new_task['task_type']}】 請求！"
                reset_to_standby() 
                st.rerun() 
    with col2:
        if st.button("❌ 返回修改", use_container_width=True): st.rerun()

def assigner_interface(view_role="護理師"):
    st.header(f"👋 {view_role} 派發介面")
    if st.session_state.success_message:
        st.success(st.session_state.success_message); st.session_state.success_message = "" 
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
        patient_name = st.text_input("【 2. 填寫病患姓名 (必填) 】", placeholder="請在此貼上或輸入病患姓名...")
        final_bed = f"無床位 (病患: {patient_name})" if patient_name else "無床位"
    else:
        bed_note = st.text_input(f"【 2. {area} 備註 (選填) 】", placeholder="例如：等待推床...")
        final_bed = area + (f" ({bed_note})" if bed_note else "")

    st.markdown("---")
    st.subheader("📋 步驟 2：選擇協助項目與優先級")
    priority = st.radio("優先級別", ["🟢 一般", "🔴 緊急"], horizontal=True)
    task_type = st.radio("協助項目", ["on Foley", "on NG", "Suture (縫合)", "會診", "藥物開立", "檢體採集", "安排洗腎", "訂ICU", "開診斷書", "拍照", "其他"], horizontal=True)
    
    details = ""; med_details = ""; consult_dept_str = ""; spec_type = ""; wound_sub = []
    wound_part_sub = []; photo_part = ""; other_desc = ""; icu_type = ""
    actual_s_parts = []; actual_s_lines = []; actual_consult_depts = []; actual_wound_parts = []; actual_wounds = []
    
    with st.container(border=True):
        if task_type == "on Foley":
            f_type = st.radio("Foley 種類", ["一般", "矽質"], horizontal=True)
            f_sample = st.checkbox("需留取檢體")
            details = f"種類: {f_type} | 檢體: {'是' if f_sample else '否'}"
        elif task_type == "on NG":
            ng_type_choice = st.radio("NG 目的", ["Re-on", "Decompression", "IRRI (沖洗)", "其他 (自行輸入)"], horizontal=True)
            actual_ng = st.text_input("請輸入自訂目的") if ng_type_choice == "其他 (自行輸入)" else ng_type_choice
            details = f"目的: {actual_ng if actual_ng else '未填寫'}"
        elif task_type == "Suture (縫合)":
            st.write("縫合部位 (可複選):")
            selected_s_parts = checkbox_matrix(["左手", "左腳", "右手", "右腳", "胸口", "肚子", "背後", "頭皮", "臉", "脖子"], num_columns=5)
            custom_s_part = st.text_input("其他縫合部位")
            actual_s_parts = selected_s_parts + ([custom_s_part] if custom_s_part else [])
            s_part_str = " + ".join(actual_s_parts) if actual_s_parts else "未選擇部位"
            
            st.write("縫線選擇 (可複選):")
            selected_s_lines = checkbox_matrix(["Nylon 1-0", "Nylon 2-0", "Nylon 3-0", "Nylon 4-0", "Nylon 5-0", "Nylon 6-0", "由專科護理師自行評估"], num_columns=4)
            custom_s_line = st.text_input("其他縫線")
            actual_s_lines = selected_s_lines + ([custom_s_line] if custom_s_line else [])
            s_line_str = " + ".join(actual_s_lines) if actual_s_lines else "未選擇縫線"
            details = f"部位: {s_part_str} | 縫線: {s_line_str}"
        elif task_type == "會診":
            st.write("會診科別 (可複選):")
            selected_depts = checkbox_matrix(["ENT (耳鼻喉科)", "OPH (眼科)", "PS (整形外科)", "GS (一般外科)", "CVS (心臟血管外科)", "GU (泌尿科)", "Ortho (骨科)", "NS (神經外科)", "GYN (婦產科)", "CV (心臟內科)", "Hospice (安寧/家醫科)", "INF (感染科)"], num_columns=4)
            custom_dept = st.text_input("其他會診科別")
            actual_consult_depts = selected_depts + ([custom_dept] if custom_dept else [])
            details = f"科別: {' + '.join(actual_consult_depts) if actual_consult_depts else '未選擇'}"
        elif task_type == "藥物開立":
            med_details = st.text_input("藥物/說明 (必填)"); details = f"說明: {med_details}"
        elif task_type == "安排洗腎":
            hd_days = checkbox_matrix(["週一", "週二", "週三", "週四", "週五", "週六", "初次洗腎"], num_columns=4)
            hd_location = st.radio("地點", ["本院", "外院", "不明"], horizontal=True)
            details = f"洗腎日: {','.join(hd_days) if hd_days else '未勾選'} | 地點: {hd_location}"
        elif task_type == "檢體採集":
            spec_type = st.radio("採集內容", ["鼻口腔黏膜", "傷口"], horizontal=True)
            if spec_type == "傷口":
                st.write("傷口部位 (可複選):")
                selected_wps = checkbox_matrix(["頭頸部", "軀幹", "上肢", "下肢", "臀部/會陰"], num_columns=5)
                custom_wp = st.text_input("其他部位")
                actual_wound_parts = selected_wps + ([custom_wp] if custom_wp else [])
                st.write("傷口培養類別 (可複選):")
                selected_ws = checkbox_matrix(["嗜氧", "厭氧"], num_columns=2)
                custom_w = st.text_input("其他培養類別")
                actual_wounds = selected_ws + ([custom_w] if custom_w else [])
                details = f"內容: 傷口 | 部位: {'+'.join(actual_wound_parts) if actual_wound_parts else '未選擇'} | 培養: {'+'.join(actual_wounds) if actual_wounds else '未選擇'}"
            else: details = f"內容: 鼻口腔黏膜"
        elif task_type == "訂ICU":
            icu_type = st.radio("ICU 類別", ["MICU (內科加護)", "CCU (心臟加護)", "PICU (兒科加護)", "其他"], horizontal=True)
            details = f"類別: {st.text_input('輸入其他 ICU 單位') if icu_type == '其他' else icu_type}"
        elif task_type == "開診斷書":
            details = f"版本: {st.radio('診斷書版本', ['中文版', '英文版', '中英雙語'], horizontal=True)}"
        elif task_type == "拍照":
            photo_part = st.text_input("拍照部位 (必填)", placeholder="例如：右小腿撕裂傷..."); details = f"部位: {photo_part}"
        elif task_type == "其他":
            other_desc = st.text_input("協助事項 (必填)", placeholder="簡述內容..."); details = f"事項: {other_desc}"
            
        global_memo = st.text_input("✍️ 通用補充說明 (選填)")
        if global_memo: details += f" | 補充: {global_memo}"

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚀 準備派發任務", use_container_width=True, type="primary"):
        if check_pii(patient_name, details, bed_note, consult_dept_str, med_details, global_memo, other_desc):
            st.error("⚠️ 偵測到疑似身分證字號！"); st.stop()
        if area == "病患無床位" and not patient_name.strip(): st.warning("⚠️ 請填寫病患姓名！")
        elif task_type == "Suture (縫合)" and not actual_s_parts: st.warning("⚠️ 請選擇部位！")
        elif task_type == "Suture (縫合)" and not actual_s_lines: st.warning("⚠️ 請選擇縫線！")
        elif task_type == "會診" and not actual_consult_depts: st.warning("⚠️ 請選擇科別！")
        elif task_type == "藥物開立" and not med_details.strip(): st.warning("⚠️ 請填寫說明！")
        elif task_type == "檢體採集" and spec_type == "傷口" and (not actual_wounds or not actual_wound_parts): st.warning("⚠️ 傷口採集請勾選「部位」與「培養」！")
        elif task_type == "拍照" and not photo_part.strip(): st.warning("⚠️ 請填寫部位！")
        elif task_type == "其他" and not other_desc.strip(): st.warning("⚠️ 請填寫事項！")
        else:
            new_task = {
                "id": str(get_tw_time().timestamp()), "time": get_tw_time().strftime("%Y-%m-%d %H:%M:%S"), 
                "priority": priority, "bed": final_bed, "task_type": task_type, "details": details, 
                "requester": st.session_state.nickname, "requester_role": view_role, "status": "待處理", 
                "handler": "", "start_time": "", "complete_time": "", "feedback": ""
            }
            if view_role == "護理師":
                if task_type in ["會診", "藥物開立", "訂ICU", "開診斷書"]: confirm_dispatch_dialog(new_task)
                elif task_type == "安排洗腎": confirm_dispatch_dialog(new_task, require_hd_consent=True)
                else: confirm_dispatch_dialog(new_task, require_prep=True)
            else: confirm_dispatch_dialog(new_task)

@st.dialog("📝 執行回報")
def np_feedback_dialog(task_id, is_doc_assisted=False):
    tasks = load_data(); task = next((t for t in tasks if t['id'] == task_id), None)
    if not task: return st.error("找不到資料！")
    st.write(f"**{task['bed']}** | **{task['task_type']}**\n派發者: {task['requester']}")
    st.markdown("---")
    
    feedback_text = ""
    if is_doc_assisted:
        feedback_text = st.text_input("備註", value="醫師已協助完成")
    else:
        if task['task_type'] == "Suture (縫合)":
            thread_choice = st.radio("實際縫線", ["Nylon 1-0", "Nylon 2-0", "Nylon 3-0", "Nylon 4-0", "Nylon 5-0", "Nylon 6-0", "其他"], horizontal=True)
            thread = st.text_input("自訂縫線") if thread_choice == "其他" else thread_choice
            stitches = st.number_input("縫合針數", min_value=1, value=3)
            feedback_text = f"縫線: {thread} | {stitches} 針"
        elif task['task_type'] == "on Foley":
            feedback_text = f"材質: {st.radio('材質', ['一般', '矽質'], horizontal=True)} | 尺寸: {st.radio('尺寸', ['14','16','18','20','22'], horizontal=True)} Fr"
        elif task['task_type'] == "on NG":
            feedback_text = f"鼻孔: {st.radio('鼻孔', ['左','右'], horizontal=True)} | 固定: {st.number_input('刻度', value=55)} cm"
        else: feedback_text = st.text_input("備註 (選填)", placeholder="已處理完畢...")

    if st.button("💾 儲存結案", type="primary", use_container_width=True):
        latest_tasks = load_data()
        for i in range(len(latest_tasks)):
            if latest_tasks[i]['id'] == task_id:
                latest_tasks[i]['status'] = '已完成'; latest_tasks[i]['complete_time'] = get_tw_time().strftime("%Y-%m-%d %H:%M:%S")
                latest_tasks[i]['handler'] = f"{st.session_state.nickname}" + (" (註記醫師完成)" if is_doc_assisted else "")
                latest_tasks[i]['feedback'] = feedback_text if feedback_text else "已處理完畢"
        save_data(latest_tasks); reset_to_standby(); st.rerun()

def np_interface():
    st.header("👩‍⚕️ 專科護理師接收介面")
    check_for_new_alerts()
    tasks = load_data(); pending = [t for t in tasks if t['status'] == '待處理']
    in_prog = [t for t in tasks if t['status'] == '執行中' and t['handler'] == st.session_state.nickname]
    
    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"🔔 待接單 ({len(pending)})")
        if pending:
            for t in pending:
                with st.container(border=True):
                    is_overdue = get_tw_time() > datetime.strptime(t['time'], "%Y-%m-%d %H:%M:%S") + timedelta(hours=1)
                    st.markdown(f"**{t['priority']}** | {'🔴' if is_overdue else '🟡'} **{t['time'][11:16]} | {t['bed']} - {t['task_type']}**")
                    st.write(f"📝 {t['details']}")
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("👉 接單", key=f"tk_{t['id']}", use_container_width=True):
                            latest = load_data()
                            for i in range(len(latest)):
                                if latest[i]['id'] == t['id']: latest[i]['status'] = '執行中'; latest[i]['handler'] = st.session_state.nickname; latest[i]['start_time'] = get_tw_time().strftime("%Y-%m-%d %H:%M:%S")
                            save_data(latest); reset_to_standby(); st.rerun()
                    with b2:
                        if st.button("👨‍⚕️ 醫師完成", key=f"dd_{t['id']}", use_container_width=True): np_feedback_dialog(t['id'], True)
        else: st.info("目前無待辦任務！☕")

    with c2:
        st.subheader(f"🏃 執行中 ({len(in_prog)})")
        if in_prog:
            for t in in_prog:
                with st.container(border=True):
                    st.markdown(f"**{t['priority']}** | **🔵 {t['bed']} - {t['task_type']}**")
                    st.write(f"📝 {t['details']}")
                    if st.button("✅ 標記完成", key=f"dn_{t['id']}", use_container_width=True, type="primary"): np_feedback_dialog(t['id'])
        else: st.success("無執行中任務。")

def whiteboard_interface():
    st.header("📊 系統動態白板")
    check_for_new_alerts()
    tasks = load_data()
    tab_realtime, tab_completed = st.tabs(["🚀 即時動態看板", "✅ 歷史完成紀錄"])
    
    with tab_realtime:
        pending = [t for t in tasks if t['status'] == '待處理']
        in_prog = [t for t in tasks if t['status'] == '執行中']
        c1, c2, c3 = st.columns(3)
        c1.metric("🔴 待處理任務", len(pending))
        c2.metric("🔵 執行中任務", len(in_prog))
        st.markdown("---")
        w1, w2 = st.columns(2)
        with w1:
            st.subheader("🚨 未接單清單")
            if pending:
                dfp = pd.DataFrame(pending)[['time', 'priority', 'bed', 'task_type', 'requester']]
                dfp['time'] = dfp['time'].str[11:16]; dfp.columns = ['時間', '優先級', '位置', '任務', '發布者']
                st.dataframe(dfp, use_container_width=True, hide_index=True)
        with w2:
            st.subheader("⚡ 執行動態")
            if in_prog:
                dfg = pd.DataFrame(in_prog)[['handler', 'priority', 'bed', 'task_type', 'start_time']]
                dfg['start_time'] = dfg['start_time'].str[11:16]; dfg.columns = ['專師', '優先級', '位置', '任務', '接單時間']
                st.dataframe(dfg, use_container_width=True, hide_index=True)
                
    with tab_completed:
        selected_date = st.date_input("選擇日期", value=get_tw_time().date())
        comp_tasks = [t for t in tasks if t['status'] == '已完成' and (t.get('complete_time') or t.get('time')).startswith(str(selected_date))]
        if comp_tasks:
            dfc = pd.DataFrame(comp_tasks)[['complete_time', 'bed', 'task_type', 'handler', 'requester', 'feedback']]
            dfc['complete_time'] = dfc['complete_time'].str[11:16]
            dfc.columns = ['完成時間', '位置', '任務', '專師', '派發者', '回報']
            st.dataframe(dfc.sort_values(by='完成時間', ascending=False), use_container_width=True, hide_index=True)

def backend_interface():
    st.header("📂 後台紀錄與管理")
    tasks = load_data()
    if not tasks: return st.info("目前無紀錄。")
    df = pd.DataFrame(tasks)
    st.dataframe(df.sort_values(by='time', ascending=False), use_container_width=True)

def main():
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
                if "nickname" in st.query_params: del st.query_params["nickname"]
                if "role" in st.query_params: del st.query_params["role"]
                st.session_state.is_logged_in = False; st.rerun()
            st.markdown("---")
            page = st.radio("選單", ["👩‍⚕️ 護理師派發", "👨‍⚕️ 醫師派發", "🧑‍⚕️ 專師接收", "📊 動態白板", "📂 後台紀錄"], index=2 if st.session_state.role == "專科護理師" else 0, label_visibility="collapsed")
            
        if "護理師" in page: assigner_interface("護理師")
        elif "醫師" in page: assigner_interface("醫師")
        elif "接收" in page: np_interface()
        elif "白板" in page: whiteboard_interface()
        elif "後台" in page: backend_interface()

if __name__ == "__main__":
    main()
