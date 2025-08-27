# app_chat.py
from __future__ import annotations
from pathlib import Path
import sys
import re
from collections import deque
import streamlit as st

# =========================
# חיבור ל-src + ייבוא ask (RAG)
# =========================
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR / "src"))  # מאפשר import מתוך src/

try:
    from rag.probe_index import ask   # expect: ask(query: str, k:int) -> dict
    RAG_READY = True
except Exception:
    ask = None  # type: ignore
    RAG_READY = False

# =========================
# הגדרות אפליקציה
# =========================
APP_TITLE = "Tender Intelligence"
APP_SUB   = "סוכן מודיעים מכרזים חכם - מקור הידע שלך למידע, תובנות והזדמנויות עסקיות בזמן אמת"

def find_logo() -> Path | None:
    for name in ("LOGO.png", "LOGO.png.gif", "logo.png", "logo.gif"):
        p = BASE_DIR / name
        if p.exists():
            return p
    return None

# =========================
# עיצוב – בלי לשנות את מה שאהבת
# =========================
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.markdown("""
<style>
html, body, .stApp { background: #000000 !important; }

header[data-testid="stHeader"] { background: transparent; }
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }

/* מעטפת מרכזית */
.shell { max-width: 1100px; margin: 0 auto; padding: 30px 16px 16px; }

/* לוגו ממורכז */
.logo-wrap { display:flex; justify-content:center; align-items:center; margin: 6px 0 8px; }

/* כותרות */
.title-row { text-align:center; margin-top: 4px; }
.title-row h1 { color: #ffffff; font-size: 46px; margin: 0 0 6px; }
.subtitle { color: #d9d9d9; text-align:center; font-size: 16px; margin-bottom: 20px; }

/* פס קלט בצמוד לתחתית */
.askbox { position: fixed; bottom: 0; left: 0; right: 0;
          padding: 12px 20px; background: #000000; }

/* שדה הטקסט כהה עם טקסט לבן */
.chat-input input {
  background: #1b1b1b !important; color: #fff !important;
  border: 1px solid #333 !important;
  border-radius: 25px !important;
  padding: 12px 20px !important;
  font-size: 16px !important;
}

/* כפתור שליחה עגול ירוק עם ✓ */
.stButton>button {
  width: 42px; height: 42px; border-radius: 50%;
  background: #25D366; border: none;
  color: white; font-size: 20px; line-height: 20px;
  margin-left: 8px;
}
.stButton>button:hover { filter: brightness(1.12); }

/* היסטוריית תשובות */
.answers { margin-bottom: 90px; }
.bubble {
  background:#0f0f10; border:1px solid #2d2d32; border-radius:12px;
  padding:14px 16px; color:#eaeaea; margin:10px 0;
}
</style>
""", unsafe_allow_html=True)

# =========================
# פונקציות עזר לשלב 5 (שיחה חכמה)
# =========================
def _init_memory():
    if "memory" not in st.session_state:
        st.session_state.memory = {
            "last_domain": None,      # למשל "אחזקה", "גינון"
            "last_office": None,      # למשל "משרד החינוך"
            "turns": deque(maxlen=8)  # 8 חילופי דברים אחרונים
        }

def remember(user_q: str, bot_a: str):
    _init_memory()
    # תחום אפשרי
    m = re.search(r"(?:ב(?:תחום|נושא)|תחום)\s+([^\n?]+)", user_q)
    if m:
        st.session_state.memory["last_domain"] = m.group(1).strip()
    # משרד/רשות אפשרי
    m2 = re.search(r"(משרד|עיריית|עירייה|רשות)\s+([^\n?]+)", user_q)
    if m2:
        st.session_state.memory["last_office"] = (m2.group(1) + " " + m2.group(2)).strip()
    # שמירת תקציר
    st.session_state.memory["turns"].append((user_q.strip(), bot_a.strip()))

def last_domain_fallback(user_q: str) -> str | None:
    _init_memory()
    q = user_q.strip()
    wants_count = bool(re.search(r"\bכמה\b|\bמספר\b", q))
    mentions_domain = bool(re.search(r"תחום|בנושא|בקטגור(יה|יית)", q))
    if wants_count and not mentions_domain and st.session_state.memory.get("last_domain"):
        return st.session_state.memory["last_domain"]
    return None

def build_context_prompt() -> str:
    _init_memory()
    if not st.session_state.memory["turns"]:
        return ""
    lines = []
    for u, b in list(st.session_state.memory["turns"])[-4:]:
        lines.append(f"משתמש: {u}")
        lines.append(f"סוכן: {b[:200]}")
    return "\n".join(lines)

def short_summary(res: dict, limit: int = 3) -> str:
    """סיכום קצר של תוצאות ה-RAG + מקורות."""
    if not res or "documents" not in res or not res["documents"]:
        return "לא נמצאו תוצאות רלוונטיות."
    docs = res["documents"][0] if isinstance(res["documents"][0], list) else res["documents"]
    metas = res.get("metadatas", [])[0] if isinstance(res.get("metadatas", []), list) else res.get("metadatas", [])
    pairs = list(zip(docs, metas)) if metas else [(d, {}) for d in docs]
    lines = []
    for d, m in pairs[:limit]:
        title = (m.get("title") or m.get("שם המכרז") or "").strip()
        due   = m.get("due") or m.get("מועד אחרון להגשה") or ""
        url   = m.get("url") or ""
        line  = "• " + (title if title else (str(d)[:120] + ("..." if len(str(d)) > 120 else "")))
        if due:
            line += f" — מועד אחרון: {due}"
        if url:
            line += f"\nמקור: {url}"
        lines.append(line)
    return "\n".join(lines)

def try_count_by_domain(user_q: str) -> str | None:
    """
    אם המשתמש שואל 'כמה מכרזים יש בתחום X' – ננסה לחשב ספירה מקומית
    מתוך data/tenders_details.csv (אם קיים). אם לא – נחזיר None.
    """
    import pandas as pd
    csv_path = BASE_DIR / "data" / "tenders_details.csv"
    if not csv_path.exists():
        return None
    q = user_q.strip()
    m = re.search(r"(?:כמה|מספר)\s+מכרזים\s+(?:יש\s+)?(?:פתוחים\s+)?(?:ב(?:תחום|נושא)\s+)?(.+)", q)
    if not m:
        return None
    domain = m.group(1).strip().rstrip("?")
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(csv_path)
    text_cols = [c for c in df.columns if df[c].dtype == object]
    if not text_cols:
        return None
    mask = False
    for c in text_cols:
        mask = mask | df[c].astype(str).str.contains(domain, case=False, na=False)
    n = int(mask.sum())
    return f"נמצאו כ-{n} מכרזים שמתאימים לתחום “{domain}”." if n else f"לא נמצאו מכרזים תואמים לתחום “{domain}”."

def reply(user_q: str) -> str:
    """מנגנון תשובה חכמה: ספירות → שאלת המשך → RAG."""
    counted = try_count_by_domain(user_q)
    if counted is not None:
        return counted
    ld = last_domain_fallback(user_q)
    q_aug = user_q if not ld else f"{user_q} (כוונה: מדובר בתחום '{ld}')"
    ctx = build_context_prompt()
    if ctx:
        q_aug = f"הקשר שיחה קודם:\n{ctx}\n\nשאלת המשתמש כעת: {q_aug}"
    if not RAG_READY:
        return "החיבור לאינדקס (RAG) לא מוכן. ודאי ש-src/rag/probe_index.py קיים וכולל ask(query, k)."
    try:
        res = ask(q_aug, k=5)
        return short_summary(res, limit=3)
    except Exception as e:
        return f"שגיאה בזמן חיפוש באינדקס: {e}"

# =========================
# ראש הדף – לוגו ממורכז, כותרת ותת־כותרת
# =========================
st.markdown('<div class="shell">', unsafe_allow_html=True)

# לוגו – רוחב נשלט כאן (שינוי הגודל במקום אחר לא נחוץ)
st.markdown('<div class="logo-wrap">', unsafe_allow_html=True)
logo = find_logo()
if logo:
    st.image(str(logo), use_container_width=False, width=130)  # <- גודל הלוגו
else:
    st.markdown('<div style="color:#777;text-align:center;font-size:13px;">(logo)</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown(f'<div class="title-row"><h1>{APP_TITLE}</h1></div>', unsafe_allow_html=True)
st.markdown(f'<div class="subtitle">{APP_SUB}</div>', unsafe_allow_html=True)

# =========================
# היסטוריית הודעות בבועות
# =========================
if "history" not in st.session_state:
    st.session_state.history = []

st.markdown('<div class="answers">', unsafe_allow_html=True)
for who, text in st.session_state.history:
    st.markdown(
        f'<div class="bubble"><b>{"את/ה" if who=="user" else "הסוכן"}</b><br>{text}</div>',
        unsafe_allow_html=True
    )
st.markdown('</div>', unsafe_allow_html=True)

# =========================
# שורת הצ'אט למטה (אותו UI)
# =========================
with st.container():
    st.markdown('<div class="askbox">', unsafe_allow_html=True)
    cols = st.columns([10, 1])
    with cols[0]:
        user_q = st.text_input(
            "הקלד/י הודעה…",
            key="chat_input",
            label_visibility="collapsed",
            placeholder="הקלד/י הודעה…"
        )
    with cols[1]:
        send = st.button("✓")  # כפתור עגול ירוק עם סימון
    st.markdown('</div>', unsafe_allow_html=True)

# =========================
# שליחת הודעה + זיכרון שיחה (UI נשאר זהה)
# =========================
if send and user_q.strip():
    q = user_q.strip()
    st.session_state.history.append(("user", q))

    if not RAG_READY:
        ans = "החיבור לאינדקס (RAG) לא מוכן. ודאי שקובץ src/rag/probe_index.py קיים וכולל פונקציה ask(query, k)."
    else:
        try:
            res = ask(q, k=10)
            want_count_only = "כמה" in q or "כמה מכרזים" in q
            ans = short_summary(res, limit=3, only_count=want_count_only)
        except Exception as e:
            ans = f"שגיאה בזמן חיפוש באינדקס: {e}"

    st.session_state.history.append(("bot", ans))
    # לא צריך לאפס את ה-chat_input ידנית
    st.rerun()

    # איפוס חכם של שדה הקלט אחרי שליחה
    if "chat_input" in st.session_state:
        st.session_state.pop("chat_input")
    st.rerun()

    # ---------- סיכום תוצאות מה-RAG (ספירה + דוגמאות) ----------
def count_results(res: dict) -> int:
    """מחזיר כמה מסמכים הוחזרו מהאינדקס."""
    if not res or "documents" not in res or not res["documents"]:
        return 0
    docs = res["documents"][0] if isinstance(res["documents"][0], list) else res["documents"]
    return len(docs)

def short_summary(res: dict, limit: int = 3, only_count: bool = False) -> str:
    """
    מייצר תשובה לבוט. אם only_count=True — נחזיר רק 'נמצאו X מכרזים'.
    אחרת נחזיר גם כמה דוגמאות עם תאריך ולינק.
    """
    total = count_results(res)
    if total == 0:
        return "לא נמצאו תוצאות רלוונטיות."

    if only_count:
        return f"נמצאו {total} מכרזים רלוונטיים."

    docs  = res["documents"][0] if isinstance(res["documents"][0], list) else res["documents"]
    metas = res.get("metadatas", [])[0] if isinstance(res.get("metadatas", []), list) else res.get("metadatas", [])
    pairs = list(zip(docs, metas)) if metas else [(d, {}) for d in docs]

    lines = [f"נמצאו {total} מכרזים רלוונטיים. הנה חלק מהם:"]
    for d, m in pairs[:limit]:
        title = (m.get("title") or m.get("שם המכרז") or "").strip()
        due   = m.get("due") or m.get("מועד אחרון להגשה") or ""
        url   = m.get("url") or ""
        line  = "• " + (title if title else (str(d)[:120] + ("..." if len(str(d)) > 120 else "")))
        if due:
            line += f" — מועד אחרון: {due}"
        if url:
            line += f"\nמקור: {url}"
        lines.append(line)

    return "\n".join(lines)