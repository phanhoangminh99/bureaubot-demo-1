from form_utils import fetch_meta, llm_build_pdf_payload, call_gemini

def fetch_meta(form_key: str) -> str:
    meta_path = pathlib.Path("../data") / f"{form_key}_meta.json"
    return meta_path.read_text(encoding="utf-8")

def parse_pdf(form_key: str) -> str:
    pdf_path = pathlib.Path("../data") / f"{form_key}.pdf"
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text

def call_gemini(system_prompt: str, user_prompt: str) -> str:
    # combined to a single user prompt
    combined_prompt = system_prompt.strip() + "\n\n" + user_prompt.strip()

    contents = [
        types.Content(role="user", parts=[types.Part(text=combined_prompt)])
    ]

    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    config = types.GenerateContentConfig(
        temperature=0.2,
        top_p=0.8,
        max_output_tokens=2040,
        response_modalities=["TEXT"],
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF")
        ],
    )

    response = client.models.generate_content_stream(
        model=MODEL, contents=contents, config=config
    )
    return "".join(chunk.text for chunk in response).strip()

def llm_build_pdf_payload(form_key: str, user_block: str, tries: int = 3) -> dict:
    meta_json = fetch_meta(form_key)
    pdf_text = parse_pdf(form_key)

    base_prompt = textwrap.dedent(f"""
        You are a CBP/EOIR/USCIS/ICE-form-filling expert.

        Form metadata:
        {meta_json}
        
        Form text:
        {pdf_text}
        
        User answers:
        \"\"\"{user_block}\"\"\"

        TASK
        ----
        Return ONE JSON object.
        • Keys = field "name" from metadata that the user clearly answered
        • Values = the user’s answer exactly as written
        • Omit every un-answered field (do NOT output nulls)
        No markdown, no code fences, no prose.
    """)

    for attempt in range(1, tries + 1):
        raw = call_gemini(SYSTEM_PROMPT, base_prompt)
        clean = re.sub(r"^[`]{3}json|[`]{3}$", "", raw.strip(), flags=re.I|re.M).strip()

        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            print(f"attempt {attempt}: invalid JSON → {e}")
            if attempt == tries:
                raise
            time.sleep(0.5)                # tiny back-off
            base_prompt = (
                "Your previous reply was not valid JSON. "
                "PLEASE resend only the JSON object, nothing else.\n\n"
                + base_prompt
            )

import streamlit as st
import json

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

st.set_page_config(page_title="Form Assistant")

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
            st.session_state.fields = meta["questions"]  # expects list of {name, prompt}
            st.session_state.stage = "ask_questions"
            st.session_state.chat.append(("bot", f"I'll help you fill out **{form}**. Let's start!"))
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
            user_block="\\n".join([f"{k}: {v}" for k, v in st.session_state.answers.items()])
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
    st.chat_message("bot").markdown("All done! Refresh to start over.")

    
