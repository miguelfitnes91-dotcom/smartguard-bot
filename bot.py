import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")

# =========================
# BANCO DE DADOS
# =========================
conn = sqlite3.connect("dados.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS logs (
    id TEXT,
    empresa TEXT,
    tipo TEXT,
    valor REAL,
    unidade TEXT,
    timestamp TEXT
)
""")
conn.commit()

# =========================
# SERVIDOR HTTP PARA RENDER
# =========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return  # evita poluir o log


def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


# =========================
# PARSER SGLOG
# =========================
def parse_sglog(texto):
    for linha in texto.splitlines():
        if linha.startswith("SGLOG|"):
            partes = linha.strip().split("|")

            if len(partes) < 6:
                return None

            try:
                valor = float(partes[4])
            except ValueError:
                return None

            return {
                "id": partes[1],
                "empresa": partes[2],
                "tipo": partes[3],
                "valor": valor,
                "unidade": partes[5],
                "timestamp": partes[6] if len(partes) > 6 else datetime.now().isoformat()
            }
    return None


# =========================
# FUNÇÕES AUXILIARES
# =========================
def salvar_log(dados):
    cursor.execute("""
        INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?)
    """, (
        dados["id"],
        dados["empresa"],
        dados["tipo"],
        dados["valor"],
        dados["unidade"],
        dados["timestamp"]
    ))
    conn.commit()


def buscar_logs_periodo(inicio_iso):
    cursor.execute("""
        SELECT id, empresa, tipo, valor, unidade, timestamp
        FROM logs
        WHERE timestamp >= ?
        ORDER BY timestamp DESC
    """, (inicio_iso,))
    return cursor.fetchall()


def buscar_logs_equipamento(equip_id, limite=20):
    cursor.execute("""
        SELECT id, empresa, tipo, valor, unidade, timestamp
        FROM logs
        WHERE id = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (equip_id, limite))
    return cursor.fetchall()


def buscar_ranking(inicio_iso):
    cursor.execute("""
        SELECT id, empresa, COUNT(*) as total
        FROM logs
        WHERE timestamp >= ?
        GROUP BY id, empresa
        ORDER BY total DESC, id ASC
        LIMIT 10
    """, (inicio_iso,))
    return cursor.fetchall()


# =========================
# COMANDOS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ SmartGuard BRAINY online.\n\n"
        "Comandos disponíveis:\n"
        "/hoje\n"
        "/semana\n"
        "/ranking\n"
        "/equipamento SG-0001"
    )


async def hoje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    logs = buscar_logs_periodo(inicio.isoformat())

    if not logs:
        await update.message.reply_text("📭 Nenhum log registrado hoje.")
        return

    total = len(logs)

    contagem_tipos = {}
    for _, _, tipo, _, _, _ in logs:
        contagem_tipos[tipo] = contagem_tipos.get(tipo, 0) + 1

    linhas = [f"📊 Relatório de hoje", f"Total de logs: {total}", ""]
    for tipo, qtd in sorted(contagem_tipos.items(), key=lambda x: x[1], reverse=True):
        linhas.append(f"- {tipo}: {qtd}")

    await update.message.reply_text("\n".join(linhas))


async def semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inicio = datetime.now() - timedelta(days=7)
    logs = buscar_logs_periodo(inicio.isoformat())

    if not logs:
        await update.message.reply_text("📭 Nenhum log registrado nos últimos 7 dias.")
        return

    total = len(logs)
    por_equipamento = {}

    for equip_id, empresa, tipo, valor, unidade, timestamp in logs:
        chave = f"{equip_id} | {empresa}"
        por_equipamento[chave] = por_equipamento.get(chave, 0) + 1

    linhas = [f"📈 Relatório dos últimos 7 dias", f"Total de logs: {total}", ""]

    for chave, qtd in sorted(por_equipamento.items(), key=lambda x: x[1], reverse=True)[:10]:
        linhas.append(f"- {chave}: {qtd}")

    await update.message.reply_text("\n".join(linhas))


async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inicio = (datetime.now() - timedelta(days=7)).isoformat()
    dados = buscar_ranking(inicio)

    if not dados:
        await update.message.reply_text("📭 Sem dados para ranking nos últimos 7 dias.")
        return

    linhas = ["🏆 Ranking de equipamentos com mais alertas (7 dias)", ""]

    for pos, (equip_id, empresa, total) in enumerate(dados, start=1):
        linhas.append(f"{pos}. {equip_id} | {empresa} — {total}")

    await update.message.reply_text("\n".join(linhas))


async def equipamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /equipamento SG-0001")
        return

    equip_id = context.args[0].strip()
    logs = buscar_logs_equipamento(equip_id)

    if not logs:
        await update.message.reply_text(f"📭 Nenhum log encontrado para {equip_id}.")
        return

    linhas = [f"🛠 Histórico do equipamento {equip_id}", ""]

    for _, empresa, tipo, valor, unidade, timestamp in logs[:10]:
        linhas.append(f"{timestamp[:19]} | {tipo} | {valor} {unidade} | {empresa}")

    await update.message.reply_text("\n".join(linhas))


# =========================
# RECEBER MENSAGENS
# =========================
async def receber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    texto = update.message.text
    dados = parse_sglog(texto)

    if not dados:
        return

    salvar_log(dados)

    await update.message.reply_text(
        f"✅ Log registrado\n"
        f"{dados['id']} | {dados['tipo']} | {dados['valor']} {dados['unidade']}"
    )


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    threading.Thread(target=run_http_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("hoje", hoje))
    app.add_handler(CommandHandler("semana", semana))
    app.add_handler(CommandHandler("ranking", ranking))
    app.add_handler(CommandHandler("equipamento", equipamento))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber))

    print("Bot rodando...")
    app.run_polling()
