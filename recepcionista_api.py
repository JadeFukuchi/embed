import json
import requests
from flask import Flask, request, jsonify
from datetime import datetime

SUPABASE_URL = "https://basesupabase.jadetrafego.com"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.ewogICJyb2xlIjogInNlcnZpY2Vfcm9sZSIsCiAgImlzcyI6ICJzdXBhYmFzZSIsCiAgImlhdCI6IDE3MTUwNTA4MDAsCiAgImV4cCI6IDE4NzI4MTcyMDAKfQ.blQRQlhMI9Y6f4OtlbiVHoSBt-gJoEM6MPjNrUPpPv0"
JADE_PASSWORD = "jadedona"

app = Flask(__name__)

HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}


def sb_get(table, filters):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, params=filters)
    return r.json() if r.status_code == 200 else []


def sb_upsert(table, data):
    requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={**HEADERS, "Prefer": "resolution=merge-duplicates"},
        json=data,
    )


def get_estado(phone):
    rows = sb_get("conversa_estado", {"phone": f"eq.{phone}", "select": "*"})
    return rows[0] if rows else {"phone": phone, "estado": "inicial", "agente_destino": None}


def set_estado(phone, estado, agente_destino=None):
    sb_upsert("conversa_estado", {
        "phone": phone,
        "estado": estado,
        "agente_destino": agente_destino,
        "updated_at": datetime.utcnow().isoformat(),
    })


def get_autorizado(phone):
    rows = sb_get("agentes_autorizados", {"phone": f"eq.{phone}", "select": "*"})
    return rows[0] if rows else None


def get_todos_agentes():
    return sb_get("agentes_config", {"select": "*"}) or []


def get_agente_config(nome):
    rows = sb_get("agentes_config", {"nome": f"eq.{nome}", "select": "*"})
    return rows[0] if rows else None


def chamar_agente(url_api, pergunta, session_id):
    try:
        r = requests.post(url_api, json={"pergunta": pergunta, "session_id": session_id}, timeout=180)
        if r.status_code == 200:
            return r.json().get("resposta", "Sem resposta do agente.")
    except Exception as e:
        return f"Erro ao consultar o agente: {e}"
    return "Agente indisponível no momento."


def lista_agentes(agentes):
    return "\n".join([f"• *{a['nome']}* — {a.get('descricao', '')}" for a in agentes])


def processar(phone, mensagem):
    conv = get_estado(phone)
    estado = conv.get("estado", "inicial")
    msg = mensagem.strip()
    msg_lower = msg.lower()

    if estado == "inicial":
        set_estado(phone, "aguardando_escolha")
        return "Olá! 👋 Bem-vindo. Você quer falar com a *Jade* ou com um *agente*?"

    if estado == "aguardando_escolha":
        if "agente" in msg_lower:
            set_estado(phone, "aguardando_numero")
            return "Ok! Me fala seu número de WhatsApp com DDD (ex: 11999999999). Assim vou te direcionar para o agente correto. 😊"
        if "jade" in msg_lower:
            set_estado(phone, "aguardando_senha")
            return "Olá, Jade! Me fala a senha de acesso:"
        return "Não entendi. Você quer falar com a *Jade* ou com um *agente*?"

    if estado == "aguardando_numero":
        numero = "".join(filter(str.isdigit, msg))
        if len(numero) < 8:
            return "Por favor, me manda seu número com DDD (ex: 11999999999)."

        autorizado = get_autorizado(numero)
        if not autorizado:
            set_estado(phone, "inicial")
            return "Número não encontrado no sistema. Entre em contato com a Jade para solicitar acesso. 🔒"

        if autorizado.get("nome") == "Jade":
            set_estado(phone, "aguardando_senha")
            return "Olá, Jade! Me fala a senha de acesso:"

        agentes = autorizado.get("agentes", [])
        if len(agentes) == 1:
            agente_nome = agentes[0]
            agente = get_agente_config(agente_nome)
            if agente:
                set_estado(phone, "ativo", agente_nome)
                return f"Perfeito! Você está conectado ao agente *{agente.get('descricao', agente_nome)}*. Pode perguntar! 🎯"

        if len(agentes) > 1:
            configs = [get_agente_config(a) for a in agentes if get_agente_config(a)]
            set_estado(phone, "escolhendo_agente")
            return f"Você tem acesso a estes agentes:\n{lista_agentes(configs)}\n\nQual você quer usar?"

        set_estado(phone, "inicial")
        return "Nenhum agente disponível para seu número. Fale com a Jade."

    if estado == "aguardando_senha":
        if msg == JADE_PASSWORD:
            agentes = get_todos_agentes()
            set_estado(phone, "jade_menu")
            return f"Acesso liberado! 🔓 Agentes disponíveis:\n{lista_agentes(agentes)}\n\nQual você quer acessar?"
        return "Senha incorreta. Tente novamente:"

    if estado in ("jade_menu", "escolhendo_agente"):
        agentes = get_todos_agentes()
        for agente in agentes:
            if agente["nome"].lower() in msg_lower or msg_lower in agente["nome"].lower():
                set_estado(phone, "ativo", agente["nome"])
                return f"Conectado ao agente *{agente.get('descricao', agente['nome'])}*! Pode perguntar. 🎯"
        nomes = ", ".join([a["nome"] for a in agentes])
        return f"Não reconheci. Escolha um dos agentes disponíveis: {nomes}"

    if estado == "ativo":
        if msg_lower in ("sair", "voltar", "menu", "inicio", "início"):
            set_estado(phone, "inicial")
            return "Ok! Voltando ao início. Você quer falar com a *Jade* ou com um *agente*?"

        agente_nome = conv.get("agente_destino")
        if not agente_nome:
            set_estado(phone, "inicial")
            return "Sessão expirada. Vamos recomeçar."

        agente = get_agente_config(agente_nome)
        if not agente:
            set_estado(phone, "inicial")
            return "Agente não encontrado. Vamos recomeçar."

        return chamar_agente(agente["url_api"], msg, phone)

    set_estado(phone, "inicial")
    return "Olá! Você quer falar com a *Jade* ou com um *agente*?"


@app.route("/recepcao", methods=["POST"])
def recepcao():
    data = request.json or {}
    phone = data.get("phone", "").strip()
    mensagem = data.get("mensagem", "").strip()
    if not phone or not mensagem:
        return jsonify({"erro": "phone e mensagem são obrigatórios"}), 400
    resposta = processar(phone, mensagem)
    return jsonify({"resposta": resposta})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
