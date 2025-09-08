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

# -------------------- Highlight CSS (theme aware / underline) --------------------
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

# Parse the model output into sections for filtering
SECTION_KEYS = {
    "meds": ["medications", "med changes", "medication changes"],
    "orders": ["orders & plan", "orders/plan", "plan changes", "orders", "plan"],
    "ptot": ["pt/ot", "rehab", "therapy"],
    "cm": ["case management", "disposition", "discharge plan"],
    "brief": ["role brief", "nursing brief", "clinician brief", "summary brief"],
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

# -------------------- Example note pairs --------------------
EXAMPLES = {
    "Med change + PT/OT + DME": (
        "Patient alert and oriented x3. On lisinopril 10 mg daily.\n"
        "PT: ambulated 20 ft with walker, min assist.\n"
        "Plan: continue current meds and PT daily.\n"
        "Case management: discharge likely to rehab facility, pending insurance auth.\n",
        "Patient alert and oriented x3. Lisinopril increased to 20 mg daily.\n"
        "PT: ambulated 40 ft with walker, contact guard.\n"
        "Plan: discontinue acetaminophen; add BMP to monitor renal function.\n"
        "Case management: insurance approved; discharge now planned for home with home health PT.\n"
    ),
    "Insulin + diet + PT consult": (
        "Patient diabetic, on lispro sliding scale insulin with meals.\n"
        "Diet: regular.\n"
        "Plan: monitor blood sugars, encourage mobility.\n",
        "Patient diabetic, lispro sliding scale insulin discontinued. Started basal glargine 20 units nightly.\n"
        "Diet: changed to carb-controlled.\n"
        "Plan: monitor for hypoglycemia; PT consult ordered.\n"
    ),
    "Post-op day shift: Foley out, IV off, discharge plan change": (
        "POD1 following laparoscopic cholecystectomy. Foley catheter in place.\n"
        "Plan: advance diet as tolerated, continue IV fluids.\n"
        "Case management: evaluating for rehab placement.\n",
        "POD2. Foley catheter removed; voiding adequately.\n"
        "Plan: advance to regular diet, discontinue IV fluids.\n"
        "Case management: cleared for discharge home with home health PT.\n"
    ),
    "Long SOAP pair (colectomy) — Yesterday/Today": (
        "S: 62M POD2 sigmoid colectomy. Pain 3/10 on acetaminophen. Clear liquids tolerated.\n"
        "O: Vitals stable. Incisions CDI. Foley present. No BM. Labs: WBC 10.2, Cr 0.9.\n"
        "A: Recovering; risk for constipation.\n"
        "P: Advance to full liquids; IV 75 mL/hr; acetaminophen PO, morphine IV PRN; PT daily; enoxaparin; Foley to remain; daily labs; plan rehab.\n",
        "S: Pain 2/10; wants solids. Ambulated twice with PT; mild dizziness.\n"
        "O: Vitals stable. Foley removed; voiding. Passed flatus and BM. Labs: WBC 9.0, Cr 1.1.\n"
        "A: POD3 progressing; bowel function returning; watch creatinine.\n"
        "P: Advance to soft solids; discontinue IV fluids; continue acetaminophen; stop morphine; PT BID; BMP tomorrow; enoxaparin; discharge home with home health nursing and PT.\n"
    ),

    # NEW: very long + messy pair
    "LONG & MESSY: Med-surg progress notes w/ labs, orders, cultures": (
        # Yesterday
        "Progress Note – Hospital Day 4\n"
        "Chief: fevers, postop ileus improving. Reports poor sleep.\n"
        "Meds: ceftriaxone 2g q24h, metronidazole 500mg q8h, enoxaparin 40mg daily, "
        "acetaminophen 650mg q6h PRN, oxycodone 5mg q4h PRN, lisinopril 10mg daily.\n"
        "Fluids/lines: PIV L forearm; LR @ 75 mL/hr; Foley in place since HD3.\n"
        "Labs (05:20): WBC 13.2 (↑), Hgb 10.1, Plt 320, Na 136, K 3.7, Cr 1.0, Glu 148.\n"
        "Micro: blood cx x2 drawn HD3 — NGTD. UA neg. Sputum not obtained.\n"
        "Imaging: CXR (HD3) mild atelectasis, no consolidation. KUB: improving bowel gas pattern.\n"
        "Consults: PT evaluated — min assist to stand; ambulated 10 ft with walker; rec: OOB TID, gait 2x/day.\n"
        "Nursing: two BMs in last 24h; I/Os incomplete; Tmax 38.2 overnight.\n"
        "Assessment: postop fever vs resolving ileus; likely atelectasis component. AKI resolved. "
        "Hypertension controlled. DVT ppx ongoing.\n"
        "Plan: continue CTX/flagyl pending cultures; IS 10x/hr while awake; wean O2 as tolerated; "
        "advance to soft diet if no N/V; PT daily; maintain Foley today, reassess tomorrow; "
        "BMP/CBC in AM; sleep hygiene (reduce overnight interruptions if stable).\n",

        # Today
        "Progress Note – Hospital Day 5\n"
        "Subjective: slept better after melatonin; hungry; minimal pain at rest.\n"
        "Meds: ceftriaxone STOPPED; switched to piperacillin–tazobactam 3.375g q8h; "
        "metronidazole STOPPED; enoxaparin 40mg daily; acetaminophen scheduled 650mg q6h; "
        "oxycodone PRN; lisinopril HELD for mild hypotension overnight; STARTED pantoprazole 40mg daily.\n"
        "Fluids/lines: LR DISCONTINUED; PIV remains; Foley REMOVED 09:00 – voided 300 mL post-removal.\n"
        "Labs (05:15): WBC 9.8 (improved), Hgb 9.7, Plt 345, Na 138, K 3.4 (↓), Cr 1.2 (slightly ↑), Glu 132.\n"
        "Micro: blood cx set #1 POS for E. coli (HD3, time to positivity 18h), set #2 NGTD; repeat cultures drawn this AM.\n"
        "Imaging: CT A/P with contrast (HD4 evening): small postoperative fluid collection near right gutter "
        "(2.5 cm) without rim enhancement, likely sterile; no free air.\n"
        "Consults: PT progress — ambulated 60 ft with walker, CGA; rec home PT at discharge if progress continues.\n"
        "Nursing: two BMs; I/Os complete; Tmax 37.6; walked hall twice with assist; tolerated soft diet.\n"
        "Assessment: bacteremia likely GI source, clinically improving after abx broadened; "
        "mild hypokalemia; borderline creatinine rise likely from dehydration; pain controlled; "
        "functional status improving.\n"
        "Plan: continue Zosyn pending sensitivities; replete KCl 40 mEq PO x1 then recheck; "
        "encourage PO intake; PT bid; remove fall-risk bracelet when stable; "
        "case management: anticipate discharge home in 48–72h with home PT; "
        "daily CBC/BMP; resume lisinopril tomorrow if BP stable.\n"
    ),

    # NEW: single messy note (use with Single note mode)
    "SINGLE NOTE: Messy hospitalist note with labs + consults": (
        "Hospitalist Progress Note – HD7\n"
        "Interval events: no acute overnight; mild orthostasis this AM after shower.\n"
        "Meds: insulin glargine 18u QHS; insulin lispro sliding scale with meals; "
        "metoprolol tartrate 25mg BID; apixaban 5mg BID; atorvastatin 40mg QHS; "
        "cefazolin STOPPED yesterday; vancomycin STARTED per ID for MRSA nares (+), trough pending.\n"
        "Diet: consistent carb; 1500 mL fluid restriction. DVT ppx: therapeutic on apixaban.\n"
        "Vitals: afebrile; BP 108/68 (overnight lows to 96/60); HR 84; sat 95% RA.\n"
        "I/O last 24h: PO 1100 mL; UOP 900 mL; 1 BM. Weight 82.1 kg (↑0.6 kg).\n"
        "Labs 06:10: WBC 11.4 (↑), Hgb 11.2, Plt 410, Na 137, K 3.9, BUN 22, Cr 1.0, Glu 172 (↑), "
        "AST/ALT wnl; A1c 8.1% (prior). Lactate 1.7.\n"
        "Micro: wound culture from LLE ulcer grew MSSA + strep; blood cx NGTD x48h.\n"
        "Imaging: Duplex LE yesterday—no DVT. Echo (HD6) EF 55%, no vegetations.\n"
        "Consults: ID recommends switch to oral doxycycline on discharge x7d; "
        "PT: ambulated 100 ft with cane, CGA; recommend stair training prior to DC; "
        "CM: home health nursing + PT arranged, pending teaching.\n"
        "Assessment: diabetic foot ulcer with cellulitis improving; hyperglycemia suboptimal; "
        "MRSA colonization; orthostatic symptoms likely from diuresis; functional status improving.\n"
        "Plan: continue vancomycin today, convert to doxycycline 100mg BID tomorrow if stable; "
        "increase glargine to 20u QHS; adjust lispro scale to moderate; "
        "hold metoprolol if SBP < 100 or HR < 60; orthostatic vitals today; "
        "PT stair training; nursing to reinforce wound care dressing change technique; "
        "target discharge tomorrow with HH nursing/PT and wound clinic follow-up in 1 week.\n",
        ""  # second element unused in single-note mode
    ),
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
    note_a = colA.text_area("Yesterday's note", value=default_a, height=260, placeholder="Paste Note A…")
    note_b = colB.text_area("Today's note", value=default_b, height=260, placeholder="Paste Note B…")
else:
    # Single note mode uses only "Today's note"
    default_b = ""
    if choice != example_names[0]:
        # load just the "today" half from any example
        _, default_b = EXAMPLES[choice]
    note_a = ""  # unused
    note_b = st.text_area("Note", value=default_b, height=260, placeholder="Paste a single note…")

# -------------------- Search / Highlight --------------------
with st.expander("Search within notes (highlights matches)"):
    hl_style = st.radio("Highlight style", ["Background", "Underline"], horizontal=True)
    inject_highlight_css(hl_style)

    search_query = st.text_input("Search term(s) (case-insensitive; multiple words allowed)")
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

# -------------------- Category filters --------------------
with st.expander("Filter summary categories"):
    f_meds = st.checkbox("Medications", value=True)
    f_orders = st.checkbox("Orders / Plan", value=True)
    f_ptot = st.checkbox("PT/OT", value=True)
    f_cm = st.checkbox("Case Management / Disposition", value=True)
    f_brief = st.checkbox("Role Brief", value=True)

role = st.radio(
    "Primary view",
    ["Nurse", "Clinician (MD/APP)", "PT/OT", "Case Management"],
    horizontal=True,
)

def role_hint(r: str) -> str:
    if r == "Nurse":
        return ("Emphasize give/hold medications, new or changed orders, safety issues, and tasks for the next shift. "
                "Return 5 concise bullets.")
    if r == "PT/OT":
        return ("Emphasize functional goals, assist levels, mobility tolerance, barriers, and discharge equipment. "
                "Return 5 concise bullets.")
    if r == "Case Management":
        return ("Emphasize disposition plan, services, insurance/authorization updates, DME, and barriers to discharge. "
                "Return 5 concise bullets.")
    return ("Emphasize assessment/plan differences, medication changes (added, discontinued, dose/frequency), "
            "consults, and diagnostic updates. Return 8 concise bullets.")

# -------------------- LLM calls --------------------
def compare_notes_structured(note_a: str, note_b: str, role: str) -> str:
    system_msg = (
        "You are a clinical documentation assistant. Compare two clinical notes and report only real differences. "
        "Return STRUCTURED MARKDOWN with EXACT headings (these exact strings):\n"
        "## Medications\n"
        "## Orders & Plan\n"
        "## PT/OT\n"
        "## Case Management / Disposition\n"
        "## Role Brief\n"
        "Under each heading, use concise bullet points. Avoid boilerplate."
    )
    user_msg = (
        f"ROLE: {role}\n"
        f"Role instruction: {role_hint(role)}\n\n"
        f"Note_A (yesterday):\n{note_a}\n\n"
        f"Note_B (today):\n{note_b}\n"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        max_tokens=900,
    )
    return resp.choices[0].message.content.strip()

def analyze_single_note_structured(note: str, role: str) -> str:
    system_msg = (
        "You are a clinical documentation assistant. Analyze ONE clinical note and extract actionable details. "
        "Return STRUCTURED MARKDOWN with EXACT headings (these exact strings):\n"
        "## Medications\n"
        "## Orders & Plan\n"
        "## PT/OT\n"
        "## Case Management / Disposition\n"
        "## Role Brief\n"
        "Under each heading, use concise bullet points. Avoid boilerplate. "
        "If a section is not mentioned, write 'No changes noted.' "
        "For Role Brief, summarize what matters for the specified role in 4–6 bullets."
    )
    user_msg = (
        f"ROLE: {role}\n"
        f"Role instruction: {role_hint(role)}\n\n"
        f"Note:\n{note}\n"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
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
            st.warning("Paste text into both boxes first or load an example.")
            st.stop()
        with st.spinner("Comparing..."):
            output_md = compare_notes_structured(note_a, note_b, role)
    else:
        if not note_b:
            st.warning("Paste a note first or load an example.")
            st.stop()
        with st.spinner("Analyzing note..."):
            output_md = analyze_single_note_structured(note_b, role)

    # Split and reassemble only selected sections (plain markdown headings)
    sections = split_sections(output_md)
    collected = []
    if f_meds and sections.get("meds"): collected.append("## Medications\n" + sections["meds"])
    if f_orders and sections.get("orders"): collected.append("## Orders & Plan\n" + sections["orders"])
    if f_ptot and sections.get("ptot"): collected.append("## PT/OT\n" + sections["ptot"])
    if f_cm and sections.get("cm"): collected.append("## Case Management / Disposition\n" + sections["cm"])
    if f_brief and sections.get("brief"): collected.append("## Role Brief\n" + sections["brief"])
    final_text = "\n\n".join(collected).strip() or output_md

    st.subheader("Summary")
    st.markdown(final_text)

    # Actions row (Copy | Print | PDF)
    c_copy, c_print, c_pdf = st.columns([1, 1, 2])
    with c_copy:
        render_copy_button(final_text, "Copy summary to clipboard")
    with c_print:
        render_print_button(final_text, "Print summary")
    with c_pdf:
        pdf_bytes = brief_to_pdf_bytes(final_text, title=f"{'Compare' if mode=='Compare two notes' else 'Single'} — {role} view")
        st.download_button(
            label="Download summary as PDF",
            data=pdf_bytes,
            file_name="change_summary.pdf",
            mime="application/pdf",
        )
