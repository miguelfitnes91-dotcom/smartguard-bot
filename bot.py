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

if not TOKEN:
    raise ValueError("BOT_TOKEN não encontrado nas variáveis de ambiente.")

# =========================
# BANCO DE DADOS
# =========================
conn = sqlite3.connect("dados.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS logs (
    equipamento_id TEXT,
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
        return


def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    print(f"Servidor HTTP iniciado na porta {port}")
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


# =========================
# PARSER SGLOG
# =========================
def parse_sglog_lines(texto):
    logs = []

    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha.startswith("SGLOG|"):
            continue

        partes = linha.split("|")
        if len(partes) < 6:
            continue

        try:
            valor = float(partes[4])
        except ValueError:
            continue

        timestamp = partes[6] if len(partes) > 6 else datetime.now().isoformat()

        logs.append({
            "equipamento_id": partes[1],
            "empresa": partes[2],
            "tipo": partes[3],
            "valor": valor,
            "unidade": partes[5],
            "timestamp": timestamp,
        })

    return logs


# =========================
# FUNÇÕES AUXILIARES
# =========================
def salvar_log(dados):
    cursor.execute("""
        INSERT INTO logs (equipamento_id, empresa, tipo, valor, unidade, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        dados["equipamento_id"],
        dados["empresa"],
        dados["tipo"],
        dados["valor"],
        dados["unidade"],
        dados["timestamp"]
    ))
    conn.commit()


def buscar_logs_periodo(inicio_iso):
    cursor.execute("""
        SELECT equipamento_id, empresa, tipo, valor, unidade, timestamp
        FROM logs
        WHERE timestamp >= ?
        ORDER BY timestamp DESC
    """, (inicio_iso,))
    return cursor.fetchall()


def buscar_logs_equipamento(equipamento_id, limite=20):
    cursor.execute("""
        SELECT equipamento_id, empresa, tipo, valor, unidade, timestamp
        FROM logs
        WHERE equipamento_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (equipamento_id, limite))
    return cursor.fetchall()


def buscar_ranking(inicio_iso):
    cursor.execute("""
        SELECT equipamento_id, empresa, COUNT(*) as total
        FROM logs
        WHERE timestamp >= ?
        GROUP BY equipamento_id, empresa
        ORDER BY total DESC, equipamento_id ASC
        LIMIT 10
    """, (inicio_iso,))
    return cursor.fetchall()


def limpar_banco():
    cursor.execute("DELETE FROM logs")
    conn.commit()


# =========================
# COMANDOS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /start recebido")
    await update.message.reply_text(
        "✅ SmartGuard BRAINY online.\n\n"
        "Comandos disponíveis:\n"
        "/ping\n"
        "/hoje\n"
        "/semana\n"
        "/ranking\n"
        "/equipamento SG-0001\n"
        "/limparbd"
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /ping recebido")
    await update.message.reply_text("🏓 Pong! Bot online.")


async def hoje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /hoje recebido")
    inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    logs = buscar_logs_periodo(inicio.isoformat())

    if not logs:
        await update.message.reply_text("📭 Nenhum log registrado hoje.")
        return

    total = len(logs)
    contagem_tipos = {}

    for _, _, tipo, _, _, _ in logs:
        contagem_tipos[tipo] = contagem_tipos.get(tipo, 0) + 1

    linhas = ["📊 Relatório de hoje", f"Total de logs: {total}", ""]
    for tipo, qtd in sorted(contagem_tipos.items(), key=lambda x: x[1], reverse=True):
        linhas.append(f"- {tipo}: {qtd}")

    await update.message.reply_text("\n".join(linhas))


async def semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /semana recebido")
    inicio = datetime.now() - timedelta(days=7)
    logs = buscar_logs_periodo(inicio.isoformat())

    if not logs:
        await update.message.reply_text("📭 Nenhum log registrado nos últimos 7 dias.")
        return

    total = len(logs)
    por_equipamento = {}

    for equipamento_id, empresa, _, _, _, _ in logs:
        chave = f"{equipamento_id} | {empresa}"
        por_equipamento[chave] = por_equipamento.get(chave, 0) + 1

    linhas = ["📈 Relatório dos últimos 7 dias", f"Total de logs: {total}", ""]

    for chave, qtd in sorted(por_equipamento.items(), key=lambda x: x[1], reverse=True)[:10]:
        linhas.append(f"- {chave}: {qtd}")

    await update.message.reply_text("\n".join(linhas))


async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /ranking recebido")
    inicio = (datetime.now() - timedelta(days=7)).isoformat()
    dados = buscar_ranking(inicio)

    if not dados:
        await update.message.reply_text("📭 Sem dados para ranking nos últimos 7 dias.")
        return

    linhas = ["🏆 Ranking de equipamentos com mais alertas (7 dias)", ""]

    for pos, (equipamento_id, empresa, total) in enumerate(dados, start=1):
        linhas.append(f"{pos}. {equipamento_id} | {empresa} — {total}")

    await update.message.reply_text("\n".join(linhas))


async def equipamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /equipamento recebido")
    if not context.args:
        await update.message.reply_text("Uso: /equipamento SG-0001")
        return

    equipamento_id = context.args[0].strip()
    logs = buscar_logs_equipamento(equipamento_id)

    if not logs:
        await update.message.reply_text(f"📭 Nenhum log encontrado para {equipamento_id}.")
        return

    linhas = [f"🛠 Histórico do equipamento {equipamento_id}", ""]

    for _, empresa, tipo, valor, unidade, timestamp in logs[:10]:
        linhas.append(f"{timestamp[:19]} | {tipo} | {valor} {unidade} | {empresa}")

    await update.message.reply_text("\n".join(linhas))


async def limparbd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Comando /limparbd recebido")
    limpar_banco()
    await update.message.reply_text("🧹 Banco de dados limpo com sucesso.")


# =========================
# RECEBER MENSAGENS
# =========================
async def receber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    texto = update.message.text
    print(f"Mensagem recebida: {texto[:120]}")

    logs = parse_sglog_lines(texto)

    if not logs:
        return

    respostas = []

    for dados in logs:
        salvar_log(dados)
        respostas.append(
            f"{dados['equipamento_id']} | {dados['tipo']} | {dados['valor']} {dados['unidade']}"
        )

    await update.message.reply_text(
        "✅ Logs registrados\n" + "\n".join(respostas)
    )


# =========================
# ERROS
# =========================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("ERRO NO BOT:")
    print(context.error)


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("Iniciando SmartGuard BRAINY...")
    threading.Thread(target=run_http_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("hoje", hoje))
    app.add_handler(CommandHandler("semana", semana))
    app.add_handler(CommandHandler("ranking", ranking))
    app.add_handler(CommandHandler("equipamento", equipamento))
    app.add_handler(CommandHandler("limparbd", limparbd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber))
    app.add_error_handler(error_handler)

    print("Bot rodando...")
    app.run_polling(drop_pending_updates=True)
