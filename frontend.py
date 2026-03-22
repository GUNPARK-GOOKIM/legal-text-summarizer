import streamlit as st
import requests, json, docx, io, re, os, hashlib

st.set_page_config(page_title="Legal AI Pro", page_icon="⚖️", layout="wide")

USER_DB = "users.json"
BACKEND_URL = "http://127.0.0.1:8000"

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def load_users():
    if os.path.exists(USER_DB):
        with open(USER_DB, "r") as f:
            return json.load(f)
    return {}

def save_user(email, password):
    users = load_users()
    users[email] = hash_password(password)
    with open(USER_DB, "w") as f:
        json.dump(users, f)

def is_valid_gmail(email):
    return re.match(r'^[a-z0-9](\.?[a-z0-9]){5,}@gmail\.com$', email)

defaults = {
    "logged_in": False,
    "user_email": "",
    "messages": [],
    "document_context": "",
    "last_summary": "",
    "last_reduction": 0,
    "orig_words": 0,
    "comp_words": 0
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if not st.session_state.logged_in:
    _, col, _ = st.columns([1, 1.5, 1])
    with col:
        st.title("⚖️ Legal AI Portal")
        tabs = st.tabs(["Login", "Create Account"])

        with tabs[0]:
            with st.form("login"):
                email = st.text_input("Gmail Address")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Login", use_container_width=True):
                    users = load_users()
                    if email in users and users[email] == hash_password(password):
                        st.session_state.logged_in = True
                        st.session_state.user_email = email
                        st.rerun()
                    else:
                        st.error("Invalid credentials.")

        with tabs[1]:
            with st.form("signup"):
                new_email = st.text_input("Enter Gmail Address")
                new_pw = st.text_input("Set Password", type="password")
                confirm_pw = st.text_input("Confirm Password", type="password")
                if st.form_submit_button("Create Account", use_container_width=True):
                    if not is_valid_gmail(new_email):
                        st.error("Use a valid @gmail.com address.")
                    elif new_pw != confirm_pw:
                        st.error("Passwords do not match.")
                    elif len(new_pw) < 6:
                        st.error("Password too short.")
                    elif new_email in load_users():
                        st.warning("Account exists.")
                    else:
                        save_user(new_email, new_pw)
                        st.success("Created! Please login.")
    st.stop()

with st.sidebar:
    st.title("⚖️ Dashboard")
    st.write(f"Logged in: **{st.session_state.user_email}**")

    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.document_context = ""
        st.session_state.last_summary = ""
        st.session_state.last_reduction = 0
        st.session_state.orig_words = 0
        st.session_state.comp_words = 0
        st.rerun()

    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.rerun()

    st.divider()
    st.subheader("⚡ Performance Monitor")

    m1 = st.empty()
    m2 = st.empty()
    p_bar = st.empty()

    reduction = st.session_state.last_reduction

    if reduction > 0:
        m1.metric("Token Reduction", f"{reduction}%")
    else:
        m1.metric("Token Reduction", "0%", "No compression")

    if st.session_state.orig_words > 0:
        saved = st.session_state.orig_words - st.session_state.comp_words
        m2.caption(
            f"Original: {st.session_state.orig_words} | "
            f"Compressed: {st.session_state.comp_words} | "
            f"Saved: {saved if saved > 0 else 0}"
        )

    progress_val = reduction / 100 if reduction > 0 else 0.05
    p_bar.progress(progress_val)

    if reduction == 0 and st.session_state.orig_words > 0 and st.session_state.last_summary:
        st.warning("No compression detected.")

    if st.session_state.last_summary:
        st.divider()
        doc = docx.Document()
        doc.add_heading("Legal Analysis Summary", 0)
        doc.add_paragraph(st.session_state.last_summary)
        bio = io.BytesIO()
        doc.save(bio)
        st.download_button(
            "Download Summary (.docx)",
            data=bio.getvalue(),
            file_name="legal_summary.docx",
            use_container_width=True
        )

st.title("💬 Legal AI Assistant")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask or attach a document...", accept_file=True):
    user_text = prompt.text
    uploaded_files = prompt.files

    if uploaded_files:
        file_name = uploaded_files[0].name
        display = f"📎 Document: {file_name}"
    else:
        display = user_text

    st.session_state.messages.append({"role": "user", "content": display})

    with st.chat_message("user"):
        st.markdown(display)

    if uploaded_files or len(user_text) > 300:
        with st.status("Analyzing Legal Content...", expanded=True) as status_box:
            p_text = {"text": user_text} if not uploaded_files else {}
            p_file = {"file": (uploaded_files[0].name, uploaded_files[0].getvalue())} if uploaded_files else None

            finished_successfully = False 

            try:
                r = requests.post(f"{BACKEND_URL}/process-logic-stream", data=p_text, files=p_file, stream=True)

                for line in r.iter_lines():
                    if line:
                        update = json.loads(line.decode('utf-8'))

                        if "reduction" in update and update["reduction"] is not None:
                            val = update["reduction"]
                            orig = update.get("original_tokens", 0)
                            comp = update.get("compressed_tokens", 0)
                            saved = orig - comp

                            st.session_state.last_reduction = val
                            st.session_state.orig_words = orig
                            st.session_state.comp_words = comp

                            m1.metric("Token Reduction", f"{val}%")
                            p_bar.progress(val / 100 if val > 0 else 0.05)

                            if orig > 0:
                                m2.caption(
                                    f"Original: {orig} | "
                                    f"Compressed: {comp} | "
                                    f"Saved: {saved if saved > 0 else 0}"
                                )

                        if update["step"] == "reading":
                            status_box.update(label="Reading document...", state="running")

                        elif update["step"] in ["reducing", "compressing"]:
                            status_box.update(label="Compressing text...", state="running")

                        elif update["step"] == "summarizing":
                            status_box.update(label="Generating summary...", state="running")

                        elif update["step"] == "done":
                            st.session_state.document_context = update["summary"]
                            st.session_state.last_summary = update["summary"]
                            st.session_state.messages.append({"role": "assistant", "content": update["summary"]})
                            status_box.update(label="Done!", state="complete")
                            finished_successfully = True

                        elif update["step"] == "error":
                            st.error(update["message"])
                            status_box.update(label="Pipeline Error", state="error")

            except Exception as e:
                st.error(f"Connection Error: {e}")
                status_box.update(label="Failed to connect to backend", state="error")

        if finished_successfully:
            st.rerun()
    else:
        api_msgs = [{"role": "system", "content": f"Expert Indian Legal Assistant. Context: {st.session_state.document_context}"}]
        api_msgs.extend([{"role": m["role"], "content": m["content"]} for m in st.session_state.messages[-5:]])

        try:
            r = requests.post(f"{BACKEND_URL}/chat", json={"messages": api_msgs})
            reply = r.json()["reply"]

            st.session_state.messages.append({"role": "assistant", "content": reply})

            with st.chat_message("assistant"):
                st.markdown(reply)

        except:
            st.error("Chat Error")