import streamlit as st
import json
import os

# --- In-memory metadata loading from local JSON files ---
def fetch_meta(form_key: str) -> dict:
    path = f"{form_key}_meta.json"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"questions": []}

# --- Simple rule-based form suggestion (demo) ---
def suggest_form(user_input: str) -> str:
    text = user_input.lower()
    if "appeal" in text or "deport" in text:
        return "eoir_form_26"
    if "address" in text or "move" in text:
        return "uscis_form_ar11"
    if "stay" in text or "stay" in text and "deport" in text:
        return "ice_form_i246"
    if "bring" in text or "goods" in text or "personal effects" in text:
        return "cbp_form_3299"
    return None

# --- Build JSON payload directly from answers ---
def build_payload(form_key: str, answers: dict) -> dict:
    # Only include non-empty answers
    return {k: v for k, v in answers.items() if v}

# --- Streamlit UI ---
st.set_page_config(page_title="Immigration Form Assistant Demo")
st.title("📝 Immigration Form Assistant (Demo)")

# Chat-like interface using session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "form_key" not in st.session_state:
    st.session_state.form_key = None
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "current_q" not in st.session_state:
    st.session_state.current_q = 0
if "questions" not in st.session_state:
    st.session_state.questions = []

# Display chat history
def show_chat():
    for role, msg in st.session_state.messages:
        with st.chat_message(role):
            st.markdown(msg)

show_chat()

# User input
user_input = st.chat_input("Type here...")
if user_input:
    # Add user message
    st.session_state.messages.append(("user", user_input))

    # If form not yet chosen, suggest
    if st.session_state.form_key is None:
        form = suggest_form(user_input)
        if form:
            st.session_state.form_key = form
            meta = fetch_meta(form)
            st.session_state.questions = meta.get("questions", [])
            st.session_state.messages.append(("bot", f"Great! We’ll fill **{form}**. {st.session_state.questions[0]['prompt']}"))
        else:
            st.session_state.messages.append(("bot", "Sorry, I couldn’t find a matching form. Try explaining your need differently."))
    else:
        # We're filling questions one by one
        idx = st.session_state.current_q
        # record answer to previous question
        if idx < len(st.session_state.questions):
            field = st.session_state.questions[idx]
            st.session_state.answers[field['name']] = user_input
            st.session_state.current_q += 1

        # next question or finish
        if st.session_state.current_q < len(st.session_state.questions):
            next_q = st.session_state.questions[st.session_state.current_q]['prompt']
            st.session_state.messages.append(("bot", next_q))
        else:
            # All questions answered
            payload = build_payload(st.session_state.form_key, st.session_state.answers)
            st.session_state.messages.append(("bot", "All done! Here’s your filled form data:"))
            st.session_state.messages.append(("bot", json.dumps(payload, indent=2)))
            # Reset for new session
            st.session_state.form_key = None
            st.session_state.current_q = 0
            st.session_state.answers = {}
            st.session_state.questions = []

    # Rerun to display new messages
    st.experimental_rerun()

# If no messages yet, show greeting
if not st.session_state.messages:
    st.session_state.messages.append(("bot", "👋 Hi! Tell me what you need help with — e.g., appeal a deportation order, change your address, request a stay, or import personal effects."))
    st.experimental_rerun()
