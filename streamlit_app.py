import streamlit as st
import json
from form_utils import fetch_meta, llm_build_pdf_payload, call_gemini

SUPPORTED_FORMS = [
    "eoir_form_26",
    "uscis_form_ar11",
    "ice_form_i246",
    "cbp_form_3299",
]

def get_form_suggestion(user_message: str) -> str:
    prompt = f"""
User case description:
{user_message}

Which of these form_keys is most appropriate? {SUPPORTED_FORMS}
Reply ONLY with the form_key.
"""
    return call_gemini("", prompt).strip()

st.set_page_config(page_title="BureauBot")

if "chat" not in st.session_state:
    st.session_state.chat = []
if "stage" not in st.session_state:
    st.session_state.stage = "suggest_form"
if "form_key" not in st.session_state:
    st.session_state.form_key = None
if "fields" not in st.session_state:
    st.session_state.fields = []
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "current_q" not in st.session_state:
    st.session_state.current_q = 0

st.title("📝 Form Assistant Bot")

if user_input := st.chat_input("Tell me what you need help with..."):
    st.session_state.chat.append(("user", user_input))

    if st.session_state.stage == "suggest_form":
        form = get_form_suggestion(user_input)
        if form in SUPPORTED_FORMS:
            st.session_state.form_key = form
            meta = fetch_meta(form)
            st.session_state.fields = meta["questions"]
            st.session_state.stage = "ask_questions"
            st.session_state.chat.append(("bot", f"I'll help you fill out **{form}**. Let's get started!"))
        else:
            st.session_state.chat.append(("bot", "Sorry, I couldn’t match that to a supported form."))

    elif st.session_state.stage == "ask_questions":
        prev_field = st.session_state.fields[st.session_state.current_q - 1]
        st.session_state.answers[prev_field["name"]] = user_input

for sender, msg in st.session_state.chat:
    st.chat_message(sender).markdown(msg)

if st.session_state.stage == "ask_questions":
    idx = st.session_state.current_q
    if idx < len(st.session_state.fields):
        question = st.session_state.fields[idx]["prompt"]
        st.chat_message("bot").markdown(question)
        if user_input:
            st.session_state.current_q += 1
    else:
        payload = llm_build_pdf_payload(
            form_key=st.session_state.form_key,
            user_block="\n".join([f"{k}: {v}" for k, v in st.session_state.answers.items()])
        )
        st.chat_message("bot").markdown("Here’s your filled form!")
        st.json(payload)
        st.download_button(
            "Download JSON",
            data=json.dumps(payload, indent=2),
            file_name=f"{st.session_state.form_key}_filled.json",
            mime="application/json",
        )
        st.session_state.stage = "done"

elif st.session_state.stage == "done":
    st.chat_message("bot").markdown("All done! Refresh the app to start over.")

