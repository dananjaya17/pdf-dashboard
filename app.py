import streamlit as st
import pdfplumber
import re
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="EOD PDF Dashboard", layout="wide")

st.title("📊 EOD Report Dashboard")

uploaded_file = st.file_uploader("Upload EOD PDF", type=["pdf"])

if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        text = ""
        for page in pdf.pages:
            text += page.extract_text() + "\n"

    # --- Extract Total Sales ---
    total_sales = re.search(r"Merchandise Sales\s+([\d\.]+)", text)
    tax = re.search(r"Tax A\s+([\d\.]+)", text)
    grand_total = re.search(r"Total\s+([\d\.]+)", text)

    total_sales = float(total_sales.group(1)) if total_sales else 0
    tax = float(tax.group(1)) if tax else 0
    grand_total = float(grand_total.group(1)) if grand_total else 0

    st.metric("🛒 Total Sales", f"${total_sales:,.2f}")
    st.metric("💰 Tax Collected", f"${tax:,.2f}")
    st.metric("📦 Grand Total", f"${grand_total:,.2f}")

    # --- Extract Payments ---
    payments = re.findall(r"(Cash|AmEx|Visa|Master|Other|Discover):\s*([\d\.]+)", text)
    if payments:
        df_payments = pd.DataFrame(payments, columns=["Method", "Amount"])
        df_payments["Amount"] = df_payments["Amount"].astype(float)

        fig = px.pie(df_payments, values="Amount", names="Method", title="Payment Methods")
        st.plotly_chart(fig, use_container_width=True)

    # --- Extract Department Sales ---
    dept_pattern = r"([A-Z\-\&\s']+)\s+(\d+)\s+([\d\.]+)"
    departments = re.findall(dept_pattern, text)

    if departments:
        df_dept = pd.DataFrame(departments, columns=["Department", "Qty", "Sales"])
        df_dept["Qty"] = df_dept["Qty"].astype(int)
        df_dept["Sales"] = df_dept["Sales"].astype(float)

        st.subheader("📂 Sales by Department")
        fig = px.bar(df_dept, x="Department", y="Sales", text="Qty", title="Sales by Department")
        fig.update_layout(xaxis_tickangle=45)
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(df_dept)

    # --- Extract Hourly Activity ---
    hour_pattern = r"(\d{1,2}[ap]m - \d{1,2}[ap]m)\s+([\d\.]+)"
    hours = re.findall(hour_pattern, text)

    if hours:
        df_hours = pd.DataFrame(hours, columns=["Hour", "Sales"])
        df_hours["Sales"] = df_hours["Sales"].astype(float)

        st.subheader("🕒 Sales by Hour")
        fig = px.line(df_hours, x="Hour", y="Sales", markers=True, title="Hourly Sales")
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(df_hours)

    # Debug text (optional)
    with st.expander("📄 Raw PDF Text"):
        st.text(text)
