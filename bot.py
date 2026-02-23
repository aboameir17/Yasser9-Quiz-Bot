import logging
import asyncio
import random
import time
import os
import httpx  # الطريقة الأسرع والأكثر أماناً للتعامل مع API الذكاء الاصطناعي
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from supabase import create_client, Client  # تم تصحيح الكلمة لضمان الربط مع Supabase
# إعداد السجلات
logging.basicConfig(level=logging.INFO)
# --- [ 1. إعدادات الهوية والاتصال ] ---
ADMIN_ID = 7988144062
OWNER_USERNAME = "@Ya_79k"

# سحب التوكينات من Render (تأكد من وجود GROQ_API_KEY في الإعدادات)
API_TOKEN = os.getenv('BOT_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# تعريف المحركات الأساسية
bot = Bot(token=API_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# قاموس المسابقات النشطة
active_quizzes = {}

# ==========================================
# --- [ 2. بداية الدوال المساعدة قالب الاجابات  ] ---
# ==========================================
async def send_creative_results(chat_id, correct_ans, winners, overall_scores):
    """تصميم ياسر المطور: دمج الفائزين والترتيب في رسالة واحدة"""
    msg =  "┉┉┅┅┅┄┄┄┈•◦•┈┄┄┄┅┅┅┉┉\n"
    msg += f"✅ الإجابة الصحيحة: <b>{correct_ans}</b>\n"
    msg += "┉┉┅┅┅┄┄┄┈•◦•┈┄┄┄┅┅┅┉┉\n\n"
    
    if winners:
        msg += "❃─── { جواب صح} ───❃\n"
        for i, w in enumerate(winners, 1):
            msg += f"{i}- {w['name']} (+10)\n"
    else:
        msg += "❌ لم ينجح أحد في الإجابة على هذا السؤال\n"
    
    leaderboard = sorted(overall_scores.values(), key=lambda x: x['points'], reverse=True)
    msg += "\n❃─── { الترتيب} ───❃\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, player in enumerate(leaderboard[:3]):
        medal = medals[i] if i < 3 else "👤"
        msg += f"{medal} {player['name']} — {player['points']}\n"
    
    await bot.send_message(chat_id, msg, parse_mode="HTML")
    
async def send_final_results(chat_id, overall_scores, correct_count):
    """تصميم ياسر لرسالة ختام المسابقة"""
    msg =  "┉┉┅┅┅┄┄┄┈•◦•┈┄┄┄┅┅┅┉┉\n"
    msg += "🏁 <b>انـتـهـت الـمـسـابـقـة بنجاح!</b> 🏁\n"
    msg += "شكرًا لكل من شارك وأمتعنا بمنافسته. 🌹\n"
    msg += "┉┉┅┅┅┄┄┄┈•◦•┈┄┄┄┅┅┅┉┉\n\n"
    msg += "❃─── { المتفوقين} ───❃\n\n"
    sorted_players = sorted(overall_scores.values(), key=lambda x: x['points'], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    for i, player in enumerate(sorted_players[:3]):
        msg += f"{medals[i]} المركز {'الأول' if i==0 else 'الثاني' if i==1 else 'الثالث'}: <b>{player['name']}</b> - [🏆 {player['points']}]\n"
    msg += "┉┉┅┅┅┄┄┄┈•◦•┈┄┄┄┅┅┅┉┉\n"
    msg += "تهانينا للفائزين وحظاً أوفر لمن لم يحالفه الحظ! ❤️"
    await bot.send_message(chat_id, msg, parse_mode="HTML")


# ==========================================
# 1. كيبوردات التحكم الرئيسية (Main Keyboards)
# ==========================================

def get_main_control_kb(user_id):
    """توليد كيبورد لوحة التحكم الرئيسية مشفرة بآيدي المستخدم"""
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("📝 إضافة خاصة", callback_data=f"custom_add_{user_id}"),
        InlineKeyboardButton("📅 جلسة سابقة", callback_data=f"dev_session_{user_id}"),
        InlineKeyboardButton("🏆 تجهيز مسابقة", callback_data=f"setup_quiz_{user_id}"),
        InlineKeyboardButton("📊 لوحة الصدارة", callback_data=f"dev_leaderboard_{user_id}"),
        InlineKeyboardButton("🛑 إغلاق", callback_data=f"close_bot_{user_id}")
    )
    return kb

def get_categories_kb(user_id):
    """توليد كيبورد إدارة الأقسام مع الحماية"""
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("➕ إضافة قسم جديد", callback_data=f"add_new_cat_{user_id}"),
        InlineKeyboardButton("📋 قائمة الأقسام", callback_data=f"list_cats_{user_id}"),
        InlineKeyboardButton("🔙 الرجوع لصفحة التحكم", callback_data=f"back_to_control_{user_id}")
    )
    return kb

# ==========================================
# 2. دوال عرض الواجهات الموحدة (UI Controllers)
# ==========================================

async def show_category_settings_ui(message: types.Message, cat_id, owner_id, is_edit=True):
    """الدالة الموحدة لعرض إعدادات القسم بضغطة واحدة"""
    # جلب البيانات من سوبابيس
    cat_res = supabase.table("categories").select("name").eq("id", cat_id).single().execute()
    q_res = supabase.table("questions").select("*", count="exact").eq("category_id", cat_id).execute()
    
    cat_name = cat_res.data['name']
    q_count = q_res.count if q_res.count else 0

    txt = (f"⚙️ **إعدادات القسم: {cat_name}**\n\n"
           f"📊 عدد الأسئلة المضافة: {q_count}\n"
           f"ماذا تريد أن تفعل الآن؟")

    # بناء الأزرار وتشفيرها بالآيدي المزدوج (cat_id + owner_id)
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ إضافة سؤال", callback_data=f"add_q_{cat_id}_{owner_id}"),
        InlineKeyboardButton("📝 تعديل الاسم", callback_data=f"edit_cat_{cat_id}_{owner_id}")
    )
    kb.add(
        InlineKeyboardButton("🔍 عرض الأسئلة", callback_data=f"view_qs_{cat_id}_{owner_id}"),
        InlineKeyboardButton("🗑️ حذف الأسئلة", callback_data=f"del_qs_menu_{cat_id}_{owner_id}")
    )
    kb.add(InlineKeyboardButton("❌ حذف القسم", callback_data=f"confirm_del_cat_{cat_id}_{owner_id}"))
    kb.add(
        InlineKeyboardButton("🔙 رجوع", callback_data=f"list_cats_{owner_id}"),
        InlineKeyboardButton("🏠 الرئيسية", callback_data=f"back_to_control_{owner_id}")
    )
    
    if is_edit:
        await message.edit_text(txt, reply_markup=kb, parse_mode="Markdown")
    else:
        # تستخدم هذه بعد الـ message_handler (save_cat) لأن الرسالة السابقة قد حذفت
        await message.answer(txt, reply_markup=kb, parse_mode="Markdown")
# ==========================================
# ==========================================
def get_setup_quiz_kb(user_id):
    """كيبورد تهيئة المسابقة مشفر بآيدي المستخدم"""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("👥 أقسام الأعضاء (إبداعات الآخرين)", callback_data=f"members_setup_step1_{user_id}"),
        InlineKeyboardButton("👤 أقسامك الخاصة (مكتبتي)", callback_data=f"my_setup_step1_{user_id}"),
        InlineKeyboardButton("🤖 أقسام البوت (الرسمية)", callback_data=f"bot_setup_step1_{user_id}"),
        # تم الإصلاح ليعود للوحة التحكم الرئيسية الخاصة بك
        InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data=f"back_to_control_{user_id}")
    )
    return kb

def generate_members_keyboard(members, selected_list, user_id):
    """كيبورد اختيار الأعضاء مع حماية المبعسسين"""
    kb = InlineKeyboardMarkup(row_width=2)
    for m in members:
        m_id = str(m['user_id'])
        mark = "✅ " if m_id in selected_list else ""
        # نمرر آيدي المستخدم في نهاية الكولباك لضمان الحماية في الخطوة القادمة
        kb.insert(InlineKeyboardButton(f"{mark}{m['name']}", callback_data=f"toggle_mem_{m_id}_{user_id}"))
    
    kb.add(InlineKeyboardButton("➡️ التالي (اختيار الأقسام)", callback_data=f"go_to_cats_selection_{user_id}"))
    kb.add(InlineKeyboardButton("🔙 رجوع", callback_data=f"setup_quiz_{user_id}"))
    return kb
# دالة عرض المبدعين المحدثة
async def render_members_list(message, eligible_ids, selected_list, owner_id):
    kb = InlineKeyboardMarkup(row_width=2)
    for m_id in eligible_ids:
        status = "✅ " if str(m_id) in selected_list else ""
        # تشفير الزر بآيدي العضو وآيدي صاحب الجلسة
        kb.insert(InlineKeyboardButton(f"{status} المبدع: {str(m_id)[-6:]}", callback_data=f"toggle_mem_{m_id}_{owner_id}"))
    
    if selected_list:
        kb.add(InlineKeyboardButton(f"➡️ تم اختيار ({len(selected_list)}) .. عرض أقسامهم", callback_data=f"go_to_cats_step_{owner_id}"))
    
    kb.add(InlineKeyboardButton("🔙 رجوع", callback_data=f"setup_quiz_{owner_id}"))
    await message.edit_text("👥 **أقسام الأعضاء:**", reply_markup=kb)

# دالة عرض الأقسام المحدثة
async def render_categories_list(message, eligible_cats, selected_cats, owner_id):
    kb = InlineKeyboardMarkup(row_width=2)
    for cat in eligible_cats:
        cat_id_str = str(cat['id'])
        status = "✅ " if cat_id_str in selected_cats else ""
        kb.insert(InlineKeyboardButton(f"{status}{cat['name']}", callback_data=f"toggle_cat_{cat_id_str}_{owner_id}"))
    
    if selected_cats:
        kb.add(InlineKeyboardButton(f"➡️ تم اختيار ({len(selected_cats)}) .. الإعدادات", callback_data=f"final_quiz_settings_{owner_id}"))
    
    kb.add(InlineKeyboardButton("🔙 رجوع", callback_data=f"setup_quiz_{owner_id}"))
    await message.edit_text("📂 **اختر الأقسام:**", reply_markup=kb)
# ==========================================
# ==========================================
async def render_final_settings_panel(message, data, owner_id):
    """الدالة الموحدة لعرض لوحة الإعدادات النهائية مشفرة بآيدي المالك"""
    q_time = data.get('quiz_time', 15)
    q_count = data.get('quiz_count', 10)
    q_mode = data.get('quiz_mode', 'السرعة ⚡')
    is_hint = data.get('quiz_hint_bool', False)
    is_broadcast = data.get('is_broadcast', False)
    
    q_hint_text = "مفعل ✅" if is_hint else "معطل ❌"
    q_scope_text = "إذاعة عامة 🌐" if is_broadcast else "مسابقة داخلية 📍"
    
    text = (
       f"⚙️ **لوحة تشطيب المسابقة النهائية**\n"
       f"━━━━━━━━━━━━━━━━━━━\n"
       f"📊 عدد الأسئلة: {q_count}\n"
       f"📡 النطاق: {q_scope_text}\n"
       f"🔖 النظام: {q_mode}\n"
       f"⏳ المهلة: {q_time} ثانية\n"
       f"💡 التلميح: {q_hint_text}\n"
       f"━━━━━━━━━━━━━━━━━━━\n"
       f"⚠️ *هذه الإعدادات خاصة بـ {data.get('owner_name', 'المنظم')} فقط*"
    )

    kb = InlineKeyboardMarkup(row_width=5)
    
    # 1. أزرار الأعداد
    kb.row(InlineKeyboardButton("📊 اختر عدد الأسئلة:", callback_data="ignore"))
    counts = [10, 15, 25, 32, 45]
    btn_counts = [InlineKeyboardButton(f"{'✅' if q_count==n else ''}{n}", callback_data=f"set_cnt_{n}_{owner_id}") for n in counts]
    kb.add(*btn_counts)

    # 2. أزرار التحكم (مشفره بالـ owner_id)
    kb.row(InlineKeyboardButton(f"⏱️ المهلة: {q_time} ثانية", callback_data=f"cyc_time_{owner_id}"))
    kb.row(
        InlineKeyboardButton(f"🔖 {q_mode}", callback_data=f"cyc_mode_{owner_id}"),
        InlineKeyboardButton(f"💡 التلميح: {q_hint_text}", callback_data=f"cyc_hint_{owner_id}")
    )
    kb.row(InlineKeyboardButton(f"📡 النطاق: {q_scope_text}", callback_data=f"tog_broad_{owner_id}"))
    
    kb.row(InlineKeyboardButton("🚀 حفظ وبدء المسابقة 🚀", callback_data=f"start_quiz_{owner_id}"))
    kb.row(InlineKeyboardButton("❌ إلغاء", callback_data=f"setup_quiz_{owner_id}"))
    
    await message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
# ==========================================
# 3. دوال الفحص الأمني (Security Helpers)
# ==========================================

async def get_group_status(chat_id):
    """فحص حالة تفعيل المجموعة في قاعدة البيانات"""
    try:
        res = supabase.table("allowed_groups").select("status").eq("group_id", chat_id).execute()
        return res.data[0]['status'] if res.data else "not_found"
    except:
        return "error"
        
# ==========================================

class Form(StatesGroup):
    waiting_for_cat_name = State()
    waiting_for_question = State()
    waiting_for_ans1 = State()
    waiting_for_ans2 = State()
    waiting_for_new_cat_name = State()

# --- 1. الأوامر الأساسية ونظام التفعيل الاحترافي ---

@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    user_mention = message.from_user.mention
    welcome_txt = (
        f"مرحبا بك {user_mention} في بوت مسابقات نسخة تجريبيه.\n\n"
        f"تستطيع الآن إضافة أقسامك الخاصة وقم بتهيئة المسابقات منها.\n\n"
        f"🔹 <b>لتفعيل البوت في مجموعتك:</b> أرسل كلمة (تفعيل)\n"
        f"🔹 <b>للإعدادات:</b> أرسل (تحكم)\n"
        f"🔹 <b>للبدء:</b> أرسل (مسابقة)"
    )
    await message.answer(welcome_txt)

# --- [ أمر التحكم الرئيسي - بعد أمر start مباشرة ] ---

@dp.message_handler(lambda m: m.text == "تحكم")
async def control_panel(message: types.Message):
    user_id = message.from_user.id
    
    
    # الحالة الأولى: إذا كانت الدردشة "خاص" (Private)
    if message.chat.type == 'private':
        # في الخاص، البوت يفتح اللوحة فوراً للمستخدم لأنها دردشة شخصية
        pass 
    
    # الحالة الثانية: إذا كانت الدردشة "مجموعة" (Group/Supergroup)
    else:
        
        if user_id == ADMIN_ID:
            pass
        else:
            # ثانياً: فحص حالة تفعيل المجموعة من قاعدة البيانات
            status = await get_group_status(message.chat.id)
            
            # إذا لم تكن المجموعة مفعلة، نمنع الجميع حتى المشرفين
            if status != "active":
                return await message.reply(
                    "⚠️ <b>عذراً، يجب تفعيل المجموعة أولاً بواسطة المطور.</b>\n"
                    "أرسل كلمة (تفعيل) لطلب الموافقة.", 
                    parse_mode="HTML"
                )
            
            # ثالثاً: إذا كانت مفعلة، نتأكد أن الذي أرسل الأمر "مشرف"
            member = await bot.get_chat_member(message.chat.id, user_id)
            if not (member.is_chat_admin() or member.is_chat_creator()):
                return await message.reply("⚠️ هذه اللوحة مخصصة لمشرفي المجموعة فقط.")

    # --- [ استدعاء اللوحة الذكية ] ---
    # هنا يتم استدعاء الدالة get_main_control_kb وتمرير user_id لها
    # لضمان أن صاحب اللوحة فقط هو من يتحكم بالأزرار
    
    txt = (f"👋 أهلا بك في لوحة أعدادات المسابقات الخاصة \n"
           f"👑 المطور: <b>{OWNER_USERNAME}</b>")
    
    await message.answer(
        txt, 
        reply_markup=get_main_control_kb(user_id), 
        disable_web_page_preview=True
    )

# --- [ معالج أزرار لوحة التحكم - المحرك الذكي ] ---

@dp.callback_query_handler(lambda c: c.data.startswith(('custom_add_', 'dev_', 'setup_quiz_', 'close_bot_')))
async def handle_control_buttons(c: types.CallbackQuery):
    # 1. فك التشفير (الأمر + آيدي صاحب اللوحة)
    data_parts = c.data.split('_')
    action = data_parts[0]
    owner_id = int(data_parts[-1]) 

    # 🛑 [ الأمان ]: طرد المبعسسين فوراً
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ هذي اللوحة مش حقك! اطلب لوحة خاصة فيك 😂", show_alert=True)

    # 🛠️ [ أزرار التطوير ]: جلسة سابقة ولوحة الصدارة
    if action == "dev":
        return await c.answer("🛠️ هذا القسم قيد التطوير حالياً.. انتظر التحديث يا بطل!", show_alert=True)

    # 🛑 [ زر الإغلاق ]: مسح الواجهة
    if action == "close":
        await c.message.delete()
        return await c.answer("تم إغلاق اللوحة ✅")

    # 📝 [ زر إضافة خاصة ]: الانتقال لقائمة الأقسام
    if action == "custom":
        await c.answer()
        # هنا نستدعي دالة قائمة الأقسام مع تمرير owner_id عشان الحماية تستمر
        await custom_add_menu(c, owner_id)
        
# --- معالج أزرار التفعيل (الإصدار الآمن والمضمون) ---
@dp.callback_query_handler(lambda c: c.data.startswith(('approve_', 'ban_')), user_id=ADMIN_ID)
async def process_auth_callback(callback_query: types.CallbackQuery):
    # تقسيم البيانات: الأكشن والآيدي
    data_parts = callback_query.data.split('_')
    action = data_parts[0]  # approve أو ban
    target_id = data_parts[1] # آيدي القروب

    if action == "approve":
        # تحديث الحالة إلى نشط
        supabase.table("allowed_groups").update({"status": "active"}).eq("group_id", target_id).execute()
        
        await callback_query.answer("تم التفعيل ✅", show_alert=True)
        await callback_query.message.edit_text(
            f"{callback_query.message.text}\n\n✅ **تم التفعيل بنجاح بواسطة المطور**", 
            parse_mode="Markdown"
        )
        # إشعار القروب
        await bot.send_message(target_id, " **مبارك! تم تفعيل القروب.** أرسل كلمة (مسابقة) للبدء.", parse_mode="Markdown")
    
    elif action == "ban":
        # تحديث الحالة إلى محظور
        supabase.table("allowed_groups").update({"status": "blocked"}).eq("group_id", target_id).execute()
        
        await callback_query.answer("تم الحظر ❌", show_alert=True)
        await callback_query.message.edit_text(
            f"{callback_query.message.text}\n\n❌ **تم رفض الطلب وحظر القروب**", 
            parse_mode="Markdown"
        )
        # إشعار القروب (اختياري)
        await bot.send_message(target_id, "🚫 **نعتذر، تم رفض طلب تفعيل البوت في هذا القروب.**")

# --- 2. إدارة الأقسام والأسئلة (نسخة محمية بآيدي المستخدم) ---

@dp.callback_query_handler(lambda c: c.data.startswith('custom_add'), state="*")
async def custom_add_menu(c: types.CallbackQuery, state: FSMContext):
    await state.finish()
    # استخراج الآيدي من الكولباك (إذا كان موجوداً) أو استخدامه من الشخص الذي ضغط
    data_parts = c.data.split('_')
    owner_id = int(data_parts[-1]) if len(data_parts) > 1 else c.from_user.id

    # حماية من المبعسسين
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ هذي اللوحة مش حقك! 😂", show_alert=True)

# ==========================================
# ==========================================
    
    await c.message.edit_text(
        "⚙️ **لوحة إعدادات أقسامك الخاصة:**\nيمكنك إضافة أقسام جديدة أو إدارة الأقسام الحالية.", 
        reply_markup=kb, 
        parse_mode="Markdown"
    )
    await c.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('add_new_cat'), state="*")
async def btn_add_cat(c: types.CallbackQuery):
    owner_id = int(c.data.split('_')[-1])
    
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا يمكنك الإضافة في لوحة غيرك!", show_alert=True)

    await c.answer() 
    await Form.waiting_for_cat_name.set()
    
    # زر إلغاء محمي يعود للأقسام بالآيدي الصحيح
    kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🚫 إلغاء", callback_data=f"custom_add_{owner_id}")
    )
    await c.message.answer("📝 **اكتب اسم القسم الجديد:**", reply_markup=kb, parse_mode="Markdown")

@dp.message_handler(state=Form.waiting_for_cat_name)
async def save_cat(message: types.Message, state: FSMContext):
    cat_name = message.text.strip()
    user_id = message.from_user.id
    try:
        # 1. إدراج القسم في قاعدة البيانات مع ربطه بآيدي المستخدم
        supabase.table("categories").insert({
            "name": cat_name, 
            "created_by": str(user_id)
        }).execute()
        
        await state.finish()
        
        # 2. أزرار نجاح محمية بالكامل
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("➕ إضافة قسم آخر", callback_data=f"add_new_cat_{user_id}"),
            InlineKeyboardButton("🔙 العودة للأقسام", callback_data=f"custom_add_{user_id}")
        )
        await message.answer(f"✅ تم حفظ القسم **'{cat_name}'** بنجاح.", reply_markup=kb, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Error saving category: {e}")
        await state.finish()
        
        # في حال الخطأ، نعرض له أقسامه فقط مع أزرار محمية
        res = supabase.table("categories").select("*").eq("created_by", str(user_id)).execute()
        categories = res.data

        kb = InlineKeyboardMarkup(row_width=1)
        if categories:
            for cat in categories:
                kb.add(InlineKeyboardButton(f"📂 {cat['name']}", callback_data=f"manage_questions_{cat['id']}_{user_id}"))

        kb.add(InlineKeyboardButton("⬅️ الرجوع", callback_data=f"custom_add_{user_id}"))
        await message.answer("❌ الاسم مكرر أو حدث خطأ. إليك أقسامك الحالية:", reply_markup=kb)
        # 1. جلب معرف المستخدم لفلترة الأقسام فوراً
        user_id = str(message.from_user.id)
        
        # 2. التعديل الجوهري: إضافة شرط .eq لكي تظهر أقسام المنشئ فقط
        res = supabase.table("categories").select("*").eq("created_by", user_id).execute()
        categories = res.data

        kb = InlineKeyboardMarkup(row_width=1)
        if categories:
            for cat in categories:
                # هنا سيتم عرض أقسام عبير فقط ولن تظهر أقسامك
                kb.add(InlineKeyboardButton(f"📂 {cat['name']}", callback_data=f"manage_questions_{cat['id']}"))

        kb.add(InlineKeyboardButton("⬅️ الرجوع", callback_data="custom_add_menu"))
        await message.answer("📋 اختر أحد أقسامك لإدارة الأسئلة:", reply_markup=kb)

    except Exception as e:
        logging.error(f"Error: {e}")
        await message.answer("⚠️ حدث خطأ أثناء الحفظ، جرب مرة أخرى.")
        
# --- 1. نافذة إعدادات القسم (عند الضغط على اسمه) ---
@dp.callback_query_handler(lambda c: c.data.startswith('manage_questions_'))
async def manage_questions_window(c: types.CallbackQuery):
    # تفكيك البيانات: manage_questions_ID_USERID
    data = c.data.split('_')
    cat_id = data[2]
    owner_id = int(data[3])

    # حماية من المبعسسين
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ هذه اللوحة ليست لك!", show_alert=True)

    await c.answer()
    # استدعاء الدالة الموحدة
    await show_category_settings_ui(c.message, cat_id, owner_id, is_edit=True)


# --- 2. بدء تعديل اسم القسم ---
@dp.callback_query_handler(lambda c: c.data.startswith('edit_cat_'))
async def edit_category_start(c: types.CallbackQuery, state: FSMContext):
    data = c.data.split('_')
    cat_id = data[2]
    owner_id = int(data[3])

    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا تملك صلاحية التعديل!", show_alert=True)

    await c.answer()
    await state.update_data(edit_cat_id=cat_id, edit_owner_id=owner_id)
    await Form.waiting_for_new_cat_name.set()
    
    # زر تراجع ذكي يعود لصفحة الإعدادات
    kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🚫 تراجع", callback_data=f"manage_questions_{cat_id}_{owner_id}")
    )
    await c.message.edit_text("📝 **نظام التعديل:**\n\nأرسل الآن الاسم الجديد للقسم:", reply_markup=kb)


# --- 3. حفظ الاسم الجديد (استدعاء الدالة الموحدة بعد الحفظ) ---
@dp.message_handler(state=Form.waiting_for_new_cat_name)
async def save_edited_category(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cat_id = data['edit_cat_id']
    owner_id = data['edit_owner_id']
    new_name = message.text.strip()
    
    # تحديث الاسم في Supabase
    supabase.table("categories").update({"name": new_name}).eq("id", cat_id).execute()
    
    # تنظيف الشات
    try: await message.delete()
    except: pass

    await state.finish()
    
    # الاستدعاء الذكي: نرسل رسالة جديدة (is_edit=False) لأننا حذفنا رسالة المستخدم
    # ونعرض لوحة الإعدادات بالاسم الجديد فوراً
    await show_category_settings_ui(message, cat_id, owner_id, is_edit=False)
# ==========================================
# --- 3. نظام إضافة سؤال (محمي ومنظم) ---
# ==========================================

@dp.callback_query_handler(lambda c: c.data.startswith('add_q_'))
async def start_add_question(c: types.CallbackQuery, state: FSMContext):
    data_parts = c.data.split('_')
    cat_id = data_parts[2]
    owner_id = int(data_parts[3])

    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا يمكنك إضافة أسئلة في لوحة غيرك!", show_alert=True)

    await c.answer()
    await state.update_data(current_cat_id=cat_id, current_owner_id=owner_id, last_bot_msg_id=c.message.message_id)
    await Form.waiting_for_question.set()
    
    # زر إلغاء محمي
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🚫 إلغاء", callback_data=f"manage_questions_{cat_id}_{owner_id}"))
    await c.message.edit_text("❓ **نظام إضافة الأسئلة:**\n\nاكتب الآن السؤال الذي تريد إضافته:", reply_markup=kb)

@dp.message_handler(state=Form.waiting_for_question)
async def process_q_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(q_content=message.text)
    
    try:
        await message.delete()
        await bot.delete_message(message.chat.id, data['last_bot_msg_id'])
    except: pass

    await Form.waiting_for_ans1.set()
    msg = await message.answer("✅ تم حفظ نص السؤال.\n\nالآن أرسل **الإجابة الصحيحة** الأولى:")
    await state.update_data(last_bot_msg_id=msg.message_id)

@dp.message_handler(state=Form.waiting_for_ans1)
async def process_first_ans(message: types.Message, state: FSMContext):
    data = await state.get_data()
    owner_id = data['current_owner_id']
    await state.update_data(ans1=message.text)
    
    try: await bot.delete_message(message.chat.id, data['last_bot_msg_id'])
    except: pass
    
    # تشفير أزرار نعم/لا بالآيدي لضمان استمرار الحماية
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ نعم، إضافة ثانية", callback_data=f"add_ans2_{owner_id}"),
        InlineKeyboardButton("❌ لا، إجابة واحدة فقط", callback_data=f"no_ans2_{owner_id}")
    )
    msg = await message.answer(f"✅ تم حفظ الإجابة: ({message.text})\n\nهل تريد إضافة إجابة ثانية (بديلة)؟", reply_markup=kb)
    await state.update_data(last_bot_msg_id=msg.message_id)

# --- معالج إضافة إجابة ثانية ---
@dp.callback_query_handler(lambda c: c.data.startswith('add_ans2_'), state='*')
async def add_second_ans_start(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ عذراً، اللوحة محمية!", show_alert=True)
    
    await c.answer()
    await Form.waiting_for_ans2.set()
    await c.message.edit_text("📝 أرسل الآن **الإجابة الثانية** البديلة:")

@dp.message_handler(state=Form.waiting_for_ans2)
async def process_second_ans(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cat_id = data.get('current_cat_id')
    owner_id = data.get('current_owner_id')

    supabase.table("questions").insert({
        "category_id": cat_id,
        "question_content": data.get('q_content'),
        "correct_answer": data.get('ans1'),
        "alternative_answer": message.text,
        "created_by": str(owner_id)
    }).execute()

    await state.finish()
    try: 
        await message.delete()
        await bot.delete_message(message.chat.id, data['last_bot_msg_id'])
    except: pass
    
    # العودة للوحة الإعدادات باستخدام الدالة الموحدة
    await show_category_settings_ui(message, cat_id, owner_id, is_edit=False)

# --- معالج رفض إضافة إجابة ثانية (إصلاح زر لا) ---
@dp.callback_query_handler(lambda c: c.data.startswith('no_ans2_'), state='*')
async def finalize_no_second(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة ليست لك!", show_alert=True)
    
    await c.answer()
    data = await state.get_data()
    cat_id = data.get('current_cat_id')

    supabase.table("questions").insert({
        "category_id": cat_id,
        "question_content": data.get('q_content'),
        "correct_answer": data.get('ans1'),
        "created_by": str(owner_id)
    }).execute()

    await state.finish()
    try: await c.message.delete()
    except: pass
    
    # العودة للوحة الإعدادات باستخدام الدالة الموحدة
    await show_category_settings_ui(c.message, cat_id, owner_id, is_edit=False)

# ==========================================
# --- 5. نظام عرض الأسئلة (المحمي بآيدي صاحب القسم) ---
# ==========================================

@dp.callback_query_handler(lambda c: c.data.startswith('view_qs_'), state="*")
async def view_questions(c: types.CallbackQuery):
    # تفكيك البيانات: view_qs_CATID_OWNERID
    data = c.data.split('_')
    cat_id = data[2]
    owner_id = int(data[3])

    # 🛑 حماية من المبعسسين
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا يمكنك عرض أسئلة في لوحة غيرك!", show_alert=True)

    await c.answer()

    # جلب الأسئلة من Supabase
    questions = supabase.table("questions").select("*").eq("category_id", cat_id).execute()
    
    # إذا كان القسم فارغاً
    if not questions.data:
        kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("🔙 رجوع", callback_data=f"manage_questions_{cat_id}_{owner_id}")
        )
        return await c.message.edit_text("⚠️ لا توجد أسئلة مضافة في هذا القسم حالياً.", reply_markup=kb)

    # بناء نص عرض الأسئلة
    txt = f"🔍 **قائمة الأسئلة المضافة:**\n"
    txt += "--- --- --- ---\n\n"
    
    for i, q in enumerate(questions.data, 1):
        txt += f"<b>{i} - {q['question_content']}</b>\n"
        txt += f"✅ ج1: {q['correct_answer']}\n"
        # التحقق من وجود إجابة بديلة (ج2)
        if q.get('alternative_answer'):
            txt += f"💡 ج2: {q['alternative_answer']}\n"
        txt += "--- --- --- ---\n"

    # أزرار التحكم في القائمة (محمية بالآيدي)
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🗑️ حذف الأسئلة", callback_data=f"del_qs_menu_{cat_id}_{owner_id}"),
        InlineKeyboardButton("🔙 رجوع لإعدادات القسم", callback_data=f"manage_questions_{cat_id}_{owner_id}")
    )
    
    # استخدام HTML ليكون النص أوضح (bold للعناوين)
    await c.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

# --- 6. نظام حذف الأسئلة (المحمي) ---

@dp.callback_query_handler(lambda c: c.data.startswith('del_qs_menu_'))
async def delete_questions_menu(c: types.CallbackQuery):
    data = c.data.split('_')
    cat_id = data[3]
    owner_id = int(data[4])

    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا تملك صلاحية الحذف هنا!", show_alert=True)

    await c.answer()
    questions = supabase.table("questions").select("*").eq("category_id", cat_id).execute()
    
    kb = InlineKeyboardMarkup(row_width=1)
    if questions.data:
        for q in questions.data:
            # تشفير بيانات الحذف (ID السؤال + ID القسم + ID المالك)
            kb.add(InlineKeyboardButton(
                f"🗑️ حذف: {q['question_content'][:25]}...", 
                callback_data=f"pre_del_q_{q['id']}_{cat_id}_{owner_id}"
            ))
    
    kb.add(InlineKeyboardButton("🔙 رجوع", callback_data=f"manage_questions_{cat_id}_{owner_id}"))
    await c.message.edit_text("🗑️ اختر السؤال المراد حذفه:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('pre_del_q_'))
async def confirm_delete_question(c: types.CallbackQuery):
    data = c.data.split('_')
    q_id, cat_id, owner_id = data[3], data[4], data[5]

    if c.from_user.id != int(owner_id):
        return await c.answer("⚠️ مبعسس؟ ما تقدر تحذف! 😂", show_alert=True)
    
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ نعم، احذف", callback_data=f"final_del_q_{q_id}_{cat_id}_{owner_id}"),
        InlineKeyboardButton("❌ تراجع", callback_data=f"del_qs_menu_{cat_id}_{owner_id}")
    )
    await c.message.edit_text("⚠️ هل أنت متأكد من حذف هذا السؤال؟", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('final_del_q_'))
async def execute_delete_question(c: types.CallbackQuery):
    data = c.data.split('_')
    q_id, cat_id, owner_id = data[3], data[4], data[5]
    
    # تنفيذ الحذف في سوبابيس
    supabase.table("questions").delete().eq("id", q_id).execute()
    await c.answer("🗑️ تم الحذف بنجاح", show_alert=True)
    
    # تحديث قائمة الحذف تلقائياً
    await delete_questions_menu(c)


# --- 7. حذف القسم نهائياً (مع التأكيد) ---

@dp.callback_query_handler(lambda c: c.data.startswith('confirm_del_cat_'))
async def confirm_delete_cat(c: types.CallbackQuery):
    data = c.data.split('_')
    cat_id = data[3]
    owner_id = int(data[4])

    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا تملك صلاحية حذف الأقسام!", show_alert=True)

    await c.answer()
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ نعم، احذف", callback_data=f"final_del_cat_{cat_id}_{owner_id}"),
        InlineKeyboardButton("❌ لا، تراجع", callback_data=f"manage_questions_{cat_id}_{owner_id}")
    )
    await c.message.edit_text("⚠️ هل أنت متأكد من حذف هذا القسم نهائياً مع كل أسئلته؟", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('final_del_cat_'))
async def execute_delete_cat(c: types.CallbackQuery):
    data = c.data.split('_')
    cat_id = data[3]
    owner_id = int(data[4])

    # تنفيذ الحذف النهائي للقسم (سوبابيس سيحذف الأسئلة المرتبطة به تلقائياً إذا فعلت Cascade)
    supabase.table("categories").delete().eq("id", cat_id).execute()
    await c.answer("🗑️ تم حذف القسم بالكامل بنجاح", show_alert=True)
    
    # الرجوع لقائمة الأقسام الرئيسية باستخدام دالة custom_add_menu التي أصلحناها بالآيدي
    await custom_add_menu(c, state=None)
    
# --- 8. نظام عرض قائمة الأقسام (تصفية وحماية) ---
@dp.callback_query_handler(lambda c: c.data.startswith('list_cats_'))
async def list_categories_for_questions(c: types.CallbackQuery):
    try:
        # استخراج الآيدي من الكولباك لضمان الحماية
        owner_id = int(c.data.split('_')[-1])
        
        if c.from_user.id != owner_id:
            return await c.answer("⚠️ لا يمكنك استعراض أقسام غيرك!", show_alert=True)

        await c.answer()
        
        # طلب الأقسام التي تخص هذا المستخدم فقط من سوبابيس
        res = supabase.table("categories").select("*").eq("created_by", str(owner_id)).execute()
        categories = res.data

        if not categories:
            # إذا لم يكن لديه أقسام، نرسل تنبيهاً ونبقى في نفس اللوحة
            return await c.answer("⚠️ ليس لديك أقسام خاصة بك حالياً، قم بإضافة قسم أولاً.", show_alert=True)

        kb = InlineKeyboardMarkup(row_width=1)
        for cat in categories:
            # تشفير أزرار الأقسام بآيدي القسم وآيدي المالك
            # manage_questions_CATID_OWNERID
            kb.add(InlineKeyboardButton(
                f"📂 {cat['name']}", 
                callback_data=f"manage_questions_{cat['id']}_{owner_id}"
            ))

        # زر الرجوع للوحة "إضافة خاصة" بآيدي المستخدم
        kb.add(InlineKeyboardButton("⬅️ الرجوع", callback_data=f"custom_add_{owner_id}"))
        
        await c.message.edit_text("📋 اختر أحد أقسامك لإدارة الأسئلة:", reply_markup=kb)

    except Exception as e:
        logging.error(f"Filter Error: {e}")
        await c.answer("⚠️ حدث خطأ في جلب الأقسام.")

# --- 1. واجهة تهيئة المسابقة (النسخة النظيفة والمحمية) ---
@dp.callback_query_handler(lambda c: c.data.startswith('setup_quiz'), state="*")
async def setup_quiz_main(c: types.CallbackQuery, state: FSMContext):
    await state.finish()
    
    # تحديد الهوية: هل هو ضغط مباشر أم قادم من زر رجوع مشفر؟
    data_parts = c.data.split('_')
    owner_id = int(data_parts[-1]) if len(data_parts) > 1 else c.from_user.id
    
    # حماية المبعسسين
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ اللوحة مش حقك يا حبيبنا 😂", show_alert=True)
    
    await c.answer()
    
    # حفظ صاحب الجلسة في الـ State
    await state.update_data(owner_id=owner_id, owner_name=c.from_user.first_name)
    
    text = "🎉 **أهلاً بك!**\nقم بتهيئة المسابقة عن طريق اختيار مصدر الأسئلة:"
    
    # هنا الحذف والاستدعاء: استدعينا الدالة من قسم المساعدة
    await c.message.edit_text(
        text, 
        reply_markup=get_setup_quiz_kb(owner_id), 
        parse_mode="Markdown"
    )

# ==========================================
# 1. اختيار مصدر الأسئلة (رسمي / خاص / أعضاء)
# ==========================================

@dp.callback_query_handler(lambda c: c.data.startswith('bot_setup_step1_'), state="*")
async def start_bot_selection(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة محمية!", show_alert=True)
    
    res = supabase.table("bot_categories").select("id, name").execute()
    if not res.data: return await c.answer("⚠️ لا توجد أقسام رسمية!", show_alert=True)

    eligible_cats = [{"id": str(item['id']), "name": item['name']} for item in res.data]
    await state.update_data(eligible_cats=eligible_cats, selected_cats=[], is_bot_quiz=True, current_owner_id=owner_id) 
    await render_categories_list(c.message, eligible_cats, [], owner_id)

@dp.callback_query_handler(lambda c: c.data.startswith('my_setup_step1_'), state="*")
async def start_private_selection(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة محمية!", show_alert=True)
    
    res = supabase.table("categories").select("*").eq("created_by", str(owner_id)).execute()
    if not res.data: return await c.answer("⚠️ ليس لديك أقسام خاصة!", show_alert=True)
    
    await state.update_data(eligible_cats=res.data, selected_cats=[], is_bot_quiz=False, current_owner_id=owner_id) 
    await render_categories_list(c.message, res.data, [], owner_id)

@dp.callback_query_handler(lambda c: c.data.startswith('members_setup_step1_'), state="*")
async def start_member_selection(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة محمية!", show_alert=True)
    
    res = supabase.table("questions").select("created_by").execute()
    if not res.data: return await c.answer("⚠️ لا يوجد أعضاء حالياً.", show_alert=True)
    
    from collections import Counter
    counts = Counter([q['created_by'] for q in res.data])
    eligible_ids = [m_id for m_id, count in counts.items() if count >= 15]
    
    if not eligible_ids: return await c.answer("⚠️ لا يوجد مبدعون وصلوا لـ 15 سؤال.", show_alert=True)
    
    await state.update_data(eligible_list=eligible_ids, selected_members=[], is_bot_quiz=False, current_owner_id=owner_id)
    await render_members_list(c.message, eligible_ids, [], owner_id)

# ==========================================
# 2. معالجات التبديل والاختيار (Toggle & Go)
# ==========================================

@dp.callback_query_handler(lambda c: c.data.startswith('toggle_mem_'), state="*")
async def toggle_member(c: types.CallbackQuery, state: FSMContext):
    data_parts = c.data.split('_')
    m_id = data_parts[2]
    owner_id = int(data_parts[3])
    
    if c.from_user.id != owner_id: return await c.answer("⚠️ مبعسس؟ ما تقدر تختار! 😂", show_alert=True)
    
    data = await state.get_data()
    selected = data.get('selected_members', [])
    eligible = data.get('eligible_list', [])
    
    if m_id in selected: selected.remove(m_id)
    else: selected.append(m_id)
    
    await state.update_data(selected_members=selected)
    await c.answer()
    await render_members_list(c.message, eligible, selected, owner_id)

@dp.callback_query_handler(lambda c: c.data.startswith('go_to_cats_step_'), state="*")
async def show_selected_members_cats(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة ليست لك!", show_alert=True)
    
    data = await state.get_data()
    chosen_ids = data.get('selected_members', [])
    res = supabase.table("categories").select("id, name").in_("created_by", chosen_ids).execute()
    
    await state.update_data(eligible_cats=res.data, selected_cats=[])
    await render_categories_list(c.message, res.data, [], owner_id)

@dp.callback_query_handler(lambda c: c.data.startswith('toggle_cat_'), state="*")
async def toggle_category_selection(c: types.CallbackQuery, state: FSMContext):
    data_parts = c.data.split('_')
    cat_id = data_parts[2]
    owner_id = int(data_parts[3])
    
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة محمية!", show_alert=True)

    data = await state.get_data()
    selected = data.get('selected_cats', [])
    eligible = data.get('eligible_cats', [])
    
    if cat_id in selected: selected.remove(cat_id)
    else: selected.append(cat_id)
    
    await state.update_data(selected_cats=selected)
    await c.answer()
    await render_categories_list(c.message, eligible, selected, owner_id)

# --- 4. لوحة الإعدادات (استدعاء دالة المساعدة) ---
@dp.callback_query_handler(lambda c: c.data.startswith('final_quiz_settings'), state="*")
async def final_quiz_settings_panel(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    # جلب owner_id من البيانات المخزنة لضمان الحماية
    owner_id = data.get('current_owner_id') or c.from_user.id
    
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ هذه اللوحة محمية لصاحب المسابقة!", show_alert=True)
    
    await c.answer()
    # استدعاء دالة العرض من قسم المساعدة
    await render_final_settings_panel(c.message, data, owner_id)


# --- 5. المحركات الموحدة (تم دمج 5 دوال في دالة واحدة ذكية) ---
@dp.callback_query_handler(lambda c: c.data.startswith(('tog_broad_', 'cyc_hint_', 'cyc_time_', 'cyc_mode_', 'set_cnt_')), state="*")
async def quiz_settings_engines(c: types.CallbackQuery, state: FSMContext):
    data_parts = c.data.split('_')
    action = data_parts[0] # tog, cyc, set
    owner_id = int(data_parts[-1])
    
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا تتدخل في إعدادات غيرك! 😂", show_alert=True)

    data = await state.get_data()
    
    # محرك النطاق (إذاعة/داخلي)
    if action == 'tog':
        await state.update_data(is_broadcast=not data.get('is_broadcast', False))
    
    # محرك التلميح
    elif action == 'cyc' and data_parts[1] == 'hint':
        await state.update_data(quiz_hint_bool=not data.get('quiz_hint_bool', False))
    
    # محرك الوقت
    elif action == 'cyc' and data_parts[1] == 'time':
        curr = data.get('quiz_time', 15)
        next_t = 20 if curr == 15 else (30 if curr == 20 else (45 if curr == 30 else 15))
        await state.update_data(quiz_time=next_t)
        
    # محرك النظام (سرعة/كامل)
    elif action == 'cyc' and data_parts[1] == 'mode':
        curr_m = data.get('quiz_mode', 'السرعة ⚡')
        next_m = 'الوقت الكامل ⏳' if curr_m == 'السرعة ⚡' else 'السرعة ⚡'
        await state.update_data(quiz_mode=next_m)

    # محرك عدد الأسئلة
    elif action == 'set' and data_parts[1] == 'cnt':
        await state.update_data(quiz_count=int(data_parts[2]))

    # بعد كل عملية.. نحدث اللوحة فوراً
    new_data = await state.get_data()
    await render_final_settings_panel(c.message, new_data, owner_id)


# --- 6. معالج الحفظ (الذي جهزناه لك قبل قليل) ---
@dp.callback_query_handler(lambda c: c.data.startswith('start_quiz_'), state="*")
async def start_save_process(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return
    
    await c.answer()
    await c.message.edit_text("📝 **يا بطل، أرسل الآن اسماً لمسابقتك:**")
    await state.set_state("wait_for_name")

@dp.message_handler(state="wait_for_name")
async def process_quiz_name(message: types.Message, state: FSMContext):
    quiz_name = message.text
    data = await state.get_data()
    selected = data.get('selected_cats', [])
    
    if not selected:
        await message.answer("⚠️ خطأ: لم تختار أي قسم!")
        return

    # ##########################################
    # بداية التعديلات الملكية لضمان عمل أسئلة البوت
    import json
    # تحويل الأقسام لنص JSON نظيف (يمنع مشكلة الاقتباسات المزدوجة المكررة)
    cats_json = json.dumps(selected)

    # ##########################################
# التعديل النهائي لضمان الحفظ بدون علامات الهروب المكسورة \
    payload = {
        "created_by": str(message.from_user.id),
        "quiz_name": quiz_name,
        "chat_id": str(message.from_user.id), 
        "is_public": True, 
        "time_limit": data.get('quiz_time', 15),
        "questions_count": data.get('quiz_count', 10),
        "mode": data.get('quiz_mode', 'السرعة ⚡'),
        "hint_enabled": True if data.get('quiz_hint') == 'مفعل ✅' else False,
        "is_bot_quiz": data.get('is_bot_quiz', False),
        "cats": selected  # أرسل 'selected' كما هي (List) ولا تستخدم json.dumps
    }
# ##########################################

    try:
        supabase.table("saved_quizzes").insert(payload).execute()
        await message.answer(f"✅ تم حفظ ({quiz_name}) بنجاح!\n🚀 ستظهر لك الآن في قائمة المسابقات المحفوظة في أي مكان.")
        await state.finish()
    except Exception as e:
        print(f"Error saving quiz: {e}")
        await message.answer(f"❌ خطأ في الحفظ: تأكد من ربط قاعدة البيانات بشكل صحيح.")
 # --- [1] عرض القائمة الرئيسية (نظام ياسر المتطور: خاص vs عام) ---
@dp.message_handler(lambda message: message.text == "مسابقة")
async def show_quizzes(obj):
    chat_id = obj.chat.id if isinstance(obj, types.Message) else obj.message.chat.id
    user = obj.from_user
    u_id = str(user.id)
    
    # 🛡️ فحص الصلاحيات المزدوج
    status = await get_group_status(chat_id)
    
    # 1. التحقق إذا كان المستخدم هو "مالك" أو "مشرف" في القروب (تشغيل خاص)
    member = await bot.get_chat_member(chat_id, user.id)
    is_admin_here = member.is_chat_admin() or member.is_chat_creator()
    
    # 2. منطق السماح:
    # يسمح بالدخول في الحالات التالية:
    # - إذا كنت أنت المطور (ياسر)
    # - إذا كان القروب مفعل رسمياً (status == 'active')
    # - إذا كان الشخص مشرفاً ويبي يشغل مسابقاته في قروبه (تشغيل خاص)
    
    can_proceed = (
        chat_id == ADMIN_ID or 
        status == "active" or 
        (is_admin_here and chat_id < 0) # chat_id < 0 يعني داخل قروب
    )

    if not can_proceed:
        msg = (
            "━━━━━━━━━━━━━━\n"
            "⚠️ <b>نظام النشر العام مقفل</b>\n"
            "━━━━━━━━━━━━━━\n"
            "عذراً، التشغيل في هذه المجموعة يتطلب تفعيل 'عام'.\n\n"
            "إذا كنت مشرفاً وتريد تشغيل البوت للجميع، أرسل: (<b>تفعيل</b>).\n"
            "━━━━━━━━━━━━━━"
        )
        if isinstance(obj, types.Message): return await obj.reply(msg, parse_mode="HTML")
        else: return await obj.message.edit_text(msg, parse_mode="HTML")

    # --- تكملة الكود الطبيعي لعرض المسابقات ---
    res = supabase.table("saved_quizzes").select("*").eq("created_by", u_id).execute()
    kb = InlineKeyboardMarkup(row_width=1)
    
    if not res.data:
        msg_text = "⚠️ ليس لديك مسابقات محفوظة باسمك حالياً."
        if isinstance(obj, types.Message): await obj.answer(msg_text)
        else: await obj.message.edit_text(msg_text)
        return

    for q in res.data:
        kb.add(InlineKeyboardButton(f"🏆 مسابقة: {q['quiz_name']}", callback_data=f"manage_quiz_{q['id']}_{u_id}"))
    
    kb.add(InlineKeyboardButton("🤖 أسئلة البوت (قيد التطوير)", callback_data=f"bot_dev_msg_{u_id}"))
    kb.add(InlineKeyboardButton("❌ إغلاق النافذة", callback_data=f"close_{u_id}"))
    
    title = f"🎁 **قائمة مسابقاتك يا {user.first_name}:**"
    if isinstance(obj, types.Message): await obj.reply(title, reply_markup=kb)
    else: await obj.message.edit_text(title, reply_markup=kb)

# ==========================================
# [2] المحرك الأمني ولوحة التحكم (نسخة التشطيب النهائي - ياسر)
# ==========================================
@dp.callback_query_handler(lambda c: c.data.startswith(('run_', 'close_', 'confirm_del_', 'final_del_', 'edit_time_', 'set_t_', 'manage_quiz_', 'quiz_settings_', 'edit_count_', 'set_c_', 'toggle_speed_', 'toggle_scope_', 'toggle_hint_', 'save_quiz_process')), state="*")
async def handle_secure_actions(c: types.CallbackQuery, state: FSMContext):
    try:
        data_parts = c.data.split('_')
        owner_id = data_parts[-1]
        user_id = str(c.from_user.id)
        
        # الدرع الأمني
        if user_id != owner_id:
            await c.answer("🚫 هذه النافذة ليست لك.", show_alert=True)
            return

        # 1️⃣ شاشة الإدارة الرئيسية
        if c.data.startswith('manage_quiz_'):
            quiz_id = data_parts[2]
            res = supabase.table("saved_quizzes").select("quiz_name").eq("id", quiz_id).single().execute()
            kb = InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🚀 بدء المسابقة", callback_data=f"run_{quiz_id}_{user_id}"),
                InlineKeyboardButton("⚙️ إعدادات المسابقة", callback_data=f"quiz_settings_{quiz_id}_{user_id}"),
                InlineKeyboardButton("🔙 رجوع للقائمة", callback_data=f"list_my_quizzes_{user_id}")
            )
            await c.message.edit_text(f"💎 **إدارة مسابقة: {res.data['quiz_name']}**", reply_markup=kb)
            return

        # 2️⃣ لوحة الإعدادات (قالب التشطيب النهائي)
        if c.data.startswith('quiz_settings_'):
            quiz_id = data_parts[2]
            res = supabase.table("saved_quizzes").select("*").eq("id", quiz_id).single().execute()
            q = res.data
            
            # تخزين البيانات في الـ State للحفظ لاحقاً
            await state.update_data(editing_quiz_id=quiz_id, quiz_name=q['quiz_name'])

            q_time = q.get('time_limit', 15)
            q_count = q.get('questions_count', 10)
            q_mode = q.get('mode', 'السرعة ⚡')
            is_hint = q.get('smart_hint', False)
            is_public = q.get('quiz_scope') == "عام"

            text = (
                f"┏━━━━━ إعدادات: {q['quiz_name']} ━━━━━┓\n"
                f"📊 عدد الاسئلة: {q_count}\n"
                f"📡 النطاق: {'إذاعة عامة 🌐' if is_public else 'مسابقة داخلية 📍'}\n"
                f"🔖 النظام: {q_mode}\n"
                f"⏳ المهلة: {q_time} ثانية\n"
                f"💡 التلميح الذكي: {'مفعل ✅' if is_hint else 'معطل ❌'}\n"
                "┗━━━━━━━━━━━━━━━━━━━━┛"
            )

            kb = InlineKeyboardMarkup(row_width=5)
            # صف اختيار الأرقام
            kb.row(InlineKeyboardButton("📊 اختر عدد الأسئلة:", callback_data="ignore"))
            counts = [10, 15, 25, 32, 45]
            kb.add(*[InlineKeyboardButton(f"{'✅' if q_count==n else ''}{n}", callback_data=f"set_c_{quiz_id}_{n}_{user_id}") for n in counts])
            
            # أزرار التحكم
            kb.row(InlineKeyboardButton(f"⏱️ المهلة: {q_time} ثانية", callback_data=f"edit_time_{quiz_id}_{user_id}"))
            kb.row(
                InlineKeyboardButton(f"🔖 {q_mode}", callback_data=f"toggle_speed_{quiz_id}_{user_id}"),
                InlineKeyboardButton(f"💡 {'مفعل ✅' if is_hint else 'معطل ❌'}", callback_data=f"toggle_hint_{quiz_id}_{user_id}")
            )
            kb.row(InlineKeyboardButton(f"📡 {'نطاق: عام 🌐' if is_public else 'نطاق: داخلي 📍'}", callback_data=f"toggle_scope_{quiz_id}_{user_id}"))
            
            # زر الحفظ النهائي (المباشر)
            kb.row(InlineKeyboardButton("💾 حفظ التعديلات 🚀", callback_data=f"save_quiz_process_{quiz_id}_{user_id}"))
            kb.row(InlineKeyboardButton("🗑️ حذف المسابقة", callback_data=f"confirm_del_{quiz_id}_{user_id}"))
            kb.row(InlineKeyboardButton("🔙 رجوع للخلف", callback_data=f"manage_quiz_{quiz_id}_{user_id}"))
            
            await c.message.edit_text(text, reply_markup=kb)
            return

                # 3️⃣ التبديلات (Toggles) - نسخة مصلحة وآمنة للنطاق
        if any(c.data.startswith(x) for x in ['toggle_hint_', 'toggle_speed_', 'toggle_scope_', 'set_c_', 'set_t_']):
            quiz_id = data_parts[2]
            
            # محرك النطاق (Scope) المصلح
            if 'toggle_scope_' in c.data:
                res = supabase.table("saved_quizzes").select("quiz_scope").eq("id", quiz_id).single().execute()
                # إذا كان الحقل فارغاً في الداتابيز، نعتبره "خاص" افتراضياً
                curr_s = res.data.get('quiz_scope', 'خاص') if res.data else 'خاص'
                new_s = "عام" if curr_s == "خاص" else "خاص"
                supabase.table("saved_quizzes").update({"quiz_scope": new_s}).eq("id", quiz_id).execute()
                await c.answer(f"🌐 النطاق الجديد: {new_s}")

            # محرك التلميح (Hint)
            elif 'toggle_hint_' in c.data:
                res = supabase.table("saved_quizzes").select("smart_hint").eq("id", quiz_id).single().execute()
                new_h = not (res.data.get('smart_hint') if res.data else False)
                supabase.table("saved_quizzes").update({"smart_hint": new_h}).eq("id", quiz_id).execute()

            # محرك النظام (Mode)
            elif 'toggle_speed_' in c.data:
                res = supabase.table("saved_quizzes").select("mode").eq("id", quiz_id).single().execute()
                curr_m = res.data.get('mode', 'السرعة ⚡') if res.data else 'السرعة ⚡'
                new_m = "الوقت الكامل ⏳" if curr_m == "السرعة ⚡" else "السرعة ⚡"
                supabase.table("saved_quizzes").update({"mode": new_m}).eq("id", quiz_id).execute()

            # محرك عدد الأسئلة
            elif 'set_c_' in c.data:
                count = int(data_parts[3])
                supabase.table("saved_quizzes").update({"questions_count": count}).eq("id", quiz_id).execute()
            
            # إعادة تنشيط الواجهة لتعكس التعديلات فوراً
            await c.answer("تم التحديث ✅")
            c.data = f"quiz_settings_{quiz_id}_{user_id}"
            return await handle_secure_actions(c, state)

        # 4️⃣ محرك تغيير الوقت (Cycle Time) - نسخة آمنة
        if c.data.startswith('edit_time_'):
            quiz_id = data_parts[2]
            res = supabase.table("saved_quizzes").select("time_limit").eq("id", quiz_id).single().execute()
            curr = res.data.get('time_limit', 15) if res.data else 15
            next_t = 20 if curr == 15 else (30 if curr == 20 else (45 if curr == 30 else 15))
            supabase.table("saved_quizzes").update({"time_limit": next_t}).eq("id", quiz_id).execute()
            
            c.data = f"quiz_settings_{quiz_id}_{user_id}"
            return await handle_secure_actions(c, state)

        # 5️⃣ الحفظ المباشر (تأكيد الحفظ)
        if c.data.startswith('save_quiz_process_'):
            quiz_id = data_parts[2]
            await c.answer("✅ تم حفظ جميع الإعدادات بنجاح!", show_alert=True)
            c.data = f"manage_quiz_{quiz_id}_{user_id}"
            return await handle_secure_actions(c, state)

        # 6️⃣ حذف وإغلاق وتشغيل (نفس كودك السابق)
        if c.data.startswith('confirm_del_'):
            quiz_id = data_parts[2]
            kb = InlineKeyboardMarkup().add(
                InlineKeyboardButton("✅ نعم، احذف", callback_data=f"final_del_{quiz_id}_{user_id}"),
                InlineKeyboardButton("🚫 تراجع", callback_data=f"quiz_settings_{quiz_id}_{user_id}")
            )
            await c.message.edit_text("⚠️ **هل أنت متأكد من الحذف؟**", reply_markup=kb)
            return

        if c.data.startswith('final_del_'):
            quiz_id = data_parts[2]
            supabase.table("saved_quizzes").delete().eq("id", quiz_id).execute()
            await c.answer("🗑️ تم الحذف")
            await show_quizzes(c)
            return

        if c.data.startswith('run_'):
            quiz_id = data_parts[1]
            res = supabase.table("saved_quizzes").select("*").eq("id", quiz_id).single().execute()
            q_data = res.data
            await c.answer("🚀 انطلقنا!")
            await countdown_timer(c.message, 5)
            await (engine_bot_questions if q_data.get('is_bot_quiz') else engine_user_questions)(c.message.chat.id, q_data, c.from_user.first_name)
            return

        if c.data.startswith('close_'):
            await c.message.delete()
            return

    except Exception as e:
        logging.error(f"Error: {e}")
        await c.answer("🚨 حدث خطأ")
        
# ==========================================
# 3. نظام المحركات الثلاثة المنفصلة (ياسر المطور)
# ==========================================

# --- [1. محرك أسئلة البوت] ---
async def engine_bot_questions(chat_id, quiz_data, owner_name):
    try:
        cat_ids = [int(c) for c in quiz_data['cats'] if str(c).isdigit()]
        res = supabase.table("bot_questions").select("*").in_("bot_category_id", cat_ids).limit(int(quiz_data['questions_count'])).execute()
        if not res.data:
            return await bot.send_message(chat_id, "⚠️ لم أجد أسئلة في جدول البوت العام.")
        await run_universal_logic(chat_id, res.data, quiz_data, owner_name, "bot")
    except Exception as e:
        logging.error(f"Bot Engine Error: {e}")


        # --- [2. محرك أسئلة الأعضاء] ---
async def engine_user_questions(chat_id, quiz_data, owner_name):
    try:
        cat_ids = [int(c) for c in quiz_data['cats'] if str(c).isdigit()]
        res = supabase.table("questions").select("*, categories(name)").in_("category_id", cat_ids).limit(int(quiz_data['questions_count'])).execute()
        if not res.data:
            return await bot.send_message(chat_id, "⚠️ لم أجد أسئلة في أقسام الأعضاء العامة.")
        await run_universal_logic(chat_id, res.data, quiz_data, owner_name, "user")
    except Exception as e:
        logging.error(f"User Engine Error: {e}")

# --- [3. محرك الأقسام الخاصة] ---
async def engine_private_questions(chat_id, quiz_data, owner_name):
    try:
        cat_ids = [int(c) for c in quiz_data['cats'] if str(c).isdigit()]
        res = supabase.table("private_questions").select("*").in_("category_id", cat_ids).limit(int(quiz_data['questions_count'])).execute()
        if not res.data:
            return await bot.send_message(chat_id, "⚠️ لم أجد أسئلة في الأقسام الخاصة.")
        await run_universal_logic(chat_id, res.data, quiz_data, owner_name, "private")
    except Exception as e:
        logging.error(f"Private Engine Error: {e}")

# --- [ محرك التلميحات الذكي - الإصدار الملكي المزخرف ✨ ] ---
async def generate_smart_hint(answer_text):
    """
    توليد وصف لغزي ذكي بتنسيق فاخر ومزخرف يجذب الأنظار.
    """
    answer_text = str(answer_text).strip()
    
    # 1. حالة عدم وجود مفتاح (قالب الطوارئ)
    if not GROQ_API_KEY:
        return (
            f"⚠️ <b>〔 تـنـبـيـه الـنـظـام 〕</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"💡 <b>تلميح تقليدي:</b> تبدأ بـ ( {answer_text[0]} )\n"
            f"━━━━━━━━━━━━━━"
        )

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {
                "role": "user", 
                "content": f"أنت خبير ألغاز محترف. الإجابة هي: ({answer_text}). أعطني وصفاً غامضاً وذكياً جداً يصف المعنى دون ذكر اسمها. عربي قصير جداً ومسلي."
            }
        ],
        "temperature": 0.6
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=10.0)
            
            if response.status_code == 200:
                res_data = response.json()
                hint = res_data['choices'][0]['message']['content'].strip()
                
                # ✨ القالب الفاخر للمحترفين
                return (
                    f"💎 <b>〔 تـلـمـيـح ذكـي نـادر 〕</b> 💎\n"
                    f"╔════════════════╗\n\n"
                    f"   <b>📜 الوصف:</b>\n"
                    f"   <i>« {hint} »</i>\n\n"
                    f"╚════════════════╝\n"
                    f"<b>⏳ يتبقى القليل.. أثبت وجودك!</b>"
                )
            
            # 2. حالة فشل الـ API (قالب مساعد فاخر)
            return (
                f"💡 <b>〔 مـسـاعـدة إضـافـيـة 〕</b>\n"
                f"📂 ━━━━━━━━━━━━━━ 📂\n"
                f"<b>• الحرف الأول:</b> ( {answer_text[0]} )\n"
                f"<b>• طول الكلمة:</b> {len(answer_text)} حروف\n"
                f"━━━━━━━━━━━━━━"
            )
                
    except Exception as e:
        logging.error(f"AI Connection Error: {str(e)}")
        return (
            f"⚡️ <b>〔 تلميح سريع 〕</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"🔑 تبدأ بـ الحرف: ( {answer_text[0]} )\n"
            f"━━━━━━━━━━━━━━"
                )
# دالة حذف الرسائل المساعدة
async def delete_after(message, delay):
    await asyncio.sleep(delay)
    try: 
        await message.delete()
    except: 
        pass

# ==========================================
# [2] المحرك الموحد (نسخة الإصلاح والتلميح الناري 🔥)
# ==========================================
async def run_universal_logic(chat_id, questions, quiz_data, owner_name, engine_type):
    random.shuffle(questions)
    overall_scores = {}

    for i, q in enumerate(questions):
        # 1. استخراج الإجابة والنص حسب نوع المصدر
        if engine_type == "bot":
            ans = str(q.get('correct_answer') or "").strip()
            cat_name = q.get('category') or "بوت"
        elif engine_type == "user":
            ans = str(q.get('answer_text') or q.get('correct_answer') or "").strip()
            cat_name = q['categories']['name'] if q.get('categories') else "عام"
        else:
            ans = str(q.get('correct_answer') or q.get('ans') or "").strip()
            cat_name = "قسم خاص 🔒"

        # 2. تصفير حالة السؤال وتجهيز الذاكرة النشطة
        active_quizzes[chat_id] = {
            "active": True, 
            "ans": ans, 
            "winners": [], 
            "mode": quiz_data['mode'], 
            "hint_sent": False
        }
        
        # 3. إرسال قالب السؤال للقروب
        await send_quiz_question(chat_id, q, i+1, len(questions), {
            'owner_name': owner_name, 
            'mode': quiz_data['mode'], 
            'time_limit': quiz_data['time_limit'], 
            'cat_name': cat_name
        })
        
        # 4. محرك الوقت الذكي ومراقبة التلميح الناري
        start_time = time.time()
        t_limit = int(quiz_data.get('time_limit', 15))
        h_msg = None  # متغير لتخزين رسالة التلميح لحذفها لاحقاً
        
        while time.time() - start_time < t_limit:
            if not active_quizzes.get(chat_id) or not active_quizzes[chat_id]['active']:
                break
            
            # --- نظام إطلاق التلميح عند منتصف الوقت بالضبط باستخدام محرك Groq ---
            if quiz_data.get('smart_hint') and not active_quizzes[chat_id]['hint_sent']:
                # إذا مرت نصف المدة ولم يتم إرسال تلميح بعد
                if (time.time() - start_time) >= (t_limit / 2):
                    try:
                        # استدعاء دالة التلميح الذكي
                        hint_text = await generate_smart_hint(ans)
                        
                        h_msg = await bot.send_message(chat_id, hint_text, parse_mode="HTML")
                        active_quizzes[chat_id]['hint_sent'] = True
                        
                        # تم إزالة الحذف التلقائي السريع (8 ثواني) ليبقى التلميح لنهاية السؤال
                    except Exception as e:
                        logging.error(f"Fire Hint Execution Error: {e}")

            await asyncio.sleep(0.5) # نبض المحرك للسماح بمعالجة الإجابات

        # --- [ إيقاف السؤال وحذف التلميح فوراً ] ---
        if h_msg:
            # حذف رسالة التلميح عند انتهاء الوقت أو فوز اللاعبين
            asyncio.create_task(delete_after(h_msg, 0))

        # 5. إنهاء السؤال وحساب النقاط للفائزين
        if chat_id in active_quizzes:
            active_quizzes[chat_id]['active'] = False
            
            for w in active_quizzes[chat_id]['winners']:
                uid = w['id']
                if uid not in overall_scores: 
                    overall_scores[uid] = {"name": w['name'], "points": 0}
                overall_scores[uid]['points'] += 10
        
            # 6. عرض لوحة المبدعين (نتائج السؤال اللحظية)
            await send_creative_results(chat_id, ans, active_quizzes[chat_id]['winners'], overall_scores)
        
        # فاصل زمني بسيط قبل الانتقال للسؤال التالي
        await asyncio.sleep(2.5)

    # 7. إعلان لوحة الشرف النهائية وتتويج الأبطال
    await send_final_results(chat_id, overall_scores, len(questions))

# ==========================================
# 4. الجزء الثالث: قالب السؤال والتلميح...........     
# ==========================================

async def countdown_timer(message: types.Message, seconds=5):
    try:
        for i in range(seconds, 0, -1):
            await message.edit_text(f"🚀 تجهيز المسابقة...\n\nستبدأ خلال: {i}")
            await asyncio.sleep(1)
    except Exception as e:
        logging.error(f"Countdown Error: {e}")


async def send_quiz_question(chat_id, q_data, current_num, total_num, settings):
    # دعم مسميات CSV الجديدة
    q_text = q_data.get('question_content') or q_data.get('question_text') or "نص مفقود"
    
    text = (
        f"🎓 **الـمنـظـم:** {settings['owner_name']} ☁️\n"
        f"┏━━━━━━━━━━━━━━┓\n"
        f"  📌 **سؤال:** « {current_num} » من « {total_num} »\n"
        f"  📂 **القسم:** {settings['cat_name']}\n"
        f"  ⏳ **المهلة:** {settings['time_limit']} ثانية\n"
        f"┗━━━━━━━━━━━━━━┛\n\n"
        f"❓ **السؤال:**\n**{q_text}**"
    )
    return await bot.send_message(chat_id, text, parse_mode='Markdown')

async def delete_after(msg, delay):
    await asyncio.sleep(delay)
    try: await msg.delete()
    except: pass

# ----رصد الإجابات (Answers)----

@dp.message_handler(lambda m: not m.text.startswith('/'))
async def check_ans(m: types.Message):
    cid = m.chat.id
    if cid in active_quizzes and active_quizzes[cid]['active']:
        user_ans = m.text.strip().lower()
        correct_ans = active_quizzes[cid]['ans'].lower()
        
        if user_ans == correct_ans:
            if not any(w['id'] == m.from_user.id for w in active_quizzes[cid]['winners']):
                active_quizzes[cid]['winners'].append({"name": m.from_user.first_name, "id": m.from_user.id})
                
                if active_quizzes[cid]['mode'] == 'السرعة ⚡':
                    active_quizzes[cid]['active'] = False # تم إصلاح الخطأ هنا
                    


# --- [ إعداد حالات الإدارة ] ---
class AdminStates(StatesGroup):
    waiting_for_new_token = State()
    waiting_for_broadcast = State()
# =========================================
#          👑 غرفة عمليات المطور 👑
# =========================================

# دالة موحدة لتوليد لوحة الأزرار المحدثة (لضمان ظهورها في كل الحالات)
def get_main_admin_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 إدارة الأسئلة", callback_data="botq_main"),
        InlineKeyboardButton("📝 مراجعة الطلبات", callback_data="admin_view_pending"),
        InlineKeyboardButton("📢 إذاعة عامة", callback_data="admin_broadcast"),
        InlineKeyboardButton("🔄 تحديث النظام", callback_data="admin_restart_now")
    )
    kb.row(InlineKeyboardButton("🔑 استبدال توكين البوت", callback_data="admin_change_token"))
    kb.row(InlineKeyboardButton("❌ إغلاق اللوحة", callback_data="botq_close"))
    return kb

# --- 1. معالج الأمر الرئيسي /admin ---
@dp.message_handler(commands=['admin'], user_id=ADMIN_ID)
async def admin_dashboard(message: types.Message):
    try:
        res = supabase.table("allowed_groups").select("*").execute()
        active = len([g for g in res.data if g['status'] == 'active'])
        pending = len([g for g in res.data if g['status'] == 'pending'])
        
        txt = (
            "👑 <b>غرفة العمليات الرئيسية</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"✅ النشطة: {active} | ⏳ المعلقة: {pending}\n"
            "━━━━━━━━━━━━━━\n"
            "👇 اختر قسماً لإدارته:"
        )
        # هنا استدعاء اللوحة المحدثة فوراً
        await message.answer(txt, reply_markup=get_main_admin_kb(), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Admin Panel Error: {e}")

# --- 2. معالج العودة للقائمة الرئيسية ---
@dp.callback_query_handler(lambda c: c.data == "admin_back", user_id=ADMIN_ID, state="*")
async def admin_back_to_main(c: types.CallbackQuery, state: FSMContext):
    await state.finish()
    try:
        res = supabase.table("allowed_groups").select("*").execute()
        active = len([g for g in res.data if g['status'] == 'active'])
        pending = len([g for g in res.data if g['status'] == 'pending'])
        
        txt = (
            "👑 <b>غرفة العمليات الرئيسية</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"✅ النشطة: {active} | ⏳ المعلقة: {pending}\n"
            "━━━━━━━━━━━━━━"
        )
        await c.message.edit_text(txt, reply_markup=get_main_admin_kb(), parse_mode="HTML")
    except Exception as e:
        await c.answer("⚠️ حدث خطأ أثناء التحديث")

# --- 3. معالج زر التحديث (Restart) ---
@dp.callback_query_handler(text="admin_restart_now", user_id=ADMIN_ID)
async def system_restart(c: types.CallbackQuery):
    await c.message.edit_text("🔄 <b>جاري تحديث النظام وإعادة التشغيل...</b>", parse_mode="HTML")
    await bot.close()
    await storage.close()
    os._exit(0)

# --- 4. معالج زر استبدال التوكين ---
@dp.callback_query_handler(text="admin_change_token", user_id=ADMIN_ID)
async def ask_new_token(c: types.CallbackQuery):
    await c.message.edit_text(
        "📝 <b>أرسل التوكين الجديد الآن:</b>\n"
        "⚠️ سيتم الحفظ في Supabase وإعادة التشغيل فوراً.", 
        reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ تراجع", callback_data="admin_back"))
    )
    await AdminStates.waiting_for_new_token.set()
# --- [ إدارة أسئلة البوت الرسمية - النسخة المصححة لياسر ] ---

@dp.callback_query_handler(lambda c: c.data.startswith('botq_'), user_id=ADMIN_ID)
async def process_bot_questions_panel(c: types.CallbackQuery, state: FSMContext):
    data_parts = c.data.split('_')
    action = data_parts[1]

    if action == "close":
        await c.message.delete()
        await c.answer("تم الإغلاق")

    elif action == "main":
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📥 رفع أسئلة (Bulk)", callback_data="botq_upload"),
            InlineKeyboardButton("🗂️ عرض الأقسام", callback_data="botq_viewcats"),
            InlineKeyboardButton("⬅️ عودة للرئيسية", callback_data="admin_back")
        )
        await c.message.edit_text("🛠️ <b>إدارة الأسئلة (الموحدة)</b>", reply_markup=kb, parse_mode="HTML")

    elif action == "upload":
        await c.message.edit_text("📥 أرسل الأسئلة بصيغة: سؤال+إجابة+القسم\n\nأرسل <b>خروج</b> للعودة.", parse_mode="HTML")
        await state.set_state("wait_for_bulk_questions")

    elif action == "viewcats":
        res = supabase.table("bot_categories").select("*").execute()
        if not res.data:
            return await c.answer("⚠️ لا توجد أقسام مسجلة.", show_alert=True)
        
        categories = res.data
        kb = InlineKeyboardMarkup(row_width=2)
        for cat in categories:
            # التعديل الذهبي هنا: نربط الزر بـ ID القسم الحقيقي من سوبابيز
            kb.insert(InlineKeyboardButton(f"📁 {cat['name']}", callback_data=f"botq_mng_{cat['id']}"))
        
        kb.add(InlineKeyboardButton("⬅️ عودة", callback_data="botq_main"))
        await c.message.edit_text("🗂️ <b>أقسام أسئلة البوت الرسمية:</b>", reply_markup=kb, parse_mode="HTML")

    # --- معالج الضغط على اسم القسم (هذا الجزء الذي كان ناقصاً لديك) ---
    elif action == "mng":
        cat_id = data_parts[2]
        # جلب عدد الأسئلة الفعلي لهذا القسم من جدول bot_questions
        # نستخدم العمود bot_category_id كما هو في ملفك الـ CSV
        res = supabase.table("bot_questions").select("id", count="exact").eq("bot_category_id", int(cat_id)).execute()
        q_count = res.count if res.count is not None else 0
        
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton(f"🗑️ حذف جميع أسئلة هذا القسم ({q_count})", callback_data=f"botq_del_{cat_id}"),
            InlineKeyboardButton("🔙 عودة للأقسام", callback_data="botq_viewcats")
        )
        
        await c.message.edit_text(
            f"📂 <b>إدارة القسم (ID: {cat_id})</b>\n\n"
            f"📊 عدد الأسئلة المتوفرة: <b>{q_count}</b>\n"
            "ماذا تريد أن تفعل؟", 
            reply_markup=kb, parse_mode="HTML"
        )

    # --- معالج حذف أسئلة القسم ---
    elif action == "del":
        cat_id = data_parts[2]
        supabase.table("bot_questions").delete().eq("bot_category_id", int(cat_id)).execute()
        await c.answer("✅ تم حذف جميع أسئلة القسم بنجاح", show_alert=True)
        # العودة لقائمة الأقسام بعد الحذف
        await process_bot_questions_panel(c, state) 

    await c.answer()
    

# --- معالج الرفع الجماعي وأمر الخروج (ياسر الملك) ---
@dp.message_handler(state="wait_for_bulk_questions", user_id=ADMIN_ID)
async def process_bulk_questions(message: types.Message, state: FSMContext):
    if message.text.strip() in ["خروج", "إلغاء", "exit"]:
        await state.finish()
        await message.answer("✅ تم الخروج من وضع الرفع الجماعي والعودة.")
        return

    lines = message.text.split('\n')
    success, error = 0, 0
    
    for line in lines:
        if '+' in line:
            parts = line.split('+')
            if len(parts) >= 3:
                q_text, q_ans, cat_name = parts[0].strip(), parts[1].strip(), parts[2].strip()
                try:
                    cat_res = supabase.table("bot_categories").select("id").eq("name", cat_name).execute()
                    if cat_res.data:
                        cat_id = cat_res.data[0]['id']
                    else:
                        new_cat = supabase.table("bot_categories").insert({"name": cat_name}).execute()
                        cat_id = new_cat.data[0]['id']

                    supabase.table("bot_questions").insert({
                        "question_content": q_text,
                        "correct_answer": q_ans,
                        "bot_category_id": cat_id,
                        "category": cat_name,
                        "created_by": str(ADMIN_ID)
                    }).execute()
                    success += 1
                except Exception as e:
                    logging.error(f"Error: {e}")
                    error += 1
            else: error += 1
        elif line.strip(): error += 1

    await message.answer(
        f"📊 <b>ملخص الرفع النهائي (ياسر الملك):</b>\n"
        f"✅ نجاح: {success}\n"
        f"❌ فشل: {error}\n\n"
        f"📥 أرسل الدفعة التالية أو أرسل 'خروج'.", 
        parse_mode="HTML"
    )

# --- إدارة المجموعات (التفعيل والحظر) ---
@dp.callback_query_handler(lambda c: c.data == "admin_view_pending", user_id=ADMIN_ID)
async def view_pending_groups(c: types.CallbackQuery):
    res = supabase.table("allowed_groups").select("*").eq("status", "pending").execute()
    if not res.data:
        return await c.answer("لا توجد طلبات معلقة.", show_alert=True)
    
    txt = "⏳ <b>طلبات التفعيل الحالية:</b>"
    kb = InlineKeyboardMarkup(row_width=1)
    for g in res.data:
        kb.add(
            InlineKeyboardButton(f"✅ تفعيل: {g['group_name']}", callback_data=f"auth_approve_{g['group_id']}"),
            InlineKeyboardButton(f"❌ حظر الآيدي: {g['group_id']}", callback_data=f"auth_block_{g['group_id']}")
        )
    kb.add(InlineKeyboardButton("⬅️ العودة", callback_data="admin_back"))
    await c.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

@dp.callback_query_handler(lambda c: c.data.startswith(('auth_approve_', 'auth_block_')), user_id=ADMIN_ID)
async def process_auth_callback(c: types.CallbackQuery):
    action, target_id = c.data.split('_')[1], c.data.split('_')[2]
    if action == "approve":
        supabase.table("allowed_groups").update({"status": "active"}).eq("group_id", target_id).execute()
        await c.answer("تم التفعيل ✅")
        await c.message.edit_text(f"✅ تم تفعيل المجموعة: {target_id}")
    elif action == "block":
        supabase.table("allowed_groups").update({"status": "blocked"}).eq("group_id", target_id).execute()
        await c.answer("تم الحظر ❌")
    
# ==========================================
# 5. نهاية الملف: ضمان التشغيل 24/7 (Keep-Alive)
# ==========================================
from aiohttp import web

# دالة الرد على "نغزة" المواقع الخارجية مثل Cron-job
async def handle_ping(request):
    return web.Response(text="Bot is Active and Running! 🚀")

if __name__ == '__main__':
    # 1. إعداد سيرفر ويب صغير في الخلفية للرد على طلبات الـ HTTP
    app = web.Application()
    app.router.add_get('/', handle_ping)
    
    loop = asyncio.get_event_loop()
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    
    # 2. تحديد المنفذ (Port): Render يستخدم غالباً 10000، و Koyeb يستخدم ما يحدده النظام
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    # تشغيل السيرفر كـ "مهمة" جانبية حتى لا يعطل البوت
    loop.create_task(site.start())
    print(f"✅ Keep-alive server started on port {port}")

    # 3. إعدادات السجلات والتشغيل النهائي للبوت
    logging.basicConfig(level=logging.INFO)
    
    # بدء استقبال الرسائل (Polling) مع تخطي التحديثات القديمة
    executor.start_polling(dp, skip_updates=True)
    
