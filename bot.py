import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import sqlite3
from datetime import datetime

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
# PARSER SGLOG
# =========================
def parse_sglog(texto):
    for linha in texto.splitlines():
        if linha.startswith("SGLOG|"):
            partes = linha.strip().split("|")

            if len(partes) < 6:
                return None

            return {
                "id": partes[1],
                "empresa": partes[2],
                "tipo": partes[3],
                "valor": float(partes[4]),
                "unidade": partes[5],
                "timestamp": partes[6] if len(partes) > 6 else datetime.now().isoformat()
            }
    return None

# =========================
# HANDLER
# =========================
async def receber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text

    dados = parse_sglog(texto)

    if dados:
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

        await update.message.reply_text(
            f"✅ Log registrado\n"
            f"{dados['id']} | {dados['tipo']} | {dados['valor']} {dados['unidade']}"
        )

# =========================
# START BOT
# =========================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber))

print("Bot rodando...")
app.run_polling()