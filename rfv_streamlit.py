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
def load_resumo(view: str = "view_rfv"):
    rows = execute_sql(f"""
        SELECT segmento,
               COUNT(*)         AS total_clientes,
               SUM(valor_total) AS receita_total
        FROM {view}
        GROUP BY segmento
    """)
    return {r["segmento"]: r for r in rows}


@st.cache_data(ttl=300)
def load_criterios(view: str = "view_rfv"):
    rows = execute_sql(f"""
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
        FROM {view}
        GROUP BY segmento
    """)
    return {r["segmento"]: r for r in rows}


@st.cache_data(ttl=300)
def load_clientes(segmento: str, view: str = "view_rfv") -> pd.DataFrame:
    seg = segmento.replace("'", "''")

    # Query 1: agrupa por cliente (view_rfv tem 1 linha por pedido)
    # COUNT(*) = nº de pedidos no segmento, igual ao que o agente conta
    rfv_rows = execute_sql(f"""
        SELECT
            customer_name,
            customer_email,
            COUNT(*)           AS pedidos_segmento,
            MAX(rfv_score)     AS rfv_score,
            MIN(dias_recencia) AS dias_recencia,
            MAX(ultima_compra) AS ultima_compra
        FROM {view}
        WHERE segmento = '{seg}'
        GROUP BY customer_name, customer_email
        ORDER BY pedidos_segmento DESC, rfv_score DESC
        LIMIT 500
    """)
    if not rfv_rows:
        return pd.DataFrame()

    emails = list({r["customer_email"] for r in rfv_rows if r.get("customer_email")})
    escaped = "','".join(e.replace("'", "''") for e in emails)

    # Query 2: pedidos reais e gasto real para esses emails específicos
    order_rows = execute_sql(f"""
        SELECT
            customer_email,
            COUNT(DISTINCT id)     AS total_pedidos,
            SUM(total)             AS total_gasto,
            MAX(customer_phone)    AS telefone,
            MAX(customer_cgc)      AS documento,
            MAX(customer_birthday) AS nascimento
        FROM view_orders
        WHERE payment_status = 'approved'
          AND status != 'canceled'
          AND customer_email IN ('{escaped}')
        GROUP BY customer_email
    """)
    order_map = {r["customer_email"]: r for r in (order_rows or [])}

    records = []
    for r in rfv_rows:
        email = r.get("customer_email", "")
        o = order_map.get(email, {})
        records.append({
            "Nome":             r.get("customer_name", ""),
            "Email":            email,
            "Score RFV":        round(float(r.get("rfv_score") or 0), 1),
            "Pedidos":          int(r.get("pedidos_segmento") or 0),
            "Total Gasto (R$)": round(float(o.get("total_gasto") or 0), 2),
            "Recência (dias)":  int(r.get("dias_recencia") or 0),
            "Última Compra":    str(r.get("ultima_compra") or "")[:10],
            "Telefone":         str(o.get("telefone") or ""),
            "CPF/CNPJ":         str(o.get("documento") or ""),
            "Nascimento":       str(o.get("nascimento") or "")[:10],
        })

    return pd.DataFrame(records)


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

col_title, col_view = st.columns([3, 1])
with col_view:
    view_opcao = st.radio(
        "Metodologia RFV",
        options=["Histórica (percentis)", "Absoluta (critérios fixos)"],
        index=0,
        horizontal=False,
    )
view_selecionada = "view_rfv" if "Histórica" in view_opcao else "view_rfv_absoluta"
st.caption(f"Passe o mouse sobre os segmentos para ver os critérios. Selecione um segmento para ver os clientes. | View: `{view_selecionada}`")

with st.spinner("Carregando segmentos..."):
    resumo = load_resumo(view_selecionada)
    criterios = load_criterios(view_selecionada)

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
    df = load_clientes(sel, view_selecionada)

if df.empty:
    st.info("Nenhum cliente encontrado neste segmento.")
    st.stop()

st.caption(f"{len(df)} clientes (ordenados por Score RFV)")

cols_order = ["Nome", "Email", "Score RFV", "Pedidos", "Total Gasto (R$)",
              "Recência (dias)", "Última Compra", "Telefone", "CPF/CNPJ", "Nascimento"]
cols_show = [c for c in cols_order if c in df.columns]

col_table, _ = st.columns([1, 0.001])
with col_table:
    st.dataframe(
        df[cols_show],
        width="stretch",
        hide_index=True,
        column_config={
            "Pedidos":          st.column_config.NumberColumn(format="%d"),
            "Total Gasto (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
            "Score RFV":        st.column_config.NumberColumn(format="%.1f"),
            "Recência (dias)":  st.column_config.NumberColumn(format="%d"),
        },
    )

csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
st.download_button(
    label="⬇️ Exportar CSV",
    data=csv_bytes,
    file_name=f"clientes_{sel.replace(' ', '_')}.csv",
    mime="text/csv",
)
