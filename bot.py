import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from config import BOT_TOKEN, ADMIN_ID
from database import Database

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Inicializar base de datos
db = Database()

# Horario desactivado - siempre disponible
HORARIO_INICIO = 0
HORARIO_FIN = 24

# Diccionario para controlar el tiempo de espera de usuarios (para /newnum)
user_last_used = {}

# Diccionario para controlar mensajes de soporte (3 cada 30 minutos)
user_soporte_count = {}  # {user_id: [count, first_timestamp]}

def verificar_horario():
    """Siempre devuelve True - horario desactivado"""
    return True

def usuario_aprobado(user_id):
    """Verifica si el usuario está aprobado y activo"""
    active, _ = db.check_user_active(user_id)
    return active

def verificar_limite_soporte(user_id):
    """Verifica si el usuario puede enviar mensaje de soporte (3 cada 30 min)"""
    current_time = time.time()
    
    if user_id not in user_soporte_count:
        user_soporte_count[user_id] = [1, current_time]
        return True, 3
    
    count, first_time = user_soporte_count[user_id]
    
    # Si pasaron más de 30 minutos, reiniciar contador
    if current_time - first_time > 1800:
        user_soporte_count[user_id] = [1, current_time]
        return True, 3
    
    if count >= 3:
        tiempo_restante = int(1800 - (current_time - first_time))
        minutos_rest = tiempo_restante // 60
        seg_rest = tiempo_restante % 60
        return False, f"{minutos_rest} minutos y {seg_rest} segundos"
    
    user_soporte_count[user_id][0] = count + 1
    return True, 3 - count

def obtener_mensaje_fuera_horario():
    return (
        "🕒 *FUERA DE HORARIO* 🕒\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏰ *Horario de servicio:*\n"
        f"   🌅 8:00 AM - 🌙 9:59 PM\n\n"
        "📅 *Días:* Lunes a Domingo\n\n"
        "✨ *Reintenta mañana* dentro del horario\n\n"
        "🔒 Estamos descansando. ¡Vuelve pronto!"
    )

async def set_commands(application):
    try:
        commands = [
            ("start", "Iniciar bot"),
            ("registrar", "Registrarse con key"),
            ("permisos", "Ver tiempo restante"),
            ("soporte", "Contactar soporte"),
            ("newnum", "Solicitar cambio de número"),
            ("generarkey", "Generar key admin"),
            ("pendientes", "Ver registros pendientes"),
            ("notificar", "Notificar restablecimiento"),
            ("notificarerror", "Notificar intermitencias"),
            ("restringir", "Restringir usuario"),
            ("info", "Ver info usuarios"),
        ]
        await application.bot.set_my_commands(commands)
    except Exception as e:
        print(f"Comandos: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Botones sin emojis
    keyboard = [
        ["/permisos", "/soporte"],
    ]
    if user.id == ADMIN_ID:
        keyboard.append(["/generarkey", "/pendientes", "/notificar"])
        keyboard.append(["/notificarerror", "/restringir", "/info"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"✨ *¡Bienvenido!* ✨\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 *Uchiha Config ID Call*\n"
        "💼 *Sistema de Solicitudes*\n\n"
        "🔑 *Para usar el bot:*\n"
        "1️⃣ Usa /registrar \"Key que te dio el administrador\"\n"
        "2️⃣ Espera aprobación del admin\n"
        "3️⃣ Una vez aprobado, usa /newnum para solicitar cambios\n\n"
        "⏰ *Horario:* 24/7 (siempre disponible)\n\n"
        "🔽 *Selecciona una opción:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    help_text = (
        "📖 *AYUDA DEL SISTEMA* 📖\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Comandos:*\n\n"
        "🔑 `/registrar KEY` - Registrarse\n"
        "📋 `/permisos` - Ver tiempo restante\n"
        "🆘 `/soporte` - Contactar soporte (3 cada 30 min)\n"
        "📱 `/newnum 5512345678` - Solicitar cambio\n\n"
    )
    
    if user.id == ADMIN_ID:
        help_text += (
            "*Admin:*\n"
            "🔐 `/generarkey 30` - Generar key\n"
            "📋 `/pendientes` - Ver pendientes\n"
            "📢 `/notificar` - Notificar restablecimiento a todos\n"
            "⚠️ `/notificarerror` - Notificar intermitencias a todos\n"
            "🔒 `/restringir ID` - Restringir usuario (suspender)\n"
            "ℹ️ `/info` - Ver todos los usuarios y días restantes\n\n"
        )
    
    help_text += "⏰ *Horario:* 24/7 (siempre disponible)"
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def permisos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    active, message = db.check_user_active(user.id)
    
    if active:
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("SELECT expiration_date FROM users WHERE user_id = ?", (user.id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            expiration = datetime.fromisoformat(result[0])
            remaining = expiration - datetime.now()
            
            days = remaining.days
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            
            await update.message.reply_text(
                f"📋 *TUS PERMISOS* 📋\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"✅ *Estado:* ACTIVO\n"
                f"📅 *Días:* {days} días\n"
                f"⏰ *Horas:* {hours} horas\n"
                f"⌛ *Minutos:* {minutes} minutos\n\n"
                f"📱 *Expira:* {expiration.strftime('%d/%m/%Y %H:%M')}",
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id FROM pending_registrations 
            WHERE user_id = ? AND status = 'pending'
        ''', (user.id,))
        pending = cursor.fetchone()
        conn.close()
        
        if pending:
            await update.message.reply_text(
                "⏳ *CUENTA PENDIENTE*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Tu registro está en espera de aprobación.\n"
                "Te notificaremos cuando sea activado.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"❌ *CUENTA INACTIVA*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{message}\n\n"
                f"🔑 Usa `/registrar KEY` para activar.",
                parse_mode=ParseMode.MARKDOWN
            )

async def soporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Verificar si el usuario está aprobado
    if not usuario_aprobado(user.id):
        await update.message.reply_text(
            f"❌ *ACCESO DENEGADO*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Debes tener una cuenta activa para usar /soporte.\n\n"
            f"🔑 Usa `/registrar KEY` para registrarte y espera aprobación.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Verificar límite de mensajes
    puede_enviar, mensaje = verificar_limite_soporte(user.id)
    
    if not puede_enviar:
        await update.message.reply_text(
            f"⏳ *LÍMITE DE MENSAJES* ⏳\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Has alcanzado el límite de 3 mensajes en 30 minutos.\n\n"
            f"⏰ *Espera:* {mensaje}\n\n"
            f"🔄 Podrás enviar más mensajes después de ese tiempo.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    await update.message.reply_text(
        f"🆘 *SOPORTE* 🆘\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 Escribe tu mensaje (máximo 100 caracteres)\n\n"
        f"✅ *Mensajes restantes:* {mensaje} de 3 cada 30 min\n\n"
        f"📢 Te responderemos a la brevedad.",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data['esperando_soporte'] = True

async def handle_soporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('esperando_soporte'):
        user = update.effective_user
        mensaje = update.message.text
        
        if not usuario_aprobado(user.id):
            await update.message.reply_text(
                "❌ No tienes permiso para usar soporte.",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['esperando_soporte'] = False
            return
        
        if len(mensaje) > 100:
            await update.message.reply_text(
                "❌ *Error:* El mensaje excede los 100 caracteres.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        context.user_data['esperando_soporte'] = False
        
        await update.message.reply_text(
            "✅ *Mensaje enviado*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Tu mensaje ha sido enviado al soporte.\n"
            "Te responderemos pronto.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        keyboard = [[InlineKeyboardButton("⏳ Esperar", callback_data=f"esperar_soporte_{user.id}")]]
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🆘 *NUEVO MENSAJE DE SOPORTE* 🆘\n"
                 f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                 f"👤 *Usuario:* {user.first_name}\n"
                 f"🆔 *ID:* `{user.id}`\n"
                 f"📝 *Mensaje:*\n"
                 f"{mensaje}\n\n"
                 f"📅 *Fecha:* {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                 f"📊 *Mensaje #{user_soporte_count[user.id][0]} de 3*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def nuevo_numero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    current_time = time.time()
    
    if not usuario_aprobado(user.id):
        await update.message.reply_text(
            f"❌ *ACCESO DENEGADO*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Debes tener una cuenta activa para usar /newnum.\n\n"
            f"🔑 Usa `/registrar KEY` para registrarte y espera aprobación.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if user_id in user_last_used:
        tiempo_restante = 600 - (current_time - user_last_used[user_id])
        if tiempo_restante > 0:
            minutos_rest = int(tiempo_restante // 60)
            segundos_rest = int(tiempo_restante % 60)
            await update.message.reply_text(
                f"⏳ *ESPERA REQUERIDA* ⏳\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Debes esperar {minutos_rest} minutos y {segundos_rest} segundos\n"
                f"para realizar otra solicitud.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
    
    # Horario desactivado - siempre permite
    # if not verificar_horario():
    #     keyboard = [[InlineKeyboardButton("OK", callback_data="ack_horario")]]
    #     await update.message.reply_text(
    #         obtener_mensaje_fuera_horario(),
    #         parse_mode=ParseMode.MARKDOWN,
    #         reply_markup=InlineKeyboardMarkup(keyboard)
    #     )
    #     return
    
    if not context.args:
        await update.message.reply_text(
            "📱 *SOLICITUD DE CAMBIO* 📱\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "❌ *Uso correcto:* `/newnum 5512345678`\n\n"
            "✅ *Requisitos:* 10 dígitos, solo números",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    phone_number = context.args[0]
    
    if not phone_number.isdigit() or len(phone_number) != 10:
        await update.message.reply_text(
            "❌ *NÚMERO INVÁLIDO*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📞 *Recibido:* `{phone_number}`\n\n"
            "⚠️ Debe ser 10 dígitos, solo números.\n"
            "📝 *Ejemplo:* `/newnum 5512345678`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    request_id = db.create_request(user.id, phone_number)
    user_last_used[user_id] = current_time
    
    await update.message.reply_text(
        f"✅ *SOLICITUD ENVIADA* ✅\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 *ID:* #{request_id}\n"
        f"📞 *Número:* `{phone_number}`\n\n"
        f"🔄 *Estado:* Pendiente\n"
        f"⏰ *Próxima solicitud:* en 10 minutos",
        parse_mode=ParseMode.MARKDOWN
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Número Cambiado", callback_data=f"complete_{request_id}"),
            InlineKeyboardButton("🔴 No Disponible", callback_data=f"no_disponible_{request_id}_{user.id}")
        ]
    ]
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔄 *NUEVA SOLICITUD* 🔄\n"
             f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
             f"👤 *Usuario:* {user.first_name}\n"
             f"🆔 *ID:* `{user.id}`\n"
             f"📞 *Número:* `{phone_number}`\n"
             f"📋 *ID:* #{request_id}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def testid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"🔍 *TU ID:* `{user_id}`\n👑 *ADMIN ID:* `{ADMIN_ID}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not context.args:
        await update.message.reply_text(
            "🔑 *REGISTRO*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "❌ Uso: `/registrar KEY`\n"
            "📝 Ejemplo: `/registrar ABC123XYZ`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    key = context.args[0]
    
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT days, is_used FROM keys WHERE key = ?", (key,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        await update.message.reply_text(f"❌ Key inválida: `{key}`", parse_mode=ParseMode.MARKDOWN)
        return
    
    if result[1] == 1:
        conn.close()
        await update.message.reply_text("❌ Key ya utilizada", parse_mode=ParseMode.MARKDOWN)
        return
    
    days = result[0]
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            key TEXT,
            days INTEGER,
            request_date TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')
    
    cursor.execute(
        "SELECT id FROM pending_registrations WHERE user_id = ? AND status = 'pending'",
        (user.id,)
    )
    existing = cursor.fetchone()
    
    if existing:
        conn.close()
        await update.message.reply_text(
            "⏳ Ya tienes una solicitud pendiente. Espera aprobación.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    cursor.execute('''
        INSERT INTO pending_registrations (user_id, username, first_name, last_name, key, days, request_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user.id, user.username, user.first_name, user.last_name, key, days, datetime.now().isoformat()))
    
    registration_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"✅ *Solicitud enviada!*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 *ID:* #{registration_id}\n"
        f"📅 *Días:* {days}\n\n"
        f"⏳ Espera aprobación del administrador.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ APROBAR", callback_data=f"approve_reg_{registration_id}"),
            InlineKeyboardButton("❌ RECHAZAR", callback_data=f"reject_reg_{registration_id}")
        ]
    ]
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🆕 *NUEVO REGISTRO*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
             f"👤 {user.first_name}\n"
             f"🆔 ID: `{user.id}`\n"
             f"🔑 Key: `{key}`\n"
             f"📅 Días: {days}\n"
             f"📋 ID: #{registration_id}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Solo administrador")
        return
    
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, user_id, first_name, key, days, request_date
        FROM pending_registrations
        WHERE status = 'pending'
        ORDER BY request_date DESC
    ''')
    
    pendings = cursor.fetchall()
    conn.close()
    
    if not pendings:
        await update.message.reply_text("📋 No hay registros pendientes")
        return
    
    mensaje = "📋 *REGISTROS PENDIENTES*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for reg in pendings[:10]:
        reg_id, uid, fname, key, days, date = reg
        mensaje += f"🔹 #{reg_id} - {fname} - {days} días\n"
    
    await update.message.reply_text(mensaje, parse_mode=ParseMode.MARKDOWN)

async def info_usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /info - Ver todos los usuarios registrados y días restantes"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Solo administrador")
        return
    
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, first_name, username, expiration_date, is_active
        FROM users
        ORDER BY expiration_date ASC
    ''')
    
    usuarios = cursor.fetchall()
    conn.close()
    
    if not usuarios:
        await update.message.reply_text("📋 No hay usuarios registrados")
        return
    
    mensaje = "👥 *USUARIOS REGISTRADOS*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for uid, nombre, username, exp_date, activo in usuarios:
        if activo:
            expiration = datetime.fromisoformat(exp_date)
            remaining = expiration - datetime.now()
            days = remaining.days
            hours = remaining.seconds // 3600
            
            if days < 0:
                estado = "⚠️ EXPIRADO"
                dias_rest = "0"
            else:
                estado = "✅ ACTIVO"
                dias_rest = f"{days}d {hours}h"
        else:
            estado = "❌ INACTIVO"
            dias_rest = "0"
        
        mensaje += (
            f"👤 *{nombre}*\n"
            f"   🆔 `{uid}`\n"
            f"   📝 @{username or 'sin username'}\n"
            f"   📊 {estado}\n"
            f"   ⏰ Días restantes: {dias_rest}\n\n"
        )
    
    if len(mensaje) > 4000:
        mensaje = mensaje[:4000] + "\n\n... (más usuarios, lista truncada)"
    
    await update.message.reply_text(mensaje, parse_mode=ParseMode.MARKDOWN)

async def restringir_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /restringir ID - Restringir usuario (quitar permisos)"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Solo administrador")
        return
    
    if not context.args:
        await update.message.reply_text(
            "🔒 *RESTRINGIR USUARIO*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "❌ Uso: `/restringir ID_USUARIO`\n\n"
            "📝 Ejemplo: `/restringir 123456789`\n\n"
            "⚠️ El usuario quedará inactivo y deberá registrarse nuevamente.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        target_id = int(context.args[0])
        
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        
        cursor.execute("SELECT first_name FROM users WHERE user_id = ?", (target_id,))
        usuario = cursor.fetchone()
        
        if not usuario:
            conn.close()
            await update.message.reply_text(f"❌ Usuario con ID `{target_id}` no encontrado", parse_mode=ParseMode.MARKDOWN)
            return
        
        nombre = usuario[0]
        
        cursor.execute("UPDATE users SET is_active = 0, expiration_date = ? WHERE user_id = ?", 
                      (datetime.now().isoformat(), target_id))
        conn.commit()
        conn.close()
        
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🔒 *CUENTA RESTRINGIDA* 🔒\n"
                     f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                     f"Tu cuenta ha sido desactivada por el administrador.\n\n"
                     f"🔑 Para volver a acceder, necesitas una nueva key y ser aprobado nuevamente.\n\n"
                     f"📞 Contacta al administrador para más información.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error notificando a {target_id}: {e}")
        
        await update.message.reply_text(
            f"✅ *USUARIO RESTRINGIDO*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 *Usuario:* {nombre}\n"
            f"🆔 *ID:* `{target_id}`\n\n"
            f"🔒 La cuenta ha sido desactivada.\n"
            f"📢 El usuario ha sido notificado.",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except ValueError:
        await update.message.reply_text("❌ ID inválido", parse_mode=ParseMode.MARKDOWN)

async def notificar_todos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /notificar - Notificar restablecimiento a TODOS los usuarios aprobados"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Solo administrador")
        return
    
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id, first_name FROM users WHERE is_active = 1")
    usuarios = cursor.fetchall()
    conn.close()
    
    if not usuarios:
        await update.message.reply_text("📋 No hay usuarios activos para notificar")
        return
    
    enviados = 0
    errores = 0
    
    for uid, nombre in usuarios:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"✅ *SERVICIO RESTABLECIDO* ✅\n"
                     f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                     f"🎉 El servicio ha sido restablecido exitosamente.\n\n"
                     f"📱 Ya puedes usar el comando `/newnum` nuevamente.\n\n"
                     f"✨ Disculpa las molestias ocasionadas.",
                parse_mode=ParseMode.MARKDOWN
            )
            enviados += 1
            
            if uid in user_last_used:
                del user_last_used[uid]
                
        except Exception as e:
            logger.error(f"Error notificando a {uid}: {e}")
            errores += 1
    
    await update.message.reply_text(
        f"📢 *NOTIFICACIÓN DE RESTABLECIMIENTO*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ *Enviados:* {enviados} usuarios\n"
        f"❌ *Errores:* {errores} usuarios",
        parse_mode=ParseMode.MARKDOWN
    )

async def notificar_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /notificarerror - Notificar intermitencias a TODOS los usuarios aprobados"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Solo administrador")
        return
    
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id, first_name FROM users WHERE is_active = 1")
    usuarios = cursor.fetchall()
    conn.close()
    
    if not usuarios:
        await update.message.reply_text("📋 No hay usuarios activos para notificar")
        return
    
    enviados = 0
    errores = 0
    
    for uid, nombre in usuarios:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"⚠️ *INTERMITENCIAS EN EL SERVICIO* ⚠️\n"
                     f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                     f"Estimado usuario, estamos presentando intermitencias en el servicio.\n\n"
                     f"🔧 Nuestro equipo ya está trabajando para solucionarlo.\n\n"
                     f"📢 *Te notificaremos cuando el servicio sea restablecido.*\n\n"
                     f"✅ Disculpa las molestias ocasionadas.",
                parse_mode=ParseMode.MARKDOWN
            )
            enviados += 1
                
        except Exception as e:
            logger.error(f"Error notificando a {uid}: {e}")
            errores += 1
    
    await update.message.reply_text(
        f"⚠️ *NOTIFICACIÓN DE INTERMITENCIAS*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ *Enviados:* {enviados} usuarios\n"
        f"❌ *Errores:* {errores} usuarios\n\n"
        f"📢 Mensaje enviado a todos los usuarios activos.",
        parse_mode=ParseMode.MARKDOWN
    )

async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    active, message = db.check_user_active(user.id)
    
    if active:
        days_match = re.search(r'(\d+)', message)
        days_left = days_match.group(1) if days_match else "?"
        await update.message.reply_text(f"✅ ACTIVO - Días: {days_left}")
    else:
        await update.message.reply_text(f"❌ {message}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "ack_horario":
        await query.edit_message_reply_markup(reply_markup=None)
        return
    
    if query.data.startswith("esperar_soporte_"):
        user_id = int(query.data.split("_")[2])
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"⏳ *SOLICITUD EN PROCESO* ⏳\n"
                 f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                 f"Hemos detectado el problema y lo estamos atendiendo.\n\n"
                 f"📢 *Serás notificado cuando el servicio sea restablecido.*\n\n"
                 f"✅ Gracias por tu paciencia.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"✅ Mensaje automático enviado al usuario.")
        return
    
    if query.data.startswith("no_disponible_"):
        parts = query.data.split("_")
        request_id = int(parts[2])
        user_id = int(parts[3])
        
        user_last_used[user_id] = time.time()
        
        await context.bot.send_message(
            chat_id=user_id,
            text="🔴 *SERVICIO NO DISPONIBLE* 🔴\n"
                 "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                 "⚠️ Estamos presentando algunos problemas de conexión.\n\n"
                 "⏰ *Intenta de nuevo en 10 minutos.*\n\n"
                 "🔒 El comando /newnum ha sido bloqueado temporalmente.\n\n"
                 "📢 Disculpa las molestias.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await query.edit_message_text(
            text=f"{query.message.text}\n\n🔴 NO DISPONIBLE - Usuario bloqueado 10 min",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.message.reply_text(f"✅ Usuario notificado. Bloqueado por 10 minutos.")
        return
    
    if query.data.startswith("approve_reg_"):
        reg_id = int(query.data.split("_")[2])
        
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id, username, first_name, last_name, key, days
            FROM pending_registrations
            WHERE id = ? AND status = 'pending'
        ''', (reg_id,))
        
        reg = cursor.fetchone()
        
        if reg:
            user_id, username, first_name, last_name, key, days = reg
            
            expiration_date = (datetime.now() + timedelta(days=days)).isoformat()
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_name, registered_date, expiration_date, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (user_id, username, first_name, last_name, datetime.now().isoformat(), expiration_date))
            
            cursor.execute(
                "UPDATE keys SET used_by = ?, used_date = ?, is_used = 1 WHERE key = ?",
                (user_id, datetime.now().isoformat(), key)
            )
            
            cursor.execute(
                "UPDATE pending_registrations SET status = 'approved' WHERE id = ?",
                (reg_id,)
            )
            
            conn.commit()
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 *¡REGISTRO APROBADO!* 🎉\n"
                     f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                     f"✅ Cuenta activada por {days} días.\n"
                     f"📱 Usa /newnum para solicitar cambios.\n\n"
                     f"📋 Usa /permisos para ver tu tiempo restante.\n\n"
                     f"🆘 Usa /soporte para recibir ayuda.\n\n"
                     f"✨ ¡Bienvenido al sistema!",
                parse_mode=ParseMode.MARKDOWN
            )
            
            await query.edit_message_text(
                text=f"{query.message.text}\n\n✅ APROBADO",
                parse_mode=ParseMode.MARKDOWN
            )
        conn.close()
        return
    
    if query.data.startswith("reject_reg_"):
        reg_id = int(query.data.split("_")[2])
        
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id FROM pending_registrations
            WHERE id = ? AND status = 'pending'
        ''', (reg_id,))
        
        reg = cursor.fetchone()
        
        if reg:
            user_id = reg[0]
            
            cursor.execute(
                "UPDATE pending_registrations SET status = 'rejected' WHERE id = ?",
                (reg_id,)
            )
            conn.commit()
            
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ *REGISTRO RECHAZADO*\n━━━━━━━━━━━━━━━━━━━━━━\n\nContacta al administrador.",
                parse_mode=ParseMode.MARKDOWN
            )
            
            await query.edit_message_text(
                text=f"{query.message.text}\n\n❌ RECHAZADO",
                parse_mode=ParseMode.MARKDOWN
            )
        conn.close()
        return
    
    if query.data.startswith("complete_"):
        request_id = int(query.data.split("_")[1])
        user_id = db.complete_request(request_id)
        
        if user_id:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ *SOLICITUD ATENDIDA* ✅\n"
                     f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                     f"📋 *ID:* #{request_id}\n\n"
                     f"🎉 Tu número ha sido cambiado exitosamente.",
                parse_mode=ParseMode.MARKDOWN
            )
            await query.edit_message_text(
                text=f"{query.message.text}\n\n✅ COMPLETADA",
                parse_mode=ParseMode.MARKDOWN
            )
        return

async def generar_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Solo administrador")
        return
    
    if not context.args:
        await update.message.reply_text(
            "🔐 *GENERAR KEY*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📝 `/generarkey <días>`\n\n"
            "📌 Ejemplos:\n"
            "• `/generarkey 1` - 1 día\n"
            "• `/generarkey 30` - 30 días",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        days = int(context.args[0])
        if days <= 0:
            await update.message.reply_text("❌ Días positivos")
            return
        
        key = db.generate_key(days)
        await update.message.reply_text(
            f"🔑 *KEY GENERADA*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"`{key}`\n\n"
            f"📅 *Días:* {days}\n"
            f"📤 *Envío:* `/registrar {key}`",
            parse_mode=ParseMode.MARKDOWN
        )
    except ValueError:
        await update.message.reply_text("❌ Error")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", help_command))
    app.add_handler(CommandHandler("testid", testid))
    app.add_handler(CommandHandler("registrar", register))
    app.add_handler(CommandHandler("pendientes", pendientes))
    app.add_handler(CommandHandler("permisos", permisos))
    app.add_handler(CommandHandler("estado", estado))
    app.add_handler(CommandHandler("newnum", nuevo_numero))
    app.add_handler(CommandHandler("generarkey", generar_key))
    app.add_handler(CommandHandler("soporte", soporte))
    app.add_handler(CommandHandler("notificar", notificar_todos))
    app.add_handler(CommandHandler("notificarerror", notificar_error))
    app.add_handler(CommandHandler("restringir", restringir_usuario))
    app.add_handler(CommandHandler("info", info_usuarios))
    
    # Mensajes
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_soporte))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Errores
    app.add_error_handler(error_handler)
    
    print("🤖 Uchiha Config ID Call - Bot iniciado")
    print("⏰ Horario: 24/7 (siempre disponible)")
    print("📋 Sistema de aprobación manual activado")
    print("⏱️ Límite de 10 minutos entre solicitudes")
    print("🆘 Límite de 3 mensajes de soporte cada 30 minutos")
    print("✅ Solo usuarios aprobados pueden usar /soporte y /newnum")
    print("📢 /notificar - Restablecimiento a TODOS")
    print("⚠️ /notificarerror - Intermitencias a TODOS")
    print("🔒 /restringir ID - Desactiva usuario")
    print("ℹ️ /info - Lista todos los usuarios")
    
    app.run_polling()

if __name__ == "__main__":
    main()