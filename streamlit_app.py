# streamlit_app.py
import os, re, html
from io import BytesIO
import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI

# -------------------- App setup --------------------
st.set_page_config(page_title="Clinical Change Tracker (Demo)", layout="wide")
st.title("Clinical Change Tracker (Demo)")
st.warning("Demo only — do NOT paste PHI. Use synthetic or de-identified text.")

# API key
API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
if not API_KEY:
    st.error('Missing OpenAI API key. In Streamlit, go to Settings → Secrets and add:\n\nOPENAI_API_KEY = "sk-..."')
    st.stop()
os.environ["OPENAI_API_KEY"] = API_KEY
client = OpenAI()

# -------------------- CSS (theme-aware highlights + small source text) --------------------
def inject_highlight_css(style: str):
    if style == "Background":
        css = """
        <style>
        :root { --hl-bg: #fff59d; --hl-fg: #111; }
        @media (prefers-color-scheme: dark) {
          :root { --hl-bg: #4b4700; --hl-fg: #fff; }
        }
        .marked { background-color: var(--hl-bg); color: var(--hl-fg); padding:0 2px; border-radius:2px; box-shadow:0 0 0 1px rgba(0,0,0,0.25) inset; }
        pre, code { white-space: pre-wrap; }
        .source-line { color:#777; font-size:0.85em; margin-left:1em; }
        </style>
        """
    else:
        css = """
        <style>
        .marked { background:none; color:inherit; border-bottom:3px solid #f6d365; padding-bottom:1px; }
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

def render_copy_button(text_to_copy: str, button_label: str = "Copy summary"):
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
    "pocu": ["plan of care updates", "plan of care", "handoff", "shift report"],
    "meds": ["medications", "med changes", "medication changes"],
    "orders": ["orders & plan", "orders/plan", "plan changes", "orders", "plan"],
    "ptot": ["pt/ot", "rehab", "therapy"],
    "cm": ["case management", "disposition", "discharge plan"],
    "brief": ["role brief", "nursing brief", "clinician brief", "summary brief"],
}

IGNORE_HEADINGS = {"note a", "note_b", "note b", "note_a", "note", "yesterday", "today"}

def normalize_key(hdr: str) -> str:
    h = hdr.strip().lower()
    if h in IGNORE_HEADINGS:
        return "__ignore__"
    for k, aliases in SECTION_KEYS.items():
        for a in aliases:
            if a in h:
                return k
    return ""

def split_sections(markdown_text: str):
    """Split LLM output by H2/H3 headings into our known buckets; ignore any Note A/B echoes."""
    sections = {}
    current_key = None
    buf = []
    lines = (markdown_text or "").splitlines()
    for line in lines:
        if line.startswith("#"):
            if current_key and current_key != "__ignore__":
                sections[current_key] = (sections.get(current_key, "") + "\n" + "\n".join(buf)).strip() if buf else sections.get(current_key, "")
            buf = []
            m = re.match(r"^#{2,3}\s+(.*)$", line)
            if m:
                hdr = m.group(1)
                k = normalize_key(hdr)
                current_key = k if k else "__ignore__"
            else:
                current_key = "__ignore__"
        else:
            buf.append(line)
    if current_key and current_key != "__ignore__":
        sections[current_key] = (sections.get(current_key, "") + "\n" + "\n".join(buf)).strip() if buf else sections.get(current_key, "")
    return sections

# -------------------- Examples (ONE pair, ONE single) --------------------
EXAMPLES = {
    "DEMO: Long messy pair (yesterday → today)": (
        # Yesterday
        "Progress Note – HD4 s/p sigmoid colectomy. Pain 4/10; clear liquids tolerated. "
        "Meds: acetaminophen 650 mg q6h, oxycodone 5 mg q4h PRN, enoxaparin 40 mg daily, lisinopril 10 mg daily. "
        "Foley in place since HD3. IV LR @75 mL/hr. Labs 05:30: WBC 12.8 (↑), Hgb 10.4, Plt 315, Na 136, K 3.7, Cr 0.9, Glu 148. "
        "CXR: mild basilar atelectasis. PT: min assist; amb 15 ft with RW; dizziness. I/Os incomplete; BM x0; flatus present. "
        "Assessment: postop ileus improving; atelectasis driving low-grade fevers. "
        "Plan: IS q1h while awake; advance to full liquids; maintain Foley; PT daily; daily CBC/BMP; consider dc IVFs if PO ↑.",
        # Today
        "Progress Note – HD5. Slept better; asking for solids. "
        "Meds: acetaminophen scheduled; oxycodone PRN; enoxaparin 40 mg daily; lisinopril HELD overnight SBP 98; START pantoprazole 40 mg daily. "
        "Foley REMOVED 09:00; voided 350 mL within 6h. IV LR DISCONTINUED. "
        "Labs 05:20: WBC 9.6 (improved), Hgb 9.9, Plt 340, Na 138, K 3.4 (↓), Cr 1.1 (sl ↑), Glu 132. "
        "CT A/P (HD4 pm): 2.5 cm postop fluid, no rim enhancement; no free air. "
        "PT: amb 60 ft CGA; rec home PT if progress continues. BM x1; tolerating soft diet. "
        "Assessment: improving; mild hypokalemia; Cr slightly up likely dehydration. "
        "Plan: KCl 40 mEq PO x1 then recheck; encourage PO; PT BID; resume lisinopril tomorrow if SBP stable; anticipate discharge 48–72h."
    ),
    "DEMO: Single messy note": (
        "Hospitalist Note – HD7. No acute overnight. Mild orthostasis after shower. "
        "Meds: insulin glargine 18 u QHS; lispro sliding scale with meals; metoprolol tartrate 25 mg BID; "
        "apixaban 5 mg BID; atorvastatin 40 mg QHS; vancomycin STARTED per ID for MRSA nares (+). "
        "Diet: consistent carb; 1500 mL fluid restriction. Vitals: afebrile, BP 108/68, HR 84, RA 95%. "
        "I/O 24h: PO 1100 mL; UOP 900 mL; BM x1. Wt 82.1 kg (+0.6). "
        "Labs: WBC 11.4, Hgb 11.2, Plt 410, Na 137, K 3.9, BUN 22, Cr 1.0, Glu 172. "
        "Cultures: wound MSSA + strep; blood NGTD. Imaging: LE duplex neg DVT; Echo EF 55%. "
        "Consults: ID → convert to doxycycline on discharge x7d; PT: amb 100 ft CGA; CM: HH nursing + PT arranged. "
        "Assessment: diabetic foot ulcer improving; hyperglycemia suboptimal; MRSA colonization; functional status improving. "
        "Plan: continue vanc today → convert to doxy 100 mg BID tomorrow if stable; increase glargine to 20 u; "
        "adjust lispro to moderate scale; hold metoprolol if SBP <100 or HR <60; orthostatic vitals today; "
        "PT stair training; nursing reinforce wound care; target discharge tomorrow with HH.",
        ""
    ),
}

# -------------------- Mode + Inputs --------------------
mode = st.radio("Mode", ["Compare two notes", "Single note"], horizontal=True)
example_names = ["-- Select example --"] + list(EXAMPLES.keys())
choice = st.selectbox("Load example (optional)", example_names, index=0)

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
        default_b = (pair[1].strip() if len(pair) > 1 and isinstance(pair[1], str) and pair[1].strip() else pair[0])
    note_a = ""
    note_b = st.text_area("Note", value=default_b, height=420, placeholder="Paste a single note…")

# -------------------- Search --------------------
with st.expander("Search within notes (highlights matches)"):
    hl_style = st.radio("Highlight style", ["Background", "Underline"], horizontal=True)
    inject_highlight_css(hl_style)
    query = st.text_input("Search term(s)")
    if query.strip():
        if mode == "Compare two notes":
            hits_a, hits_b = count_hits(note_a, query), count_hits(note_b, query)
            st.caption(f"Matches — Yesterday: {hits_a} | Today: {hits_b}")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("Yesterday (highlighted):")
                st.markdown(highlight_text(note_a, query), unsafe_allow_html=True)
            with c2:
                st.markdown("Today (highlighted):")
                st.markdown(highlight_text(note_b, query), unsafe_allow_html=True)
        else:
            st.caption(f"Matches — Note: {count_hits(note_b, query)}")
            st.markdown(highlight_text(note_b, query), unsafe_allow_html=True)

# -------------------- Filters --------------------
with st.expander("Filter summary categories"):
    f_pocu  = st.checkbox("Plan of Care Updates (handoff)", value=True)
    f_meds  = st.checkbox("Medications", value=True)
    f_orders= st.checkbox("Orders / Plan", value=True)
    f_ptot  = st.checkbox("PT/OT", value=True)
    f_cm    = st.checkbox("Case Management / Disposition", value=True)
    f_brief = st.checkbox("Role Brief", value=True)
    f_src   = st.checkbox("Show evidence/source lines", value=False)

role = st.radio("Primary view", ["Nurse", "Clinician (MD/APP)", "PT/OT", "Case Management"], horizontal=True)

def role_hint(r: str) -> str:
    if r == "Nurse": return "Emphasize meds, orders, safety issues, and tasks for next shift."
    if r == "PT/OT": return "Emphasize mobility goals, assist levels, tolerance, barriers, equipment."
    if r == "Case Management": return "Emphasize disposition plan, services, insurance/authorization, DME."
    return "Emphasize assessment/plan differences, med changes, consults, diagnostic updates."

# -------------------- LLM calls --------------------
BASE_COMPARE_INSTR = (
    "You are a clinical documentation assistant. Compare two clinical notes and report ONLY real differences. "
    "STRICT FORMAT RULES:\n"
    "• OUTPUT ONLY these H2 headings, exactly as written, in this order:\n"
    "## Plan of Care Updates\n## Medications\n## Orders & Plan\n## PT/OT\n## Case Management / Disposition\n## Role Brief\n"
    "• DO NOT include any other headings.\n"
    "• DO NOT repeat, quote, or echo the raw notes or any 'Note A/Note B' sections.\n"
    "• Use concise bullet points under each heading. Avoid boilerplate.\n"
    "• For 'Plan of Care Updates', produce a copy-paste-ready nurse handoff list (short imperative bullets for the next shift).\n"
)
BASE_SINGLE_INSTR = (
    "You are a clinical documentation assistant. Analyze ONE clinical note and extract actionable details. "
    "STRICT FORMAT RULES:\n"
    "• OUTPUT ONLY these H2 headings, exactly as written, in this order:\n"
    "## Plan of Care Updates\n## Medications\n## Orders & Plan\n## PT/OT\n## Case Management / Disposition\n## Role Brief\n"
    "• DO NOT include any other headings.\n"
    "• DO NOT repeat, quote, or echo the raw note.\n"
    "• If a section is not mentioned, write 'No changes noted.'\n"
    "• For 'Plan of Care Updates', produce a copy-paste-ready nurse handoff list (short imperative bullets for the next shift).\n"
)

def compare_notes_structured(a: str, b: str, role: str, show_sources: bool) -> str:
    sys = BASE_COMPARE_INSTR + ("• After each bullet, include a brief 'Source:' in parentheses.\n" if show_sources else "")
    user = f"ROLE: {role}\nRole guidance: {role_hint(role)}\n\nNote_A (yesterday):\n{a}\n\nNote_B (today):\n{b}\n"
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
        temperature=0.2, max_tokens=900,
    )
    return r.choices[0].message.content.strip()

def analyze_single_note_structured(note: str, role: str, show_sources: bool) -> str:
    sys = BASE_SINGLE_INSTR + ("• After each bullet, include a brief 'Source:' in parentheses.\n" if show_sources else "")
    user = f"ROLE: {role}\nRole guidance: {role_hint(role)}\n\nNote:\n{note}\n"
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
        temperature=0.2, max_tokens=900,
    )
    return r.choices[0].message.content.strip()

# -------------------- PDF helper --------------------
def brief_to_pdf_bytes(markdown_text: str, title: str = "Clinical Change Tracker"):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import inch
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter
    c.setFont("Helvetica-Bold", 14); c.drawString(1*inch, h-1*inch, title)
    c.setFont("Helvetica", 10); y = h-1.3*inch; maxw = w-2*inch
    for line in (markdown_text or "").splitlines():
        words, cur = line.split(" "), ""
        for wd in words:
            test = (cur + " " + wd).strip()
            if c.stringWidth(test, "Helvetica", 10) > maxw:
                c.drawString(1*inch, y, cur); y -= 14; cur = wd
                if y < 1*inch: c.showPage(); c.setFont("Helvetica", 10); y = h-1*inch
            else: cur = test
        if cur:
            c.drawString(1*inch, y, cur); y -= 14
            if y < 1*inch: c.showPage(); c.setFont("Helvetica", 10); y = h-1*inch
    c.showPage(); c.save(); buf.seek(0); return buf.getvalue()

# -------------------- Run --------------------
if st.button("Run", type="primary"):
    if mode == "Compare two notes":
        if not (note_a and note_b):
            st.warning("Paste text into both boxes first."); st.stop()
        with st.spinner("Comparing..."):
            output_md = compare_notes_structured(note_a, note_b, role, show_sources=f_src)
    else:
        if not note_b:
            st.warning("Paste a note first."); st.stop()
        with st.spinner("Analyzing..."):
            output_md = analyze_single_note_structured(note_b, role, show_sources=f_src)

    sections = split_sections(output_md)
    # Assemble in the exact order we want, with Plan of Care Updates first
    collected = []
    if sections.get("pocu") and st.session_state.get("show_pocu", True) if True else True:
        if st.session_state.get("show_pocu", True):
            pass
    if sections.get("pocu"): collected.append("## Plan of Care Updates\n" + sections["pocu"])
    if sections.get("meds")  : collected.append("## Medications\n" + sections["meds"])
    if sections.get("orders"): collected.append("## Orders & Plan\n" + sections["orders"])
    if sections.get("ptot")  : collected.append("## PT/OT\n" + sections["ptot"])
    if sections.get("cm")    : collected.append("## Case Management / Disposition\n" + sections["cm"])
    if sections.get("brief") : collected.append("## Role Brief\n" + sections["brief"])

    # Apply checkboxes (hide any section unchecked)
    def keep(label, enabled):
        return (label.startswith("## Plan of Care Updates") and f_pocu) or \
               (label.startswith("## Medications") and f_meds) or \
               (label.startswith("## Orders & Plan") and f_orders) or \
               (label.startswith("## PT/OT") and f_ptot) or \
               (label.startswith("## Case Management / Disposition") and f_cm) or \
               (label.startswith("## Role Brief") and f_brief)

    final_text = "\n\n".join([sec for sec in collected if keep(sec, True)]).strip() or output_md

    st.subheader("Summary")
    st.markdown(final_text)

    c1, c2, c3 = st.columns([1,1,2])
    with c1: render_copy_button(final_text, "Copy summary")
    with c2: render_print_button(final_text, "Print summary")
    with c3:
        pdf_bytes = brief_to_pdf_bytes(final_text, title=f"{'Compare' if mode=='Compare two notes' else 'Single'} — {role}")
        st.download_button("Download PDF", data=pdf_bytes, file_name="summary.pdf", mime="application/pdf")
