import json
import requests
from flask import Flask, jsonify, render_template_string

SUPABASE_URL = "https://basesupabase.jadetrafego.com"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.ewogICJyb2xlIjogInNlcnZpY2Vfcm9sZSIsCiAgImlzcyI6ICJzdXBhYmFzZSIsCiAgImlhdCI6IDE3MTUwNTA4MDAsCiAgImV4cCI6IDE4NzI4MTcyMDAKfQ.blQRQlhMI9Y6f4OtlbiVHoSBt-gJoEM6MPjNrUPpPv0"

app = Flask(__name__)

HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}

SEGMENTOS = [
    {"nome": "Campeão",           "cor": "#F59E0B", "texto": "#fff", "icone": "🏆"},
    {"nome": "Fiel",              "cor": "#10B981", "texto": "#fff", "icone": "💚"},
    {"nome": "Não Pode Perder",   "cor": "#EF4444", "texto": "#fff", "icone": "🚨"},
    {"nome": "Em Risco",          "cor": "#F97316", "texto": "#fff", "icone": "⚠️"},
    {"nome": "Potencial",         "cor": "#3B82F6", "texto": "#fff", "icone": "🌱"},
    {"nome": "Novo Cliente",      "cor": "#8B5CF6", "texto": "#fff", "icone": "✨"},
    {"nome": "Hibernando",        "cor": "#6B7280", "texto": "#fff", "icone": "😴"},
    {"nome": "Em Desenvolvimento","cor": "#D1D5DB", "texto": "#374151", "icone": "📈"},
]

def execute_sql(sql):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/execute_analytics_query",
        headers=HEADERS,
        json={"query_text": sql},
        timeout=30,
    )
    if r.status_code == 200:
        return r.json() or []
    return []


@app.route("/api/resumo")
def api_resumo():
    rows = execute_sql("""
        SELECT segmento,
               COUNT(*)         AS total_clientes,
               SUM(valor_total) AS receita_total
        FROM view_rfv
        GROUP BY segmento
    """)
    by_seg = {r["segmento"]: r for r in rows}
    result = []
    for s in SEGMENTOS:
        info = by_seg.get(s["nome"], {})
        result.append({
            **s,
            "total_clientes": info.get("total_clientes", 0),
            "receita_total":  round(float(info.get("receita_total") or 0), 2),
        })
    return jsonify(result)


@app.route("/api/clientes/<segmento>")
def api_clientes(segmento):
    rows = execute_sql(f"""
        SELECT
            r.customer_name,
            r.customer_email,
            MAX(o.customer_phone)    AS telefone,
            MAX(o.customer_cgc)      AS documento,
            MAX(o.customer_birthday) AS nascimento,
            r.frequencia             AS total_pedidos,
            COALESCE(SUM(oi.item_quantity), 0) AS total_produtos,
            r.valor_total            AS total_gasto
        FROM view_rfv r
        LEFT JOIN view_orders o
               ON o.customer_email = r.customer_email
              AND o.payment_status = 'approved'
              AND o.status != 'canceled'
        LEFT JOIN view_order_items oi
               ON oi.customer_email = r.customer_email
              AND oi.payment_status = 'approved'
              AND oi.status != 'canceled'
        WHERE r.segmento = '{segmento.replace("'", "''")}'
        GROUP BY r.customer_name, r.customer_email, r.frequencia, r.valor_total
        ORDER BY r.valor_total DESC
    """)
    return jsonify(rows or [])


HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Matriz RFV — Pano</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #F3F4F6; color: #111827; min-height: 100vh; padding: 24px; }
  h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 24px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }
  .card { border-radius: 12px; padding: 20px; cursor: pointer;
          transition: transform .15s, box-shadow .15s; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .card:hover { transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,.15); }
  .card.active { outline: 3px solid #1D4ED8; }
  .card .icone { font-size: 1.8rem; margin-bottom: 8px; }
  .card .nome { font-size: .95rem; font-weight: 600; margin-bottom: 10px; }
  .card .stat { font-size: .8rem; opacity: .85; }
  .card .stat span { font-weight: 700; font-size: 1rem; display: block; }
  .tabela-wrap { background: #fff; border-radius: 12px; padding: 24px;
                 box-shadow: 0 1px 3px rgba(0,0,0,.1); overflow-x: auto; }
  .tabela-titulo { font-size: 1.1rem; font-weight: 600; margin-bottom: 16px; }
  table { width: 100%; border-collapse: collapse; font-size: .875rem; }
  th { text-align: left; padding: 10px 12px; background: #F9FAFB;
       border-bottom: 2px solid #E5E7EB; font-weight: 600; color: #6B7280; }
  td { padding: 10px 12px; border-bottom: 1px solid #F3F4F6; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #F9FAFB; }
  .loading { color: #6B7280; font-style: italic; }
  .vazio { color: #9CA3AF; padding: 24px 0; text-align: center; }
  .moeda::before { content: "R$ "; }
</style>
</head>
<body>
<h1>📊 Matriz RFV — Pano Ecommerce</h1>
<div class="grid" id="grid"></div>
<div class="tabela-wrap" id="tabela-wrap" style="display:none">
  <div class="tabela-titulo" id="tabela-titulo"></div>
  <div id="tabela-conteudo"></div>
</div>

<script>
let segmentoAtivo = null;

async function carregarResumo() {
  const res = await fetch('/api/resumo');
  const data = await res.json();
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  data.forEach(s => {
    const card = document.createElement('div');
    card.className = 'card';
    card.style.background = s.cor;
    card.style.color = s.texto;
    card.innerHTML = `
      <div class="icone">${s.icone}</div>
      <div class="nome">${s.nome}</div>
      <div class="stat">Clientes<span>${s.total_clientes}</span></div>
      <div class="stat" style="margin-top:8px">Receita<span>R$ ${s.receita_total.toLocaleString('pt-BR',{minimumFractionDigits:2})}</span></div>
    `;
    card.addEventListener('click', () => abrirSegmento(s.nome, card));
    grid.appendChild(card);
  });
}

async function abrirSegmento(nome, card) {
  document.querySelectorAll('.card').forEach(c => c.classList.remove('active'));
  card.classList.add('active');
  segmentoAtivo = nome;

  const wrap = document.getElementById('tabela-wrap');
  const titulo = document.getElementById('tabela-titulo');
  const conteudo = document.getElementById('tabela-conteudo');

  wrap.style.display = 'block';
  titulo.textContent = `Clientes — ${nome}`;
  conteudo.innerHTML = '<p class="loading">Carregando...</p>';
  wrap.scrollIntoView({behavior: 'smooth', block: 'start'});

  const res = await fetch('/api/clientes/' + encodeURIComponent(nome));
  const clientes = await res.json();

  if (!clientes.length) {
    conteudo.innerHTML = '<p class="vazio">Nenhum cliente neste segmento.</p>';
    return;
  }

  const tabela = `
    <table>
      <thead>
        <tr>
          <th>Nome</th>
          <th>Telefone</th>
          <th>Documento</th>
          <th>Email</th>
          <th>Nascimento</th>
          <th>Pedidos</th>
          <th>Produtos</th>
          <th>Total Gasto</th>
        </tr>
      </thead>
      <tbody>
        ${clientes.map(c => `
          <tr>
            <td>${c.customer_name || '—'}</td>
            <td>${c.telefone || '—'}</td>
            <td>${c.documento || '—'}</td>
            <td>${c.customer_email || '—'}</td>
            <td>${c.nascimento ? c.nascimento.substring(0,10) : '—'}</td>
            <td>${c.total_pedidos}</td>
            <td>${c.total_produtos}</td>
            <td class="moeda">${parseFloat(c.total_gasto).toLocaleString('pt-BR',{minimumFractionDigits:2})}</td>
          </tr>`).join('')}
      </tbody>
    </table>`;
  conteudo.innerHTML = tabela;
}

carregarResumo();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
