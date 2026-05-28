"""
Telegram Invite Link Tracking Bot – Finale Version
===================================================
Voraussetzungen:
    pip install "python-telegram-bot[job-queue]==21.5"
    pip install pyotp
    
    py -c "import pyotp; print(pyotp.random_base32())"
"""
# vorwort 
# -mods werden überwacht missbrauchen sie ihre rechte haben sie kein zufriff mehr den bot zu benutzen supermods haben das nicht 
# -der bot verfügt über eine funktion falls der admin gebannt wurde kann er mithilfe der google authenticator funktion /getowner allen gruppen wieder beitreten und kriegt admin rechte 
# commands
#
# -------------------------------------- 
# Admin 
# --------------------------------------
# /see                  statistik
# /deleteall            Alle Links Löschen 
# /returnall            Alle gelöschten Links wiederherstellen 
# /free                 Erstellt kostenlose Einladungslink für Gruppe B und Gruppe C
# /message              Nachricht über den Bot schicken
# /closebot             Bot wird gesperrt er wird niemanden mehr antworten 
# /openbot              Bot wird öffnet sich für alle 
# --------------------------------------
# Supermod und mod 
# --------------------------------------
# /kick 
# /ban 
# /mute 
# /unmute 
# /open                 öffnet die gruppe alle können schreiben 
# /close                schließt die gruppe keiner kann schreiben 
# /global               Jeder Nutzer erhält eine private nachricht vom bot wenn beide einen chat haben 
# /umfrage              Umfrage wird erstellt 
# /send admin/smod      Support wird weitergegeben 
# --------------------------------------
# Nutzer 
# -------------------------------------- 
# /createlink           ersttellt Link der überprüft wird je nach einladungen 
# /delete               löscht erstellten link
# /status               status über den link 
# /support              
# /closechat            schließt support chat/anfrage 



import logging
import asyncio
import json
import os
import re
import pyotp
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
from datetime import datetime, timedelta
from telegram import (
    Update, ChatInviteLink, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatPermissions, Message
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ChatMemberHandler, MessageHandler, ContextTypes,
    filters, ConversationHandler,
)

# ──────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────

# Variable setzen: BOT_TOKEN
BOT_TOKEN = os.environ.get("BOT_TOKEN", "DEIN_BOT_TOKEN")

# Google Authenticator Secret – als Railway Variable setzen: TOTP_SECRET
TOTP_SECRET = os.environ.get("TOTP_SECRET", "")

GROUP_A_ID = int(os.environ.get("GROUP_A_ID", "-1001234567891"))
GROUP_B_ID = int(os.environ.get("GROUP_B_ID", "-1001234567891"))
GROUP_C_ID = int(os.environ.get("GROUP_C_ID", "-1001234567891"))

# ── Gruppennamen – nur hier anpassen! ──
GROUP_A_NAME = os.environ.get("GROUP_A_NAME", "GROUP_A_NAME")
GROUP_B_NAME = os.environ.get("GROUP_B_NAME", "GROUP_B_NAME")
GROUP_C_NAME = os.environ.get("GROUP_C_NAME", "GROUP_C_NAME")

ADMIN_ID = int(os.environ.get("ADMIN_ID", "5555555555"))

# Kommagetrennte IDs: z.B. "111111111,222222222"
MODERATOR_IDS: list[int] = [
    int(x.strip()) for x in os.environ.get("MODERATOR_IDS", "111111111,222222222").split(",") if x.strip()
]

SUPERMOD_IDS: list[int] = [
    int(x.strip()) for x in os.environ.get("SUPERMOD_IDS", "333333333,444444444").split(",") if x.strip()
]

# Hier können benötigte invites variiert werden (auch per Railway-Variable setzbar)
JOIN_THRESHOLD_B = int(os.environ.get("JOIN_THRESHOLD_B", "3"))
JOIN_THRESHOLD_C = int(os.environ.get("JOIN_THRESHOLD_C", "10"))
LEAVE_THRESHOLD = int(os.environ.get("LEAVE_THRESHOLD", "2"))

WELCOME_MESSAGE = (
    "👋 Willkommen bei *" + GROUP_A_NAME + "*, {name}!\n\n"
    "Schön dass du dabei bist! 🎉\n"
    "Schreib unserem Bot um deinen eigenen Invite-Link zu erstellen! 🚀"
)

AUTO_DELETE_DAYS = 30
DATA_FILE = "/app/storage/data.json"
ALL_GROUP_IDS = [GROUP_A_ID, GROUP_B_ID, GROUP_C_ID]

EXTERNAL_LINK_PATTERN = re.compile(
    r"(https?://)?"
    r"(discord\.(gg|com|io)|t\.me/(?!joinchat)|telegram\.(me|org|dog)|"
    r"wa\.me|whatsapp\.com|chat\.whatsapp\.com|invite\.gg|linktr\.ee)",
    re.IGNORECASE
)

MOD_ABUSE_COUNT = 3
MOD_ABUSE_WINDOW = 30

# States
SUPPORT_CHOOSE = 1
GETOWNER_WAIT_CODE = 40
GETOWNER_WAIT_CONFIRM = 41
UMFRAGE_FRAGE = 10
UMFRAGE_OPTIONEN = 11
UMFRAGE_BESTAETIGEN = 12
MOD_WAIT_ID = 20
MESSAGE_WAIT_GROUP = 30
MESSAGE_WAIT_CONTENT = 31
# ──────────────────────────────────────────────

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

tracked_links: dict[str, dict] = {}
known_users: set[int] = set()
umfrage_data: dict[int, dict] = {}
mod_action_data: dict[int, dict] = {}
message_data: dict[int, dict] = {}
blocked_mods: set[int] = set()
bot_closed: bool = False  # /closebot schaltet den Bot stumm
mod_action_log: dict[int, list] = {}
pending_mod_confirmations: dict[str, dict] = {}
deleted_links_backup: list = []

# Support-Sessions
# { user_id: { "staff_id": int, "support_type": str, "active": bool } }
support_sessions: dict[int, dict] = {}
# Staff → User Mapping
support_staff_map: dict[int, int] = {}


# ──────────────────────────────────────────────
#  Rollen
# ──────────────────────────────────────────────
def is_admin(uid): return uid == ADMIN_ID
def is_supermod(uid): return uid in SUPERMOD_IDS and uid not in blocked_mods
def is_mod(uid): return uid in MODERATOR_IDS and uid not in blocked_mods
def is_admin_or_mod(uid): return is_admin(uid) or is_mod(uid) or is_supermod(uid)

def get_role_label(uid):
    if is_admin(uid): return "👑 Admin"
    if is_supermod(uid): return "⚡ SuperMod"
    if uid in MODERATOR_IDS: return "🛡️ Moderator"
    return "👤 Nutzer"


# ──────────────────────────────────────────────
#  Persistenter Speicher
# ──────────────────────────────────────────────
def save_data():
    try:
        sl = {}
        for link, data in tracked_links.items():
            e = data.copy()
            if isinstance(e.get("created_at"), datetime):
                e["created_at"] = e["created_at"].isoformat()
            e.pop("link_obj", None)
            sl[link] = e
        backup = []
        for item in deleted_links_backup:
            e = item.copy()
            if isinstance(e.get("created_at"), datetime):
                e["created_at"] = e["created_at"].isoformat()
            e.pop("link_obj", None)
            backup.append(e)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "tracked_links": sl,
                "known_users": list(known_users),
                "blocked_mods": list(blocked_mods),
                "deleted_links_backup": backup,
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Speichern: %s", e)


def load_data():
    global tracked_links, known_users, blocked_mods, deleted_links_backup
    if not os.path.exists(DATA_FILE): return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for link, data in raw.get("tracked_links", {}).items():
            if "created_at" in data and isinstance(data["created_at"], str):
                data["created_at"] = datetime.fromisoformat(data["created_at"])
            tracked_links[link] = data
        known_users = set(raw.get("known_users", []))
        blocked_mods = set(raw.get("blocked_mods", []))
        for item in raw.get("deleted_links_backup", []):
            if "created_at" in item and isinstance(item["created_at"], str):
                item["created_at"] = datetime.fromisoformat(item["created_at"])
            deleted_links_backup.append(item)
        logger.info("Geladen: %d Links, %d Nutzer.", len(tracked_links), len(known_users))
    except Exception as e:
        logger.error("Laden: %s", e)


def register_user(uid):
    known_users.add(uid)
    save_data()


# ──────────────────────────────────────────────
#  Hilfsfunktionen
# ──────────────────────────────────────────────
async def kick_from_group(context, gid, uid, gname) -> bool:
    try:
        await context.bot.ban_chat_member(chat_id=gid, user_id=uid)
        await context.bot.unban_chat_member(chat_id=gid, user_id=uid)
        return True
    except: return False


async def revoke_link(context, link_str) -> bool:
    try:
        await context.bot.revoke_chat_invite_link(chat_id=GROUP_A_ID, invite_link=link_str)
        return True
    except: return False


async def notify_staff_all(context, text, keyboard=None):
    for uid in [ADMIN_ID] + SUPERMOD_IDS + MODERATOR_IDS:
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown", reply_markup=keyboard)
        except: pass


def gruppe_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ " + GROUP_A_NAME + " (Gruppe A)", callback_data=f"{action}_g_a")],
        [InlineKeyboardButton("2️⃣ " + GROUP_B_NAME + " (Gruppe B)", callback_data=f"{action}_g_b")],
        [InlineKeyboardButton("3️⃣ " + GROUP_C_NAME + " (Gruppe C)", callback_data=f"{action}_g_c")],
        [InlineKeyboardButton("4️⃣ Alle Gruppen", callback_data=f"{action}_g_all")],
    ])


def get_groups_from_key(key: str) -> list:
    return {
        "a": [(GROUP_A_ID, GROUP_A_NAME)],
        "b": [(GROUP_B_ID, GROUP_B_NAME)],
        "c": [(GROUP_C_ID, GROUP_C_NAME)],
        "all": [(GROUP_A_ID, GROUP_A_NAME), (GROUP_B_ID, GROUP_B_NAME), (GROUP_C_ID, GROUP_C_NAME)],
    }.get(key, [])


USERINFOBOT_TIP = (
    "💡 *Wie bekomme ich die Chat-ID?*\n\n"
    "1. Gehe in eine der Gruppen\n"
    "2. Schreibe *@userinfobot*\n"
    "3. Der Bot antwortet mit der Chat-ID\n\n"
    "Dann schicke mir die Zahl (z.B. `123456789`)"
)


# ──────────────────────────────────────────────
#  Beitritts-/Austrittsnachrichten automatisch löschen
# ──────────────────────────────────────────────
async def delete_service_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Löscht automatisch alle Telegram-Systemnachrichten in den Gruppen."""
    message = update.effective_message
    if not message:
        return
    if message.chat_id not in ALL_GROUP_IDS:
        return
    try:
        await message.delete()
        logger.debug("Service-Nachricht gelöscht in Chat %s", message.chat_id)
    except Exception as e:
        logger.debug("Service-Nachricht konnte nicht gelöscht werden: %s", e)


# ──────────────────────────────────────────────
#  /getowner – Notfall-Admin-Zugang via Google Authenticator
#  Nicht in /help gelistet – nur für Notfälle
# ──────────────────────────────────────────────
async def getowner_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    register_user(user.id)
    if update.effective_chat.type != "private":
        await update.message.reply_text("Bitte nur im privaten Chat nutzen.")
        return ConversationHandler.END
    if not TOTP_SECRET:
        await update.message.reply_text("Kein TOTP Secret konfiguriert.")
        return ConversationHandler.END
    await update.message.reply_text("Gib den aktuellen 6-stelligen Code aus deiner Google Authenticator App ein:")
    return GETOWNER_WAIT_CODE


async def getowner_check_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    code = update.message.text.strip()
    try:
        totp = pyotp.TOTP(TOTP_SECRET)
        valid = totp.verify(code, valid_window=1)
    except Exception as e:
        logger.error("TOTP Fehler: %s", e)
        await update.message.reply_text("Fehler bei der Ueberpruefung. Bitte versuche es erneut.")
        return ConversationHandler.END
    if not valid:
        await update.message.reply_text("Falscher Code! Bitte versuche es erneut mit /getowner.")
        return ConversationHandler.END
    await update.message.reply_text("Code korrekt! Erstelle Einladungslinks ...")
    links = []
    group_info = [(GROUP_A_ID, GROUP_A_NAME), (GROUP_B_ID, GROUP_B_NAME), (GROUP_C_ID, GROUP_C_NAME)]
    for gid, gname in group_info:
        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=gid,
                name="Owner_" + str(user.id) + "_" + datetime.now().strftime("%H%M%S"),
                creates_join_request=False,
            )
            links.append((gid, gname, invite.invite_link))
        except Exception as e:
            links.append((gid, gname, None))
            logger.warning("Link fuer %s fehlgeschlagen: %s", gname, e)
    context.user_data["getowner_links"] = links
    link_lines = []
    for _, gname, lnk in links:
        link_lines.append(gname + ": " + (lnk if lnk else "Fehler"))
    link_text = "\n".join(link_lines)
    await update.message.reply_text(
        "Deine Einladungslinks:\n\n" + link_text + "\n\nTritt allen Gruppen bei und bestatige dann:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Ich bin allen Gruppen beigetreten", callback_data="getowner_confirm")],
            [InlineKeyboardButton("Abbrechen", callback_data="getowner_cancel")],
        ])
    )
    return GETOWNER_WAIT_CONFIRM


async def getowner_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if query.data == "getowner_cancel":
        await query.edit_message_text("Abgebrochen.")
        return ConversationHandler.END
    links = context.user_data.get("getowner_links", [])
    results = []
    for gid, gname, link in links:
        try:
            await context.bot.promote_chat_member(
                chat_id=gid,
                user_id=user.id,
                can_change_info=True,
                can_delete_messages=True,
                can_invite_users=True,
                can_restrict_members=True,
                can_pin_messages=True,
                can_promote_members=True,
                can_manage_chat=True,
                can_manage_video_chats=True,
                is_anonymous=False,
            )
            results.append(gname + " - Admin gesetzt")
            logger.info("User %d zum Admin in %s gemacht.", user.id, gname)
        except Exception as e:
            results.append(gname + ": Fehler - " + str(e))
    user_mention = "@" + user.username if user.username else user.first_name + " (ID: " + str(user.id) + ")"
    try:
        msg = "/getowner wurde genutzt!\n\nNutzer: " + user_mention + "\nID: " + str(user.id) + "\n\nErgebnis:\n" + "\n".join(results)
        await context.bot.send_message(chat_id=ADMIN_ID, text=msg)
    except: pass
    await query.edit_message_text("Du bist jetzt Admin in allen Gruppen!\n\n" + "\n".join(results))
    return ConversationHandler.END


async def getowner_cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Abgebrochen.")
    return ConversationHandler.END


# ──────────────────────────────────────────────
#  Support-System
# ──────────────────────────────────────────────
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    register_user(user.id)

    if bot_closed and not is_admin(user.id):
        await update.message.reply_text("Der Bot ist aktuell nicht verfuegbar.")
        return ConversationHandler.END

    if update.effective_chat.type != "private":
        await update.message.reply_text("Bitte nutze /support nur im privaten Chat!")
        return ConversationHandler.END

    if user.id in support_sessions and support_sessions[user.id].get("active"):
        await update.message.reply_text(
            "💬 Du hast bereits eine aktive Support-Session.\n\n"
            "Schreib einfach weiter oder nutze /closechat um den Chat zu beenden."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🎧 *Support*\n\nWelche Art von Support brauchst du?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👑 Admin-Support", callback_data="support_type_admin")],
            [InlineKeyboardButton("🛡️ Normaler Support (Mod)", callback_data="support_type_mod")],
        ])
    )
    return SUPPORT_CHOOSE


async def support_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user

    support_type = query.data.replace("support_type_", "")

    if support_type == "admin":
        targets = [ADMIN_ID] + list(SUPERMOD_IDS)
        target_label = "Admin/SuperMod"
    else:
        targets = list(MODERATOR_IDS)
        target_label = "Moderator"

    user_mention = f"@{user.username}" if user.username else user.first_name
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Support übernehmen", callback_data=f"support_take_{user.id}_{support_type}")]
    ])

    team_info = (
        f"🎧 *Neue Support-Anfrage!*\n\n"
        f"👤 Nutzer: {user_mention}\n"
        f"🆔 Chat-ID: `{user.id}`\n"
        f"📋 Typ: *{target_label}*"
    )
    await notify_staff_all(context, team_info)

    notified = False
    for uid in targets:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=team_info + "\n\nKlicke um den Support zu übernehmen:",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            notified = True
        except: pass

    if notified:
        support_sessions[user.id] = {"staff_id": None, "support_type": support_type, "active": False}
        await query.edit_message_text(
            "✅ Anfrage weitergeleitet!\n\n"
            "Sobald jemand antwortet, wirst du benachrichtigt. 😊\n\n"
            "_Mit /closechat kannst du die Anfrage abbrechen._",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("❌ Konnte das Team nicht erreichen. Bitte versuche es später.")

    return ConversationHandler.END


async def support_take_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    staff = query.from_user

    if not is_admin_or_mod(staff.id):
        await query.answer("❌ Keine Berechtigung.", show_alert=True)
        return

    parts = query.data.split("_")
    user_id = int(parts[2])
    support_type = parts[3]

    session = support_sessions.get(user_id)
    if not session:
        await query.edit_message_text(query.message.text + "\n\n⚠️ Nutzer hat abgebrochen.", parse_mode="Markdown")
        return

    if session.get("active"):
        await query.answer("⚠️ Wird bereits betreut.", show_alert=True)
        return

    support_sessions[user_id] = {"staff_id": staff.id, "support_type": support_type, "active": True}
    support_staff_map[staff.id] = user_id

    role = get_role_label(staff.id)
    staff_mention = f"@{staff.username}" if staff.username else staff.first_name

    await query.edit_message_text(
        query.message.text + f"\n\n✅ *{role} {staff_mention} hat übernommen.*",
        parse_mode="Markdown"
    )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ *{role} ist jetzt für dich da!*\n\n"
                f"Schreib einfach deine Nachrichten.\n\n"
                f"_Mit /closechat beendest du den Chat._"
            ),
            parse_mode="Markdown"
        )
    except: pass

    try:
        await context.bot.send_message(
            chat_id=staff.id,
            text=(
                f"💬 *Support-Chat gestartet!*\n\n"
                f"🆔 Nutzer-ID: `{user_id}`\n\n"
                f"Schreib einfach – Nachrichten werden weitergeleitet.\n"
                f"_Mit /closechat beendest du den Chat._\n"
                f"_Mit /send admin oder /send smod übergibst du den Chat._"
            ),
            parse_mode="Markdown"
        )
    except: pass


async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    if not is_admin_or_mod(user.id):
        await update.message.reply_text("❌ Keine Berechtigung.")
        return

    if user.id not in support_staff_map:
        await update.message.reply_text("❌ Du führst gerade keinen Support-Chat.")
        return

    if not context.args or context.args[0].lower() not in ("admin", "smod"):
        await update.message.reply_text(
            "ℹ️ Nutzung:\n"
            "`/send admin` – Chat an Admin übergeben\n"
            "`/send smod`  – Chat an SuperMod übergeben",
            parse_mode="Markdown"
        )
        return

    ziel_typ = context.args[0].lower()
    user_id = support_staff_map[user.id]
    session = support_sessions.get(user_id)

    if not session or not session.get("active"):
        await update.message.reply_text("❌ Keine aktive Session gefunden.")
        return

    if ziel_typ == "admin":
        new_targets = [ADMIN_ID]
        ziel_label = "Admin"
    else:
        new_targets = list(SUPERMOD_IDS)
        ziel_label = "SuperMod"

    old_role = get_role_label(user.id)
    old_mention = f"@{user.username}" if user.username else user.first_name

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Chat übernehmen", callback_data=f"support_take_{user_id}_{ziel_typ}")]
    ])

    del support_staff_map[user.id]
    support_sessions[user_id]["active"] = False
    support_sessions[user_id]["staff_id"] = None

    notified = False
    for uid in new_targets:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"🔄 *Chat-Übergabe!*\n\n"
                    f"🛡️ Von: {old_role} {old_mention}\n"
                    f"🆔 Nutzer-ID: `{user_id}`\n\n"
                    f"Klicke um den Chat zu übernehmen:"
                ),
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            notified = True
        except: pass

    if notified:
        await update.message.reply_text(
            f"✅ Chat wurde an *{ziel_label}* übergeben.\n\nDeine Session ist beendet.",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔄 Dein Chat wird an einen *{ziel_label}* übergeben. Bitte warte kurz …",
                parse_mode="Markdown"
            )
        except: pass
    else:
        support_staff_map[user.id] = user_id
        support_sessions[user_id]["active"] = True
        support_sessions[user_id]["staff_id"] = user.id
        await update.message.reply_text(f"❌ Konnte keinen {ziel_label} erreichen. Chat läuft weiter.")


async def support_message_relay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Leitet Nachrichten zwischen Nutzer und Staff weiter."""
    user = update.effective_user
    message = update.effective_message

    if not message or update.effective_chat.type != "private":
        return

    if bot_closed and not is_admin(user.id) and user.id not in support_staff_map and user.id not in support_sessions:
        return

    # Nutzer → Staff
    if user.id in support_sessions and support_sessions[user.id].get("active"):
        session = support_sessions[user.id]
        staff_id = session.get("staff_id")
        if not staff_id:
            return
        user_info = f"💬 *Nutzer* (`{user.id}`):\n"
        try:
            if message.text:
                await context.bot.send_message(chat_id=staff_id, text=user_info + message.text, parse_mode="Markdown")
            elif message.photo:
                await context.bot.send_photo(chat_id=staff_id, photo=message.photo[-1].file_id, caption=f"📷 Nutzer (`{user.id}`): {message.caption or ''}")
            elif message.document:
                await context.bot.send_document(chat_id=staff_id, document=message.document.file_id, caption=f"📎 Nutzer (`{user.id}`): {message.caption or ''}")
            elif message.video:
                await context.bot.send_video(chat_id=staff_id, video=message.video.file_id, caption=f"🎥 Nutzer (`{user.id}`): {message.caption or ''}")
            elif message.voice:
                await context.bot.send_voice(chat_id=staff_id, voice=message.voice.file_id)
            elif message.sticker:
                await context.bot.send_sticker(chat_id=staff_id, sticker=message.sticker.file_id)
        except Exception as e:
            logger.warning("Relay Nutzer→Staff: %s", e)
        return

    # Staff → Nutzer
    if user.id in support_staff_map:
        user_id = support_staff_map[user.id]
        session = support_sessions.get(user_id)
        if not session or not session.get("active"):
            return
        role = get_role_label(user.id)
        role_prefix = f"💬 *{role}*:\n"
        try:
            if message.text:
                await context.bot.send_message(chat_id=user_id, text=role_prefix + message.text, parse_mode="Markdown")
            elif message.photo:
                await context.bot.send_photo(chat_id=user_id, photo=message.photo[-1].file_id, caption=f"📷 {role}: {message.caption or ''}")
            elif message.document:
                await context.bot.send_document(chat_id=user_id, document=message.document.file_id, caption=f"📎 {role}: {message.caption or ''}")
            elif message.video:
                await context.bot.send_video(chat_id=user_id, video=message.video.file_id, caption=f"🎥 {role}: {message.caption or ''}")
            elif message.voice:
                await context.bot.send_voice(chat_id=user_id, voice=message.voice.file_id)
            elif message.sticker:
                await context.bot.send_sticker(chat_id=user_id, sticker=message.sticker.file_id)
        except Exception as e:
            logger.warning("Relay Staff→Nutzer: %s", e)


async def close_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/closechat – für alle: Nutzer, Mods, SuperMods, Admin."""
    user = update.effective_user

    # Nutzer schließt
    if user.id in support_sessions:
        session = support_sessions.pop(user.id)
        staff_id = session.get("staff_id")
        if staff_id and staff_id in support_staff_map:
            del support_staff_map[staff_id]
            try:
                await context.bot.send_message(
                    chat_id=staff_id,
                    text="🔒 *Support-Chat wurde vom Nutzer beendet.*",
                    parse_mode="Markdown"
                )
            except: pass
        await update.message.reply_text("🔒 Support-Chat beendet.")
        return

    # Staff schließt
    if user.id in support_staff_map:
        user_id = support_staff_map.pop(user.id)
        if user_id in support_sessions:
            del support_sessions[user_id]
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🔒 *Der Support-Chat wurde beendet.*\n\n"
                    "Für weitere Hilfe nutze /support."
                ),
                parse_mode="Markdown"
            )
        except: pass
        await update.message.reply_text("🔒 Support-Chat beendet.")
        return

    await update.message.reply_text("Du hast keinen aktiven Support-Chat.")


async def support_cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Support abgebrochen.")
    return ConversationHandler.END


# ──────────────────────────────────────────────
#  Missbrauchserkennung
# ──────────────────────────────────────────────
def log_mod_action(mod_id: int) -> bool:
    now = datetime.now()
    if mod_id not in mod_action_log:
        mod_action_log[mod_id] = []
    mod_action_log[mod_id] = [t for t in mod_action_log[mod_id] if (now - t).total_seconds() <= MOD_ABUSE_WINDOW]
    mod_action_log[mod_id].append(now)
    return len(mod_action_log[mod_id]) >= MOD_ABUSE_COUNT


async def notify_abuse(context, mod_id: int, action: str, target_id: int, gruppen: list):
    import uuid
    pending_id = str(uuid.uuid4())[:8]
    pending_mod_confirmations[pending_id] = {
        "mod_id": mod_id, "action": action, "target_id": target_id,
        "gruppen": gruppen, "timestamp": datetime.now().isoformat(),
    }
    gruppen_str = ", ".join([g for _, g in gruppen])
    labels = {"kick": "kicken", "ban": "bannen", "mute": "stummschalten", "unmute": "entstummen"}
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 1. Zulassen", callback_data=f"abuse_allow_{pending_id}")],
        [InlineKeyboardButton("❌ 2. Ablehnen", callback_data=f"abuse_deny_{pending_id}")],
        [InlineKeyboardButton("🚫 3. Ablehnen + Mod entfernen", callback_data=f"abuse_remove_{pending_id}")],
    ])
    msg = (
        f"⚠️ *Missbrauchsverdacht!*\n\n"
        f"🛡️ Mod-ID: `{mod_id}`\n"
        f"⚡ Aktion: *{labels.get(action, action)}*\n"
        f"🎯 Ziel: `{target_id}`\n"
        f"🏠 Gruppen: *{gruppen_str}*\n\n"
        f"Zu viele Aktionen – *pausiert.*"
    )
    for uid in [ADMIN_ID] + list(SUPERMOD_IDS):
        try:
            await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown", reply_markup=keyboard)
        except: pass


async def abuse_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if not (is_admin(user.id) or is_supermod(user.id)):
        await query.answer("❌ Keine Berechtigung.", show_alert=True)
        return
    parts = query.data.split("_")
    decision = parts[1]
    pending_id = parts[2]
    pending = pending_mod_confirmations.pop(pending_id, None)
    if not pending:
        await query.edit_message_text(query.message.text + "\n\n⚠️ Anfrage abgelaufen.", parse_mode="Markdown")
        return
    mod_id = pending["mod_id"]
    action = pending["action"]
    target_id = pending["target_id"]
    gruppen = pending["gruppen"]
    role = get_role_label(user.id)
    if decision == "allow":
        results = await _execute_mod_action(context, action, target_id, gruppen)
        await query.edit_message_text(query.message.text + f"\n\n✅ *Zugelassen ({role}).*\n" + "\n".join(results), parse_mode="Markdown")
        try: await context.bot.send_message(chat_id=mod_id, text="✅ Deine Aktion wurde *genehmigt*.", parse_mode="Markdown")
        except: pass
    elif decision == "deny":
        await query.edit_message_text(query.message.text + f"\n\n❌ *Abgelehnt ({role}).*", parse_mode="Markdown")
        try: await context.bot.send_message(chat_id=mod_id, text="❌ Deine Aktion wurde *abgelehnt*.", parse_mode="Markdown")
        except: pass
    elif decision == "remove":
        blocked_mods.add(mod_id)
        save_data()
        await query.edit_message_text(query.message.text + f"\n\n🚫 *Abgelehnt + Mod entfernt ({role}).*", parse_mode="Markdown")
        try: await context.bot.send_message(chat_id=mod_id, text="🚫 Du wurdest als Moderator *entfernt*.", parse_mode="Markdown")
        except: pass


async def _execute_mod_action(context, action: str, target_id: int, gruppen: list) -> list:
    results = []
    for gid, gname in gruppen:
        try:
            if action == "kick":
                await context.bot.ban_chat_member(chat_id=gid, user_id=target_id)
                await context.bot.unban_chat_member(chat_id=gid, user_id=target_id)
                results.append(f"✅ {gname}")
            elif action == "ban":
                await context.bot.ban_chat_member(chat_id=gid, user_id=target_id)
                results.append(f"✅ {gname}")
            elif action == "mute":
                await context.bot.restrict_chat_member(chat_id=gid, user_id=target_id, permissions=ChatPermissions(can_send_messages=False, can_send_audios=False, can_send_documents=False, can_send_photos=False, can_send_videos=False, can_send_video_notes=False, can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False, can_add_web_page_previews=False))
                results.append(f"✅ {gname}")
            elif action == "unmute":
                await context.bot.restrict_chat_member(chat_id=gid, user_id=target_id, permissions=ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True))
                results.append(f"✅ {gname}")
        except Exception as e:
            results.append(f"❌ {gname}: {e}")
    return results


# ──────────────────────────────────────────────
#  Mod-Aktionen
# ──────────────────────────────────────────────
async def _mod_start(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> int:
    user = update.effective_user
    if not is_admin_or_mod(user.id):
        if user.id in blocked_mods:
            await update.message.reply_text("🚫 Du hast keinen Zugriff mehr auf Bot-Funktionen.")
        else:
            await update.message.reply_text("❌ Keine Berechtigung.")
        return ConversationHandler.END
    mod_action_data.pop(user.id, None)
    mod_action_data[user.id] = {"action": action}
    labels = {"kick": "kicken", "ban": "bannen", "mute": "stummschalten", "unmute": "entstummen"}
    await update.message.reply_text(
        f"🔍 Wen möchtest du *{labels[action]}*?\n\n"
        f"Schicke mir die *Chat-ID*.\n\n"
        f"{USERINFOBOT_TIP}\n\n_(Mit /cancel abbrechen)_",
        parse_mode="Markdown"
    )
    return MOD_WAIT_ID


async def kick_start(u, c): return await _mod_start(u, c, "kick")
async def ban_start(u, c): return await _mod_start(u, c, "ban")
async def mute_start(u, c): return await _mod_start(u, c, "mute")
async def unmute_start(u, c): return await _mod_start(u, c, "unmute")


async def mod_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin_or_mod(user.id): return ConversationHandler.END
    data = mod_action_data.get(user.id)
    if not data: return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.lstrip("-").isdigit():
        await update.message.reply_text(f"❌ Nur Chat-ID (Zahlen) eingeben.\n\n{USERINFOBOT_TIP}", parse_mode="Markdown")
        return MOD_WAIT_ID
    target_id = int(raw)
    data["target_id"] = target_id
    await update.message.reply_text(f"✅ Chat-ID: `{target_id}`\n\nIn welcher Gruppe?", parse_mode="Markdown", reply_markup=gruppe_keyboard(f"modact_{target_id}"))
    return ConversationHandler.END


async def mod_cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    mod_action_data.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Aktion abgebrochen.")
    return ConversationHandler.END


async def mod_gruppe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin_or_mod(query.from_user.id): return
    parts = query.data.split("_")
    target_id = int(parts[1])
    gruppe_key = parts[3]
    data = mod_action_data.get(query.from_user.id, {})
    action = data.get("action", "")
    role = get_role_label(query.from_user.id)
    gruppen = get_groups_from_key(gruppe_key)
    labels = {"kick": "gekickt", "ban": "gebannt", "mute": "stummgeschaltet", "unmute": "entstummt"}

    if is_mod(query.from_user.id) and not is_admin(query.from_user.id) and not is_supermod(query.from_user.id):
        if log_mod_action(query.from_user.id):
            await query.edit_message_text("⏳ *Aktion pausiert* – zur Überprüfung weitergeleitet.", parse_mode="Markdown")
            await notify_abuse(context, query.from_user.id, action, target_id, gruppen)
            return

    results = await _execute_mod_action(context, action, target_id, gruppen)
    await query.edit_message_text(
        f"🎯 *Aktion abgeschlossen!*\n\n🆔 `{target_id}`\n⚡ *{labels.get(action, action)}*\n\n"
        + "\n".join(results) + f"\n\n_{role}_",
        parse_mode="Markdown"
    )

    if is_mod(query.from_user.id) and not is_admin(query.from_user.id):
        gruppen_str = ", ".join([g for _, g in gruppen])
        for uid in [ADMIN_ID] + list(SUPERMOD_IDS):
            try:
                await context.bot.send_message(chat_id=uid, text=f"📋 *Mod-Aktion*\n\n🛡️ Mod: `{query.from_user.id}`\n⚡ *{labels.get(action, action)}*\n🎯 `{target_id}`\n🏠 {gruppen_str}", parse_mode="Markdown")
            except: pass

    mod_action_data.pop(query.from_user.id, None)


# ──────────────────────────────────────────────
#  /open /close
# ──────────────────────────────────────────────
async def open_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("❌ Keine Berechtigung.")
        return
    await update.message.reply_text("🔓 In welcher Gruppe öffnen?", reply_markup=gruppe_keyboard("open"))


async def close_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("❌ Keine Berechtigung.")
        return
    await update.message.reply_text("🔒 In welcher Gruppe schließen?", reply_markup=gruppe_keyboard("close"))


async def open_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin_or_mod(query.from_user.id): return
    parts = query.data.split("_")
    action = parts[0]
    gruppe_key = parts[2]
    gruppen = get_groups_from_key(gruppe_key)
    role = get_role_label(query.from_user.id)
    is_open = action == "open"
    perms = ChatPermissions(can_send_messages=is_open, can_send_audios=is_open, can_send_documents=is_open, can_send_photos=is_open, can_send_videos=is_open, can_send_video_notes=is_open, can_send_voice_notes=is_open, can_send_polls=is_open, can_send_other_messages=is_open, can_add_web_page_previews=is_open)
    results = []
    for gid, gname in gruppen:
        try:
            await context.bot.set_chat_permissions(chat_id=gid, permissions=perms)
            results.append(f"✅ {gname}")
        except Exception as e:
            results.append(f"❌ {gname}: {e}")
    emoji = "🔓" if is_open else "🔒"
    verb = "geöffnet" if is_open else "geschlossen"
    await query.edit_message_text(f"{emoji} *{verb}!*\n\n" + "\n".join(results) + f"\n\n_{role}_", parse_mode="Markdown")


# ──────────────────────────────────────────────
#  MODERATION – Externe Links
# ──────────────────────────────────────────────
async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message: Message = update.effective_message
    if not message: return
    chat_id = message.chat_id
    if chat_id not in ALL_GROUP_IDS: return
    user = message.from_user
    if user and is_admin_or_mod(user.id): return
    text = message.text or message.caption or ""
    urls = [e.url for e in (message.entities or []) + (message.caption_entities or []) if e.url]
    if not EXTERNAL_LINK_PATTERN.search(text + " " + " ".join(urls)): return
    try: await message.delete()
    except: pass
    try:
        await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user.id, permissions=ChatPermissions(can_send_messages=False, can_send_audios=False, can_send_documents=False, can_send_photos=False, can_send_videos=False, can_send_video_notes=False, can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False, can_add_web_page_previews=False, can_change_info=False, can_invite_users=False, can_pin_messages=False))
    except: pass
    group_names = {GROUP_A_ID: GROUP_A_NAME, GROUP_B_ID: GROUP_B_NAME, GROUP_C_ID: GROUP_C_NAME}
    user_mention = f"@{user.username}" if user.username else f"{user.first_name} (ID: {user.id})"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Bannen", callback_data=f"mod_ban_{chat_id}_{user.id}"), InlineKeyboardButton("🔊 Entstummen", callback_data=f"mod_unmute_{chat_id}_{user.id}")]])
    await notify_staff_all(context, text=f"⚠️ *Externer Link!*\n\n👤 {user_mention}\n🏠 *{group_names.get(chat_id)}*\n🔗 `{text[:200]}`\n\nStummgeschaltet.", keyboard=keyboard)


async def moderation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin_or_mod(query.from_user.id):
        await query.answer("❌ Keine Berechtigung.", show_alert=True)
        return
    parts = query.data.split("_")
    action, chat_id, user_id = parts[1], int(parts[2]), int(parts[3])
    group_names = {GROUP_A_ID: GROUP_A_NAME, GROUP_B_ID: GROUP_B_NAME, GROUP_C_ID: GROUP_C_NAME}
    role = get_role_label(query.from_user.id)
    if action == "ban":
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await query.edit_message_text(query.message.text + f"\n\n✅ *Gebannt.* _{role}_", parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(query.message.text + f"\n\n❌ {e}", parse_mode="Markdown")
    elif action == "unmute":
        try:
            await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True))
            await query.edit_message_text(query.message.text + f"\n\n✅ *Entstummt in {group_names.get(chat_id)}.* _{role}_", parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(query.message.text + f"\n\n❌ {e}", parse_mode="Markdown")


# ──────────────────────────────────────────────
#  /message mit Medien
# ──────────────────────────────────────────────
async def message_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ Keine Berechtigung.")
        return ConversationHandler.END
    message_data.pop(user.id, None)
    message_data[user.id] = {}
    await update.message.reply_text(
        "📨 *Nachricht senden*\n\nIn welche Gruppe?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("1️⃣ " + GROUP_A_NAME + " (Gruppe A)", callback_data="msg_gruppe_a")],
            [InlineKeyboardButton("2️⃣ " + GROUP_B_NAME + " (Gruppe B)", callback_data="msg_gruppe_b")],
            [InlineKeyboardButton("3️⃣ " + GROUP_C_NAME + " (Gruppe C)", callback_data="msg_gruppe_c")],
            [InlineKeyboardButton("4️⃣ Alle Gruppen", callback_data="msg_gruppe_all")],
        ])
    )
    return MESSAGE_WAIT_GROUP


async def message_gruppe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id): return ConversationHandler.END
    gruppe = query.data.replace("msg_gruppe_", "")
    message_data[query.from_user.id] = {"gruppe": gruppe}
    namen = {"a": GROUP_A_NAME, "b": GROUP_B_NAME, "c": GROUP_C_NAME, "all": "Alle Gruppen"}
    await query.edit_message_text(f"✅ Gruppe: *{namen[gruppe]}*\n\n✏️ Was schicke ich?\n_(Text, Bild, Datei, Video …)_", parse_mode="Markdown")
    return MESSAGE_WAIT_CONTENT


async def message_content_erhalten(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.id): return ConversationHandler.END
    daten = message_data.get(user.id)
    if not daten or "gruppe" not in daten: return ConversationHandler.END
    message = update.effective_message
    gruppen = get_groups_from_key(daten["gruppe"])
    results = []
    for gid, gname in gruppen:
        try:
            if message.text:
                await context.bot.send_message(chat_id=gid, text=message.text)
            elif message.photo:
                await context.bot.send_photo(chat_id=gid, photo=message.photo[-1].file_id, caption=message.caption or "")
            elif message.document:
                await context.bot.send_document(chat_id=gid, document=message.document.file_id, caption=message.caption or "")
            elif message.video:
                await context.bot.send_video(chat_id=gid, video=message.video.file_id, caption=message.caption or "")
            elif message.audio:
                await context.bot.send_audio(chat_id=gid, audio=message.audio.file_id, caption=message.caption or "")
            elif message.voice:
                await context.bot.send_voice(chat_id=gid, voice=message.voice.file_id)
            elif message.sticker:
                await context.bot.send_sticker(chat_id=gid, sticker=message.sticker.file_id)
            else:
                results.append(f"⚠️ {gname}: Dateityp nicht unterstützt")
                continue
            results.append(f"✅ {gname}")
        except Exception as e:
            results.append(f"❌ {gname}: {e}")
    message_data.pop(user.id, None)
    await update.message.reply_text(f"📨 *Gesendet!*\n\n" + "\n".join(results), parse_mode="Markdown")
    return ConversationHandler.END


async def message_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message_data.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Abgebrochen.")
    return ConversationHandler.END


# ──────────────────────────────────────────────
#  /returnall
# ──────────────────────────────────────────────
async def return_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not (is_admin(user.id) or is_supermod(user.id)):
        await update.message.reply_text("❌ Keine Berechtigung.")
        return
    if not deleted_links_backup:
        await update.message.reply_text("📭 Kein Backup vorhanden.")
        return
    restored, skipped = 0, 0
    for item in deleted_links_backup:
        link_str = item.get("link_str")
        data = item.get("data")
        if not link_str or not data: continue
        if link_str in tracked_links:
            skipped += 1
            continue
        try:
            creator_id = data.get("creator_id")
            mode = data.get("mode", "b")
            new_invite: ChatInviteLink = await context.bot.create_chat_invite_link(chat_id=GROUP_A_ID, name=f"Restored_{creator_id}_{datetime.now().strftime('%H%M%S')}", creates_join_request=False)
            new_link = new_invite.invite_link
            data["restored"] = True
            tracked_links[new_link] = data
            try:
                await context.bot.send_message(chat_id=data["creator_chat_id"], text=f"♻️ *Dein Invite-Link wurde wiederhergestellt!*\n\nNeuer Link: `{new_link}`", parse_mode="Markdown")
            except: pass
            restored += 1
        except Exception as e:
            logger.warning("Wiederherstellen: %s", e)
            skipped += 1
    deleted_links_backup.clear()
    save_data()
    await update.message.reply_text(f"♻️ *Wiederherstellung abgeschlossen!*\n\n✅ {restored}\n⏭️ Übersprungen: {skipped}", parse_mode="Markdown")


# ──────────────────────────────────────────────
#  /createlink
# ──────────────────────────────────────────────
async def create_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    register_user(user.id)
    if bot_closed and not is_admin(user.id):
        await update.message.reply_text("Der Bot ist aktuell nicht verfuegbar.")
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text("Bitte schreib mir direkt als DM!")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔵 Option 1 – {GROUP_B_NAME} ({JOIN_THRESHOLD_B} Einladungen)", callback_data="createlink_b")],
        [InlineKeyboardButton(f"⭐ Option 2 – {GROUP_C_NAME} ({JOIN_THRESHOLD_C} Einladungen)", callback_data="createlink_c")],
    ])
    await update.message.reply_text(
        f"🔗 *Welchen Link moechtest du erstellen?*\n\n🔵 *Option 1 – {GROUP_B_NAME}*\nLade {JOIN_THRESHOLD_B} Personen ein → Link fuer {GROUP_B_NAME}\n\n⭐ *Option 2 – {GROUP_C_NAME}*\nLade {JOIN_THRESHOLD_C} Personen ein → Link fuer {GROUP_C_NAME}",
        parse_mode="Markdown", reply_markup=keyboard)


async def createlink_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    register_user(user.id)
    mode = "b" if query.data == "createlink_b" else "c"
    threshold = JOIN_THRESHOLD_B if mode == "b" else JOIN_THRESHOLD_C
    target_name = GROUP_B_NAME if mode == "b" else GROUP_C_NAME
    await query.edit_message_text("⏳ Erstelle Link …")
    try:
        invite: ChatInviteLink = await context.bot.create_chat_invite_link(chat_id=GROUP_A_ID, name=f"Invite{mode.upper()}_{user.id}_{datetime.now().strftime('%H%M%S')}", creates_join_request=False)
    except:
        await query.edit_message_text("❌ Konnte keinen Link erstellen. Bin ich Admin in " + GROUP_A_NAME + "?")
        return
    link_str = invite.invite_link
    tracked_links[link_str] = {"creator_id": user.id, "creator_chat_id": query.message.chat_id, "count": 0, "leave_count": 0, "mode": mode, "done": False, "kicked": False, "created_at": datetime.now()}
    save_data()
    await query.edit_message_text(f"✅ Dein Invite-Link:\n\n`{link_str}`\n\nSobald *{threshold} Personen* beitreten → Link für *{target_name}*! 🎯\n\n⚠️ Bei {LEAVE_THRESHOLD} Austritten → Kick aus allen Gruppen\n\n🗑️ /delete löscht deinen Link.", parse_mode="Markdown")


# ──────────────────────────────────────────────
#  /delete
# ──────────────────────────────────────────────
async def delete_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    register_user(user.id)
    if is_admin_or_mod(user.id):
        zero_links = [(l, d) for l, d in tracked_links.items() if d["count"] == 0]
        if not zero_links:
            await update.message.reply_text("✅ Keine Links mit 0 Einladungen.")
            return
        for link_str, data in zero_links:
            await revoke_link(context, link_str)
            tracked_links.pop(link_str, None)
            try: await context.bot.send_message(chat_id=data["creator_chat_id"], text="🗑️ Dein Link wurde gelöscht (0 Einladungen).\n\nNeu mit /createlink.", parse_mode="Markdown")
            except: pass
        save_data()
        await update.message.reply_text(f"✅ {len(zero_links)} Link(s) gelöscht.")
        return
    user_links = [(l, d) for l, d in tracked_links.items() if d["creator_id"] == user.id]
    if not user_links:
        await update.message.reply_text("Du hast keinen aktiven Link. Erstelle einen mit /createlink!")
        return
    for link_str, _ in user_links:
        await revoke_link(context, link_str)
        tracked_links.pop(link_str, None)
    save_data()
    await update.message.reply_text("🗑️ Dein Link wurde gelöscht. Neu mit /createlink!")


# ──────────────────────────────────────────────
#  /deleteall
# ──────────────────────────────────────────────
async def delete_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not (is_admin(user.id) or is_supermod(user.id)):
        await update.message.reply_text("❌ Keine Berechtigung.")
        return
    all_links = list(tracked_links.items())
    if not all_links:
        await update.message.reply_text("✅ Keine aktiven Links.")
        return
    deleted_links_backup.clear()
    for link_str, data in all_links:
        deleted_links_backup.append({"link_str": link_str, "data": data.copy()})
    await update.message.reply_text(f"⏳ Lösche {len(all_links)} Links …")
    deleted, notified = 0, 0
    for link_str, data in all_links:
        await revoke_link(context, link_str)
        tracked_links.pop(link_str, None)
        deleted += 1
        try:
            await context.bot.send_message(chat_id=data["creator_chat_id"], text="🗑️ Dein Link wurde gelöscht.\n\nNeu mit /createlink.", parse_mode="Markdown")
            notified += 1
        except: pass
    save_data()
    await update.message.reply_text(f"✅ Alle Links gelöscht!\n• {deleted} gelöscht\n• {notified} benachrichtigt\n\n💡 /returnall stellt sie wieder her.")


# ──────────────────────────────────────────────
#  /see
# ──────────────────────────────────────────────
async def see_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not (is_admin(user.id) or is_supermod(user.id)):
        await update.message.reply_text("❌ Keine Berechtigung.")
        return
    now = datetime.now()
    wl = [(l, d) for l, d in tracked_links.items() if d.get("created_at") and d["created_at"] >= now - timedelta(days=7)]
    if not wl:
        await update.message.reply_text("📊 Diese Woche keine Links.")
        return
    lines = [f"📊 *Wochenstatistik* ({now.strftime('%d.%m.%Y')})\n", f"🔗 Links: *{len(wl)}*", f"👥 Beitritte: *{sum(d['count'] for _, d in wl)}*", f"✅ Ziel B: *{sum(1 for _, d in wl if d.get('done') and d.get('mode')=='b')}*", f"⭐ Ziel C: *{sum(1 for _, d in wl if d.get('done') and d.get('mode')=='c')}*", f"🚫 Gekickt: *{sum(1 for _, d in wl if d.get('kicked'))}*\n📋 *Links:*"]
    for _, data in wl:
        mode = data.get("mode", "b")
        t = JOIN_THRESHOLD_B if mode == "b" else JOIN_THRESHOLD_C
        target = GROUP_B_NAME if mode == "b" else GROUP_C_NAME
        st = "✅" if data.get("done") else "🚫" if data.get("kicked") else "⏳"
        lines.append(f"{st} Link uses {data['count']}/{t} → {target}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
#  /free
# ──────────────────────────────────────────────
async def free_links(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Nur der Admin kann /free nutzen.")
        return
    results = []
    for gid, name, emoji in [(GROUP_B_ID, GROUP_B_NAME, "🔵"), (GROUP_C_ID, GROUP_C_NAME, "⭐")]:
        try:
            inv: ChatInviteLink = await context.bot.create_chat_invite_link(chat_id=gid, name=f"Free_{datetime.now().strftime('%d%m%Y_%H%M%S')}", creates_join_request=False, member_limit=10)
            results.append(f"{emoji} *{name}* (max. 10):\n`{inv.invite_link}`")
        except Exception as e:
            results.append(f"{emoji} *{name}*: ❌ {e}")
    await update.message.reply_text("🎟️ *Freie Links:*\n\n" + "\n\n".join(results), parse_mode="Markdown")


# ──────────────────────────────────────────────
#  /global
# ──────────────────────────────────────────────
async def global_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin_or_mod(user.id):
        await update.message.reply_text("❌ Keine Berechtigung.")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Nutzung: `/global Nachricht`", parse_mode="Markdown")
        return
    if is_admin(user.id): absender = "👑 *Nachricht vom Admin:*"
    elif is_supermod(user.id): absender = "⚡ *Nachricht vom SuperMod:*"
    else: absender = "🛡️ *Nachricht vom Moderator:*"
    msg = f"📢 {absender}\n\n{' '.join(context.args)}"
    success, failed = 0, 0
    for uid in known_users:
        try:
            await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
            success += 1
        except: failed += 1
    await update.message.reply_text(f"✅ Fertig!\n• Erfolgreich: {success}\n• Fehlgeschlagen: {failed}")


# ──────────────────────────────────────────────
#  /umfrage
# ──────────────────────────────────────────────
async def umfrage_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("❌ Keine Berechtigung.")
        return ConversationHandler.END
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ " + GROUP_A_NAME + " (Gruppe A)", callback_data="umfrage_gruppe_a")],
        [InlineKeyboardButton("2️⃣ " + GROUP_B_NAME + " (Gruppe B)", callback_data="umfrage_gruppe_b")],
        [InlineKeyboardButton("3️⃣ " + GROUP_C_NAME + " (Gruppe C)", callback_data="umfrage_gruppe_c")],
        [InlineKeyboardButton("4️⃣ Alle Gruppen", callback_data="umfrage_gruppe_all")],
    ])
    await update.message.reply_text("📊 *Umfrage erstellen*\n\nIn welche Gruppe?", parse_mode="Markdown", reply_markup=keyboard)
    return UMFRAGE_FRAGE


async def umfrage_gruppe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin_or_mod(query.from_user.id): return ConversationHandler.END
    gruppe = query.data.replace("umfrage_gruppe_", "")
    umfrage_data[query.from_user.id] = {"gruppe": gruppe, "optionen": []}
    namen = {"a": GROUP_A_NAME, "b": GROUP_B_NAME, "c": GROUP_C_NAME, "all": "Alle Gruppen"}
    await query.edit_message_text(f"✅ Gruppe: *{namen[gruppe]}*\n\n📝 Die *Frage*?", parse_mode="Markdown")
    return UMFRAGE_FRAGE


async def umfrage_frage_erhalten(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin_or_mod(user.id): return ConversationHandler.END
    umfrage_data[user.id]["frage"] = update.message.text
    await update.message.reply_text(f"✅ Frage: *{update.message.text}*\n\n🔢 Wie viele Optionen?", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("2", callback_data="umfrage_anzahl_2"), InlineKeyboardButton("3", callback_data="umfrage_anzahl_3"), InlineKeyboardButton("4", callback_data="umfrage_anzahl_4")],
            [InlineKeyboardButton("5", callback_data="umfrage_anzahl_5"), InlineKeyboardButton("6", callback_data="umfrage_anzahl_6"), InlineKeyboardButton("7", callback_data="umfrage_anzahl_7")],
            [InlineKeyboardButton("8", callback_data="umfrage_anzahl_8"), InlineKeyboardButton("9", callback_data="umfrage_anzahl_9"), InlineKeyboardButton("10", callback_data="umfrage_anzahl_10")],
        ]))
    return UMFRAGE_OPTIONEN


async def umfrage_anzahl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin_or_mod(query.from_user.id): return ConversationHandler.END
    anzahl = int(query.data.replace("umfrage_anzahl_", ""))
    umfrage_data[query.from_user.id].update({"anzahl": anzahl, "optionen": []})
    await query.edit_message_text(f"✅ Anzahl: *{anzahl}*\n\n✏️ *Option 1* von {anzahl}:", parse_mode="Markdown")
    return UMFRAGE_OPTIONEN


async def umfrage_option_erhalten(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin_or_mod(user.id): return ConversationHandler.END
    daten = umfrage_data.get(user.id)
    if not daten: return ConversationHandler.END
    daten["optionen"].append(update.message.text)
    aktuelle = len(daten["optionen"])
    gesamt = daten.get("anzahl", 4)
    if aktuelle < gesamt:
        await update.message.reply_text(f"✅ Option {aktuelle}: *{update.message.text}*\n\n✏️ *Option {aktuelle + 1}* von {gesamt}:", parse_mode="Markdown")
        return UMFRAGE_OPTIONEN
    namen = {"a": GROUP_A_NAME, "b": GROUP_B_NAME, "c": GROUP_C_NAME, "all": "Alle Gruppen"}
    optionen_text = "\n".join([f"  {i+1}. {o}" for i, o in enumerate(daten["optionen"])])
    await update.message.reply_text(f"📊 *Vorschau:*\n\n🏠 *{namen[daten['gruppe']]}*\n❓ *{daten['frage']}*\n\n{optionen_text}\n\nAbschicken?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Absenden", callback_data="umfrage_senden"), InlineKeyboardButton("❌ Abbrechen", callback_data="umfrage_abbrechen")]]))
    return UMFRAGE_BESTAETIGEN


async def umfrage_senden_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin_or_mod(query.from_user.id): return ConversationHandler.END
    daten = umfrage_data.get(query.from_user.id)
    if not daten or query.data == "umfrage_abbrechen":
        umfrage_data.pop(query.from_user.id, None)
        await query.edit_message_text("❌ Umfrage abgebrochen.")
        return ConversationHandler.END
    ziel = {"all": [(GROUP_A_ID, GROUP_A_NAME), (GROUP_B_ID, GROUP_B_NAME), (GROUP_C_ID, GROUP_C_NAME)], "a": [(GROUP_A_ID, GROUP_A_NAME)], "b": [(GROUP_B_ID, GROUP_B_NAME)], "c": [(GROUP_C_ID, GROUP_C_NAME)]}.get(daten["gruppe"], [])
    erfolg, fehler = [], []
    for gid, gname in ziel:
        try:
            await context.bot.send_poll(chat_id=gid, question=daten["frage"], options=daten["optionen"], is_anonymous=True)
            erfolg.append(gname)
        except Exception as e:
            fehler.append(f"{gname}: {e}")
    umfrage_data.pop(query.from_user.id, None)
    ergebnis = (f"✅ *{', '.join(erfolg)}*\n" if erfolg else "") + (f"❌ {', '.join(fehler)}" if fehler else "")
    await query.edit_message_text(f"📊 Abgeschickt!\n\n{ergebnis}", parse_mode="Markdown")
    return ConversationHandler.END


async def umfrage_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    umfrage_data.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Umfrage abgebrochen.")
    return ConversationHandler.END


# ──────────────────────────────────────────────
#  Chat-Member-Handler
# ──────────────────────────────────────────────
async def track_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.chat_member
    if result.chat.id != GROUP_A_ID: return
    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    new_member = result.new_chat_member.user
    joined = old_status in ("left", "kicked") and new_status == "member"
    left = old_status == "member" and new_status in ("left", "kicked")
    if joined:
        try: await context.bot.send_message(chat_id=GROUP_A_ID, text=WELCOME_MESSAGE.format(name=new_member.first_name or "dort"), parse_mode="Markdown")
        except: pass
    invite_link = result.invite_link
    if not invite_link: return
    link_str = invite_link.invite_link
    if link_str not in tracked_links: return
    data = tracked_links[link_str]
    mode = data.get("mode", "b")
    threshold = JOIN_THRESHOLD_B if mode == "b" else JOIN_THRESHOLD_C
    if joined:
        data["count"] += 1
        save_data()
        try: await context.bot.send_message(chat_id=data["creator_chat_id"], text=f"👤 Jemand beigetreten! ({data['count']}/{threshold})")
        except: pass
        if data["count"] >= threshold: await handle_threshold_reached(context, link_str, data)
    elif left:
        data["leave_count"] += 1
        save_data()
        try: await context.bot.send_message(chat_id=data["creator_chat_id"], text=f"⚠️ Jemand hat die Gruppe verlassen! ({data['leave_count']}/{LEAVE_THRESHOLD})")
        except: pass
        if data["leave_count"] >= LEAVE_THRESHOLD: await handle_kick_creator(context, link_str, data)


async def handle_threshold_reached(context, link_str, data):
    if data.get("done"): return
    data["done"] = True
    save_data()
    mode = data.get("mode", "b")
    target_id = GROUP_B_ID if mode == "b" else GROUP_C_ID
    target_name = GROUP_B_NAME if mode == "b" else GROUP_C_NAME
    threshold = JOIN_THRESHOLD_B if mode == "b" else JOIN_THRESHOLD_C
    try:
        inv: ChatInviteLink = await context.bot.create_chat_invite_link(chat_id=target_id, name=f"Reward_{data['creator_id']}_{datetime.now().strftime('%H%M%S')}", creates_join_request=False, member_limit=1)
        await context.bot.send_message(chat_id=data["creator_chat_id"], text=f"🎉 *Ziel erreicht!* {threshold} Personen beigetreten.\n\nLink für *{target_name}*:\n\n`{inv.invite_link}`\n\n⚠️ Nur *einmal* nutzbar!", parse_mode="Markdown")
    except Exception as e: logger.error("Reward-Link Fehler: %s", e)


async def handle_kick_creator(context, link_str, data):
    if data.get("kicked"): return
    data["kicked"] = True
    save_data()
    creator_id = data["creator_id"]
    kicked_names = [gname for gid, gname in [(GROUP_A_ID, GROUP_A_NAME), (GROUP_B_ID, GROUP_B_NAME), (GROUP_C_ID, GROUP_C_NAME)] if await kick_from_group(context, gid, creator_id, gname)]
    msg = f"🚫 Du wurdest aus *{', '.join(kicked_names)}* entfernt." if kicked_names else "⚠️ Kick fehlgeschlagen."
    try: await context.bot.send_message(chat_id=data["creator_chat_id"], text=msg, parse_mode="Markdown")
    except: pass


# ──────────────────────────────────────────────
#  /set – Schwellenwerte zur Laufzeit ändern (nur Admin)
#  Nutzung:
#    /set joinb 5      → JOIN_THRESHOLD_B = 5
#    /set joinc 15     → JOIN_THRESHOLD_C = 15
#    /set leaves 3     → LEAVE_THRESHOLD = 3
# ──────────────────────────────────────────────
async def set_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global JOIN_THRESHOLD_B, JOIN_THRESHOLD_C, LEAVE_THRESHOLD
    user = update.effective_user

    if not is_admin(user.id):
        await update.message.reply_text("❌ Nur der Admin kann /set nutzen.")
        return

    # Kein Argument → aktuellen Stand anzeigen
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⚙️ *Aktuelle Schwellenwerte:*\n\n"
            f"┣ `joinb`  → *{JOIN_THRESHOLD_B}* Einladungen für {GROUP_B_NAME}\n"
            f"┣ `joinc`  → *{JOIN_THRESHOLD_C}* Einladungen für {GROUP_C_NAME}\n"
            f"┗ `leaves` → *{LEAVE_THRESHOLD}* Austritte bis Kick\n\n"
            "📝 *Nutzung:*\n"
            "`/set joinb 5` – Einladungen für Gruppe B\n"
            "`/set joinc 15` – Einladungen für Gruppe C\n"
            "`/set leaves 3` – Austritte bis Kick",
            parse_mode="Markdown"
        )
        return

    key = context.args[0].lower()
    raw = context.args[1]

    if not raw.isdigit() or int(raw) < 1:
        await update.message.reply_text("❌ Bitte eine positive Zahl angeben.")
        return

    value = int(raw)

    if key == "joinb":
        JOIN_THRESHOLD_B = value
        await update.message.reply_text(
            f"✅ *JOIN_THRESHOLD_B* auf *{value}* gesetzt.\n\n"
            f"Nutzer brauchen jetzt *{value} Einladungen* für {GROUP_B_NAME}.",
            parse_mode="Markdown"
        )
    elif key == "joinc":
        JOIN_THRESHOLD_C = value
        await update.message.reply_text(
            f"✅ *JOIN_THRESHOLD_C* auf *{value}* gesetzt.\n\n"
            f"Nutzer brauchen jetzt *{value} Einladungen* für {GROUP_C_NAME}.",
            parse_mode="Markdown"
        )
    elif key == "leaves":
        LEAVE_THRESHOLD = value
        await update.message.reply_text(
            f"✅ *LEAVE_THRESHOLD* auf *{value}* gesetzt.\n\n"
            f"Nutzer werden bei *{value} Austritten* gekickt.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "❌ Unbekannter Schlüssel.\n\n"
            "Gültige Schlüssel: `joinb`, `joinc`, `leaves`",
            parse_mode="Markdown"
        )


# ──────────────────────────────────────────────
#  /closebot / /openbot
# ──────────────────────────────────────────────
async def closebot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global bot_closed
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Keine Berechtigung.")
        return
    bot_closed = True
    await update.message.reply_text(
        "🔴 *Bot ist jetzt geschlossen!*\n\nNiemand ausser dir kann den Bot nutzen.\nMit /openbot reaktivierst du ihn.",
        parse_mode="Markdown"
    )
    logger.info("Bot von Admin geschlossen.")


async def openbot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global bot_closed
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Keine Berechtigung.")
        return
    bot_closed = False
    await update.message.reply_text(
        "🟢 *Bot ist wieder offen!*\n\nAlle Nutzer koennen den Bot wieder nutzen.",
        parse_mode="Markdown"
    )
    logger.info("Bot von Admin geoeffnet.")


async def bot_closed_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global bot_closed
    if not bot_closed:
        return
    user = update.effective_user
    if user and is_admin(user.id):
        return
    return


# ──────────────────────────────────────────────
#  Auto-Löschung
# ──────────────────────────────────────────────
async def auto_delete_zero_links(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now()
    to_delete = [(l, d) for l, d in tracked_links.items() if d["count"] == 0 and d.get("created_at") and (now - d["created_at"]) >= timedelta(days=AUTO_DELETE_DAYS)]
    for link_str, data in to_delete:
        await revoke_link(context, link_str)
        tracked_links.pop(link_str, None)
        try: await context.bot.send_message(chat_id=data["creator_chat_id"], text=f"🗑️ Dein Link wurde automatisch gelöscht.\n\nNeu mit /createlink.", parse_mode="Markdown")
        except: pass
    if to_delete: save_data()


# ──────────────────────────────────────────────
#  /status
# ──────────────────────────────────────────────
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    register_user(user.id)
    if bot_closed and not is_admin(user.id):
        await update.message.reply_text("Der Bot ist aktuell nicht verfuegbar.")
        return
    user_links = [(l, d) for l, d in tracked_links.items() if d["creator_id"] == user.id]
    if not user_links:
        await update.message.reply_text("Du hast noch keinen Link. Nutze /createlink!")
        return
    lines = ["📊 *Deine Links:*\n"]
    for link, data in user_links:
        mode = data.get("mode", "b")
        threshold = JOIN_THRESHOLD_B if mode == "b" else JOIN_THRESHOLD_C
        target = GROUP_B_NAME if mode == "b" else GROUP_C_NAME
        join_str = "✅ Ziel erreicht!" if data.get("done") else f"{data['count']}/{threshold}"
        kick_str = "🚫 Gekickt" if data.get("kicked") else f"{data['leave_count']}/{LEAVE_THRESHOLD}"
        age = (datetime.now() - data["created_at"]).days
        lines.append(f"• `{link}`\n  Ziel: {target}\n  Beitritte: {join_str}\n  Austritte: {kick_str}\n  Alter: {age} Tag(e)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────────
#  /help
# ──────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    register_user(user.id)

    if bot_closed and not is_admin(user.id):
        await update.message.reply_text("🔴 Der Bot ist aktuell nicht verfuegbar. Bitte versuche es spaeter.")
        return

    if is_admin(user.id):
        text = (
            "╔══════════════════════╗\n"
            "║  👑  *ADMIN PANEL*  👑  ║\n"
            "╚══════════════════════╝\n\n"
            "👤 *Nutzer-Befehle*\n"
            "┣ /createlink — Invite-Link erstellen\n"
            "┣ /delete — Deinen Link loeschen\n"
            "┣ /status — Links & Zaehlerstand\n"
            "┣ /support — Support kontaktieren\n"
            "┗ /closechat — Support-Chat beenden\n\n"
            "🛡️ *Moderations-Befehle*\n"
            "┣ /kick — Nutzer kicken\n"
            "┣ /ban — Nutzer bannen\n"
            "┣ /mute — Nutzer stummschalten\n"
            "┣ /unmute — Nutzer entstummen\n"
            "┣ /open — Gruppe oeffnen\n"
            "┣ /close — Gruppe schliessen\n"
            "┣ /global — Broadcast senden\n"
            "┣ /umfrage — Umfrage erstellen\n"
            "┣ /send admin — Chat an Admin uebergeben\n"
            "┗ /send smod — Chat an SuperMod uebergeben\n\n"
            "👑 *Admin-Befehle*\n"
            "┣ /see — Wochenstatistik\n"
            "┣ /deleteall — Alle Links loeschen\n"
            "┣ /returnall — Links wiederherstellen\n"
            "┣ /free — Freie Einladungslinks\n"
            "┣ /message — Nachricht in Gruppe senden\n"
            "┣ /set — Schwellenwerte anpassen\n"
            "┣ /closebot — Bot fuer alle sperren\n"
            "┗ /openbot — Bot wieder oeffnen\n"
        )
    elif is_supermod(user.id):
        text = (
            "╔══════════════════════╗\n"
            "║  ⚡  *SUPERMOD PANEL*  ⚡  ║\n"
            "╚══════════════════════╝\n\n"
            "👤 *Nutzer-Befehle*\n"
            "┣ /createlink — Invite-Link erstellen\n"
            "┣ /delete — Deinen Link loeschen\n"
            "┣ /status — Links & Zaehlerstand\n"
            "┣ /support — Support kontaktieren\n"
            "┗ /closechat — Support-Chat beenden\n\n"
            "⚡ *SuperMod-Befehle*\n"
            "┣ /kick — Nutzer kicken\n"
            "┣ /ban — Nutzer bannen\n"
            "┣ /mute — Nutzer stummschalten\n"
            "┣ /unmute — Nutzer entstummen\n"
            "┣ /open — Gruppe oeffnen\n"
            "┣ /close — Gruppe schliessen\n"
            "┣ /global — Broadcast senden\n"
            "┣ /umfrage — Umfrage erstellen\n"
            "┣ /see — Wochenstatistik\n"
            "┣ /deleteall — Alle Links loeschen\n"
            "┣ /returnall — Links wiederherstellen\n"
            "┣ /send admin — Chat an Admin uebergeben\n"
            "┗ /send smod — Chat an SuperMod uebergeben\n"
        )
    elif is_mod(user.id):
        text = (
            "╔══════════════════════╗\n"
            "║  🛡️  *MODERATOR PANEL*  🛡️  ║\n"
            "╚══════════════════════╝\n\n"
            "👤 *Nutzer-Befehle*\n"
            "┣ /createlink — Invite-Link erstellen\n"
            "┣ /delete — Deinen Link loeschen\n"
            "┣ /status — Links & Zaehlerstand\n"
            "┣ /support — Support kontaktieren\n"
            "┗ /closechat — Support-Chat beenden\n\n"
            "🛡️ *Moderations-Befehle*\n"
            "┣ /kick — Nutzer kicken\n"
            "┣ /ban — Nutzer bannen\n"
            "┣ /mute — Nutzer stummschalten\n"
            "┣ /unmute — Nutzer entstummen\n"
            "┣ /open — Gruppe oeffnen\n"
            "┣ /close — Gruppe schliessen\n"
            "┣ /global — Broadcast senden\n"
            "┣ /umfrage — Umfrage erstellen\n"
            "┣ /send admin — Chat an Admin uebergeben\n"
            "┗ /send smod — Chat an SuperMod uebergeben\n"
        )
    elif user.id in blocked_mods:
        text = "🚫 Du hast keinen Zugriff auf Bot-Funktionen."
    else:
        text = (
            "╔══════════════════════╗\n"
            "║  🤖  *BESTLEAKZ BOT*  🤖  ║\n"
            "╚══════════════════════╝\n\n"
            "🔗 *Einladungs-System*\n"
            f"┣ 🔵 {JOIN_THRESHOLD_B} Einladungen → {GROUP_B_NAME}\n"
            f"┗ ⭐ {JOIN_THRESHOLD_C} Einladungen → {GROUP_C_NAME}\n\n"
            "📋 *Deine Befehle*\n"
            "┣ /createlink — Invite-Link erstellen\n"
            "┣ /delete — Deinen Link loeschen\n"
            "┣ /status — Links & Zaehlerstand\n"
            "┣ /support — Support kontaktieren\n"
            "┗ /closechat — Support-Chat beenden\n\n"
            "⚠️ *Wichtige Infos*\n"
            f"┣ 🚫 Bei {LEAVE_THRESHOLD} Austritten → Kick aus allen Gruppen\n"
            "┗ 🛡️ Externe Links werden automatisch geloescht\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────
async def main() -> None:
    load_data()
    app = Application.builder().token(BOT_TOKEN).build()

    mod_conv = ConversationHandler(
        entry_points=[
            CommandHandler("kick", kick_start),
            CommandHandler("ban", ban_start),
            CommandHandler("mute", mute_start),
            CommandHandler("unmute", unmute_start),
        ],
        states={
            MOD_WAIT_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, mod_receive_id),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", mod_cancel_conv),
            CommandHandler("kick", kick_start),
            CommandHandler("ban", ban_start),
            CommandHandler("mute", mute_start),
            CommandHandler("unmute", unmute_start),
        ],
        allow_reentry=True,
        per_chat=False,
        per_message=False,
    )

    message_conv = ConversationHandler(
        entry_points=[CommandHandler("message", message_start)],
        states={
            MESSAGE_WAIT_GROUP: [
                CallbackQueryHandler(message_gruppe_callback, pattern="^msg_gruppe_"),
            ],
            MESSAGE_WAIT_CONTENT: [
                MessageHandler(
                    (filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Sticker.ALL) & ~filters.COMMAND & filters.ChatType.PRIVATE,
                    message_content_erhalten
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", message_cancel)],
        allow_reentry=True,
        per_chat=False,
        per_message=False,
    )

    support_conv = ConversationHandler(
        entry_points=[CommandHandler("support", support_start)],
        states={
            SUPPORT_CHOOSE: [
                CallbackQueryHandler(support_type_callback, pattern="^support_type_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", support_cancel_conv)],
        allow_reentry=True,
        per_chat=False,
        per_message=False,
    )

    umfrage_handler = ConversationHandler(
        entry_points=[CommandHandler("umfrage", umfrage_start)],
        states={
            UMFRAGE_FRAGE: [
                CallbackQueryHandler(umfrage_gruppe_callback, pattern="^umfrage_gruppe_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, umfrage_frage_erhalten),
            ],
            UMFRAGE_OPTIONEN: [
                CallbackQueryHandler(umfrage_anzahl_callback, pattern="^umfrage_anzahl_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, umfrage_option_erhalten),
            ],
            UMFRAGE_BESTAETIGEN: [
                CallbackQueryHandler(umfrage_senden_callback, pattern="^umfrage_(senden|abbrechen)$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", umfrage_cancel)],
        allow_reentry=True,
        per_chat=False,
        per_message=False,
    )

    getowner_handler = ConversationHandler(
        entry_points=[CommandHandler("getowner", getowner_start)],
        states={
            GETOWNER_WAIT_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, getowner_check_code),
            ],
            GETOWNER_WAIT_CONFIRM: [
                CallbackQueryHandler(getowner_confirm_callback, pattern="^getowner_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", getowner_cancel_conv)],
        allow_reentry=True,
        per_chat=False,
        per_message=False,
    )

    # ConversationHandlers zuerst
    app.add_handler(getowner_handler)
    app.add_handler(mod_conv)
    app.add_handler(message_conv)
    app.add_handler(support_conv)
    app.add_handler(umfrage_handler)

    # Commands
    app.add_handler(CommandHandler("open", open_start))
    app.add_handler(CommandHandler("close", close_start))
    app.add_handler(CommandHandler("send", send_command))
    app.add_handler(CommandHandler("closechat", close_chat))
    app.add_handler(CommandHandler("createlink", create_link))
    app.add_handler(CommandHandler("delete", delete_link))
    app.add_handler(CommandHandler("deleteall", delete_all))
    app.add_handler(CommandHandler("returnall", return_all))
    app.add_handler(CommandHandler("see", see_stats))
    app.add_handler(CommandHandler("free", free_links))
    app.add_handler(CommandHandler("global", global_message))
    app.add_handler(CommandHandler("set", set_threshold))
    app.add_handler(CommandHandler("closebot", closebot))
    app.add_handler(CommandHandler("openbot", openbot))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("start", help_command))

    # Callbacks
    app.add_handler(CallbackQueryHandler(createlink_callback, pattern="^createlink_"))
    app.add_handler(CallbackQueryHandler(moderation_callback, pattern="^mod_(ban|unmute)_\\d+_\\d+$"))
    app.add_handler(CallbackQueryHandler(mod_gruppe_callback, pattern="^modact_\\d+_g_"))
    app.add_handler(CallbackQueryHandler(open_close_callback, pattern="^(open|close)_g_"))
    app.add_handler(CallbackQueryHandler(abuse_callback, pattern="^abuse_(allow|deny|remove)_"))
    app.add_handler(CallbackQueryHandler(support_take_callback, pattern="^support_take_"))
    app.add_handler(CallbackQueryHandler(getowner_confirm_callback, pattern="^getowner_"))

    # ── Beitritts-/Austrittsnachrichten automatisch löschen ──
    # filters.StatusUpdate.ALL deckt alle Systemnachrichten ab:
    # neue Mitglieder, Austritte, Pinned Messages, etc.
    app.add_handler(MessageHandler(
        filters.StatusUpdate.ALL & filters.Chat(ALL_GROUP_IDS),
        delete_service_messages
    ), group=0)

    # Bot-Closed Middleware
    app.add_handler(MessageHandler(
        filters.ALL & ~filters.Chat([ADMIN_ID]),
        bot_closed_check
    ), group=-1)

    # Support Relay
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND &
        (filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Sticker.ALL),
        support_message_relay
    ))

    # Gruppen-Moderation
    app.add_handler(MessageHandler(filters.TEXT & filters.Chat(ALL_GROUP_IDS), moderate_message))
    app.add_handler(MessageHandler(filters.CAPTION & filters.Chat(ALL_GROUP_IDS), moderate_message))
    app.add_handler(ChatMemberHandler(track_join, ChatMemberHandler.CHAT_MEMBER))

    app.job_queue.run_daily(auto_delete_zero_links, time=datetime.strptime("03:00", "%H:%M").time())

    logger.info("Bot startet …")
    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=["message", "chat_member", "callback_query", "my_chat_member"])
        logger.info("Bot läuft! Drücke STRG+C zum Beenden.")
        await asyncio.Event().wait()


# ──────────────────────────────────────────────
#  Watchdog
# ──────────────────────────────────────────────
RESTART_DELAY = 10
MAX_RESTARTS = 999
RESTART_COOLDOWN = 5

async def run_with_watchdog():
    restart_count = 0
    last_restart = datetime.now()

    while restart_count < MAX_RESTARTS:
        try:
            logger.info("▶️  Bot-Start (Versuch %d) …", restart_count + 1)
            await main()

        except KeyboardInterrupt:
            logger.info("⏹️  Bot manuell gestoppt.")
            break

        except Exception as e:
            restart_count += 1
            now = datetime.now()
            zeit_seit_letztem = (now - last_restart).total_seconds()

            logger.error(
                "❌ Bot abgestürzt (Versuch %d): %s",
                restart_count, e, exc_info=True
            )

            wait = max(RESTART_DELAY, RESTART_COOLDOWN - zeit_seit_letztem)
            logger.info("⏳ Neustart in %.0f Sekunden …", wait)
            await asyncio.sleep(wait)

            last_restart = datetime.now()
            logger.info("🔄 Starte Bot neu …")

    logger.warning("⚠️  Maximale Neustarts erreicht. Bot wird beendet.")


if __name__ == "__main__":
    asyncio.run(run_with_watchdog())"""
