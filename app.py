import os, json, re
import streamlit as st
import pdfplumber, pandas as pd, plotly.express as px
from openai import OpenAI

st.set_page_config(page_title="EOD PDF Dashboard + AI", layout="wide")
st.title("📊 EOD Report Dashboard")

# --- API client (works with local env or Streamlit secrets) ---
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# --- sidebar: model + options ---
st.sidebar.header("AI Settings")
model = st.sidebar.selectbox(
    "Choose model",
    ["gpt-5", "gpt-5-mini"],  # quick = mini, deep = gpt-5
    index=1
)
run_auto = st.sidebar.checkbox("Auto-run AI after parse", value=False)

uploaded_file = st.file_uploader("Upload EOD PDF", type=["pdf"])

def extract_text(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        return "\n".join([(p.extract_text() or "") for p in pdf.pages])

def parse_basic_metrics(text):
    # subtotal, tax, grand total
    def grab(pat, default="0"):
        m = re.search(pat, text)
        return float(m.group(1)) if m else float(default)

    subtotal = grab(r"Merchandise Sales\s+([\d\.]+)")
    tax_a   = grab(r"Tax A\s+([\d\.]+)")
    tax_b   = grab(r"Tax B\s+([\d\.]+)")
    tax_c   = grab(r"Tax C\s+([\d\.]+)")
    tax_total = grab(r"Tax Total\s+([\d\.]+)")
    grand   = grab(r"\bTotal\s+([\d\.]+)")

    # payment methods (captures last drawer totals page)
    pays = dict(re.findall(r"\b(Cash|AmEx|Visa|Master|Other|Discover):\s*([\d\.]+)", text))
    for k in ["Cash","AmEx","Visa","Master","Other","Discover"]:
        pays[k] = float(pays.get(k, 0))

    # department table
    dept_rows = re.findall(r"([A-Z0-9 \-&'\.]+?)\s+(\d+)\s+([\d\.]+)\s+(?:[\d\.]+\s+)?[\d\.]+", text)
    dept_df = pd.DataFrame(dept_rows, columns=["Department","Qty","Sales"]) if dept_rows else pd.DataFrame(columns=["Department","Qty","Sales"])
    if not dept_df.empty:
        dept_df["Qty"] = dept_df["Qty"].astype(int)
        dept_df["Sales"] = dept_df["Sales"].astype(float)

    return {
        "subtotal": subtotal,
        "tax_a": tax_a, "tax_b": tax_b, "tax_c": tax_c, "tax_total": tax_total,
        "grand_total": grand,
        "payments": pays,
        "dept_df": dept_df
    }

def analyze_with_ai(text, metrics, model_name):
    if client is None:
        return {"error":"No OPENAI_API_KEY set."}, None

    # compact department table for the prompt
    dept_preview = (
        metrics["dept_df"][["Department","Qty","Sales"]]
        .sort_values("Sales", ascending=False)
        .head(20)
        .to_dict(orient="records")
        if not metrics["dept_df"].empty else []
    )

    system = (
        "You are a meticulous retail auditor. "
        "Given an end-of-day report, you MUST return strict JSON with findings."
    )
    user = {
        "instructions": [
            "Summarize key insights (top departments, peak hours if present).",
            "Validate math: subtotal + taxes ≈ grand_total; payment sums ≈ grand_total.",
            "Flag anomalies: negative numbers, zero tax when subtotal>0, drawer mismatches, weird spikes, missing hours.",
            "Severity levels: INFO, WARNING, CRITICAL.",
        ],
        "parsed_numbers": {
            "subtotal": metrics["subtotal"],
            "tax_a": metrics["tax_a"],
            "tax_b": metrics["tax_b"],
            "tax_c": metrics["tax_c"],
            "tax_total": metrics["tax_total"],
            "grand_total": metrics["grand_total"],
            "payments": metrics["payments"],
            "departments_top20": dept_preview
        },
        "raw_text_excerpt": text[:6000]  # enough context; keeps tokens low
    }

    # Responses API (chat-style) — returns usage we can show as cost
    resp = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role":"system","content":system},
            {"role":"user","content":json.dumps(user)}
        ],
        temperature=0.1,
        response_format={"type":"json_object"}
    )
    content = resp.choices[0].message.content
    usage = getattr(resp, "usage", None)
    result = json.loads(content)
    return result, usage

if uploaded_file:
    text = extract_text(uploaded_file)
    m = parse_basic_metrics(text)

    # KPI row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🛒 Merchandise Sales", f"${m['subtotal']:,.2f}")
    col2.metric("🧾 Tax Total", f"${m['tax_total']:,.2f}")
    col3.metric("💵 Payments (sum)", f"${sum(m['payments'].values()):,.2f}")
    col4.metric("🏁 Grand Total", f"${m['grand_total']:,.2f}")

    # Payments pie
    pay_df = pd.DataFrame([{"Method":k, "Amount":v} for k,v in m["payments"].items()])
    fig_pay = px.pie(pay_df, values="Amount", names="Method", title="Payment Methods")
    st.plotly_chart(fig_pay, use_container_width=True)

    # Dept bar
    if not m["dept_df"].empty:
        st.subheader("📂 Sales by Department")
        fig_dept = px.bar(m["dept_df"].sort_values("Sales", ascending=False),
                          x="Department", y="Sales", text="Qty")
        fig_dept.update_layout(xaxis_tickangle=45)
        st.plotly_chart(fig_dept, use_container_width=True)
        st.dataframe(m["dept_df"].sort_values("Sales", ascending=False), use_container_width=True, height=320)

    # --- AI analysis section ---
    st.subheader("🤖 AI Audit & Feedback")
    run_now = st.button(f"Run AI analysis with {model}") or run_auto
    if run_now:
        with st.spinner("Analyzing…"):
            result, usage = analyze_with_ai(text, m, model)
        if isinstance(result, dict) and "error" in result:
            st.error(result["error"])
        else:
            # Show findings
            st.markdown("**Summary**")
            st.write(result.get("summary", "—"))

            issues = result.get("issues", [])
            if issues:
                df_issues = pd.DataFrame(issues)  # expected keys: severity, message, where, numbers
                st.markdown("**Findings**")
                st.dataframe(df_issues, use_container_width=True, height=220)
            else:
                st.success("No issues found by AI.")

            # Cost / tokens
            if usage:
                in_tok  = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)
                st.caption(f"Tokens — input: {in_tok:,}, output: {out_tok:,}, total: {in_tok+out_tok:,}")

                # simple cost estimator for gpt-5 family
                def estimated_cost(model_name, in_t, out_t):
                    if model_name == "gpt-5":
                        return (in_t/1_000_000)*1.25 + (out_t/1_000_000)*10.0
                    if model_name == "gpt-5-mini":
                        return (in_t/1_000_000)*0.25 + (out_t/1_000_000)*2.0
                    return 0.0
                st.caption(f"Estimated cost: ${estimated_cost(model, in_tok, out_tok):.4f}")

    with st.expander("📄 Raw PDF text (debug)"):
        st.text(text[:20000])
else:
    st.info("Upload a Crystal Reports–style EOD PDF to see the dashboard and run the AI audit.")
