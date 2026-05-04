import requests
from flask import Flask, jsonify

SUPABASE_URL = "https://basesupabase.jadetrafego.com"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.ewogICJyb2xlIjogInNlcnZpY2Vfcm9sZSIsCiAgImlzcyI6ICJzdXBhYmFzZSIsCiAgImlhdCI6IDE3MTUwNTA4MDAsCiAgImV4cCI6IDE4NzI4MTcyMDAKfQ.blQRQlhMI9Y6f4OtlbiVHoSBt-gJoEM6MPjNrUPpPv0"

app = Flask(__name__)

HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}

# row 1 = high recency (top), row 3 = low recency (bottom)
# col 1 = low F/V (left),    col 3 = high F/V (right)
SEGMENTOS = [
    {"nome": "Campeão",            "cor": "#F59E0B", "texto": "#fff",    "icone": "🏆", "row": 1, "col": 3},
    {"nome": "Fiel",               "cor": "#10B981", "texto": "#fff",    "icone": "💚", "row": 2, "col": 3},
    {"nome": "Não Pode Perder",    "cor": "#EF4444", "texto": "#fff",    "icone": "🚨", "row": 3, "col": 3},
    {"nome": "Em Risco",           "cor": "#F97316", "texto": "#fff",    "icone": "⚠️", "row": 3, "col": 2},
    {"nome": "Potencial",          "cor": "#3B82F6", "texto": "#fff",    "icone": "🌱", "row": 1, "col": 2},
    {"nome": "Novo Cliente",       "cor": "#8B5CF6", "texto": "#fff",    "icone": "✨", "row": 1, "col": 1},
    {"nome": "Hibernando",         "cor": "#6B7280", "texto": "#fff",    "icone": "😴", "row": 3, "col": 1},
    {"nome": "Em Desenvolvimento", "cor": "#D1D5DB", "texto": "#374151", "icone": "📈", "row": 2, "col": 2},
]


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


@app.route("/api/criterios")
def api_criterios():
    rows = execute_sql("""
        SELECT
            segmento,
            MIN(recencia_dias)  AS min_recencia,
            MAX(recencia_dias)  AS max_recencia,
            AVG(recencia_dias)  AS avg_recencia,
            MIN(frequencia)     AS min_freq,
            MAX(frequencia)     AS max_freq,
            AVG(frequencia)     AS avg_freq,
            MIN(valor_total)    AS min_valor,
            MAX(valor_total)    AS max_valor,
            AVG(valor_total)    AS avg_valor
        FROM view_rfv
        GROUP BY segmento
    """)
    return jsonify(rows or [])


HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Matriz RFV — Pano</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #F3F4F6; color: #111827; min-height: 100vh; padding: 24px; }
  h1   { font-size: 1.5rem; font-weight: 700; margin-bottom: 4px; }
  .sub { color: #6B7280; font-size: .85rem; margin-bottom: 28px; }

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
    grid-template-rows: repeat(3, 1fr);
    gap: 8px;
    height: 480px;
  }

  .x-axis {
    display: flex; justify-content: space-between;
    font-size: .65rem; color: #9CA3AF; margin-top: 6px; padding: 0 2px;
  }
  .x-lbl {
    text-align: center; font-size: .7rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px; color: #6B7280; margin-top: 2px;
  }

  .card {
    border-radius: 10px; padding: 12px; cursor: pointer;
    transition: transform .15s, box-shadow .15s;
    box-shadow: 0 1px 4px rgba(0,0,0,.12);
    position: relative; display: flex; flex-direction: column;
    justify-content: space-between; overflow: hidden; z-index: 1;
    height: 100%; min-height: 0;
  }
  .card:hover { transform: translateY(-3px); box-shadow: 0 6px 20px rgba(0,0,0,.2);
                z-index: 10; overflow: visible; }
  .card.active { outline: 3px solid #1D4ED8; outline-offset: 2px; }
  .card-empty  { background: #F9FAFB; border: 2px dashed #E5E7EB; border-radius: 10px; }
  .card .icone { font-size: 1.3rem; line-height: 1; }
  .card .nome  { font-size: .78rem; font-weight: 700; margin: 3px 0 8px; line-height: 1.2; }
  .card .stat  { font-size: .65rem; opacity: .9; }
  .card .stat b { font-size: .78rem; display: block; font-weight: 700; }

  .tip {
    display: none; position: absolute;
    bottom: calc(100% + 10px); left: 50%; transform: translateX(-50%);
    background: #111827; color: #F9FAFB;
    font-size: .72rem; line-height: 1.7; font-weight: 400;
    padding: 10px 14px; border-radius: 8px; width: 250px;
    text-align: left; z-index: 400;
    box-shadow: 0 4px 16px rgba(0,0,0,.35);
    pointer-events: none; white-space: normal;
  }
  .tip strong { display: block; font-size: .78rem; margin-bottom: 6px;
                border-bottom: 1px solid rgba(255,255,255,.2); padding-bottom: 5px; }
  .tip::after {
    content: ''; position: absolute;
    top: 100%; left: 50%; transform: translateX(-50%);
    border: 7px solid transparent; border-top-color: #111827;
  }
  .card:hover .tip { display: block; }

  .tabela-wrap { background: #fff; border-radius: 12px; padding: 24px;
                 box-shadow: 0 1px 3px rgba(0,0,0,.1); overflow-x: auto; }
  .tabela-header { display: flex; align-items: center;
                   justify-content: space-between; margin-bottom: 16px; }
  .tabela-titulo { font-size: 1.1rem; font-weight: 600; }
  .btn-export {
    background: #1D4ED8; color: #fff; border: none; border-radius: 6px;
    padding: 8px 18px; font-size: .82rem; font-weight: 600;
    cursor: pointer; transition: background .15s; white-space: nowrap;
  }
  .btn-export:hover { background: #1E40AF; }
  table { width: 100%; border-collapse: collapse; font-size: .875rem; }
  th {
    text-align: left; padding: 10px 12px; background: #F9FAFB;
    border-bottom: 2px solid #E5E7EB; font-weight: 600; color: #6B7280;
    white-space: nowrap; user-select: none;
  }
  th.sortable { cursor: pointer; }
  th.sortable:hover { background: #F3F4F6; color: #374151; }
  th.sorted { color: #1D4ED8; }
  td { padding: 10px 12px; border-bottom: 1px solid #F3F4F6; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #F9FAFB; }
  .loading { color: #6B7280; font-style: italic; }
  .vazio { color: #9CA3AF; padding: 24px 0; text-align: center; }
</style>
</head>
<body>
<h1>📊 Matriz RFV — Pano Ecommerce</h1>
<p class="sub">Passe o mouse sobre um segmento para ver os critérios reais. Clique para ver os clientes.</p>

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
  <div class="tabela-header">
    <div class="tabela-titulo" id="tabela-titulo"></div>
    <button class="btn-export" onclick="exportCSV()">&#11015; Exportar CSV</button>
  </div>
  <div id="tabela-conteudo"></div>
</div>

<script>
var allClientes  = [];
var criterios    = {};
var sortCol      = -1;
var sortDir      = 1;
var segmentoAtivo = null;

var COL_KEYS   = ['customer_name','customer_email','telefone','documento','nascimento','total_pedidos','total_gasto'];
var COL_LABELS = ['Nome','Email','Telefone','Documento','Nascimento','Pedidos','Total Gasto'];

async function init() {
  var resumo = [], crit = [];
  try { resumo = await (await fetch('/api/resumo')).json();   } catch(e) {}
  try { crit   = await (await fetch('/api/criterios')).json(); } catch(e) {}
  crit.forEach(function(c) { criterios[c.segmento] = c; });
  renderMatrix(resumo);
}

function renderMatrix(data) {
  var matrix = document.getElementById('matrix');
  var byPos  = {};
  var colW   = [0, 0, 0];
  var rowW   = [0, 0, 0];

  data.forEach(function(s) {
    byPos[s.row + '-' + s.col] = s;
    colW[s.col - 1] += s.total_clientes;
    rowW[s.row - 1] += s.total_clientes;
  });

  var maxW = Math.max.apply(null, colW.concat(rowW).concat([1]));
  var minW = maxW * 0.15;
  var cw = colW.map(function(w) { return Math.max(w, minW); });
  var rw = rowW.map(function(w) { return Math.max(w, minW); });

  matrix.style.gridTemplateColumns = cw.map(function(w) { return w + 'fr'; }).join(' ');
  matrix.style.gridTemplateRows    = rw.map(function(w) { return w + 'fr'; }).join(' ');
  matrix.innerHTML = '';

  for (var row = 1; row <= 3; row++) {
    for (var col = 1; col <= 3; col++) {
      var s = byPos[row + '-' + col];
      if (s) {
        var card = document.createElement('div');
        card.className = 'card';
        card.style.background  = s.cor;
        card.style.color       = s.texto;
        card.style.gridRow     = row;
        card.style.gridColumn  = col;
        card.innerHTML =
          '<div class="tip">' + buildTooltip(s.nome) + '</div>' +
          '<div>' +
            '<div class="icone">' + s.icone + '</div>' +
            '<div class="nome">'  + s.nome  + '</div>' +
          '</div>' +
          '<div>' +
            '<div class="stat">Clientes<b>' +
              s.total_clientes.toLocaleString('pt-BR') + '</b></div>' +
            '<div class="stat" style="margin-top:2px">Receita<b>R$ ' +
              s.receita_total.toLocaleString('pt-BR',{minimumFractionDigits:2}) +
            '</b></div>' +
          '</div>';
        (function(nome, el) {
          el.addEventListener('click', function() { abrirSegmento(nome, el); });
        })(s.nome, card);
        matrix.appendChild(card);
      } else {
        var empty = document.createElement('div');
        empty.className   = 'card-empty';
        empty.style.gridRow    = row;
        empty.style.gridColumn = col;
        matrix.appendChild(empty);
      }
    }
  }
}

function buildTooltip(nome) {
  var c = criterios[nome];
  if (!c) return '<strong>' + nome + '</strong>Carregando dados...';

  function fmtV(v) {
    return 'R$ ' + parseFloat(v).toLocaleString('pt-BR',
      {minimumFractionDigits:2, maximumFractionDigits:2});
  }
  function fmtDias(v) {
    var d = Math.round(v);
    return d === 1 ? '1 dia' : d + ' dias';
  }

  var html = '<strong>' + nome + '</strong>';
  if (c.min_recencia != null) {
    html += '📅 Última compra: de ' + fmtDias(c.min_recencia) +
            ' a ' + fmtDias(c.max_recencia) + ' atrás' +
            ' (média: ' + fmtDias(c.avg_recencia) + ')<br>';
  }
  if (c.min_freq != null) {
    html += '🛒 Pedidos: ' + c.min_freq + ' a ' + c.max_freq +
            ' (média: ' + parseFloat(c.avg_freq).toFixed(1) + ')<br>';
  }
  if (c.min_valor != null) {
    html += '💰 Gasto total: ' + fmtV(c.min_valor) +
            ' – ' + fmtV(c.max_valor);
  }
  return html;
}

async function abrirSegmento(nome, card) {
  document.querySelectorAll('.card').forEach(function(c) { c.classList.remove('active'); });
  card.classList.add('active');
  segmentoAtivo = nome;
  sortCol = -1;
  sortDir = 1;

  var wrap     = document.getElementById('tabela-wrap');
  var titulo   = document.getElementById('tabela-titulo');
  var conteudo = document.getElementById('tabela-conteudo');

  wrap.style.display = 'block';
  titulo.textContent = 'Clientes — ' + nome;
  conteudo.innerHTML = '<p class="loading">Carregando...</p>';
  wrap.scrollIntoView({behavior:'smooth', block:'start'});

  var res = await fetch('/api/clientes/' + encodeURIComponent(nome));
  allClientes = await res.json();

  if (!allClientes.length) {
    conteudo.innerHTML = '<p class="vazio">Nenhum cliente neste segmento.</p>';
    return;
  }
  renderTabela();
}

function renderTabela() {
  var conteudo = document.getElementById('tabela-conteudo');
  var sorted = allClientes.slice().sort(function(a, b) {
    if (sortCol < 0) return 0;
    var key = COL_KEYS[sortCol];
    var va = a[key] != null ? a[key] : '';
    var vb = b[key] != null ? b[key] : '';
    var na = parseFloat(va), nb = parseFloat(vb);
    if (!isNaN(na) && !isNaN(nb)) return (na - nb) * sortDir;
    return String(va).localeCompare(String(vb), 'pt-BR') * sortDir;
  });

  var ths = COL_LABELS.map(function(label, i) {
    var arrow = sortCol === i ? (sortDir === 1 ? ' ▲' : ' ▼') : '';
    var cls   = 'sortable' + (sortCol === i ? ' sorted' : '');
    return '<th class="' + cls + '" data-col="' + i + '">' + label + arrow + '</th>';
  }).join('');

  var rows = '';
  sorted.forEach(function(c) {
    rows += '<tr>' +
      '<td>' + (c.customer_name  || '—') + '</td>' +
      '<td>' + (c.customer_email || '—') + '</td>' +
      '<td>' + (c.telefone       || '—') + '</td>' +
      '<td>' + (c.documento      || '—') + '</td>' +
      '<td>' + (c.nascimento ? c.nascimento.substring(0,10) : '—') + '</td>' +
      '<td>' + c.total_pedidos + '</td>' +
      '<td>R$ ' + parseFloat(c.total_gasto).toLocaleString('pt-BR',{minimumFractionDigits:2}) + '</td>' +
      '</tr>';
  });

  conteudo.innerHTML =
    '<table><thead><tr>' + ths + '</tr></thead>' +
    '<tbody>' + rows + '</tbody></table>';

  conteudo.querySelectorAll('th.sortable').forEach(function(th) {
    th.addEventListener('click', function() {
      var col = parseInt(th.dataset.col);
      if (sortCol === col) { sortDir *= -1; }
      else { sortCol = col; sortDir = 1; }
      renderTabela();
    });
  });
}

function exportCSV() {
  if (!allClientes.length) return;
  var rows = [COL_LABELS.join(',')];
  allClientes.forEach(function(c) {
    var vals = [
      c.customer_name  || '',
      c.customer_email || '',
      c.telefone       || '',
      c.documento      || '',
      c.nascimento ? c.nascimento.substring(0,10) : '',
      c.total_pedidos,
      parseFloat(c.total_gasto || 0).toFixed(2)
    ].map(function(v) {
      var s = String(v);
      return (s.indexOf(',') >= 0 || s.indexOf('"') >= 0)
        ? '"' + s.replace(/"/g, '""') + '"' : s;
    });
    rows.push(vals.join(','));
  });
  var csv  = '﻿' + rows.join('\r\n');
  var blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
  var url  = URL.createObjectURL(blob);
  var a    = document.createElement('a');
  a.href     = url;
  a.download = 'clientes_' + (segmentoAtivo||'rfv').replace(/\s+/g,'_') + '.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

init();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
