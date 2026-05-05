import os
import json
import requests
import anthropic
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify

SUPABASE_URL      = os.getenv("SUPABASE_URL",      "https://basesupabase.jadetrafego.com")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

EVO_URL    = "https://wpp.jadetrafego.com/message/sendText/RiseNumero"
EVO_APIKEY = "8BA92DBAF892-426F-9AE3-BCA650D7DC58"
JADE_PHONE = "5521987080442"

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Modelo ativo — padrão Opus. Jade pode trocar via WhatsApp a qualquer momento.
current_model = "claude-opus-4-6"

MODELOS = {
    "1":      ("claude-haiku-4-5-20251001", "Haiku"),
    "haiku":  ("claude-haiku-4-5-20251001", "Haiku"),
    "2":      ("claude-sonnet-4-6",          "Sonnet"),
    "sonnet": ("claude-sonnet-4-6",          "Sonnet"),
    "3":      ("claude-opus-4-6",            "Opus"),
    "opus":   ("claude-opus-4-6",            "Opus"),
}


def send_whatsapp(phone: str, text: str):
    try:
        requests.post(
            EVO_URL,
            headers={"apikey": EVO_APIKEY, "Content-Type": "application/json"},
            json={"number": phone, "text": text},
            timeout=10,
        )
    except Exception:
        pass


def execute_sql(sql: str) -> str:
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/execute_analytics_query",
        headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
        },
        json={"query_text": sql},
    )
    if response.status_code == 200:
        result = response.json()
        if result is None:
            return "Nenhum resultado encontrado."
        return json.dumps(result, ensure_ascii=False, indent=2)
    return f"Erro ao consultar banco: {response.text}"


tools = [
    {
        "name": "consultar_banco",
        "description": (
            "Executa uma query SQL SELECT no banco de dados de pedidos do ecommerce Pano. "
            "Use view_orders para dados de pedidos (1 linha por pedido, sem duplicar faturamento). "
            "Use view_order_items para análise de produtos e variações (1 linha por item). "
            "Use view_trafego_geral para dados de mídia paga (meta, google, tiktok). "
            "Use view_rfv para análise RFV de clientes (segmentação). "
            "Campos de view_orders: id, code, total, subtotal, discount, status, payment_status, "
            "fulfillment_status, created_at, updated_at, customer_name, customer_email, customer_phone, "
            "city, state, payment_method, shipping_name, shipping_price. "
            "Campos de view_order_items: order_id, code, status, payment_status, created_at, "
            "customer_name, customer_email, product_id, item_name, item_variation, item_quantity, "
            "item_total, item_discount. "
            "Campos de view_trafego_geral: dia (date), fonte (text: meta/google/tiktok), "
            "investimento (numeric), impressoes (numeric), cliques (numeric), "
            "conversoes (numeric), receita_ads (numeric), cpm (numeric), cpc (numeric), ctr (numeric). "
            "Campos de view_rfv: customer_email, customer_name, ultima_compra, primeira_compra, "
            "dias_recencia, frequencia, valor_total, r_score, f_score, v_score, rfv_score, segmento. "
            "Segmentos possíveis: Campeão, Fiel, Novo Cliente, Potencial, Não Pode Perder, Em Risco, Hibernando, Em Desenvolvimento. "
            "payment_status possíveis: approved, pending, denied, refunded, canceled. "
            "status possíveis: open, archived, canceled. "
            "Datas no formato: '2026-03-27' ou com cast: created_at::date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Query SQL SELECT para executar no banco",
                }
            },
            "required": ["sql"],
        },
    }
]


def get_system_prompt():
    sp = ZoneInfo("America/Sao_Paulo")
    hoje = datetime.now(sp).strftime("%Y-%m-%d")
    ontem = (datetime.now(sp) - timedelta(days=1)).strftime("%Y-%m-%d")
    return f"""Você é um assistente especializado em análise de dados do ecommerce Pano.
Você responde perguntas sobre vendas, faturamento, produtos, clientes e mídia paga consultando o banco de dados.

Referência de datas (horário de Brasília):
- Hoje: {hoje}
- Ontem: {ontem}
Use essas datas diretamente nas queries SQL (ex: created_at::date = '{hoje}').

Regras importantes:
- Para faturamento e contagem de pedidos, use sempre view_orders (evita duplicar por causa de múltiplos itens por pedido)
- Para análise de produtos, variações e quantidades vendidas, use view_order_items
- Para dados de mídia paga (investimento, cliques, impressões), use view_trafego_geral
- Para pedidos aprovados (faturamento real), filtre SEMPRE com: payment_status = 'approved' AND status != 'canceled'
  (pedidos cancelados mesmo com pagamento aprovado não devem entrar no faturamento real)
- Para cancelados/estornados: status = 'canceled' OR payment_status IN ('refunded', 'canceled')
- Datas: use created_at::date para comparar apenas a data; em view_trafego_geral use o campo dia diretamente
- Sempre que calcular faturamento de pedidos, some o campo total em view_orders (não em view_order_items)
- Para quantidade de itens vendidos, some item_quantity em view_order_items
- Para ROAS: divida SUM(total) de view_orders (payment_status = 'approved' AND status != 'canceled') por SUM(investimento) de view_trafego_geral no mesmo período
- Para CPV (custo por venda): divida SUM(investimento) de view_trafego_geral pelo número de pedidos aprovados (payment_status = 'approved' AND status != 'canceled')
- Para análise RFV/segmentação de clientes, use view_rfv diretamente
- Responda sempre em português, de forma clara e direta
- Formate valores monetários com R$ e duas casas decimais
- Formate ROAS com duas casas decimais seguido de 'x' (ex: 3.45x)
- Se não houver dados para o período, informe claramente"""


def _run_inference(messages: list, model: str) -> object:
    return client.messages.create(
        model=model,
        max_tokens=4096,
        system=get_system_prompt(),
        tools=tools,
        messages=messages,
    )


def chat_api(pergunta: str, session_id: str) -> str:
    global current_model

    if session_id not in sessions:
        sessions[session_id] = []
    messages = sessions[session_id]
    messages.append({"role": "user", "content": pergunta})

    while True:
        try:
            response = _run_inference(messages, current_model)
        except anthropic.RateLimitError:
            if current_model == "claude-opus-4-6":
                # Fallback automático + notificação para Jade
                current_model = "claude-haiku-4-5-20251001"
                send_whatsapp(
                    JADE_PHONE,
                    "⚠️ *Rate limit atingido no Claude Opus!*\n\n"
                    "Troquei automaticamente para *Haiku*. Qual modelo usar?\n\n"
                    "Responda a qualquer momento:\n"
                    "*modelo 1* — Haiku (rápido, sem limite)\n"
                    "*modelo 2* — Sonnet (equilibrado)\n"
                    "*modelo 3* — Opus (tentar novamente)",
                )
                response = _run_inference(messages, current_model)
            else:
                raise

        if response.stop_reason == "end_turn":
            answer = next((b.text for b in response.content if b.type == "text"), "")
            messages.append({"role": "assistant", "content": response.content})
            return answer

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_sql(block.input["sql"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})


app = Flask(__name__)
sessions = {}


@app.route("/perguntar", methods=["POST"])
def perguntar():
    data = request.json or {}
    pergunta   = data.get("pergunta", "")
    session_id = data.get("session_id", "default")
    if not pergunta:
        return jsonify({"erro": "Campo pergunta é obrigatório"}), 400
    resposta = chat_api(pergunta, session_id)
    return jsonify({"resposta": resposta})


@app.route("/modelo", methods=["POST"])
def set_modelo():
    global current_model
    data  = request.json or {}
    chave = data.get("modelo", "").lower().strip()
    if chave in MODELOS:
        current_model, nome = MODELOS[chave]
        return jsonify({"modelo": current_model, "nome": nome})
    return jsonify({"erro": "Use: 1/haiku, 2/sonnet, 3/opus"}), 400


@app.route("/modelo", methods=["GET"])
def get_modelo():
    nome = {
        "claude-haiku-4-5-20251001": "Haiku",
        "claude-sonnet-4-6":         "Sonnet",
        "claude-opus-4-6":           "Opus",
    }.get(current_model, current_model)
    return jsonify({"modelo": current_model, "nome": nome})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
