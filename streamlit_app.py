# streamlit_app.py
import os
import re
import html
from io import BytesIO
import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI

# -------------------- App setup --------------------
st.set_page_config(page_title="Clinical Change Tracker (Demo)", layout="wide")
st.title("Clinical Change Tracker (Demo)")
st.warning("Demo only — do NOT paste PHI. Use synthetic or de-identified text.")

# Read API key
API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
if not API_KEY:
    st.error('Missing OpenAI API key. In Streamlit, go to Settings → Secrets and add:\n\nOPENAI_API_KEY = "sk-..."')
    st.stop()

os.environ["OPENAI_API_KEY"] = API_KEY
client = OpenAI()

# -------------------- Highlight CSS --------------------
def inject_highlight_css(style: str):
    if style == "Background":
        css = """
        <style>
        :root { --hl-bg: #fff59d; --hl-fg: #111; }
        @media (prefers-color-scheme: dark) {
          :root { --hl-bg: #4b4700; --hl-fg: #fff; }
        }
        .marked {
          background-color: var(--hl-bg);
          color: var(--hl-fg);
          padding: 0 2px;
          border-radius: 2px;
          box-shadow: 0 0 0 1px rgba(0,0,0,0.25) inset;
        }
        pre, code { white-space: pre-wrap; }
        .source-line { color:#777; font-size:0.85em; margin-left:1em; }
        </style>
        """
    else:
        css = """
        <style>
        .marked {
          background: none;
          color: inherit;
          border-bottom: 3px solid #f6d365;
          padding-bottom: 1px;
        }
        pre, code { white-space: pre-wrap; }
        .source-line { color:#777; font-size:0.85em; margin-left:1em; }
        </style>
        """
    st.markdown(css, unsafe_allow_html=True)

# -------------------- Helpers --------------------
def highlight_text(text: str, query: str) -> str:
    if not text or not query.strip():
        return "<pre>" + html.escape(text or "") + "</pre>"
    escaped = html.escape(text)
    tokens = [re.escape(tok) for tok in re.findall(r"\w+", query, flags=re.I)]
    if not tokens:
        return "<pre>" + escaped + "</pre>"
    pattern = re.compile(r"(" + "|".join(tokens) + r")", flags=re.I)
    highlighted = pattern.sub(lambda m: f'<span class="marked">{m.group(0)}</span>', escaped)
    return "<pre>" + highlighted + "</pre>"

def count_hits(text: str, query: str) -> int:
    if not text or not query.strip():
        return 0
    tokens = [re.escape(tok) for tok in re.findall(r"\w+", query, flags=re.I)]
    if not tokens:
        return 0
    pattern = re.compile(r"(" + "|".join(tokens) + r")", flags=re.I)
    return len(pattern.findall(text))

def render_copy_button(text_to_copy: str, button_label: str = "Copy summary to clipboard"):
    escaped = html.escape(text_to_copy or "")
    component_html = f"""
    <div style="display:flex;gap:8px;align-items:center;margin:8px 0 16px 0;">
      <button style="padding:6px 10px;border:1px solid #bbb;border-radius:4px;background:#f5f5f5;cursor:pointer;"
        onclick="navigator.clipboard.writeText(document.getElementById('copy-src').value).then(() => {{
          const n = document.getElementById('copy-note');
          n.textContent='Copied';
          setTimeout(()=>{{n.textContent='';}}, 1500);
      }});">{button_label}</button>
      <span id="copy-note" style="color:#666;font-size:12px;"></span>
    </div>
    <textarea id="copy-src" style="position:absolute; left:-10000px; top:-10000px;">{escaped}</textarea>
    """
    components.html(component_html, height=0)

def render_print_button(text_to_print: str, button_label: str = "Print summary"):
    escaped = html.escape(text_to_print or "").replace("\n", "<br>")
    component_html = f"""
    <div style="display:flex;gap:8px;align-items:center;margin:8px 0 16px 0;">
      <button style="padding:6px 10px;border:1px solid #bbb;border-radius:4px;background:#f5f5f5;cursor:pointer;"
        onclick="
          const w = window.open('', '_blank');
          w.document.write(`
            <html>
              <head>
                <title>Change Summary</title>
                <meta charset='utf-8' />
                <style>
                  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 24px; }}
                  pre {{ white-space: pre-wrap; word-wrap: break-word; }}
                  .source-line {{ color:#777; font-size:0.85em; margin-left:1em; }}
                </style>
              </head>
              <body><pre>{escaped}</pre></body>
            </html>
          `);
          w.document.close();
          w.focus();
          w.print();
        ">
        {button_label}
      </button>
    </div>
    """
    components.html(component_html, height=0)

# -------------------- Section keys --------------------
SECTION_KEYS = {
    "meds": ["medications", "med changes", "medication changes"],
    "orders": ["orders & plan", "orders/plan", "plan changes", "orders", "plan"],
    "ptot": ["pt/ot", "rehab", "therapy"],
    "cm": ["case management", "disposition", "discharge plan"],
    "brief": ["role brief", "nursing brief", "clinician brief", "summary brief"],
    "pocu": ["plan of care updates", "plan of care", "handoff", "shift report"],
}

def normalize_key(hdr: str) -> str:
    h = hdr.strip().lower()
    for k, aliases in SECTION_KEYS.items():
        for a in aliases:
            if a in h:
                return k
    return ""

def split_sections(markdown_text: str):
    sections = {}
    current_key = None
    buf = []
    lines = (markdown_text or "").splitlines()
    for line in lines:
        if line.startswith("#"):
            if current_key:
                sections[current_key] = "\n".join(buf).strip()
                buf = []
            m = re.match(r"^#{2,3}\s+(.*)$", line)
            if m:
                hdr = m.group(1)
                k = normalize_key(hdr)
                current_key = k if k else None
            else:
                current_key = None
        else:
            buf.append(line)
    if current_key:
        sections[current_key] = "\n".join(buf).strip()
    return sections

# -------------------- Example notes (keep short here) --------------------
EXAMPLES = {
    "Simple Med Change": (
        "Patient on lisinopril 10mg daily.\nPT: ambulated 20 ft with walker.\nPlan: continue meds.\n",
        "Patient switched to lisinopril 20mg daily.\nPT: ambulated 40 ft with walker.\nPlan: add BMP.\n"
    )
}

# -------------------- Mode + Inputs --------------------
mode = st.radio("Mode", ["Compare two notes", "Single note"], horizontal=True)

example_names = ["-- Select example notes --"] + list(EXAMPLES.keys())
choice = st.selectbox("Load example notes (optional)", example_names, index=0)

if mode == "Compare two notes":
    colA, colB = st.columns(2)
    default_a, default_b = ("", "")
    if choice != example_names[0]:
        default_a, default_b = EXAMPLES[choice]
    note_a = colA.text_area("Yesterday's note", value=default_a, height=420, placeholder="Paste Note A…")
    note_b = colB.text_area("Today's note", value=default_b, height=420, placeholder="Paste Note B…")
else:
    default_b = ""
    if choice != example_names[0]:
        pair = EXAMPLES[choice]
        if len(pair) > 1 and isinstance(pair[1], str) and pair[1].strip():
            default_b = pair[1].strip()
        else:
            default_b = pair[0]
    note_a = ""
    note_b = st.text_area("Note", value=default_b, height=420, placeholder="Paste a single note…")

# -------------------- Search --------------------
with st.expander("Search within notes (highlights matches)"):
    hl_style = st.radio("Highlight style", ["Background", "Underline"], horizontal=True)
    inject_highlight_css(hl_style)

    search_query = st.text_input("Search term(s)")
    if search_query.strip():
        if mode == "Compare two notes":
            hits_a = count_hits(note_a, search_query)
            hits_b = count_hits(note_b, search_query)
            st.caption(f"Matches — Yesterday: {hits_a} | Today: {hits_b}")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("Yesterday (highlighted):")
                st.markdown(highlight_text(note_a, search_query), unsafe_allow_html=True)
            with c2:
                st.markdown("Today (highlighted):")
                st.markdown(highlight_text(note_b, search_query), unsafe_allow_html=True)
        else:
            hits_b = count_hits(note_b, search_query)
            st.caption(f"Matches — Note: {hits_b}")
            st.markdown(highlight_text(note_b, search_query), unsafe_allow_html=True)

# -------------------- Filters --------------------
with st.expander("Filter summary categories"):
    f_meds = st.checkbox("Medications", value=True)
    f_orders = st.checkbox("Orders / Plan", value=True)
    f_ptot = st.checkbox("PT/OT", value=True)
    f_cm = st.checkbox("Case Management / Disposition", value=True)
    f_brief = st.checkbox("Role Brief", value=True)
    f_pocu = st.checkbox("Plan of Care Updates (handoff)", value=True)
    f_sources = st.checkbox("Show evidence/source lines", value=False)

role = st.radio(
    "Primary view",
    ["Nurse", "Clinician (MD/APP)", "PT/OT", "Case Management"],
    horizontal=True,
)

def role_hint(r: str) -> str:
    if r == "Nurse":
        return "Emphasize meds, orders, safety issues, and tasks for next shift."
    if r == "PT/OT":
        return "Emphasize mobility goals, assist levels, tolerance, barriers, equipment."
    if r == "Case Management":
        return "Emphasize disposition plan, services, insurance/authorization, DME."
    return "Emphasize assessment/plan differences, med changes, consults, diagnostic updates."

# -------------------- LLM calls --------------------
def compare_notes_structured(note_a: str, note_b: str, role: str, show_sources=False) -> str:
    system_msg = (
        "You are a clinical documentation assistant. Compare two notes and report only real differences. "
        "Return STRUCTURED MARKDOWN with EXACT headings:\n"
        "## Medications\n## Orders & Plan\n## PT/OT\n## Case Management / Disposition\n"
        "## Role Brief\n## Plan of Care Updates\n"
        "For 'Plan of Care Updates', give a copy-paste-ready nurse handoff list. "
    )
    if show_sources:
        system_msg += "After each bullet, include the original sentence in parentheses prefixed with 'Source:'. "
    user_msg = (
        f"ROLE: {role}\nInstruction: {role_hint(role)}\n\n"
        f"Note_A:\n{note_a}\n\nNote_B:\n{note_b}"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system_msg},
                  {"role": "user", "content": user_msg}],
        temperature=0.2,
        max_tokens=900,
    )
    return resp.choices[0].message.content.strip()

def analyze_single_note_structured(note: str, role: str, show_sources=False) -> str:
    system_msg = (
        "You are a clinical documentation assistant. Analyze ONE note and extract actionable details. "
        "Return STRUCTURED MARKDOWN with EXACT headings:\n"
        "## Medications\n## Orders & Plan\n## PT/OT\n## Case Management / Disposition\n"
        "## Role Brief\n## Plan of Care Updates\n"
        "For 'Plan of Care Updates', give a copy-paste-ready nurse handoff list. "
    )
    if show_sources:
        system_msg += "After each bullet, include the original sentence in parentheses prefixed with 'Source:'. "
    user_msg = (
        f"ROLE: {role}\nInstruction: {role_hint(role)}\n\nNote:\n{note}"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system_msg},
                  {"role": "user", "content": user_msg}],
        temperature=0.2,
        max_tokens=900,
    )
    return resp.choices[0].message.content.strip()

# -------------------- PDF helper --------------------
def brief_to_pdf_bytes(markdown_text: str, title: str = "Clinical Change Tracker"):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import inch

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1 * inch, height - 1 * inch, title)
    c.setFont("Helvetica", 10)
    y = height - 1.3 * inch
    max_width = width - 2 * inch
    for line in (markdown_text or "").splitlines():
        words = line.split(" ")
        current = ""
        for w in words:
            test = (current + " " + w).strip()
            if c.stringWidth(test, "Helvetica", 10) > max_width:
                c.drawString(1 * inch, y, current)
                y -= 14
                current = w
                if y < 1 * inch:
                    c.showPage()
                    c.setFont("Helvetica", 10)
                    y = height - 1 * inch
            else:
                current = test
        if current:
            c.drawString(1 * inch, y, current)
            y -= 14
            if y < 1 * inch:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = height - 1 * inch
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

# -------------------- Action --------------------
run_btn = st.button("Run", type="primary")

if run_btn:
    if mode == "Compare two notes":
        if not (note_a and note_b):
            st.warning("Paste text into both boxes first.")
            st.stop()
        with st.spinner("Comparing..."):
            output_md = compare_notes_structured(note_a, note_b, role, show_sources=f_sources)
    else:
        if not note_b:
            st.warning("Paste a note first.")
            st.stop()
        with st.spinner("Analyzing..."):
            output_md = analyze_single_note_structured(note_b, role, show_sources=f_sources)

    sections = split_sections(output_md)
    collected = []
    if f_pocu and sections.get("pocu"): collected.append("## Plan of Care Updates\n" + sections["pocu"])
    if f_meds and sections.get("meds"): collected.append("## Medications\n" + sections["meds"])
    if f_orders and sections.get("orders"): collected.append("## Orders & Plan\n" + sections["orders"])
    if f_ptot and sections.get("ptot"): collected.append("## PT/OT\n" + sections["ptot"])
    if f_cm and sections.get("cm"): collected.append("## Case Management / Disposition\n" + sections["cm"])
    if f_brief and sections.get("brief"): collected.append("## Role Brief\n" + sections["brief"])
    final_text = "\n\n".join(collected).strip() or output_md

    st.subheader("Summary")
    st.markdown(final_text)

    c_copy, c_print, c_pdf = st.columns([1, 1, 2])
    with c_copy:
        render_copy_button(final_text, "Copy summary")
    with c_print:
        render_print_button(final_text, "Print summary")
    with c_pdf:
        pdf_bytes = brief_to_pdf_bytes(final_text, title=f"{'Compare' if mode=='Compare two notes' else 'Single'} — {role}")
        st.download_button("Download PDF", data=pdf_bytes, file_name="summary.pdf", mime="application/pdf")
