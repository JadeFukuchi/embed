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

# row/col: position in 3x3 RFV matrix
# row 1 = top (alta recência), row 3 = bottom (baixa recência)
# col 1 = left (baixa freq/valor), col 3 = right (alta freq/valor)
SEGMENTOS = [
    {
        "nome": "Campeão",
        "cor": "#F59E0B", "texto": "#fff", "icone": "🏆",
        "row": 1, "col": 3,
        "tooltip": "Compraram recentemente, com alta frequência e alto valor. São seus melhores clientes — recompense e peça indicações.",
    },
    {
        "nome": "Fiel",
        "cor": "#10B981", "texto": "#fff", "icone": "💚",
        "row": 2, "col": 3,
        "tooltip": "Compram com regularidade e bom valor. Ofereça programas de fidelidade e upsells para elevá-los a Campeão.",
    },
    {
        "nome": "Não Pode Perder",
        "cor": "#EF4444", "texto": "#fff", "icone": "🚨",
        "row": 3, "col": 3,
        "tooltip": "Alto valor histórico, mas não compram há muito tempo. Prioridade máxima: reative com ofertas exclusivas ou contato direto.",
    },
    {
        "nome": "Em Risco",
        "cor": "#F97316", "texto": "#fff", "icone": "⚠️",
        "row": 3, "col": 2,
        "tooltip": "Compravam com frequência mas sumiram. Envie ofertas personalizadas ou pesquise o motivo do afastamento.",
    },
    {
        "nome": "Potencial",
        "cor": "#3B82F6", "texto": "#fff", "icone": "🌱",
        "row": 1, "col": 2,
        "tooltip": "Clientes recentes com potencial crescente. Com o incentivo certo evoluem para Fiel ou Campeão.",
    },
    {
        "nome": "Novo Cliente",
        "cor": "#8B5CF6", "texto": "#fff", "icone": "✨",
        "row": 1, "col": 1,
        "tooltip": "Compraram pela primeira vez recentemente. Foque em onboarding e segunda compra para fidelizá-los.",
    },
    {
        "nome": "Hibernando",
        "cor": "#6B7280", "texto": "#fff", "icone": "😴",
        "row": 3, "col": 1,
        "tooltip": "Compraram pouco e há muito tempo. Precisam de uma oferta agressiva ou campanha de reativação para voltar.",
    },
    {
        "nome": "Em Desenvolvimento",
        "cor": "#D1D5DB", "texto": "#374151", "icone": "📈",
        "row": 2, "col": 2,
        "tooltip": "Padrão médio em recência, frequência e valor. Acompanhe e incentive compras para acelerar a evolução.",
    },
]


def execute_sql(sql):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/execute_analytics_query",
        headers=HEADERS,
        json={"query_text": sql.strip()},
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
    seg = segmento.replace("'", "''")
    rows = execute_sql(f"""
        SELECT
            r.customer_name,
            r.customer_email,
            r.frequencia             AS total_pedidos,
            r.valor_total            AS total_gasto,
            MAX(o.customer_phone)    AS telefone,
            MAX(o.customer_cgc)      AS documento,
            MAX(o.customer_birthday) AS nascimento
        FROM (
            SELECT customer_name, customer_email, frequencia, valor_total
            FROM view_rfv
            WHERE segmento = '{seg}'
            ORDER BY valor_total DESC
            LIMIT 300
        ) r
        LEFT JOIN view_orders o ON o.customer_email = r.customer_email
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
  h1  { font-size: 1.5rem; font-weight: 700; margin-bottom: 4px; }
  .sub { color: #6B7280; font-size: .85rem; margin-bottom: 28px; }

  /* ---- Matrix layout ---- */
  .matrix-outer { display: flex; gap: 10px; align-items: stretch; margin-bottom: 32px; }

  .y-axis {
    display: flex; flex-direction: column;
    align-items: center; justify-content: space-between;
    padding: 4px 0; min-width: 32px;
  }
  .y-axis span { font-size: .65rem; color: #9CA3AF; }
  .y-axis .lbl {
    writing-mode: vertical-rl; transform: rotate(180deg);
    font-size: .7rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 1px; color: #6B7280;
  }

  .matrix-col { flex: 1; }

  .matrix {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    grid-template-rows: repeat(3, 155px);
    gap: 8px;
  }

  .x-axis {
    display: flex; justify-content: space-between;
    font-size: .65rem; color: #9CA3AF; margin-top: 6px; padding: 0 2px;
  }
  .x-lbl {
    text-align: center; font-size: .7rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px; color: #6B7280; margin-top: 2px;
  }

  /* ---- Cards ---- */
  .card {
    border-radius: 10px; padding: 14px 12px; cursor: pointer;
    transition: transform .15s, box-shadow .15s;
    box-shadow: 0 1px 4px rgba(0,0,0,.12);
    position: relative; display: flex; flex-direction: column;
    justify-content: space-between; overflow: visible; z-index: 1;
  }
  .card:hover { transform: translateY(-3px); box-shadow: 0 6px 20px rgba(0,0,0,.2); z-index: 10; }
  .card.active { outline: 3px solid #1D4ED8; outline-offset: 2px; }
  .card-empty { background: #F9FAFB; border: 2px dashed #E5E7EB; border-radius: 10px; }
  .card .icone { font-size: 1.4rem; }
  .card .nome  { font-size: .8rem; font-weight: 700; margin: 4px 0 10px; line-height: 1.2; }
  .card .stat  { font-size: .68rem; opacity: .9; }
  .card .stat b { font-size: .82rem; display: block; font-weight: 700; }

  /* ---- Tooltip ---- */
  .tip {
    display: none; position: absolute;
    bottom: calc(100% + 10px); left: 50%; transform: translateX(-50%);
    background: #111827; color: #F9FAFB;
    font-size: .72rem; line-height: 1.5; font-weight: 400;
    padding: 9px 13px; border-radius: 8px; width: 210px;
    text-align: center; z-index: 300;
    box-shadow: 0 4px 16px rgba(0,0,0,.3);
    pointer-events: none; white-space: normal;
  }
  .tip::after {
    content: ''; position: absolute;
    top: 100%; left: 50%; transform: translateX(-50%);
    border: 7px solid transparent; border-top-color: #111827;
  }
  .card:hover .tip { display: block; }

  /* ---- Table ---- */
  .tabela-wrap { background: #fff; border-radius: 12px; padding: 24px;
                 box-shadow: 0 1px 3px rgba(0,0,0,.1); overflow-x: auto; }
  .tabela-titulo { font-size: 1.1rem; font-weight: 600; margin-bottom: 16px; }
  table { width: 100%; border-collapse: collapse; font-size: .875rem; }
  th { text-align: left; padding: 10px 12px; background: #F9FAFB;
       border-bottom: 2px solid #E5E7EB; font-weight: 600; color: #6B7280; white-space: nowrap; }
  td { padding: 10px 12px; border-bottom: 1px solid #F3F4F6; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #F9FAFB; }
  .loading { color: #6B7280; font-style: italic; }
  .vazio { color: #9CA3AF; padding: 24px 0; text-align: center; }
</style>
</head>
<body>
<h1>📊 Matriz RFV — Pano Ecommerce</h1>
<p class="sub">Passe o mouse sobre um segmento para ver sua descrição. Clique para ver os clientes.</p>

<div class="matrix-outer">
  <div class="y-axis">
    <span>Alta ↑</span>
    <span class="lbl">Recência</span>
    <span>↓ Baixa</span>
  </div>
  <div class="matrix-col">
    <div class="matrix" id="matrix"></div>
    <div class="x-axis">
      <span>← Freq/Valor baixo</span>
      <span>Freq/Valor alto →</span>
    </div>
    <div class="x-lbl">Frequência / Valor</div>
  </div>
</div>

<div class="tabela-wrap" id="tabela-wrap" style="display:none">
  <div class="tabela-titulo" id="tabela-titulo"></div>
  <div id="tabela-conteudo"></div>
</div>

<script>
let segmentoAtivo = null;

async function carregarResumo() {
  const res = await fetch('/api/resumo');
  const data = await res.json();
  const matrix = document.getElementById('matrix');
  matrix.innerHTML = '';

  const byPos = {};
  data.forEach(s => { byPos[s.row + '-' + s.col] = s; });

  for (let row = 1; row <= 3; row++) {
    for (let col = 1; col <= 3; col++) {
      const s = byPos[row + '-' + col];
      if (s) {
        const card = document.createElement('div');
        card.className = 'card';
        card.style.background = s.cor;
        card.style.color = s.texto;
        card.style.gridRow = row;
        card.style.gridColumn = col;
        card.innerHTML =
          '<div class="tip">' + s.tooltip + '</div>' +
          '<div><div class="icone">' + s.icone + '</div>' +
          '<div class="nome">' + s.nome + '</div></div>' +
          '<div>' +
          '<div class="stat">Clientes<b>' + s.total_clientes.toLocaleString('pt-BR') + '</b></div>' +
          '<div class="stat" style="margin-top:3px">Receita<b>R$ ' +
          s.receita_total.toLocaleString('pt-BR', {minimumFractionDigits:2}) + '</b></div>' +
          '</div>';
        card.addEventListener('click', () => abrirSegmento(s.nome, card));
        matrix.appendChild(card);
      } else {
        const empty = document.createElement('div');
        empty.className = 'card-empty';
        empty.style.gridRow = row;
        empty.style.gridColumn = col;
        matrix.appendChild(empty);
      }
    }
  }
}

async function abrirSegmento(nome, card) {
  document.querySelectorAll('.card').forEach(c => c.classList.remove('active'));
  card.classList.add('active');
  segmentoAtivo = nome;

  const wrap = document.getElementById('tabela-wrap');
  const titulo = document.getElementById('tabela-titulo');
  const conteudo = document.getElementById('tabela-conteudo');

  wrap.style.display = 'block';
  titulo.textContent = 'Clientes — ' + nome;
  conteudo.innerHTML = '<p class="loading">Carregando...</p>';
  wrap.scrollIntoView({behavior: 'smooth', block: 'start'});

  const res = await fetch('/api/clientes/' + encodeURIComponent(nome));
  const clientes = await res.json();

  if (!clientes.length) {
    conteudo.innerHTML = '<p class="vazio">Nenhum cliente neste segmento.</p>';
    return;
  }

  let rows = '';
  clientes.forEach(c => {
    rows += '<tr>' +
      '<td>' + (c.customer_name || '—') + '</td>' +
      '<td>' + (c.customer_email || '—') + '</td>' +
      '<td>' + (c.telefone || '—') + '</td>' +
      '<td>' + (c.documento || '—') + '</td>' +
      '<td>' + (c.nascimento ? c.nascimento.substring(0,10) : '—') + '</td>' +
      '<td>' + c.total_pedidos + '</td>' +
      '<td>R$ ' + parseFloat(c.total_gasto).toLocaleString('pt-BR',{minimumFractionDigits:2}) + '</td>' +
      '</tr>';
  });

  conteudo.innerHTML =
    '<table><thead><tr>' +
    '<th>Nome</th><th>Email</th><th>Telefone</th>' +
    '<th>Documento</th><th>Nascimento</th><th>Pedidos</th><th>Total Gasto</th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table>';
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
