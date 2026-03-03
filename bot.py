import logging
import asyncio
import random
import time
import os
import json
import re
import difflib
import random
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

# سحب التوكينات من Render (لن يعمل البوت بدونها في الإعدادات)
API_TOKEN = os.getenv('BOT_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# --- [ استدعاء القلوب الثلاثة - تشفير خارجي ] ---
# هنا الكود يطلب المفاتيح من المتغيرات فقط، ولا توجد أي قيمة مسجلة هنا
GROQ_KEYS = [
    os.getenv('G_KEY_1'),
    os.getenv('G_KEY_2'),
    os.getenv('G_KEY_3')
]

# تصفية المصفوفة لضمان عدم وجود قيم فارغة
GROQ_KEYS = [k for k in GROQ_KEYS if k]
current_key_index = 0  # مؤشر تدوير القلوب

# التحقق من وجود المتغيرات الأساسية لضمان عدم حدوث Crash
if not API_TOKEN or not GROQ_KEYS:
    logging.error("❌ خطأ: المتغيرات المشفرة مفقودة في إعدادات Render!")

# تعريف المحركات
bot = Bot(token=API_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

active_quizzes = {}

global_active_quizzes = {}
cancelled_groups = set() # لحفظ المجموعات التي ضغطت إلغاء مؤقتاً
# ==========================================
# 4. محركات العرض والقوالب (Display Engines) - النسخة المصلحة
# ==========================================

# [2] دالة إعلان تفاصيل المسابقة (المصلحة)
async def announce_quiz_type(chat_id, quiz_data, engine_type):
    """إعلان تفاصيل المسابقة بناءً على عمود is_public الحقيقي"""
    source_map = {
        "bot": "أسئلة البوت الذكية 🤖", 
        "user": "أسئلة المستخدم الخاصة 👤"
    }
    source_text = source_map.get(engine_type, "قاعدة بيانات خاصة 🔒")
    
    q_name = quiz_data.get('quiz_name', 'تحدي جديد')
    q_count = quiz_data.get('questions_count', 10)
    q_time = quiz_data.get('time_limit', 15)
    q_mode = quiz_data.get('mode', 'السرعة ⚡')
    
    # 🛠️ التصحيح الحقيقي هنا:
    is_pub = quiz_data.get('is_public', False)
    q_scope = "إذاعة عامة 🌐" if is_pub is True else "مسابقة داخلية 📍"
    
    announcement = (
        f"📊 **تفاصيل المسابقة المنطلقة:**\n"
        f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
        f"🏆 الاسم: **{q_name}**\n"
        f"📁 المصدر: `{source_text}`\n"
        f"📡 النطاق: **{q_scope}**\n"
        f"🔢 عدد الأسئلة: `{q_count}`\n"
        f"⏳ وقت السؤال: `{q_time} ثانية`\n"
        f"🔖 النظام: **{q_mode}**\n"
        f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n\n"
        f"⏳ **استعدوا.. السؤال الأول سيبدأ خلال 3 ثواني!**"
    )
    
    try:
        msg = await bot.send_message(chat_id, announcement, parse_mode="Markdown")
        await asyncio.sleep(3) 
        await msg.delete() 
    except Exception as e:
        logging.error(f"Error in announcement: {e}")

# [3] دالة قالب السؤال (المصلحة)
async def send_quiz_question(chat_id, q_data, current_num, total_num, settings):
    """
    قالب السؤال - تصميم ياسر المطور 2026
    المميزات: دعم النطاق، عرض المصدر، والعودة بكائن الرسالة للحذف.
    """
    # 1. تحديد النطاق (إذاعة عامة أو مسابقة داخلية)
    is_pub = settings.get('is_public', False) 
    q_scope = "إذاعة عامة 🌐" if is_pub else "مسابقة داخلية 📍"
    
    # 2. جلب نص السؤال ومصدره
    source = settings.get('source', 'قاعدة البيانات')
    # فحص محتوى السؤال في حال كان من البوت أو من مكتبتك
    q_text = q_data.get('question_content') or q_data.get('question_text') or "⚠️ نص السؤال مفقود!"
    
    # 3. تنسيق نص الرسالة الفخم
    text = (
        f"🎓 **الـمنـظـم:** {settings['owner_name']} ☁️\n"
        f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
        f"📌 **السؤال:** « {current_num} » من « {total_num} »\n"
        f"📂 **القسم:** `{settings['cat_name']}`\n"
        f"🛠 **المصدر:** `{source}`\n"
        f"📡 **النطاق:** **{q_scope}**\n"
        f"⏳ **المهلة:** {settings['time_limit']} ثانية\n"
        f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n\n"
        f"❓ **السؤال:**\n**{q_text}**"
    )
    
    # 4. الإرسال مع return (ضروري جداً لمحرك الحذف)
    try:
        return await bot.send_message(chat_id, text, parse_mode='Markdown')
    except Exception as e:
        # في حال فشل الماركدوان، نحاول إرساله بنص عادي لضمان عدم توقف المسابقة
        return await bot.send_message(chat_id, text.replace("*", "").replace("`", ""))
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
    
    # ✅ التعديل الجوهري هنا: أضفنا return ليعود كائن الرسالة للمحرك
    return await bot.send_message(chat_id, msg, parse_mode="HTML")
    
async def send_final_results(chat_id, scores, total_q, is_public=False):
    """
    إصلاح ياسر المطور: عرض العباقرة في كل الحالات مع معالجة الأخطاء
    """
    try:
        msg = "🏁 **انتهت المسابقة بنجاح!** 🏁\n"
        msg += "شكرًا لكل من شارك وأمتعنا بمنافسته. 🌹\n\n"
        msg += "❃┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅❃\n"
        msg += "🏆 **{ العباقرة }** 🏆\n"
        msg += "❃┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅❃\n\n"

        found_winners = False

        if is_public:
            # 🌐 في الإذاعة العامة: نعرض ترتيب المجموعات
            sorted_groups = sorted(
                scores.items(), 
                key=lambda x: sum(p['points'] for p in x[1].values()) if isinstance(x[1], dict) else 0, 
                reverse=True
            )
            
            for i, (gid, players) in enumerate(sorted_groups, 1):
                if not players: continue
                found_winners = True
                total_pts = sum(p['points'] for p in players.values())
                msg += f"{i}️⃣ **مجموعة: {gid}** 🎖 (إجمالي: {total_pts})\n"
                top_p = max(players.values(), key=lambda x: x['points'])
                msg += f"┗ 👤 بطلها: {top_p['name']} ({top_p['points']} ن)\n"
                msg += "┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅\n"
        else:
            # 📍 في المسابقة الخاصة: نعرض ترتيب الأفراد
            sorted_players = sorted(scores.values(), key=lambda x: x['points'], reverse=True)
            medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
            
            for i, p in enumerate(sorted_players[:5]):
                found_winners = True
                icon = medals[i] if i < len(medals) else "👤"
                msg += f"{icon} **{p['name']}** — {p['points']} نقطة\n"
                msg += "┈┉┈┉┈┉┈┉┈┉┈┉┈┉┈┉┈\n"

        if not found_winners:
            msg = "🏁 **انتهت المسابقة!**\n\n❌ للأسف لم يتم تسجيل أي نقاط في هذه الجولة. حظاً أوفر المرة القادمة! 🌹"
        else:
            msg += f"\n📊 إجمالي أسئلة الجولة: {total_q}\n"
            msg += "تهانينا للفائزين وحظاً أوفر للجميع! ❤️"

        return await bot.send_message(chat_id, msg, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Error in send_final_results: {e}")
        # محاولة إرسال رسالة بسيطة في حال فشل القالب الفخم
        try:
            return await bot.send_message(chat_id, "🏁 انتهت المسابقة! (حدث خطأ في عرض الترتيب)")
        except:
            pass
    # [اختياري] هنا يمكنك استدعاء دالة لترحيل النقاط إلى SQL (groups_hub) إذا أردت حفظها للأبد
async def sync_points_to_db(group_scores, is_public=False):
    """
    مهمة ياسر الكبرى: ترحيل نقاط الجولة الحالية إلى جدول groups_hub
    """
    for cid, players in group_scores.items():
        if not players: continue

        # 1. حساب إجمالي نقاط المجموعة في هذه الجولة
        round_total = sum(p['points'] for p in players.values())
        
        # 2. تجهيز بيانات الأعضاء للتحديث (JSON)
        # سنجلب البيانات القديمة أولاً ثم نضيف عليها
        try:
            # استعلام لجلب البيانات الحالية للمجموعة
            res = supabase.table("groups_hub").select("*").eq("group_id", cid).execute()
            
            if res.data:
                db_data = res.data[0]
                # تحديث نقاط الأعضاء (نقاط الجولة + النقاط القديمة)
                old_members_pts = db_data.get('group_members_points', {}) or {}
                for uid, p_data in players.items():
                    u_name = p_data['name']
                    old_pts = old_members_pts.get(u_name, 0) # نستخدم الاسم كمفتاح حسب طلبك
                    old_members_pts[u_name] = old_pts + p_data['points']

                # 3. تنفيذ التحديث في SQL
                supabase.table("groups_hub").update({
                    "total_group_score": db_data.get('total_group_score', 0) + round_total,
                    "group_members_points": old_members_pts,
                    "updated_at": "now()"
                }).eq("group_id", cid).execute()
                
            else:
                # إذا كانت المجموعة جديدة، ننشئ لها سجلاً أولاً
                new_members = {p['name']: p['points'] for p in players.values()}
                supabase.table("groups_hub").insert({
                    "group_id": cid,
                    "total_group_score": round_total,
                    "group_members_points": new_members,
                    "status": "active"
                }).execute()
                
        except Exception as e:
            logging.error(f"خطأ أثناء ترحيل النقاط للمجموعة {cid}: {e}")
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

# 3️⃣ [ دالة عرض القائمة الرئيسية للأقسام ]
async def custom_add_menu(c, owner_id, state):
    if state:
        await state.finish()
        
    kb = get_categories_kb(owner_id) 
    await c.message.edit_text(
        "⚙️ **لوحة إعدادات أقسامك الخاصة:**\n\nأهلاً بك! اختر من الخيارات أدناه لإدارة بنك أسئلتك وإضافة أقسام جديدة:",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await c.answer()
# ==========================================
# ---الدالة التي طلبتها (تأكد أنها موجودة بهذا الاسم) ---
# ==========================================
def get_categories_kb(user_id):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("➕ إضافة قسم جديد", callback_data=f"add_new_cat_{user_id}"))
    kb.add(InlineKeyboardButton("📋 قائمة الأقسام", callback_data=f"list_cats_{user_id}"))
    kb.add(InlineKeyboardButton("🔙 الرجوع لصفحة التحكم", callback_data=f"back_to_main_{user_id}"))
    
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
    
    txt = (f"⚙️ إعدادات القسم: {cat_name}\n\n"
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
        InlineKeyboardButton("👥 أقسام الأعضاء (إسئلة الاعضاء)", callback_data=f"members_setup_step1_{user_id}"),
        InlineKeyboardButton("👤 أقسامك الخاصة (مكتبتي)", callback_data=f"my_setup_step1_{user_id}"),
        InlineKeyboardButton("🤖 أقسام البوت (الرسمية)", callback_data=f"bot_setup_step1_{user_id}"),
        InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data=f"back_to_control_{user_id}")
    )
    return kb


# ==========================================
# الدوال المساعدة المحدثة (حماية + أسماء حقيقية)
# ==========================================
async def render_members_list(message, eligible_list, selected_list, owner_id):
    """
    eligible_list: قائمة تحتوي على ديكشنري [{id: ..., name: ...}]
    """
    kb = InlineKeyboardMarkup(row_width=2)
    for member in eligible_list:
        m_id = str(member['id'])
        # نستخدم الاسم الحقيقي اللي جلبناه من جدول users
        status = "✅ " if m_id in selected_list else ""
        # الحماية: نمرر owner_id في نهاية الكولباك
        kb.insert(InlineKeyboardButton(
            f"{status}{member['name']}", 
            callback_data=f"toggle_mem_{m_id}_{owner_id}"
        ))
    
    if selected_list:
        # زر محمي تماماً لا ينتقل إلا بآيدي صاحب الجلسة
        kb.add(InlineKeyboardButton(
            f"➡️ تم اختيار ({len(selected_list)}) .. عرض أقسامهم", 
            callback_data=f"go_to_cats_step_{owner_id}"
        ))
    
    kb.add(InlineKeyboardButton("🔙 رجوع", callback_data=f"setup_quiz_{owner_id}"))
    await message.edit_text("👥 <b>أقسام الأعضاء المبدعين:</b>\nاختر المبدعين لعرض أقسامهم:", reply_markup=kb, parse_mode="HTML")

# 2. دالة عرض المجلدات (نظام البوت الرسمي الجديد)
async def render_folders_list(message, eligible_folders, selected_folders, owner_id):
    kb = InlineKeyboardMarkup(row_width=2)
    for folder in eligible_folders:
        f_id = str(folder['id'])
        status = "✅ " if f_id in selected_folders else ""
        kb.insert(InlineKeyboardButton(
            f"{status}{folder['name']}", 
            callback_data=f"toggle_folder_{f_id}_{owner_id}"
        ))
    
    if selected_folders:
        kb.add(InlineKeyboardButton(
            f"➡️ تم اختيار ({len(selected_folders)}) .. عرض الأقسام", 
            callback_data=f"confirm_folders_{owner_id}"
        ))
    
    kb.add(InlineKeyboardButton("🔙 رجوع", callback_data=f"setup_quiz_{owner_id}"))
    await message.edit_text("🗂️ <b>مجلدات البوت الرسمية:</b>\nاختر المجلدات المطلوبة:", reply_markup=kb, parse_mode="HTML")

# 3. دالة عرض الأقسام (محمية من المبعسسين)
async def render_categories_list(message, eligible_cats, selected_cats, owner_id):
    kb = InlineKeyboardMarkup(row_width=2)
    for cat in eligible_cats:
        cat_id_str = str(cat['id'])
        status = "✅ " if cat_id_str in selected_cats else ""
        kb.insert(InlineKeyboardButton(
            f"{status}{cat['name']}", 
            callback_data=f"toggle_cat_{cat_id_str}_{owner_id}"
        ))
    
    if selected_cats:
        # زر محمي: يمنع المبعسس من الانتقال لواجهة الإعدادات النهائية
        kb.add(InlineKeyboardButton(
            f"➡️ تم اختيار ({len(selected_cats)}) .. الإعدادات", 
            callback_data=f"final_quiz_settings_{owner_id}"
        ))
    
    kb.add(InlineKeyboardButton("🔙 رجوع", callback_data=f"setup_quiz_{owner_id}"))
    await message.edit_text("📂 <b>اختر الأقسام المطلوبة:</b>", reply_markup=kb, parse_mode="HTML")
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
       f"⚙️ لوحة إعدادات المسابقة\n"
       f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
       f"📊 عدد الأسئلة: {q_count}\n"
       f"📡 النطاق: {q_scope_text}\n"
       f"🔖 النظام: {q_mode}\n"
       f"⏳ المهلة: {q_time} ثانية\n"
       f"💡 التلميح: {q_hint_text}\n"
       f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
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
# 3. دوال الفحص الأمني والمحركات (Security Helpers & Engines)
# ==========================================

async def get_group_status(chat_id):
    """فحص حالة تفعيل المجموعة في الجدول الموحد الجديد groups_hub"""
    try:
        res = supabase.table("groups_hub").select("status").eq("group_id", chat_id).execute()
        return res.data[0]['status'] if res.data else "not_found"
    except Exception as e:
        logging.error(f"Error checking group status: {e}")
        return "error"

async def start_broadcast_process(c: types.CallbackQuery, quiz_id: int, owner_id: int):
    try:
        # 1. جلب بيانات المسابقة
        res_q = supabase.table("saved_quizzes").select("*").eq("id", quiz_id).single().execute()
        q = res_q.data
        if not q: return await c.answer("❌ تعذر جلب بيانات المسابقة")

        # 2. جلب المجموعات
        groups_res = supabase.table("groups_hub").select("group_id").eq("status", "active").execute()
        if not groups_res.data: return await c.answer("⚠️ لا توجد مجموعات!")

        all_chats = [g['group_id'] for g in groups_res.data]
        cancelled_groups.clear() # تصفية القائمة قبل كل إذاعة

        # 3. تجهيز بيانات القالب (المجلد، القسم، النوع)
        quiz_name = q.get('quiz_name', 'تحدي جديد')
        q_count = q.get('questions_count', 10)
        q_mode = q.get('mode', 'السرعة ⚡')
        # نفترض أن q['cats'] تحتوي على اسم القسم أو المجلد
        cat_info = q.get('category_name', 'عام') 

        # 4. إرسال الرسالة الأولى وتخزين المعرفات
        group_msgs = {}
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🚫 إلغاء المسابقة في مجموعتنا", callback_data=f"cancel_quiz_{quiz_id}"))

        for cid in all_chats:
            try:
                msg = await bot.send_message(cid, "🛰️ **جاري تحضير الإذاعة العالمية...**")
                group_msgs[cid] = msg.message_id
            except: continue

        # 5. دورة العد التنازلي (30 رقم، كل رقم ثانيتين)
        # إيموجيات الأرقام من 30 إلى 1
        timer_emojis = ["3️⃣0️⃣", "2️⃣9️⃣", "2️⃣8️⃣", "2️⃣7️⃣", "2️⃣6️⃣", "2️⃣5️⃣", "2️⃣4️⃣", "2️⃣3️⃣", "2️⃣2️⃣", "2️⃣1️⃣", 
                        "2️⃣0️⃣", "1️⃣9️⃣", "1️⃣8️⃣", "1️⃣7️⃣", "1️⃣6️⃣", "1️⃣5️⃣", "1️⃣4️⃣", "1️⃣3️⃣", "1️⃣2️⃣", "1️⃣1️⃣", 
                        "1️⃣0️⃣", "9️⃣", "8️⃣", "7️⃣", "6️⃣", "5️⃣", "4️⃣", "3️⃣", "2️⃣", "1️⃣"]

        for emoji in timer_emojis:
            # القالب الملكي المحدث
            text = (
                f"📢 **إعلان: مسابقة عالمية منطلقة الآن!** 🌐\n"
                f"━━━━━━━━━━━━━━\n"
                f"🏆 المسابقة: **{quiz_name}**\n"
                f"📂 القسم: **{cat_info}**\n"
                f"🔢 عدد الأسئلة: **{q_count}**\n"
                f"⚙️ النوع: **{q_mode}**\n"
                f"👤 المنظم: **{c.from_user.first_name}**\n"
                f"━━━━━━━━━━━━━━\n"
                f"⏳ ستبدأ المسابقة بعد انتهاء العد التنازلي:\n"
                f"🔥 {emoji} 🔥\n"
                f"━━━━━━━━━━━━━━\n"
                f"👈 إن كنت لا تريد المشاركة اضغط إلغاء أدناه."
            )

            edit_tasks = []
            for cid, mid in group_msgs.items():
                if cid not in cancelled_groups: # تعديل فقط للمجموعات التي لم تلغِ
                    edit_tasks.append(bot.edit_message_text(text, cid, mid, reply_markup=kb, parse_mode="Markdown"))
            
            await asyncio.gather(*edit_tasks, return_exceptions=True)
            await asyncio.sleep(2) # ثانيتين لكل رقم كما طلبت

        # 6. التصفية النهائية (حذف من ضغط إلغاء) والانطلاق
        final_groups = [cid for cid in group_msgs if cid not in cancelled_groups]
        
        if final_groups:
            await engine_global_broadcast(final_groups, q, "الإذاعة العالمية 🌐")
        
        # تنظيف الرسائل القديمة
        for cid, mid in group_msgs.items():
            try: await bot.delete_message(cid, mid)
            except: pass

    except Exception as e:
        logging.error(f"🚨 Broadcast Error: {e}")
# 4. حالات النظام (FSM States)
# ==========================================
class Form(StatesGroup):
    waiting_for_cat_name = State()
    waiting_for_question = State()
    waiting_for_ans1 = State()
    waiting_for_ans2 = State()
    waiting_for_new_cat_name = State()
    waiting_for_quiz_name = State()

# ==========================================
# 5. الترحيب التلقائي بصورة البوت
# ==========================================
@dp.message_handler(content_types=types.ContentTypes.NEW_CHAT_MEMBERS)
async def welcome_bot_to_group(message: types.Message):
    for member in message.new_chat_members:
        if member.id == (await bot.get_me()).id:
            group_name = message.chat.title
            
            kb_welcome = InlineKeyboardMarkup(row_width=1)
            kb_welcome.add(
                InlineKeyboardButton("👑 مبرمج البوت (ياسر)", url="https://t.me/Ya_79k")
            )

            welcome_text = (
                f"👋 <b>أهلاً بكم في عالم المسابقات!</b>\n"
                f"تمت إضافتي بنجاح في: <b>{group_name}</b>\n"
                f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
                f"🤖 <b>أنا بوت المسابقات الذكي (Questions Bot).</b>\n\n"
                f"🛠️ <b>كيفية البدء:</b>\n"
                f"يجب على المشرف كتابة أمر (تفعيل) لإرسال طلب للمطور.\n\n"
                f"📜 <b>الأوامر الأساسية:</b>\n"
                f"🔹 <b>تفعيل :</b> لطلب تشغيل البوت.\n"
                f"🔹 <b>تحكم :</b> لوحة الإعدادات (للمشرفين).\n"
                f"🔹 <b>مسابقة :</b> لبدء جولة أسئلة.\n"
                f"🔹 <b>عني :</b> لعرض ملفك الشخصي ونقاطك.\n"
                f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
                f"📢 <i>اكتب (تفعيل) الآن لنبدأ الرحلة!</i>"
            )

            try:
                # ضع الـ File ID الذي حصلت عليه من @FileIdBot هنا
                bot_photo_id = "AgACAgQAAxkBAA..." # استبدل هذا بالكود الذي سيعطيك إياه البوت
                await message.answer_photo(
                    photo=bot_photo_id, 
                    caption=welcome_text, 
                    reply_markup=kb_welcome, 
                    parse_mode="HTML"
                )
            except:
                # في حال لم تضع الآيدي بعد أو حدث خطأ، يرسل نصاً فقط
                await message.answer(welcome_text, reply_markup=kb_welcome, parse_mode="HTML")
# ==========================================
# --- ---
# ==========================================
@dp.callback_query_handler(lambda c: c.data.startswith('cancel_quiz_'))
async def cancel_quiz_handler(c: types.CallbackQuery):
    chat_id = c.message.chat.id
    cancelled_groups.add(chat_id)
    await c.message.edit_text("🚫 **تم إلغاء المسابقة في هذه المجموعة.**")
    await c.answer("تم الإلغاء بنجاح", show_alert=True)
    
# ==========================================
# 6. أمر التفعيل (Request Activation)
# ==========================================
@dp.message_handler(lambda m: m.text == "تفعيل", chat_type=[types.ChatType.GROUP, types.ChatType.SUPERGROUP])
async def activate_group_hub(message: types.Message):
    user_id = message.from_user.id
    chat_member = await message.chat.get_member(user_id)
    
    if not (chat_member.is_chat_admin() or user_id == ADMIN_ID):
        return await message.reply("⚠️ عذراً، هذا الأمر مخصص لمشرفي القروب لطلب التفعيل.")

    group_id = message.chat.id
    group_name = message.chat.title

    try:
        res = supabase.table("groups_hub").select("*").eq("group_id", group_id).execute()
        
        if res.data:
            status = res.data[0]['status']
            if status == 'active':
                return await message.reply("🛡️ <b>القروب مفعل مسبقاً وجاهز للعمل!</b>", parse_mode="HTML")
            elif status == 'pending':
                return await message.reply("⏳ <b>طلبكم قيد المراجعة حالياً!</b>\nيرجى انتظار موافقة المطور.", parse_mode="HTML")
            elif status == 'blocked':
                return await message.reply("🚫 <b>هذا القروب محظور من قبل المطور.</b>", parse_mode="HTML")
        
        supabase.table("groups_hub").insert({
            "group_id": group_id, "group_name": group_name, "status": "pending",
            "is_global": True, "group_members_points": {}, "global_users_points": {}, "total_group_score": 0
        }).execute()

        kb_dev = InlineKeyboardMarkup().add(InlineKeyboardButton("👑 تواصل مع المطور", url="https://t.me/Ya_79k"))
        await message.reply(
            f"✅ <b>تم إرسال طلب التفعيل بنجاح!</b>\n"
            f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
            f"⚙️ الحالة: بانتظار موافقة المطور ⏳\n"
            f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
            f"سيتم إشعاركم هنا فور القبول.", 
            reply_markup=kb_dev, 
            parse_mode="HTML"
        )
        
        kb_fast_action = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ موافقة", callback_data=f"auth_approve_{group_id}"),
            InlineKeyboardButton("🚫 رفض وحظر", callback_data=f"auth_block_{group_id}")
        )
        await bot.send_message(ADMIN_ID, 
            f"🔔 <b>طلب تفعيل جديد بانتظارك!</b>\n"
            f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
            f"👥 القروب: <b>{group_name}</b>\n"
            f"🆔 الآيدي: <code>{group_id}</code>\n"
            f"اتخذ قرارك الآن:", 
            reply_markup=kb_fast_action, 
            parse_mode="HTML")

    except Exception as e:
        logging.error(f"Activation Error: {e}")
        await message.reply("❌ حدث خطأ تقني في قاعدة البيانات.")

# ==========================================
# 2. تعديل أمر "تحكم" لضمان عدم العمل إلا بعد التفعيل
# ==========================================
@dp.message_handler(lambda m: m.text == "تحكم")
async def control_panel(message: types.Message):
    user_id = message.from_user.id
    group_id = message.chat.id

    # في المجموعات، نتحقق من حالة التفعيل
    if message.chat.type != 'private':
        # إذا لم يكن المطور، نتحقق من حالة القروب
        if user_id != ADMIN_ID:
            status = await get_group_status(group_id)
            if status != "active":
                return await message.reply("⚠️ <b>هذا القروب غير مفعل.</b>\nيجب أن يوافق المطور على طلب التفعيل أولاً.", parse_mode="HTML")
            
            # فحص هل المستخدم مشرف
            member = await bot.get_chat_member(group_id, user_id)
            if not (member.is_chat_admin() or member.is_chat_creator()):
                return await message.reply("⚠️ لوحة التحكم مخصصة للمشرفين فقط.")

    # إذا كان المطور أو قروب مفعل، تظهر اللوحة
    txt = (f"👋 أهلاً بك في لوحة الإعدادات\n"
           f"👑 المطور: <b>{OWNER_USERNAME}</b>")
    
    await message.answer(txt, reply_markup=get_main_control_kb(user_id), parse_mode="HTML")

# التعديل في السطر 330 (أضفنا close_bot_)
@dp.callback_query_handler(lambda c: c.data.startswith(('custom_add_', 'dev_', 'setup_quiz_', 'close_bot_', 'back_')), state="*")
async def handle_control_buttons(c: types.CallbackQuery, state: FSMContext):
    data_parts = c.data.split('_')
    action = data_parts[0] 
    owner_id = int(data_parts[-1])

    # 🛑 [ الأمان ]
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا تلمس أزرار غيرك! 😂", show_alert=True)

    # 1️⃣ [ زر الإغلاق ] - فحص الكلمة بالكامل أو أول جزء
    if action == "close":
        await c.answer("تم إغلاق اللوحة ✅")
        return await c.message.delete()

    # 2️⃣ [ زر الرجوع ] - النسخة المصلحة (التعديل بدل الإرسال)
    elif action == "back":
        await state.finish()
        await c.answer("🔙 جاري العودة...")
        # بدلاً من استدعاء control_panel التي ترسل رسالة جديدة، نعدل الرسالة الحالية
        return await c.message.edit_text(
            f"👋 **أهلاً بك في لوحة التحكم الرئيسية**\n\nاختر من الأسفل ما تود القيام به:",
            reply_markup=get_main_control_kb(owner_id), # تأكد من وضع دالة الكيبورد الرئيسي هنا
            parse_mode="Markdown"
        )

    # 3️⃣ [ زر إضافة خاصة ]
    elif action == "custom":
        await c.answer()
        # التعديل هنا: يجب أن يكون السطر القادم تحت elif مباشرة (4 مسافات)
        return await custom_add_menu(c, state=state)

    # 4️⃣ [ زر تجهيز المسابقة ]
    elif action == "setup":
        await c.answer()
        keyboard = get_setup_quiz_kb(owner_id)
        return await c.message.edit_text(
            "🏆 **مرحباً بك في معمل تجهيز المسابقات!**\n\nمن أين تريد جلب الأسئلة لمسابقتك؟",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

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
# --- [ 2. إدارة الأقسام والأسئلة (النسخة النهائية المصلحة) ] ---

@dp.callback_query_handler(lambda c: c.data.startswith('custom_add'), state="*")
async def custom_add_menu(c: types.CallbackQuery, state: FSMContext = None):
    if state:
        await state.finish()
    
    data_parts = c.data.split('_')
    try:
        owner_id = int(data_parts[-1])
    except (ValueError, IndexError):
        owner_id = c.from_user.id

    if c.from_user.id != owner_id:
        return await c.answer("⚠️ هذي اللوحة مش حقك! 😂", show_alert=True)

    kb = get_categories_kb(owner_id)

    # هنا نستخدم edit_text لضمان التعديل بدل الإرسال الجديد
    await c.message.edit_text(
        "⚙️ **لوحة إعدادات أقسامك الخاصة:**\n\nاختر من القائمة أدناه لإدارة أقسامك وأسئلتك:", 
        reply_markup=kb, 
        parse_mode="Markdown"
    )
    await c.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('back_to_main'), state="*")
async def back_to_main_panel(c: types.CallbackQuery, state: FSMContext = None):
    if state:
        await state.finish()
    
    owner_id = int(c.data.split('_')[-1])
    
    # استدعاء كيبورد لوحة التحكم الرئيسية
    kb = get_main_control_kb(owner_id)

    # التعديل الجوهري: نستخدم edit_text ليحذف اللوحة السابقة وتظهر الرئيسية مكانها
    await c.message.edit_text(
        f"👋 أهلاً بك في لوحة إعدادات المسابقات الخاصة\n👑 المطور: @Ya_79k",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await c.answer("🔙 تمت العودة للقائمة الرئيسية")

@dp.callback_query_handler(lambda c: c.data.startswith('add_new_cat'), state="*")
async def btn_add_cat(c: types.CallbackQuery):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا يمكنك الإضافة في لوحة غيرك!", show_alert=True)

    await c.answer() 
    await Form.waiting_for_cat_name.set()
    
    kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🔙 إلغاء والعودة", callback_data=f"custom_add_{owner_id}")
    )
    # تحديث الرسالة لطلب الاسم لمنع التراكم
    await c.message.edit_text("📝 **اكتب اسم القسم الجديد الآن:**", reply_markup=kb, parse_mode="Markdown")

@dp.message_handler(state=Form.waiting_for_cat_name)
async def save_cat(message: types.Message, state: FSMContext):
    cat_name = message.text.strip()
    user_id = message.from_user.id
    
    try:
        supabase.table("categories").insert({
            "name": cat_name, 
            "created_by": str(user_id)
        }).execute()
        
        await state.finish()
        
        # عند النجاح، نرسل رسالة جديدة كإشعار ثم نعطيه زر العودة الذي يقوم بالتعديل
        kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("🔙 العودة للأقسام", callback_data=f"custom_add_{user_id}")
        )
        await message.answer(f"✅ تم حفظ القسم **'{cat_name}'** بنجاح.", reply_markup=kb, parse_mode="Markdown")

    except Exception as e:
        await state.finish()
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ الرجوع", callback_data=f"custom_add_{user_id}"))
        await message.answer("⚠️ حدث خطأ أو الاسم مكرر. حاول مرة أخرى.", reply_markup=kb)

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
    txt = f"🔍 قائمة الأسئلة المضافة:\n"
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
    # del(0) _ qs(1) _ menu(2) _ catid(3) _ ownerid(4)
    cat_id = data[3]
    owner_id = int(data[4])

    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا تملك صلاحية الحذف هنا!", show_alert=True)

    await c.answer()
    res = supabase.table("questions").select("*").eq("category_id", cat_id).execute()
    questions = res.data
    
    kb = InlineKeyboardMarkup(row_width=1)
    if questions:
        for q in questions:
            kb.add(InlineKeyboardButton(
                f"🗑️ حذف: {q['question_content'][:25]}...", 
                callback_data=f"pre_del_q_{q['id']}_{cat_id}_{owner_id}"
            ))
    
    # تصحيح زر الرجوع ليعود للقائمة السابقة
    kb.add(InlineKeyboardButton("🔙 رجوع", callback_data=f"manage_questions_{cat_id}_{owner_id}"))
    await c.message.edit_text("🗑️ اختر السؤال المراد حذفه:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('pre_del_q_'))
async def confirm_delete_question(c: types.CallbackQuery):
    data = c.data.split('_')
    # pre(0) _ del(1) _ q(2) _ qid(3) _ catid(4) _ ownerid(5)
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
    # final(0) _ del(1) _ q(2) _ qid(3) _ catid(4) _ ownerid(5)
    q_id, cat_id, owner_id = data[3], data[4], data[5]
    
    supabase.table("questions").delete().eq("id", q_id).execute()
    await c.answer("🗑️ تم الحذف بنجاح", show_alert=True)
    
    # تحديث البيانات في الـ Callback لاستدعاء القائمة مجدداً
    c.data = f"del_qs_menu_{cat_id}_{owner_id}"
    await delete_questions_menu(c)


# --- 7. حذف القسم نهائياً (النسخة المصلحة) ---

@dp.callback_query_handler(lambda c: c.data.startswith('confirm_del_cat_'))
async def confirm_delete_cat(c: types.CallbackQuery):
    data = c.data.split('_')
    cat_id = data[3]
    owner_id = int(data[4])

    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا تملك صلاحية حذف الأقسام!", show_alert=True)

    await c.answer()
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("✅ نعم، احذف", callback_data=f"final_del_cat_{cat_id}_{owner_id}"),
        InlineKeyboardButton("❌ لا، تراجع", callback_data=f"manage_questions_{cat_id}_{owner_id}")
    )
    # تعديل نص الرسالة الحالية لطلب التأكيد
    await c.message.edit_text("⚠️ هل أنت متأكد من حذف هذا القسم نهائياً مع كل أسئلته؟", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('final_del_cat_'))
async def execute_delete_cat(c: types.CallbackQuery):
    data = c.data.split('_')
    cat_id = data[3]
    owner_id = int(data[4])

    # 1. تنفيذ الحذف في سوبابيس
    try:
        supabase.table("categories").delete().eq("id", cat_id).execute()
        await c.answer("🗑️ تم حذف القسم بنجاح", show_alert=True)
    except Exception as e:
        return await c.answer("❌ فشل الحذف من قاعدة البيانات")

    # 2. العودة لقائمة الأقسام بتحديث نفس الرسالة
    # استخدمنا await لضمان التنفيذ وتمرير المتغيرات لعمل Edit
    await custom_add_menu(c)
    
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
# 1. اختيار مصدر الأسئلة (رسمي / خاص / أعضاء) - نسخة المجلدات والأسماء
# ==========================================

# --- [ أسئلة البوت: نظام المجلدات الجديد ] --
@dp.callback_query_handler(lambda c: c.data.startswith('bot_setup_step1_'), state="*")
async def start_bot_selection(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة محمية!", show_alert=True)
    
    # جلب المجلدات بدلاً من الأقسام مباشرة
    res = supabase.table("folders").select("id, name").execute()
    if not res.data: return await c.answer("⚠️ لا توجد مجلدات رسمية!", show_alert=True)

    eligible_folders = [{"id": str(item['id']), "name": item['name']} for item in res.data]
    
    # تخزين البيانات في الحالة للبدء باختيار المجلدات
    await state.update_data(
        eligible_folders=eligible_folders, 
        selected_folders=[], 
        is_bot_quiz=True, 
        current_owner_id=owner_id
    ) 
    
    # استدعاء دالة عرض المجلدات
    await render_folders_list(c.message, eligible_folders, [], owner_id)

# --- [ أسئلة خاصة: جلب أقسام المستخدم نفسه ] ---
@dp.callback_query_handler(lambda c: c.data.startswith('my_setup_step1_'), state="*")
async def start_private_selection(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة محمية!", show_alert=True)
    
    res = supabase.table("categories").select("*").eq("created_by", str(owner_id)).execute()
    if not res.data: return await c.answer("⚠️ ليس لديك أقسام خاصة!", show_alert=True)
    
    await state.update_data(eligible_cats=res.data, selected_cats=[], is_bot_quiz=False, current_owner_id=owner_id) 
    await render_categories_list(c.message, res.data, [], owner_id)

# --- [ أسئلة الأعضاء: إظهار الأسماء بدلاً من الأرقام ] ---
@dp.callback_query_handler(lambda c: c.data.startswith('members_setup_step1_'), state="*")
async def start_member_selection(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة محمية!", show_alert=True)
    
    # جلب المعرفات التي لها أسئلة
    res = supabase.table("questions").select("created_by").execute()
    if not res.data: return await c.answer("⚠️ لا يوجد أعضاء حالياً.", show_alert=True)
    
    from collections import Counter
    counts = Counter([q['created_by'] for q in res.data])
    eligible_ids = [m_id for m_id, count in counts.items() if count >= 15]
    
    if not eligible_ids: return await c.answer("⚠️ لا يوجد مبدعون وصلوا لـ 15 سؤال.", show_alert=True)
    
    # الإصلاح: جلب الأسماء من جدول المستخدمين (users) لربط الـ ID بالاسم
    users_res = supabase.table("users").select("user_id, name").in_("user_id", eligible_ids).execute()
    
    # تحويل البيانات لقائمة كائنات تحتوي على الاسم والمعرف
    eligible_list = [{"id": str(u['user_id']), "name": u['name'] or f"مبدع {u['user_id']}"} for u in users_res.data]
    
    await state.update_data(eligible_list=eligible_list, selected_members=[], is_bot_quiz=False, current_owner_id=owner_id)
    await render_members_list(c.message, eligible_list, [], owner_id)

# ==========================================
# 2. معالجات التبديل والاختيار (Toggle & Go) - نسخة المجلدات المحدثة
# ==========================================

# --- [ 1. معالج تبديل المجلدات (Folders Toggle) ] ---
@dp.callback_query_handler(lambda c: c.data.startswith('toggle_folder_'), state="*")
async def toggle_folder_selection(c: types.CallbackQuery, state: FSMContext):
    data_parts = c.data.split('_')
    f_id = data_parts[2]
    owner_id = int(data_parts[3])
    
    if c.from_user.id != owner_id: 
        return await c.answer("⚠️ مبعسس؟ المجلدات لصاحب المسابقة بس! 😂", show_alert=True)
    
    data = await state.get_data()
    selected = data.get('selected_folders', [])
    eligible = data.get('eligible_folders', [])
    
    if f_id in selected: selected.remove(f_id)
    else: selected.append(f_id)
    
    await state.update_data(selected_folders=selected)
    await c.answer()
    # استدعاء دالة رندر المجلدات لتحديث الشكل
    await render_folders_list(c.message, eligible, selected, owner_id)

# --- [ 2. معالج الانتقال من المجلدات إلى الأقسام ] ---
@dp.callback_query_handler(lambda c: c.data.startswith('confirm_folders_'), state="*")
async def confirm_folders_to_cats(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة محمية!", show_alert=True)
    
    data = await state.get_data()
    chosen_folder_ids = data.get('selected_folders', [])
    
    if not chosen_folder_ids:
        return await c.answer("⚠️ اختر مجلد واحد على الأقل!", show_alert=True)

    # جلب الأقسام التابعة للمجلدات المختارة فقط من جدول bot_categories
    res = supabase.table("bot_categories").select("id, name").in_("folder_id", chosen_folder_ids).execute()
    
    if not res.data:
        return await c.answer("⚠️ هذه المجلدات لا تحتوي على أقسام حالياً!", show_alert=True)
    
    await state.update_data(eligible_cats=res.data, selected_cats=[])
    await c.answer("✅ تم جلب أقسام المجلدات")
    # الانتقال لعرض الأقسام
    await render_categories_list(c.message, res.data, [], owner_id)

# --- [ 3. معالج تبديل الأعضاء (Members Toggle) ] ---
@dp.callback_query_handler(lambda c: c.data.startswith('toggle_mem_'), state="*")
async def toggle_member(c: types.CallbackQuery, state: FSMContext):
    data_parts = c.data.split('_')
    m_id = data_parts[2]
    owner_id = int(data_parts[3])
    
    if c.from_user.id != owner_id: return await c.answer("⚠️ مبعسس؟ ما تقدر تختار! 😂", show_alert=True)
    
    data = await state.get_data()
    selected = data.get('selected_members', [])
    eligible = data.get('eligible_list', []) # تحتوي على الأوبجكت {id, name}
    
    if m_id in selected: selected.remove(m_id)
    else: selected.append(m_id)
    
    await state.update_data(selected_members=selected)
    await c.answer()
    await render_members_list(c.message, eligible, selected, owner_id)

# --- [ 4. معالج الانتقال من الأعضاء إلى الأقسام ] ---
@dp.callback_query_handler(lambda c: c.data.startswith('go_to_cats_step_'), state="*")
async def show_selected_members_cats(c: types.CallbackQuery, state: FSMContext):
    owner_id = int(c.data.split('_')[-1])
    if c.from_user.id != owner_id: return await c.answer("⚠️ اللوحة ليست لك!", show_alert=True)
    
    data = await state.get_data()
    chosen_ids = data.get('selected_members', [])
    
    # جلب الأقسام الخاصة بالأعضاء المختارين
    res = supabase.table("categories").select("id, name").in_("created_by", chosen_ids).execute()
    
    await state.update_data(eligible_cats=res.data, selected_cats=[])
    await render_categories_list(c.message, res.data, [], owner_id)

# --- [ 5. معالج تبديل الأقسام (Categories Toggle) ] ---
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
    
# --- [ 5 + 6 ] المحرك الموحد ومعالج الحفظ النهائي --- #
@dp.callback_query_handler(lambda c: c.data.startswith(('tog_', 'cyc_', 'set_', 'start_quiz_')), state="*")
async def quiz_settings_engines(c: types.CallbackQuery, state: FSMContext):
    data_parts = c.data.split('_')
    action = data_parts[0] 
    owner_id = int(data_parts[-1])
    
    if c.from_user.id != owner_id:
        return await c.answer("⚠️ لا تتدخل في إعدادات غيرك! 😂", show_alert=True)

    data = await state.get_data()

    # 1️⃣ --- قسم المحركات (التعديل اللحظي) ---
    if action in ['tog', 'cyc', 'set']:
        await c.answer()
        
        # --- [جديد] محرك النطاق (إذاعة عامة / خاصة) ---
        if action == 'tog' and data_parts[1] == 'broad':
            current_broad = data.get('is_broadcast', False)
            new_status = not current_broad
            await state.update_data(is_broadcast=new_status)
            status_txt = "🌐 تم تفعيل الإذاعة العامة" if new_status else "📍 تم تحديد المسابقة داخلية"
            await c.answer(status_txt)

        # محرك التلميح الموحد
        elif action == 'cyc' and data_parts[1] == 'hint':
            is_currently_on = data.get('quiz_hint_bool', False)
            if not is_currently_on:
                await state.update_data(quiz_hint_bool=True, quiz_smart_bool=True)
                await c.answer("✅ تم تفعيل التلميحات")
            else:
                await state.update_data(quiz_hint_bool=False, quiz_smart_bool=False)
                await c.answer("❌ تم إيقاف التلميحات")
        
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

        # تحديث اللوحة فوراً بعد أي تغيير
        new_data = await state.get_data()
        return await render_final_settings_panel(c.message, new_data, owner_id)

    # 2️⃣ --- قسم بدء الحفظ والتشغيل ---
    elif action == 'start' and data_parts[1] == 'quiz':
        if not data.get('selected_cats'):
            return await c.answer("⚠️ اختر قسماً واحداً على الأقل!", show_alert=True)
        
        # فحص النطاق قبل البدء
        is_broadcast = data.get('is_broadcast', False)
        
        if is_broadcast:
            # إذا كانت عامة، نتأكد أن القروبات المفعلة متوفرة
            res = supabase.table("groups_hub").select("group_id").eq("status", "active").execute()
            if not res.data:
                return await c.answer("❌ لا توجد قروبات مفعلة حالياً للإذاعة العامة!", show_alert=True)
            await c.answer(f"🌐 سيتم البث في {len(res.data)} قروب!", show_alert=True)
        else:
            await c.answer("📍 مسابقة داخلية لهذا القروب.")

        await Form.waiting_for_quiz_name.set() 
        return await c.message.edit_text(
            "📝 يا بطل، أرسل الآن اسماً لمسابقتك:\n\n*(سيتم حفظ التلميحات ونطاق الإرسال تحت هذا الاسم)*",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("❌ إلغاء", callback_data=f"final_quiz_settings_{owner_id}")
            )
        )

@dp.message_handler(state=Form.waiting_for_quiz_name)
async def process_quiz_name_final(message: types.Message, state: FSMContext):
    quiz_name = message.text.strip()
    data = await state.get_data()
    
    selected_cats = data.get('selected_cats', [])
    clean_list = [str(c) for c in selected_cats] 
    u_id = str(message.from_user.id)

    # تجهيز البيانات بناءً على الأعمدة الفعلية في جدولك (CSV)
    payload = {
        "created_by": u_id,
        "quiz_name": quiz_name,
        "chat_id": u_id,
        "time_limit": int(data.get('quiz_time', 15)),
        "questions_count": int(data.get('quiz_count', 10)),
        "mode": data.get('quiz_mode', 'السرعة ⚡'),
        "hint_enabled": bool(data.get('quiz_hint_bool', False)),
        "smart_hint": bool(data.get('quiz_smart_bool', False)),
        "is_bot_quiz": bool(data.get('is_bot_quiz', False)), # عمود موجود في جدولك
        "cats": json.dumps(clean_list), # سوبابيس يفضل JSON للنصوص المصفوفة
        "is_public": bool(data.get('is_broadcast', False)) # استخدمنا is_public بدلاً من is_broadcast
    }

    try:
        # تنفيذ الحفظ
        supabase.table("saved_quizzes").insert(payload).execute()
        
        # تنسيق رسالة النجاح
        is_pub = payload["is_public"]
        scope_emoji = "🌐" if is_pub else "📍"
        scope_text = "إذاعة عامة" if is_pub else "مسابقة داخلية"
        
        success_msg = (
            f"✅ **تم حفظ المسابقة بنجاح!**\n"
            f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
            f"🏷 الاسم: `{quiz_name}`\n"
            f"⏱ الوقت: `{payload['time_limit']} ثانية`\n"
            f"📊 الأقسام: `{len(selected_cats)}` قسم\n"
            f"{scope_emoji} النطاق: **{scope_text}**\n"
            f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n\n"
            f"🚀 اكتب كلمة مسابقة ستجدها الآن في 'قائمة مسابقاتك'!"
        )
        
        await message.answer(success_msg, parse_mode="Markdown")
        await state.finish()

    except Exception as e:
        import logging
        logging.error(f"Error saving quiz: {e}")
        # هنا البوت بيعلمك لو فيه عمود ثاني ناقص
        await message.answer(f"❌ خطأ في قاعدة البيانات:\n`{str(e)}`", parse_mode="Markdown")
# ==========================================
# [1] عرض قائمة المسابقات (نسخة ياسر المصفاة)
# ==========================================
@dp.message_handler(lambda message: message.text == "مسابقة")
@dp.callback_query_handler(lambda c: c.data.startswith('list_my_quizzes_'), state="*")
async def show_quizzes(obj):
    is_callback = isinstance(obj, types.CallbackQuery)
    user = obj.from_user
    u_id = str(user.id)
    
    # جلب المسابقات الخاصة بالمستخدم فقط من سوبابيس
    res = supabase.table("saved_quizzes").select("*").eq("created_by", u_id).execute()
    kb = InlineKeyboardMarkup(row_width=1)
    
    if not res.data:
        msg_empty = f"⚠️ يا {user.first_name}، لا توجد لديك مسابقات محفوظة.**"
        if is_callback: return await obj.message.edit_text(msg_empty)
        return await obj.answer(msg_empty)

    # بناء قائمة المسابقات
    for q in res.data:
        kb.add(InlineKeyboardButton(
            f"🏆 {q['quiz_name']}", 
            callback_data=f"manage_quiz_{q['id']}_{u_id}"
        ))
    
    kb.add(InlineKeyboardButton("❌ إغلاق", callback_data=f"close_{u_id}"))
    
    title = f"🎁 مسابقاتك الجاهزة يا {user.first_name}:"

    if is_callback:
        await obj.message.edit_text(title, reply_markup=kb, parse_mode="Markdown")
    else:
        await obj.reply(title, reply_markup=kb, parse_mode="Markdown")

# ==========================================
# [2] المحرك الأمني ولوحة التحكم (التشطيب النهائي المصلح)
# ==========================================
@dp.callback_query_handler(lambda c: c.data.startswith(('run_', 'close_', 'confirm_del_', 'final_del_', 'edit_time_', 'manage_quiz_', 'quiz_settings_', 'set_c_', 'toggle_speed_', 'toggle_scope_', 'toggle_hint_', 'save_quiz_process_')), state="*")
async def handle_secure_actions(c: types.CallbackQuery, state: FSMContext):
    try:
        data_parts = c.data.split('_')
        owner_id = data_parts[-1]
        user_id = str(c.from_user.id)
        
        # الدرع الأمني
        if user_id != owner_id:
            return await c.answer("🚫 هذه اللوحة ليست لك.", show_alert=True)

        # 1️⃣ شاشة الإدارة الرئيسية للمسابقة
        if c.data.startswith('manage_quiz_'):
            quiz_id = data_parts[2]
            res = supabase.table("saved_quizzes").select("quiz_name").eq("id", quiz_id).single().execute()
            
            kb = InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🚀 بدء الانطلاق", callback_data=f"run_{quiz_id}_{user_id}"),
                InlineKeyboardButton("⚙️ الإعدادات", callback_data=f"quiz_settings_{quiz_id}_{user_id}"),
                InlineKeyboardButton("🔙 رجوع", callback_data=f"list_my_quizzes_{user_id}")
            )
            await c.message.edit_text(f"💎 إدارة: {res.data['quiz_name']}", reply_markup=kb)
            return

        # 2️⃣ لوحة الإعدادات
        elif c.data.startswith('quiz_settings_'):
            quiz_id = data_parts[2]
            res = supabase.table("saved_quizzes").select("*").eq("id", quiz_id).single().execute()
            q = res.data
            
            await state.update_data(editing_quiz_id=quiz_id, quiz_name=q['quiz_name'])
            q_time, q_count = q.get('time_limit', 15), q.get('questions_count', 10)
            q_mode = q.get('mode', 'السرعة ⚡')
            is_hint = q.get('smart_hint', False)
            is_public = q.get('is_public', False)

            text = (
                f"❃┏━━━━━ إعدادات: {q['quiz_name']} ━━━━━┓❃\n"
                f"📊 عدد الاسئلة: {q_count}\n"
                f"📡 النطاق: {'إذاعة عامة 🌐' if is_public else 'مسابقة داخلية 📍'}\n"
                f"🔖 النظام: {q_mode}\n"
                f"⏳ المهلة: {q_time} ثانية\n"
                f"💡 التلميح الذكي: {'مفعل ✅' if is_hint else 'معطل ❌'}\n"
                "❃┗━━━━━━━━━━━━━━━━━━━━┛❃"
            )

            kb = InlineKeyboardMarkup(row_width=5)
            kb.row(InlineKeyboardButton("📊 اختر عدد الأسئلة:", callback_data="ignore"))
            counts = [10, 15, 25, 32, 45]
            kb.add(*[InlineKeyboardButton(f"{'✅' if q_count==n else ''}{n}", callback_data=f"set_c_{quiz_id}_{n}_{user_id}") for n in counts])
            kb.row(InlineKeyboardButton(f"⏱️ المهلة: {q_time} ثانية", callback_data=f"edit_time_{quiz_id}_{user_id}"))
            kb.row(
                InlineKeyboardButton(f"🔖 {q_mode}", callback_data=f"toggle_speed_{quiz_id}_{user_id}"),
                InlineKeyboardButton(f"💡 {'مفعل ✅' if is_hint else 'معطل ❌'}", callback_data=f"toggle_hint_{quiz_id}_{user_id}")
            )
            kb.row(InlineKeyboardButton(f"📡 {'نطاق: عام 🌐' if is_public else 'نطاق: داخلي 📍'}", callback_data=f"toggle_scope_{quiz_id}_{user_id}"))
            kb.row(InlineKeyboardButton("💾 حفظ التعديلات 🚀", callback_data=f"save_quiz_process_{quiz_id}_{user_id}"))
            kb.row(InlineKeyboardButton("🗑️ حذف المسابقة", callback_data=f"confirm_del_{quiz_id}_{user_id}"))
            kb.row(InlineKeyboardButton("🔙 رجوع للخلف", callback_data=f"manage_quiz_{quiz_id}_{user_id}"))
            
            await c.message.edit_text(text, reply_markup=kb)
            return

        # 3️⃣ التبديلات (Toggles)
        elif any(c.data.startswith(x) for x in ['toggle_hint_', 'toggle_speed_', 'toggle_scope_', 'set_c_']):
            quiz_id = data_parts[2]
            # محرك النطاق (Scope) - المصلح ليتناسب مع عمود is_public
            if 'toggle_scope_' in c.data:
                res = supabase.table("saved_quizzes").select("is_public").eq("id", quiz_id).single().execute()
                # جلب القيمة الحالية (True أو False)
                curr_is_public = res.data.get('is_public', False)
                # عكس القيمة
                new_is_public = not curr_is_public
                # التحديث في قاعدة البيانات
                supabase.table("saved_quizzes").update({"is_public": new_is_public}).eq("id", quiz_id).execute()
                
                status_text = "عام 🌐" if new_is_public else "داخلي 📍"
                await c.answer(f"✅ أصبح النطاق: {status_text}")
            elif 'toggle_hint_' in c.data:
                res = supabase.table("saved_quizzes").select("smart_hint").eq("id", quiz_id).single().execute()
                new_h = not res.data.get('smart_hint', False)
                supabase.table("saved_quizzes").update({"smart_hint": new_h}).eq("id", quiz_id).execute()
            elif 'toggle_speed_' in c.data:
                res = supabase.table("saved_quizzes").select("mode").eq("id", quiz_id).single().execute()
                new_m = "الوقت الكامل ⏳" if res.data.get('mode') == "السرعة ⚡" else "السرعة ⚡"
                supabase.table("saved_quizzes").update({"mode": new_m}).eq("id", quiz_id).execute()
            elif 'set_c_' in c.data:
                count = int(data_parts[3])
                supabase.table("saved_quizzes").update({"questions_count": count}).eq("id", quiz_id).execute()
            
            await c.answer("تم التحديث ✅")
            # إعادة توجيه ذاتي لتحديث الواجهة
            c.data = f"quiz_settings_{quiz_id}_{user_id}"
            return await handle_secure_actions(c, state)
        
        # 4️⃣ تغيير الوقت
        elif c.data.startswith('edit_time_'):
            quiz_id = data_parts[2]
            res = supabase.table("saved_quizzes").select("time_limit").eq("id", quiz_id).single().execute()
            curr = res.data.get('time_limit', 15)
            next_t = 20 if curr == 15 else (30 if curr == 20 else (45 if curr == 30 else 15))
            supabase.table("saved_quizzes").update({"time_limit": next_t}).eq("id", quiz_id).execute()
            c.data = f"quiz_settings_{quiz_id}_{user_id}"
            return await handle_secure_actions(c, state)

        # 5️⃣ الحفظ وتشغيل وحذف وإغلاق (النسخة المصلحة 2026 🚀)
        elif c.data.startswith('save_quiz_process_'):
            # 🛠️ تصحيح الاندكس من 2 إلى 3 لسحب الرقم الحقيقي
            quiz_id = data_parts[3] 
            await c.answer("✅ تم الحفظ بنجاح!", show_alert=True)
            c.data = f"manage_quiz_{quiz_id}_{user_id}"
            return await handle_secure_actions(c, state)

        elif c.data.startswith('close_'):
            try: return await c.message.delete()
            except: pass

        elif c.data.startswith('confirm_del_'):
            quiz_id = data_parts[2]
            kb = InlineKeyboardMarkup().add(
                InlineKeyboardButton("✅ نعم، احذف", callback_data=f"final_del_{quiz_id}_{user_id}"),
                InlineKeyboardButton("🚫 تراجع", callback_data=f"manage_quiz_{quiz_id}_{user_id}")
            )
            return await c.message.edit_text("⚠️ **هل أنت متأكد من الحذف؟**", reply_markup=kb)

        elif c.data.startswith('final_del_'):
            quiz_id = data_parts[2]
            supabase.table("saved_quizzes").delete().eq("id", quiz_id).execute()
            await c.answer("🗑️ تم الحذف", show_alert=True)
            # إعادة عرض القائمة بعد الحذف
            c.data = f"show_quizzes_{user_id}"
            return await handle_secure_actions(c, state)

       # --- [ نظام تشغيل المسابقات: عامة أو خاصة ] ---
        elif c.data.startswith('run_'):
            quiz_id = data_parts[1]
            user_id = data_parts[2]
            
            # 1. جلب بيانات المسابقة لمرة واحدة فقط
            res = supabase.table("saved_quizzes").select("*").eq("id", quiz_id).single().execute()
            q_data = res.data
            
            if not q_data: 
                return await c.answer("❌ المسابقة غير موجودة!")

            # 2. التحقق: هل هي إذاعة عامة (بث) أم تشغيل خاص؟
            if q_data.get('is_public'):
                # 🌐 مسار الإذاعة العامة
                await c.answer("🌐 جاري إطلاق الإذاعة العامة للمجموعات...")
                await start_broadcast_process(c, quiz_id, user_id)
            else:
                # 📍 مسار التشغيل الخاص (في نفس الشات)
                await c.answer("🚀 انطلقنا!")
                
                # اختيار المحرك المناسب بناءً على نوع المسابقة
                if q_data.get('is_bot_quiz'):
                    # استدعاء المحرك الشغال (نظام البوت)
                    asyncio.create_task(engine_bot_questions(c.message.chat.id, q_data, c.from_user.first_name))
                else:
                    # استدعاء محرك أسئلة الأعضاء
                    asyncio.create_task(engine_user_questions(c.message.chat.id, q_data, c.from_user.first_name))
            
            return # إنهاء المعالج بنجاح

    except Exception as e:
        # 🛡️ معالج الأخطاء العام للوحة
        logging.error(f"Handle Secure Actions Error: {e}")
        try: 
            await c.answer("🚨 خطأ في اللوحة أو البيانات", show_alert=True)
        except: 
            pass
# ==========================================
# 3. نظام المحركات المنفصلة (ياسر المطور - نسخة عشوائية)
# ==========================================

# --- [1. محرك أسئلة البوت] ---
async def engine_bot_questions(chat_id, quiz_data, owner_name):
    try:
        raw_cats = quiz_data.get('cats', [])
        if isinstance(raw_cats, str):
            try:
                cat_ids_list = json.loads(raw_cats)
            except:
                cat_ids_list = raw_cats.replace('[','').replace(']','').replace('"','').split(',')
        else:
            cat_ids_list = raw_cats

        cat_ids = [int(c) for c in cat_ids_list if str(c).strip().isdigit()]
        if not cat_ids:
            return await bot.send_message(chat_id, "⚠️ خطأ: لم يتم العثور على أقسام صالحة.")

        # جلب الأسئلة وخلطها عشوائياً
        res = supabase.table("bot_questions").select("*").in_("bot_category_id", cat_ids).execute()
        if not res.data:
            return await bot.send_message(chat_id, "⚠️ لم أجد أسئلة في جدول البوت.")

        questions_pool = res.data
        random.shuffle(questions_pool)
        count = int(quiz_data.get('questions_count', 10))
        selected_questions = questions_pool[:count]

        await run_universal_logic(chat_id, selected_questions, quiz_data, owner_name, "bot")
    except Exception as e:
        logging.error(f"Bot Engine Error: {e}")

# --- [2. محرك أسئلة الأعضاء] ---
async def engine_user_questions(chat_id, quiz_data, owner_name):
    try:
        raw_cats = quiz_data.get('cats', [])
        if isinstance(raw_cats, str):
            try:
                cat_ids_list = json.loads(raw_cats)
            except:
                cat_ids_list = raw_cats.replace('[','').replace(']','').replace('"','').split(',')
        else:
            cat_ids_list = raw_cats

        cat_ids = [int(c) for c in cat_ids_list if str(c).strip().isdigit()]
        if not cat_ids:
            return await bot.send_message(chat_id, "⚠️ خطأ في أقسام الأعضاء.")

        # جلب الأسئلة وخلطها عشوائياً
        res = supabase.table("questions").select("*, categories(name)").in_("category_id", cat_ids).execute()
        if not res.data:
            return await bot.send_message(chat_id, "⚠️ لم أجد أسئلة في أقسام الأعضاء.")

        questions_pool = res.data
        random.shuffle(questions_pool)
        count = int(quiz_data.get('questions_count', 10))
        selected_questions = questions_pool[:count]

        await run_universal_logic(chat_id, selected_questions, quiz_data, owner_name, "user")
    except Exception as e:
        logging.error(f"User Engine Error: {e}")


# --- [ محرك التلميحات الملكي المطور: 3 قلوب + ذاكرة سحابية ✨ ] ---

current_key_index = 0 # متغير تدوير المفاتيح

async def generate_smart_hint(answer_text):
    """
    توليد وصف لغزي ذكي مع تدوير 3 مفاتيح وحفظ النتيجة في Supabase.
    """
    global current_key_index
    answer_text = str(answer_text).strip()
    
    # 1. البحث في الذاكرة السحابية (Supabase) لتوفير المفاتيح
    try:
        cached_res = supabase.table("hints").select("hint").eq("word", answer_text).execute()
        if cached_res.data:
            return cached_res.data[0]['hint'] # إذا وجده، يرسله فوراً بالتنسيق المخزن
    except Exception as e:
        logging.error(f"Supabase Cache Check Error: {e}")

    # 2. إذا لم يوجد في الذاكرة، نبدأ رحلة البحث في "القلوب الثلاثة"
    url = "https://api.groq.com/openai/v1/chat/completions"
    
    for _ in range(len(GROQ_KEYS)):
        active_key = GROQ_KEYS[current_key_index].strip()
        headers = {
            "Authorization": f"Bearer {active_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "أنت خبير ألغاز محترف. أعطِ وصفاً غامضاً وذكياً جداً يصف المعنى دون ذكر الكلمة بالعربية."},
                {"role": "user", "content": f"الإجابة هي: ({answer_text}). أعطني وصفاً غامضاً عربي قصير جداً ومسلي."}
            ],
            "temperature": 0.6
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=12.0)
                
                if response.status_code == 200:
                    res_data = response.json()
                    ai_hint = res_data['choices'][0]['message']['content'].strip()
                    
                    # ✨ صياغة القالب الملكي الفاخر
                    final_styled_hint = (
                        f"💎 <b>〔 تـلـمـيـح ذكـي  〕</b> 💎\n"
                        f"❃╔════════════════╗❃\n\n"
                        f"   <b>📜 الوصف:</b>\n"
                        f"   <i>« {ai_hint} »</i>\n\n"
                        f"❃╚════════════════╝❃\n"
                        f"<b>⏳ يتبقى القليل.. أثبت وجودك!</b>"
                    )
                    
                    # حفظ النتيجة في سوبابيس للمستقبل
                    try:
                        supabase.table("hints").insert({"word": answer_text, "hint": final_styled_hint}).execute()
                    except: pass
                    
                    return final_styled_hint
                
                # إذا تجاوز الحد (Rate Limit)، ننتقل للقلب التالي
                elif response.status_code == 429:
                    current_key_index = (current_key_index + 1) % len(GROQ_KEYS)
                    continue
        except:
            current_key_index = (current_key_index + 1) % len(GROQ_KEYS)
            continue

    # 3. حالة الطوارئ (إذا فشلت كل المفاتيح ولم نجد الكلمة في الذاكرة)
    return (
        f"💡 <b>〔 مـسـاعـدة إضـافـيـة 〕</b>\n"
        f"📂 ❃━━━━━━━━━━━━━━❃ 📂\n"
        f"<b>• الحرف الأول:</b> ( {answer_text[0]} )\n"
        f"<b>• طول الكلمة:</b> {len(answer_text)} حروف\n"
        f"❃━━━━━━━━━━━━━━❃"
    )

# دالة حذف الرسائل المساعدة (تم إصلاحها لتعمل بسلاسة ✅)
async def delete_after(message, delay):
    await asyncio.sleep(delay)
    try: 
        await message.delete()
    except Exception: 
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
        
        # 4. محرك الوقت الذكي ومراقبة التلميح الملكي ✨
        start_time = time.time()
        t_limit = int(quiz_data.get('time_limit', 15))
        h_msg = None 
        
        while time.time() - start_time < t_limit:
            if not active_quizzes.get(chat_id) or not active_quizzes[chat_id]['active']:
                break
            
            if quiz_data.get('smart_hint') and not active_quizzes[chat_id]['hint_sent']:
                if (time.time() - start_time) >= (t_limit / 2):
                    try:
                        hint_text = await generate_smart_hint(ans)
                        h_msg = await bot.send_message(chat_id, hint_text, parse_mode="HTML")
                        active_quizzes[chat_id]['hint_sent'] = True
                    except Exception as e:
                        logging.error(f"⚠️ خطأ في التلميح: {e}")

            await asyncio.sleep(0.5)

        if h_msg:
            asyncio.create_task(delete_after(h_msg, 0))

        # 5. إنهاء السؤال وحساب النقاط
        if chat_id in active_quizzes:
            active_quizzes[chat_id]['active'] = False
            for w in active_quizzes[chat_id]['winners']:
                uid = w['id']
                if uid not in overall_scores: 
                    overall_scores[uid] = {"name": w['name'], "points": 0}
                overall_scores[uid]['points'] += 10
        
            # 6. عرض لوحة المبدعين اللحظية
            await send_cccreative_results(chat_id, ans, active_quizzes[chat_id]['winners'], overall_scores)
        
        # --- [ ⏱️ محرك العداد التنازلي المطور لتجنب الـ Flood ] ---
        if i < len(questions) - 1:
            icons = ["🔴", "🟠", "🟡", "🟢", "🔵"]
            try:
                countdown_msg = await bot.send_message(chat_id, f"⌛ استعدوا.. السؤال التالي يبدأ بعد 5 ثواني...")
                
                # سنقوم بالتحديث كل ثانية ونصف أو ثانيتين لتقليل الضغط
                for count in range(4, 0, -2): # تقليل عدد التحديثات (تحديث كل ثانيتين)
                    await asyncio.sleep(2)
                    icon = icons[count] if count < len(icons) else "⚪"
                    try:
                        await countdown_msg.edit_text(f"{icon} استعدوا.. السؤال التالي يبدأ بعد <b>{count}</b> ثواني...")
                    except Exception as e:
                        logging.warning(f"Flood avoidance: {e}")
                        break # توقف عن التحديث إذا ضغط التليجرام
                
                await asyncio.sleep(1.5)
                await countdown_msg.delete()
            except Exception as e:
                logging.error(f"Countdown Error: {e}")
        else:
            await asyncio.sleep(2)
    # 7. إعلان لوحة الشرف النهائية
    await send_final_results(chat_id, overall_scores, len(questions))
# ==========================================

# 1️⃣ صمام الأمان العالمي (خارج الدالة لمنع الطلقة المزدوجة)
active_broadcasts = set()

# 2️⃣ دالة العداد التنازلي المصححة لتجنب أي NameError
async def run_countdown(chat_id):
    try:
        msg = await bot.send_message(chat_id, "⏳ استعدوا.. السؤال القادم بعد: 3")
        for i in range(2, 0, -1):
            await asyncio.sleep(1)
            try: await bot.edit_message_text(f"⏳ استعدوا.. السؤال القادم بعد: {i}", chat_id, msg.message_id)
            except: pass
        await asyncio.sleep(1)
        try: await bot.delete_message(chat_id, msg.message_id)
        except: pass
    except: pass

# 3️⃣ المحرك الرئيسي الموحد
async def engine_global_broadcast(chat_ids, quiz_data, owner_name):
    # --- [ أ ] تصفية المجموعات ومنع التكرار الجذري ---
    input_ids = chat_ids if isinstance(chat_ids, list) else [chat_ids]
    # 🔥 الحل القاطع: نعتمد فقط على القائمة القادمة من "المشاركين" لمنع دبلجة الإرسال
    all_chats = list(set(input_ids))

    if not all_chats: return

    # --- [ ب ] منع الطلقة المزدوجة (القفل العالمي) ---
    for cid in all_chats:
        if cid in active_broadcasts:
            logging.warning(f"⚠️ مسابقة نشطة بالفعل في {cid}")
            return
    for cid in all_chats: active_broadcasts.add(cid)

    try:
        # --- [ ج ] جلب وتجهيز الأسئلة (إصلاح خطأ selected_questions) ---
        raw_cats = quiz_data.get('cats', [])
        if isinstance(raw_cats, str):
            try: cat_ids_list = json.loads(raw_cats)
            except: cat_ids_list = raw_cats.replace('[','').replace(']','').replace('"','').split(',')
        else: cat_ids_list = raw_cats
        cat_ids = [int(c) for c in cat_ids_list if str(c).strip().isdigit()]

        is_bot = quiz_data.get("is_bot_quiz", False)
        table = "bot_questions" if is_bot else "questions"
        cat_col = "bot_category_id" if is_bot else "category_id"
        
        # 🛰️ جلب البيانات من سوبابيس
        res_q = supabase.table(table).select("*, categories(name)" if not is_bot else "*").in_(cat_col, cat_ids).execute()
        
        if not res_q.data:
            logging.error(f"⚠️ لم يتم العثور على أسئلة في الأقسام المختارة")
            return

        pool = res_q.data
        random.shuffle(pool)
        count = int(quiz_data.get('questions_count', 10))
        
        # ✅ التعريف الصحيح للمتغير لحل مشكلة الـ NameError
        selected_questions = pool[:count] 

        total_q = len(selected_questions)
        group_scores = {cid: {} for cid in all_chats}
        messages_to_delete = {cid: [] for cid in all_chats}

        # --- [ د ] دورة البث الموحدة ---
        for i, q in enumerate(selected_questions):
            ans = str(q.get('correct_answer') or q.get('answer_text') or "").strip()
            cat_name = q.get('category') or "عام"

            for cid in all_chats:
                global_active_quizzes[cid] = {
                    "active": True, "ans": ans, "winners": [], 
                    "mode": quiz_data.get('mode', 'السرعة ⚡'), "start_time": time.time()
                }

            # 4️⃣ بث السؤال (تصحيح النطاق إلى إذاعة عالمية 🌐)
send_tasks = [
    send_quiz_question(
        cid, 
        q, 
        i+1, 
        total_q, 
        {
            'owner_name': owner_name, 
            'mode': quiz_data.get('mode', 'السرعة ⚡'), 
            'time_limit': quiz_data.get('time_limit', 15), 
            'cat_name': cat_name,
            'source': "إذاعة عالمية 🌐",
            'is_public': True   # ✅ هذا هو السطر المهم
        }
    ) 
    for cid in all_chats
]

q_msgs = await asyncio.gather(*send_tasks, return_exceptions=True)

for idx, m in enumerate(q_msgs):
    if isinstance(m, types.Message): 
        messages_to_delete[all_chats[idx]].append(m.message_id)

            # 5️⃣ انتظار الإجابة
            t_limit = int(quiz_data.get('time_limit', 15))
            start_wait = time.time()
            while time.time() - start_wait < t_limit:
                if all(not global_active_quizzes.get(c, {}).get('active', False) for c in all_chats): break
                await asyncio.sleep(0.4)

            # 6️⃣ إغلاق النشاط وتحديث النقاط (المنطق المصفى) ✅
            res_tasks = []
            for cid in all_chats:
                # 1. إغلاق السؤال في هذا الجروب
                if cid in global_active_quizzes:
                    global_active_quizzes[cid]['active'] = False
                
                # 2. جلب فائزين هذا الجروب فقط في هذا السؤال
                current_winners = global_active_quizzes.get(cid, {}).get('winners', [])
                
                # 3. تحديث قاموس النقاط العالمي (group_scores)
                # نحدث فقط من فازوا في هذا السؤال ولم تضف نقاطهم بعد
                for w in current_winners:
                    uid = w['id']
                    if uid not in group_scores[cid]:
                        group_scores[cid][uid] = {"name": w['name'], "points": 0}
                    
                    # إضافة النقاط (تأكد أن الرادار لا يضيف نقاط، المحرك فقط يضيفها هنا)
                    group_scores[cid][uid]['points'] += 10

                # 4. تجهيز مهمة إرسال القالب (المحرك فقط هو من يرسل)
                res_tasks.append(send_creative_results(cid, ans, current_winners, group_scores[cid]))
            
            # إرسال النتائج لكل المجموعات دفعة واحدة
            await asyncio.gather(*res_tasks, return_exceptions=True)

            # 7️⃣ العداد التنازلي وتصفير الفائزين للسؤال القادم
            if i < total_q - 1:
                # تصفير قائمة الفائزين في الرادار استعداداً للسؤال الجديد
                for cid in all_chats:
                    if cid in global_active_quizzes:
                        global_active_quizzes[cid]['winners'] = []
                
                count_tasks = [run_countdown(cid) for cid in all_chats]
                await asyncio.gather(*count_tasks, return_exceptions=True)
            else:
                await asyncio.sleep(2)

        # 8️⃣ النتائج النهائية والتنظيف
        for cid in all_chats:
            try: await send_final_results(cid, group_scores.get(cid, {}), total_q)
            except: pass
            
            for mid in messages_to_delete.get(cid, []):
                try: await bot.delete_message(cid, mid)
                except: pass

    except Exception as e:
        logging.error(f"🚨 Global Engine Fatal Error: {e}")
    finally:
        # 🔓 فتح القفل للسماح ببدء إذاعة جديدة لاحقاً
        for cid in all_chats: active_broadcasts.discard(cid)
            
# ======================================================
# --- [ 🏁 المرحلة الأخيرة: إعلان النتائج وترحيل البيانات ] ---
# ======================================================
async def sync_points_to_db(group_scores, is_pub):
    """
    الدالة 7 الملحقة: ترحيل النقاط النهائية من الذاكرة إلى حقول JSONB
    """
    for cid, scores in group_scores.items():
        if not scores: continue
        
        try:
            # 1. جلب البيانات الحالية للمجموعة (عشان ما نمسح النقاط القديمة)
            res = supabase.table("groups_hub").select("group_members_points, global_users_points").eq("group_id", cid).single().execute()
            
            if res.data:
                g_points = res.data.get('group_members_points') or {}
                glob_points = res.data.get('global_users_points') or {}

                for uid, info in scores.items():
                    uid_str = str(uid)
                    earned_points = info['points']
                    u_name = info['name']

                    # أ. تحديث نقاط المجموعة الداخلية
                    if uid_str in g_points:
                        g_points[uid_str]['points'] += earned_points
                    else:
                        g_points[uid_str] = {"name": u_name, "points": earned_points}

                    # ب. تحديث النقاط العالمية (لو كانت الإذاعة عامة)
                    if is_pub:
                        if uid_str in glob_points:
                            glob_points[uid_str]['points'] += earned_points
                        else:
                            glob_points[uid_str] = {"name": u_name, "points": earned_points}

                # 2. رفع التحديث النهائي لسوبابيس
                supabase.table("groups_hub").update({
                    "group_members_points": g_points,
                    "global_users_points": glob_points,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("group_id", cid).execute()

        except Exception as e:
            logging.error(f"❌ خطأ ترحيل نقاط المجموعة {cid}: {e}")
# =======================================
# 4. نظام رصد الإجابات الذكي (ياسر المطور)
# ==========================================
def is_answer_correct(user_msg, correct_ans):
    if not user_msg or not correct_ans: return False

    def clean_logic(text):
        # 1. تنظيف أساسي (حذف المسافات وتحويل لصغير)
        text = text.strip().lower()
        # 2. توحيد الألفات (أإآ -> ا)
        text = re.sub(r'[أإآ]', 'ا', text)
        # 3. توحيد التاء المربوطة (ة -> ه)
        text = re.sub(r'ة', 'ه', text)
        # 4. توحيد الياء (ى -> ي)
        text = re.sub(r'ى', 'ي', text)
        # 5. معالجة الواو الزائدة (مثل عمرو -> عمر)
        if text.endswith('و') and len(text) > 3:
            text = text[:-1]
        # 6. حذف المسافات الزائدة بين الكلمات
        text = ' '.join(text.split())
        return text

    user_clean = clean_logic(user_msg)
    correct_clean = clean_logic(correct_ans)

    # 1. فحص التطابق التام
    if user_clean == correct_clean:
        return True

    # 2. فحص الاحتواء (كلمة من إجابة طويلة)
    if len(user_clean) > 3 and (user_clean in correct_clean or correct_clean in user_clean):
        return True

    # 3. فحص نسبة التشابه (تجاوز الأخطاء الإملائية 80%)
    similarity = difflib.SequenceMatcher(None, user_clean, correct_clean).ratio()
    if similarity >= 0.80:
        return True

    return False

# ==========================================
# 🎯 رادار الإجابات الموحد (يمنع التكرار نهائياً)
# ==========================================
@dp.message_handler(lambda m: not m.text.startswith('/'))
async def unified_answer_checker(m: types.Message):
    cid = m.chat.id
    uid = m.from_user.id
    user_text = m.text.strip()

    # 1️⃣ أولاً: التحقق من "الإذاعة العالمية" (الأولوية القصوى)
    quiz_g = global_active_quizzes.get(cid)
    if quiz_g and quiz_g.get('active'):
        correct_ans = str(quiz_g['ans']).strip()
        
        if is_answer_correct(user_text, correct_ans):
            # التأكد أن المستخدم لم يفز مسبقاً في هذا السؤال
            if not any(w['id'] == uid for w in quiz_g['winners']):
                elapsed = round(time.time() - quiz_g['start_time'], 2)
                
                # تسجيل الفوز في الإذاعة
                quiz_g['winners'].append({
                    "name": m.from_user.first_name, 
                    "id": uid,
                    "time": elapsed
                })
                
                # إذا كان وضع السرعة، نغلق السؤال عالمياً فوراً
                if quiz_g.get('mode') == 'السرعة ⚡':
                    participants = quiz_g.get('participants', [cid])
                    for p_cid in participants:
                        if p_cid in global_active_quizzes:
                            global_active_quizzes[p_cid]['active'] = False
                    
                    await m.reply(f"🚀 <b>إجابة عالمية!</b>\nأنت الأسرع في الإذاعة خلال {elapsed} ثانية!", parse_mode="HTML")
                else:
                    await m.reply(f"✅ <b>إجابة صحيحة في التحدي العالمي!</b>", parse_mode="HTML")
                
                return # ✋ توقف هنا! لا تذهب للفحص الخاص (هذا ما يمنع التكرار)

    # 2️⃣ ثانياً: التحقق من "المسابقات الخاصة" (إذا لم يكن هناك إذاعة)
    elif cid in active_quizzes and active_quizzes[cid]['active']:
        quiz_p = active_quizzes[cid]
        correct_ans = str(quiz_p['ans']).strip()
        
        if is_answer_correct(user_text, correct_ans):
            if not any(w['id'] == uid for w in quiz_p['winners']):
                quiz_p['winners'].append({
                    "name": m.from_user.first_name, 
                    "id": uid
                })
                
                if quiz_p.get('mode') == 'السرعة ⚡':
                    quiz_p['active'] = False
                
                # هنا لا تضع m.reply إذا كان المحرك هو من يرسل القالب لاحقاً
                return
# ==========================================
# ==========================================
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

# --- 1. معالج الأمر الرئيسي /admin (المعدل للنظام الموحد) ---
@dp.message_handler(commands=['admin'], user_id=ADMIN_ID)
async def admin_dashboard(message: types.Message):
    try:
        # جلب البيانات من الجدول الموحد groups_hub
        res = supabase.table("groups_hub").select("*").execute()
        
        # تصنيف المجموعات بناءً على حالتها في الجدول الجديد
        active = len([g for g in res.data if g['status'] == 'active'])
        blocked = len([g for g in res.data if g['status'] == 'blocked'])
        total_global_points = sum([g.get('total_group_score', 0) for g in res.data])

        txt = (
            "👑 <b>غرفة العمليات الرئيسية</b>\n"
            "❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
            f"✅ المجموعات النشطة: <b>{active}</b>\n"
            f"🚫 المجموعات المحظورة: <b>{blocked}</b>\n"
            f"🏆 إجمالي نقاط الهب: <b>{total_global_points}</b>\n"
            "❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
            "👇 اختر قسماً لإدارته:"
        )
        
        await message.answer(txt, reply_markup=get_main_admin_kb(), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Admin Panel Error: {e}")
        await message.answer("❌ خطأ في الاتصال بقاعدة البيانات الموحدة.")

# --- 2. معالج العودة للقائمة الرئيسية (المعدل) ---
@dp.callback_query_handler(lambda c: c.data == "admin_back", user_id=ADMIN_ID, state="*")
async def admin_back_to_main(c: types.CallbackQuery, state: FSMContext):
    await state.finish()
    try:
        # تحديث الإحصائيات عند العودة
        res = supabase.table("groups_hub").select("*").execute()
        active = len([g for g in res.data if g['status'] == 'active'])
        blocked = len([g for g in res.data if g['status'] == 'blocked'])
        
        txt = (
            "👑 <b>غرفة العمليات الرئيسية</b>\n"
            "❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
            f"✅ المجموعات النشطة: <b>{active}</b>\n"
            f"🚫 المجموعات المحظورة: <b>{blocked}</b>\n"
            "❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃"
        )
        await c.message.edit_text(txt, reply_markup=get_main_admin_kb(), parse_mode="HTML")
    except Exception as e:
        await c.answer("⚠️ حدث خطأ أثناء تحديث البيانات الموحدة")

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
# --- [ إدارة أسئلة البوت الرسمية - نسخة ياسر الملك المحدثة 2026 ] ---

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
            InlineKeyboardButton("📥 رفع (Bulk)", callback_data="botq_upload"),
            InlineKeyboardButton("📂 عرض المجلدات", callback_data="botq_viewfolders"),
            InlineKeyboardButton("⬅️ عودة للرئيسية", callback_data="admin_back")
        )
        await c.message.edit_text("🛠️ <b>إدارة الأسئلة (نظام المجلدات)</b>", reply_markup=kb, parse_mode="HTML")

    elif action == "upload":
        await c.message.edit_text(
            "📥 <b>وضع الرفع المطور:</b>\n\n"
            "أرسل الأسئلة بالصيغة التالية:\n"
            "<code>سؤال+إجابة+القسم+المجلد</code>\n\n"
            "أرسل <b>خروج</b> للعودة.", 
            parse_mode="HTML"
        )
        await state.set_state("wait_for_bulk_questions")

    # --- المستوى الأول: عرض المجلدات ---
    elif action == "viewfolders":
        res = supabase.table("folders").select("*").execute()
        if not res.data:
            return await c.answer("⚠️ لا توجد مجلدات مسجلة.", show_alert=True)
        
        kb = InlineKeyboardMarkup(row_width=2)
        for folder in res.data:
            kb.insert(InlineKeyboardButton(f"📁 {folder['name']}", callback_data=f"botq_showcats_{folder['id']}"))
        
        kb.add(InlineKeyboardButton("⬅️ عودة للرئيسية", callback_data="botq_main"))
        await c.message.edit_text("📂 <b>المجلدات الرئيسية:</b>\nاختر مجلداً لعرض أقسامه:", reply_markup=kb, parse_mode="HTML")

    # --- المستوى الثاني: عرض الأقسام داخل المجلد ---
    elif action == "showcats":
        folder_id = data_parts[2]
        res = supabase.table("bot_categories").select("*").eq("folder_id", folder_id).execute()
        
        kb = InlineKeyboardMarkup(row_width=2)
        if res.data:
            for cat in res.data:
                kb.insert(InlineKeyboardButton(f"🏷️ {cat['name']}", callback_data=f"botq_mng_{cat['id']}"))
        else:
            kb.add(InlineKeyboardButton("🚫 لا توجد أقسام هنا", callback_data="none"))
            
        kb.add(InlineKeyboardButton("🔙 عودة للمجلدات", callback_data="botq_viewfolders"))
        await c.message.edit_text("🗂️ <b>الأقسام المتوفرة في هذا المجلد:</b>", reply_markup=kb, parse_mode="HTML")

    # --- المستوى الثالث: إدارة القسم المختار ---
    elif action == "mng":
        cat_id = data_parts[2]
        res = supabase.table("bot_questions").select("id", count="exact").eq("bot_category_id", int(cat_id)).execute()
        q_count = res.count if res.count is not None else 0
        
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton(f"🗑️ حذف جميع الأسئلة ({q_count})", callback_data=f"botq_confdel_{cat_id}"),
            InlineKeyboardButton("🔙 عودة للأقسام", callback_data="botq_viewfolders")
        )
        await c.message.edit_text(
            f"📊 <b>إدارة القسم (ID: {cat_id})</b>\n\n"
            f"عدد الأسئلة المتوفرة: <b>{q_count}</b>\n\n"
            "⚠️ تنبيه: خيار الحذف سيقوم بمسح كافة الأسئلة التابعة لهذا القسم فقط.", 
            reply_markup=kb, parse_mode="HTML"
        )

    # --- نظام الحماية: تأكيد الحذف (نعم / لا) ---
    elif action == "confdel":
        cat_id = data_parts[2]
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ نعم، احذف", callback_data=f"botq_realdel_{cat_id}"),
            InlineKeyboardButton("❌ تراجع (إلغاء)", callback_data=f"botq_mng_{cat_id}")
        )
        await c.message.edit_text(
            "⚠️ <b>تأكيد الحذف النهائي!</b>\n\n"
            "هل أنت متأكد من مسح جميع أسئلة هذا القسم؟\n"
            "لا يمكن التراجع عن هذه العملية بعد التنفيذ.", 
            reply_markup=kb, parse_mode="HTML"
        )

    # تنفيذ الحذف الفعلي
    elif action == "realdel":
        cat_id = data_parts[2]
        try:
            supabase.table("bot_questions").delete().eq("bot_category_id", int(cat_id)).execute()
            await c.answer("✅ تم الحذف بنجاح", show_alert=True)
            await process_bot_questions_panel(c, state) # العودة للرئيسية
        except Exception as e:
            await c.answer(f"❌ خطأ: {e}", show_alert=True)

    await c.answer()

# --- معالج الرفع المطور (سؤال+إجابة+قسم+مجلد) ---
@dp.message_handler(state="wait_for_bulk_questions", user_id=ADMIN_ID)
async def process_bulk_questions(message: types.Message, state: FSMContext):
    if message.text.strip() in ["خروج", "إلغاء", "exit"]:
        await state.finish()
        await message.answer("✅ تم الخروج من وضع الرفع.")
        return

    lines = message.text.split('\n')
    success, error = 0, 0
    
    for line in lines:
        if '+' in line:
            parts = line.split('+')
            if len(parts) == 4:
                q_text, q_ans, cat_name, f_name = [p.strip() for p in parts]
                try:
                    # 1. فحص المجلد
                    f_res = supabase.table("folders").select("id").eq("name", f_name).execute()
                    f_id = f_res.data[0]['id'] if f_res.data else supabase.table("folders").insert({"name": f_name}).execute().data[0]['id']

                    # 2. فحص القسم وربطه
                    c_res = supabase.table("bot_categories").select("id").eq("name", cat_name).execute()
                    if c_res.data:
                        cat_id = c_res.data[0]['id']
                        supabase.table("bot_categories").update({"folder_id": f_id}).eq("id", cat_id).execute()
                    else:
                        cat_id = supabase.table("bot_categories").insert({"name": cat_name, "folder_id": f_id}).execute().data[0]['id']

                    # 3. رفع السؤال
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

# ==========================================
# إدارة مجموعات الهب (الموافقة، الحظر، التفعيل)
# ==========================================

# 1. قائمة المجموعات (عرض الحالات: انتظار ⏳، نشط ✅، محظور 🚫)
@dp.callback_query_handler(lambda c: c.data == "admin_view_pending", user_id=ADMIN_ID)
async def admin_manage_groups(c: types.CallbackQuery):
    try:
        res = supabase.table("groups_hub").select("group_id, group_name, status").execute()
        
        if not res.data:
            return await c.answer("📭 لا توجد مجموعات مسجلة بعد.", show_alert=True)
        
        txt = (
            "🛠️ <b>إدارة مجموعات الهب الموحد:</b>\n\n"
            "⏳ = بانتظار موافقتك (Pending)\n"
            "✅ = نشطة وشغالة (Active)\n"
            "🚫 = محظورة (Blocked)\n"
            "━━━━━━━━━━━━━━"
        )
        
        kb = InlineKeyboardMarkup(row_width=1)
        for g in res.data:
            # تحديد الإيقونة بناءً على الحالة
            status_icon = "⏳" if g['status'] == 'pending' else "✅" if g['status'] == 'active' else "🚫"
            
            kb.add(
                InlineKeyboardButton(
                    f"{status_icon} {g['group_name']}", 
                    callback_data=f"manage_grp_{g['group_id']}"
                )
            )
        
        kb.add(InlineKeyboardButton("⬅️ العودة للقائمة الرئيسية", callback_data="admin_back"))
        await c.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Error viewing groups: {e}")
        await c.answer("❌ خطأ في جلب البيانات")

# 2. لوحة التحكم بمجموعة محددة (إعطاء الصلاحية أو سحبها)
@dp.callback_query_handler(lambda c: c.data.startswith('manage_grp_'), user_id=ADMIN_ID)
async def group_control_options(c: types.CallbackQuery):
    g_id = c.data.split('_')[2]
    res = supabase.table("groups_hub").select("group_name, status").eq("group_id", g_id).execute()
    
    if not res.data: return await c.answer("⚠️ المجموعة غير موجودة.")
    
    g = res.data[0]
    status_map = {'active': 'نشطة ✅', 'pending': 'بانتظار الموافقة ⏳', 'blocked': 'محظورة 🚫'}
    
    txt = (
        f"📍 <b>إدارة المجموعة:</b> {g['group_name']}\n"
        f"🆔 الآيدي: <code>{g_id}</code>\n"
        f"⚙️ الحالة الحالية: <b>{status_map.get(g['status'], g['status'])}</b>\n"
        f"━━━━━━━━━━━━━━"
    )

    kb = InlineKeyboardMarkup(row_width=2)
    # تظهر الأزرار حسب الحاجة (تفعيل للمنتظر والمحظور، وحظر للنشط والمنتظر)
    if g['status'] != 'active':
        kb.add(InlineKeyboardButton("✅ موافقة وتفعيل", callback_data=f"auth_approve_{g_id}"))
    if g['status'] != 'blocked':
        kb.add(InlineKeyboardButton("🚫 رفض وحظر", callback_data=f"auth_block_{g_id}"))
    
    kb.add(InlineKeyboardButton("⬅️ رجوع للقائمة", callback_data="admin_view_pending"))
    await c.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

# ==========================================
# 7. معالج العمليات (Admin Callbacks)
# ==========================================
@dp.callback_query_handler(lambda c: c.data.startswith(('auth_approve_', 'auth_block_')), user_id=ADMIN_ID)
async def process_auth_callback(c: types.CallbackQuery):
    action = c.data.split('_')[1]
    target_id = c.data.split('_')[2]
    
    if action == "approve":
        supabase.table("groups_hub").update({"status": "active"}).eq("group_id", target_id).execute()
        await c.answer("تم تفعيل المجموعة بنجاح! ✅", show_alert=True)
        
        try:
            full_template = (
                f"🎉 <b>تم تفعيل القروب بنجاح!</b>\n"
                f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n"
                f"⚙️ الحالة: متصل (Active) ✅\n"
                f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃\n\n"
                f"🚀 <b>دليلك السريع للبدء:</b>\n"
                f"🔹 <b>تحكم :</b> لوحة الإعدادات ⚙️\n"
                f"🔹 <b>مسابقة :</b> لبدء التنافس 📝\n"
                f"🔹 <b>عني :</b> ملفك الشخصي ونقاطك 👤\n"
                f"🔹 <b>القروبات :</b> الترتيب العالمي 🌍\n\n"
                f"❃┅┅┅┄┄┄┈•❃•┈┄┄┄┅┅┅❃"
            )
            await bot.send_message(target_id, full_template, parse_mode="HTML")
        except: pass
    elif action == "block":
        supabase.table("groups_hub").update({"status": "blocked"}).eq("group_id", target_id).execute()
        await c.answer("تم الحظر بنجاح ❌", show_alert=True)
    
    await c.message.delete()
    
    # تحديث القائمة أمام المطور فوراً
    await admin_manage_groups(c)
# ==========================================
# --- قبول طلبات المشرفين اداعات
# ==========================================

@dp.callback_query_handler(lambda c: c.data.startswith('accept_q_'), state="*")
async def handle_accept_quiz(c: types.CallbackQuery):
    """معالج الانضمام المتوافق مع جدول quiz_participants الحقيقي"""
    try:
        # 1. تفكيك البيانات من الزر
        data_parts = c.data.split('_')
        # الترتيب المتوقع في الزر: accept_q_{quiz_id}_{owner_id}
        if len(data_parts) < 4:
            return await c.answer("⚠️ بيانات الانضمام ناقصة!")

        quiz_id = data_parts[2]
        owner_id = data_parts[3]
        chat_id = str(c.message.chat.id) # حولناه لنص لأن جدولك يتوقع text
        group_name = c.message.chat.title or "مجموعة"

        # 2. فحص هل المجموعة انضمت سابقاً
        check = supabase.table("quiz_participants")\
            .select("*")\
            .eq("quiz_id", quiz_id)\
            .eq("chat_id", chat_id)\
            .execute()

        if check.data and len(check.data) > 0:
            return await c.answer("✅ مجموعتكم مسجلة بالفعل في هذا البث!", show_alert=True)

        # 3. إدراج البيانات (بناءً على أعمدة جدولك: quiz_id, chat_id, owner_id)
        supabase.table("quiz_participants").insert({
            "quiz_id": int(quiz_id),
            "chat_id": chat_id,
            "owner_id": str(owner_id)
        }).execute()

        # 4. إشعار النجاح وتحديث الرسالة
        await c.answer(f"🌟 كفو! تم انضمام {group_name} للتحدي العالمي!", show_alert=True)
        
        try:
            current_text = c.message.text
            new_text = f"{current_text}\n\n✅ انضمت الآن: **{group_name}**"
            await c.message.edit_text(new_text, reply_markup=c.message.reply_markup, parse_mode="Markdown")
        except:
            pass

    except Exception as e:
        logging.error(f"Join Error: {e}")
        await c.answer(f"🚨 خطأ: {str(e)[:40]}", show_alert=True)
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
    
