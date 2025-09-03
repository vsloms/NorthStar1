# streamlit_app.py
import os
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="Clinical Change Tracker (Demo)", page_icon="🩺", layout="wide")
st.title("Clinical Change Tracker (Demo)")
st.caption("Demo only — do NOT paste PHI. Uses OpenAI Python SDK v1.x.")

# --- API key: Streamlit Secrets (preferred) or env var fallback ---
API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))  # <-- add key in Settings → Secrets
if not API_KEY:
    st.error("Missing OpenAI API key. In Streamlit, go to Settings → Secrets and add:\n\nOPENAI_API_KEY = \"sk-...\"")
    st.stop()

# Set env var so the client picks it up cleanly
os.environ["OPENAI_API_KEY"] = API_KEY
client = OpenAI()  # v1 SDK reads OPENAI_API_KEY from env

# --- UI ---
with st.expander("How to use (demo)"):
    st.markdown(
        "- Paste **yesterday’s** note on the left and **today’s** note on the right.\n"
        "- Click **Compare Notes** to see differences + a role-specific brief.\n"
        "- This demo does not store text and is for **synthetic/de-identified** notes only."
    )

colA, colB = st.columns(2)
note_a = colA.text_area("Yesterday's note", height=250, placeholder="Paste Note A…")
note_b = colB.text_area("Today's note", height=250, placeholder="Paste Note B…")

role = st.radio("Primary view", ["Nurse", "Clinician (MD/APP)", "PT/OT", "Case Management"], horizontal=True)

def role_hint(r: str) -> str:
    if r == "Nurse":
        return ("Emphasize give/hold meds, new/changed orders, safety/sentinel issues, and tasks for next shift. "
                "Return 5 concise bullets.")
    if r == "PT/OT":
        return ("Emphasize functional goals, assist levels, mobility tolerance, barriers, and discharge equipment. "
                "Return 5 concise bullets.")
    if r == "Case Management":
        return ("Emphasize disposition plan, services, insurance/authorization updates, DME, and barriers to discharge. "
                "Return 5 concise bullets.")
    return ("Emphasize assessment/plan deltas, meds changes (added/discontinued/dose), consults, and diagnostics. "
            "Return 8 concise bullets.")

if st.button("🔍 Compare Notes", type="primary"):
    if not (note_a and note_b):
        st.warning("Paste text into both boxes first.")
        st.stop()

    system_msg = (
        "You are a clinical documentation assistant. Compare two clinical notes and report ONLY real differences. "
        "Produce:\n"
        "1) A concise markdown list covering:\n"
        "   - Medications: added, discontinued, dose/frequency changes\n"
        "   - Orders / Plan changes\n"
        "   - PT/OT functional changes\n"
        "   - Case management / discharge plan changes\n"
        "2) A role-aware brief per the instruction. Be factual, concise, and avoid boilerplate."
    )
    user_msg = (
        f"ROLE: {role}\n"
        f"Role instruction: {role_hint(role)}\n\n"
        f"Note_A (yesterday):\n{note_a}\n\n"
        f"Note_B (today):\n{note_b}\n"
    )

    with st.spinner("Comparing…"):
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=900,
        )

    out = resp.choices[0].message.content.strip()
    st.subheader("Differences & Role Brief")
    st.markdown(out)
