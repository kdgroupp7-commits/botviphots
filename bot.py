import logging
import asyncio
import aiohttp
import qrcode
import io
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

# ============================================================
#  ✏️  CONFIGURAÇÕES — EDITE AQUI
# ============================================================
BOT_TOKEN    = "82"
ADMIN_ID     = 9    # << seu ID (pegue no @userinfobot)
GRUPO_VIP    = "https://t.me/"

# ─────────────────────────────────────────────────────────────
#  ➡️  COLE SUA API KEY DO ASAAS AQUI quando tiver
#      Sandbox:  começa com $aact_...YWRhZjY0Zjg...
#      Producao: mesma chave, só trocar a URL abaixo
# ─────────────────────────────────────────────────────────────
ASAAS_API_KEY     = h"
ASAAS_BASE_URL    = "https://sandbox.asaas.com/api/v3"   # troque para https://api.asaas.com/api/v3 em producao
ASAAS_CUSTOMER_ID = "          # cus_000000000000

# Planos
PLANOS = {
    "mensal":     {"nome": "Mensal",     "preco": 19.99, "dias": 30, "emoji": "📅"},
    "trimestral": {"nome": "Trimestral", "preco": 29.99, "dias": 90, "emoji": "📆"},
    "vitalicio":  {"nome": "Vitalício",  "preco": 39.99, "dias": 0,  "emoji": "👑"},
}

# Video de apresentacao — cole o file_id quando tiver
VIDEO_FILE_ID = None  # ex: "BAACAgIAAxkBAAI..."

TEXTO_APRESENTACAO = """» 👇VENHA FAZER PARTE, SE TORNE + 1 MEMBRO VIP E RECEBA ACESSO AQUELA FAMOSA QUE SEMPRE QUIS VER E MILHARES DE OUTRAS GOSTOSAS ANÔNIMAS👇 »

☆★⭐️ EXCLUSIVAS - VIP ⭐️★☆

🔶 SÃO 10 GRUPOS VIPS EM 1 COM MAIS DE MILHARES DE MÍDIAS DE R$ 150,00 POR APENAS R$ 39,99 *Vitalício* 🔶
*Você paga uma vez só e tem acesso a tudo*

💰 PAGAMENTO VIA PIX 💠 💳
🔴FOTOS E VÍDEOS SEM PROPAGANDAS
🟡CONTEÚDOS EXCLUSIVOS
🟪 ACESSO A:
✅ 0nlyFans, CloseFriends, Priv4cy e Afins
✅ BigoLive, Buzzcast, Tango, Superlive e Afins
✅ XvideosRed, Pornhub e Afins
✅ Amadoras, Packs, Câmeras de Segurança e Muito Mais"""

# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DADOS_FILE = "dados.json"


# ── Banco de dados em JSON ───────────────────────────────────
def carregar_dados():
    if not os.path.exists(DADOS_FILE):
        return {"pagamentos": {}, "assinaturas": {}}
    with open(DADOS_FILE, "r") as f:
        return json.load(f)

def salvar_dados(dados):
    with open(DADOS_FILE, "w") as f:
        json.dump(dados, f, indent=2, default=str)

def salvar_pedido(user_id, plano_key, cobranca_id):
    dados = carregar_dados()
    plano = PLANOS[plano_key]
    if plano["dias"] == 0:
        validade = None
    else:
        validade = (datetime.now() + timedelta(days=plano["dias"])).strftime("%Y-%m-%d %H:%M:%S")
    dados["pagamentos"][cobranca_id] = {
        "user_id":       user_id,
        "plano":         plano_key,
        "status":        "pendente",
        "data_compra":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_validade": validade
    }
    salvar_dados(dados)

def marcar_pago(cobranca_id):
    dados = carregar_dados()
    if cobranca_id in dados["pagamentos"]:
        dados["pagamentos"][cobranca_id]["status"] = "pago"
        user_id   = dados["pagamentos"][cobranca_id]["user_id"]
        plano_key = dados["pagamentos"][cobranca_id]["plano"]
        validade  = dados["pagamentos"][cobranca_id]["data_validade"]
        # Salva assinatura ativa do usuario
        dados["assinaturas"][str(user_id)] = {
            "plano":         plano_key,
            "data_compra":   dados["pagamentos"][cobranca_id]["data_compra"],
            "data_validade": validade
        }
        salvar_dados(dados)

def verificar_pagamento_local(cobranca_id):
    dados = carregar_dados()
    return dados["pagamentos"].get(cobranca_id)

def get_assinatura(user_id):
    dados = carregar_dados()
    return dados["assinaturas"].get(str(user_id))


# ── Asaas API ────────────────────────────────────────────────
async def criar_cobranca_asaas(user_id: int, plano_key: str) -> dict:
    plano      = PLANOS[plano_key]
    vencimento = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    payload = {
        "customer":        ASAAS_CUSTOMER_ID,
        "billingType":     "PIX",
        "value":           plano["preco"],
        "dueDate":         vencimento,
        "description":     f"Acesso VIP — Plano {plano['nome']}",
        "externalReference": f"{user_id}_{plano_key}_{int(datetime.now().timestamp())}"
    }
    headers = {"Content-Type": "application/json", "access_token": ASAAS_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{ASAAS_BASE_URL}/payments",
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()
                cobranca_id = data.get("id", "")
            if not cobranca_id:
                return {"cobranca_id": "", "pix_code": "", "qr_b64": ""}
            async with session.get(
                f"{ASAAS_BASE_URL}/payments/{cobranca_id}/pixQrCode",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp2:
                pix_data = await resp2.json()
                pix_code = pix_data.get("payload", "")
                qr_b64   = pix_data.get("encodedImage", "")
        return {"cobranca_id": cobranca_id, "pix_code": pix_code, "qr_b64": qr_b64}
    except Exception as e:
        logger.error(f"criar_cobranca_asaas: {e}")
        return {"cobranca_id": "", "pix_code": "", "qr_b64": ""}

async def verificar_pagamento_asaas(cobranca_id: str) -> bool:
    headers = {"access_token": ASAAS_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{ASAAS_BASE_URL}/payments/{cobranca_id}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()
                return data.get("status") in ("RECEIVED", "CONFIRMED")
    except Exception as e:
        logger.error(f"verificar_pagamento_asaas: {e}")
        return False


# ── QR Code local ────────────────────────────────────────────
def gerar_qr_bytes(pix_code: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(pix_code)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── /start ───────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if VIDEO_FILE_ID:
        await update.message.reply_video(video=VIDEO_FILE_ID)
    teclado = [
        [InlineKeyboardButton(f"{PLANOS['mensal']['emoji']} Mensal — R$ {PLANOS['mensal']['preco']:.2f}",           callback_data="plano_mensal")],
        [InlineKeyboardButton(f"{PLANOS['trimestral']['emoji']} Trimestral — R$ {PLANOS['trimestral']['preco']:.2f}", callback_data="plano_trimestral")],
        [InlineKeyboardButton(f"{PLANOS['vitalicio']['emoji']} Vitalício — R$ {PLANOS['vitalicio']['preco']:.2f}",    callback_data="plano_vitalicio")],
    ]
    await update.message.reply_text(
        TEXTO_APRESENTACAO,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(teclado)
    )


# ── /suporte ─────────────────────────────────────────────────
async def suporte_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teclado = [[InlineKeyboardButton("💬 Falar com Suporte", url="https://t.me/silkjay0")]]
    await update.message.reply_text(
        "💬 *Suporte*\n\nClique abaixo para falar diretamente com o suporte:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(teclado)
    )


# ── /status ──────────────────────────────────────────────────
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user       = update.effective_user
    assinatura = get_assinatura(user.id)
    if not assinatura:
        await update.message.reply_text(
            "⚠️ *Você ainda não possui nenhuma assinatura ativa.*\n\n"
            "Use /start para ver os planos e adquirir seu acesso VIP!",
            parse_mode="Markdown"
        )
        return
    plano_key  = assinatura["plano"]
    plano      = PLANOS.get(plano_key, {})
    nome_plano = plano.get("nome", plano_key.capitalize())
    data_compra = assinatura["data_compra"][:10].replace("-", "/")
    # Inverte para dd/mm/aaaa
    dc = data_compra.split("/")
    data_compra = f"{dc[2]}/{dc[1]}/{dc[0]}"

    if plano_key == "vitalicio" or not assinatura["data_validade"]:
        validade_txt = "♾️ *Ilimitado* (Vitalício)"
    else:
        validade = datetime.strptime(assinatura["data_validade"], "%Y-%m-%d %H:%M:%S")
        dias_rest = (validade - datetime.now()).days
        v = validade.strftime("%d/%m/%Y")
        validade_txt = f"📅 {v} ({max(dias_rest, 0)} dias restantes)"

    await update.message.reply_text(
        f"⭐ *Sua Assinatura*\n\n"
        f"📦 Plano: *{nome_plano}*\n"
        f"📆 Data da compra: {data_compra}\n"
        f"⏳ Validade: {validade_txt}\n\n"
        f"[🔥 Acessar Grupo VIP]({GRUPO_VIP})",
        parse_mode="Markdown"
    )


# ── Callbacks ─────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    # ── Escolheu plano ──
    if data.startswith("plano_"):
        plano_key = data.replace("plano_", "")
        plano = PLANOS.get(plano_key)
        if not plano:
            return

        await query.edit_message_text("⏳ Gerando seu QR Code PIX, aguarde...")

        cobranca    = await criar_cobranca_asaas(user.id, plano_key)
        cobranca_id = cobranca["cobranca_id"]
        pix_code    = cobranca["pix_code"]
        qr_b64      = cobranca["qr_b64"]

        if not cobranca_id:
            await query.edit_message_text(
                "❌ Erro ao gerar cobrança. Tente novamente ou use /suporte."
            )
            return

        salvar_pedido(user.id, plano_key, cobranca_id)
        context.user_data["cobranca_id"] = cobranca_id
        context.user_data["pix_code"]    = pix_code

        teclado = [
            [InlineKeyboardButton("📋 Copiar código PIX",   callback_data=f"copiar_{cobranca_id}")],
            [InlineKeyboardButton("✅ Confirmar pagamento", callback_data=f"confirmar_{cobranca_id}")],
        ]
        caption = (
            f"💳 *Pagamento via PIX*\n\n"
            f"Plano: *{plano['nome']}*\n"
            f"Valor: *R$ {plano['preco']:.2f}*\n\n"
            f"📲 Escaneie o QR Code ou copie o código PIX.\n"
            f"Após pagar clique em *Confirmar pagamento*."
        )

        if qr_b64:
            import base64
            img_bytes = base64.b64decode(qr_b64)
        elif pix_code:
            img_bytes = gerar_qr_bytes(pix_code)
        else:
            img_bytes = None

        if img_bytes:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=io.BytesIO(img_bytes),
                caption=caption,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(teclado)
            )
            try:
                await query.delete_message()
            except Exception:
                pass
        else:
            await query.edit_message_text(
                caption, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(teclado)
            )

    # ── Copiar PIX ──
    elif data.startswith("copiar_"):
        pix_code = context.user_data.get("pix_code", "")
        if pix_code:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📋 *Código PIX Copia e Cola:*\n\n`{pix_code}`\n\n_Copie e cole no seu banco._",
                parse_mode="Markdown"
            )
        else:
            await query.answer("Código PIX não disponível.", show_alert=True)

    # ── Confirmar pagamento ──
    elif data.startswith("confirmar_"):
        cobranca_id = data.replace("confirmar_", "")

        pedido = verificar_pagamento_local(cobranca_id)
        pago   = pedido and pedido["status"] == "pago"

        if not pago:
            pago = await verificar_pagamento_asaas(cobranca_id)
            if pago:
                marcar_pago(cobranca_id)

        if pago:
            teclado = [[InlineKeyboardButton("🔥 Acessar Grupo VIP", url=GRUPO_VIP)]]
            try:
                await query.edit_message_caption(
                    caption=(
                        "✅ *Pagamento confirmado! Obrigado pela compra!*\n\n"
                        "Clique abaixo para acessar o Grupo VIP agora:"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(teclado)
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=(
                        "✅ *Pagamento confirmado! Obrigado pela compra!*\n\n"
                        f"[🔥 Acessar Grupo VIP]({GRUPO_VIP})"
                    ),
                    parse_mode="Markdown"
                )
        else:
            await query.answer(
                "❌ Pagamento não identificado.\n"
                "Faça o pagamento e confirme novamente.",
                show_alert=True
            )


# ── Setup ────────────────────────────────────────────────────
async def setup_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start",   "🚀 Iniciar"),
        BotCommand("suporte", "💬 Suporte"),
        BotCommand("status",  "⭐ Minha Assinatura"),
    ])

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(setup_commands).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("suporte", suporte_cmd))
    app.add_handler(CommandHandler("status",  status_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    logger.info("✅ Bot rodando...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
