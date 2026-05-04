import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

SUPABASE_URL = "https://basesupabase.jadetrafego.com"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.ewogICJyb2xlIjogInNlcnZpY2Vfcm9sZSIsCiAgImlzcyI6ICJzdXBhYmFzZSIsCiAgImlhdCI6IDE3MTUwNTA4MDAsCiAgImV4cCI6IDE4NzI4MTcyMDAKfQ.blQRQlhMI9Y6f4OtlbiVHoSBt-gJoEM6MPjNrUPpPv0"

HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}

SEGMENTOS = [
    {"nome": "Campeão",            "cor": "#F59E0B", "icone": "🏆"},
    {"nome": "Fiel",               "cor": "#10B981", "icone": "💚"},
    {"nome": "Não Pode Perder",    "cor": "#EF4444", "icone": "🚨"},
    {"nome": "Em Risco",           "cor": "#F97316", "icone": "⚠️"},
    {"nome": "Potencial",          "cor": "#3B82F6", "icone": "🌱"},
    {"nome": "Novo Cliente",       "cor": "#8B5CF6", "icone": "✨"},
    {"nome": "Hibernando",         "cor": "#6B7280", "icone": "😴"},
    {"nome": "Em Desenvolvimento", "cor": "#D1D5DB", "icone": "📈"},
]
SEG_MAP = {s["nome"]: s for s in SEGMENTOS}


def brl(v):
    return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def num(v):
    return f"{int(v):,}".replace(",", ".")


def execute_sql(sql):
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/execute_analytics_query",
            headers=HEADERS,
            json={"query_text": sql.strip()},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json() or []
        return []
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_resumo():
    rows = execute_sql("""
        SELECT segmento,
               COUNT(*)         AS total_clientes,
               SUM(valor_total) AS receita_total
        FROM view_rfv
        GROUP BY segmento
    """)
    return {r["segmento"]: r for r in rows}


@st.cache_data(ttl=300)
def load_criterios():
    rows = execute_sql("""
        SELECT
            segmento,
            MIN(dias_recencia) AS min_recencia,
            MAX(dias_recencia) AS max_recencia,
            AVG(dias_recencia) AS avg_recencia,
            MIN(frequencia)    AS min_freq,
            MAX(frequencia)    AS max_freq,
            AVG(frequencia)    AS avg_freq,
            MIN(valor_total)   AS min_valor,
            MAX(valor_total)   AS max_valor,
            AVG(valor_total)   AS avg_valor
        FROM view_rfv
        GROUP BY segmento
    """)
    return {r["segmento"]: r for r in rows}


@st.cache_data(ttl=300)
def load_clientes(segmento: str) -> pd.DataFrame:
    seg = segmento.replace("'", "''")
    rows = execute_sql(f"""
        SELECT
            r.customer_name,
            r.customer_email,
            COUNT(DISTINCT CASE
                WHEN o.payment_status = 'approved' AND o.status != 'canceled'
                THEN o.id END)                                AS total_pedidos,
            SUM(CASE
                WHEN o.payment_status = 'approved' AND o.status != 'canceled'
                THEN o.total ELSE 0 END)                     AS total_gasto,
            MAX(o.customer_phone)                            AS telefone,
            MAX(o.customer_cgc)                              AS documento,
            MAX(o.customer_birthday)                         AS nascimento
        FROM view_rfv r
        LEFT JOIN view_orders o ON o.customer_email = r.customer_email
        WHERE r.segmento = '{seg}'
        GROUP BY r.customer_name, r.customer_email
        ORDER BY total_gasto DESC
    """)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["nascimento"] = df["nascimento"].astype(str).str[:10].replace("None", "").replace("nan", "")
    df = df.rename(columns={
        "customer_name":  "Nome",
        "customer_email": "Email",
        "total_pedidos":  "Pedidos",
        "total_gasto":    "Total Gasto (R$)",
        "telefone":       "Telefone",
        "documento":      "CPF/CNPJ",
        "nascimento":     "Nascimento",
    })
    df["Total Gasto (R$)"] = df["Total Gasto (R$)"].apply(lambda v: round(float(v), 2))
    return df


def build_treemap(resumo, criterios):
    labels, parents, values, colors, customdata = [], [], [], [], []

    for s in SEGMENTOS:
        nome = s["nome"]
        info = resumo.get(nome, {})
        total = int(info.get("total_clientes") or 0)
        receita = float(info.get("receita_total") or 0)
        crit = criterios.get(nome, {})

        tooltip = f"<b>{s['icone']} {nome}</b><br>"
        tooltip += f"👥 {num(total)} clientes<br>"
        tooltip += f"💰 {brl(receita)}<br>"
        if crit:
            min_r = round(float(crit.get("min_recencia") or 0))
            max_r = round(float(crit.get("max_recencia") or 0))
            min_f = int(crit.get("min_freq") or 0)
            max_f = int(crit.get("max_freq") or 0)
            min_v = float(crit.get("min_valor") or 0)
            max_v = float(crit.get("max_valor") or 0)
            tooltip += f"📅 Recência: {min_r}–{max_r} dias<br>"
            tooltip += f"🛒 Pedidos: {min_f}–{max_f}<br>"
            tooltip += f"💵 Gasto: {brl(min_v)} – {brl(max_v)}"

        label_text = f"{s['icone']} {nome}<br><b>{num(total)}</b><br>{brl(receita)}"

        labels.append(nome)
        parents.append("")
        values.append(max(total, 1))
        colors.append(s["cor"])
        customdata.append(tooltip)

    fig = go.Figure(go.Treemap(
        labels=labels,
        parents=parents,
        values=values,
        text=labels,
        customdata=customdata,
        hovertemplate="%{customdata}<extra></extra>",
        texttemplate=[
            f"{SEG_MAP[l]['icone']} {l}<br><b>{num(int(resumo.get(l, {}).get('total_clientes') or 0))}</b><br>"
            + brl(float(resumo.get(l, {}).get('receita_total') or 0))
            for l in labels
        ],
        marker=dict(
            colors=colors,
            line=dict(width=2, color="#ffffff"),
        ),
        textfont=dict(size=13),
        pathbar_visible=False,
        tiling=dict(packing="squarify", pad=4),
    ))
    fig.update_layout(
        margin=dict(t=0, b=0, l=0, r=0),
        height=440,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ── App ──────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Matriz RFV — Pano", page_icon="📊", layout="wide")

st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #F3F4F6; }
  [data-testid="stHeader"] { background: transparent; }
  h1 { font-size: 1.6rem !important; margin-bottom: 0 !important; }
  .stMetric { background: #fff; border-radius: 10px; padding: 12px 16px; }
  div[data-testid="metric-container"] { background: #fff; border-radius: 10px; padding: 12px 16px; }
</style>
""", unsafe_allow_html=True)

st.title("📊 Matriz RFV — Pano Ecommerce")
st.caption("Passe o mouse sobre os segmentos para ver os critérios. Selecione um segmento para ver os clientes.")

with st.spinner("Carregando segmentos..."):
    resumo = load_resumo()
    criterios = load_criterios()

if not resumo:
    st.error("Não foi possível carregar os dados. Verifique a conexão com o Supabase.")
    st.stop()

st.plotly_chart(build_treemap(resumo, criterios), use_container_width=True)

st.divider()

col_sel, col_total = st.columns([3, 1])
with col_sel:
    nomes_disp = [s["nome"] for s in SEGMENTOS if s["nome"] in resumo]
    sel = st.selectbox(
        "Segmento",
        options=[""] + nomes_disp,
        format_func=lambda x: f"{SEG_MAP[x]['icone']} {x}" if x else "— selecione um segmento para ver os clientes —",
        label_visibility="collapsed",
    )

if not sel:
    totais = sum(int(v.get("total_clientes") or 0) for v in resumo.values())
    receita_total = sum(float(v.get("receita_total") or 0) for v in resumo.values())
    with col_total:
        st.metric("Total de clientes", num(totais))
    st.stop()

info = resumo.get(sel, {})
crit = criterios.get(sel, {})
seg  = SEG_MAP[sel]

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Clientes", num(int(info.get("total_clientes") or 0)))
with m2:
    st.metric("Receita total", brl(info.get("receita_total") or 0))
with m3:
    if crit:
        avg_r = round(float(crit.get("avg_recencia") or 0))
        st.metric("Recência média", f"{avg_r} dias")
with m4:
    if crit:
        avg_f = float(crit.get("avg_freq") or 0)
        st.metric("Pedidos médios", f"{avg_f:.1f}")

if crit:
    with st.expander("📋 Critérios do segmento", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            min_r = round(float(crit.get("min_recencia") or 0))
            max_r = round(float(crit.get("max_recencia") or 0))
            avg_r = round(float(crit.get("avg_recencia") or 0))
            st.write(f"**📅 Recência**  \n{min_r} – {max_r} dias  \nmédia: {avg_r} dias")
        with c2:
            min_f = int(crit.get("min_freq") or 0)
            max_f = int(crit.get("max_freq") or 0)
            avg_f = float(crit.get("avg_freq") or 0)
            st.write(f"**🛒 Pedidos aprovados**  \n{min_f} – {max_f}  \nmédia: {avg_f:.1f}")
        with c3:
            min_v = float(crit.get("min_valor") or 0)
            max_v = float(crit.get("max_valor") or 0)
            avg_v = float(crit.get("avg_valor") or 0)
            st.write(f"**💰 Gasto total**  \n{brl(min_v)} – {brl(max_v)}  \nmédia: {brl(avg_v)}")

st.subheader(f"{seg['icone']} Clientes — {sel}")

with st.spinner("Carregando clientes..."):
    df = load_clientes(sel)

if df.empty:
    st.info("Nenhum cliente encontrado neste segmento.")
    st.stop()

st.caption(f"{len(df)} clientes (ordenados por maior gasto)")

col_table, _ = st.columns([1, 0.001])
with col_table:
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Pedidos":         st.column_config.NumberColumn(format="%d"),
            "Total Gasto (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )

csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
st.download_button(
    label="⬇️ Exportar CSV",
    data=csv_bytes,
    file_name=f"clientes_{sel.replace(' ', '_')}.csv",
    mime="text/csv",
)
