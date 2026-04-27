import asyncio
import logging
import io
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- KONFIGURATSIYA ---
TOKEN = "8517141564:AAEpbrJvj6JrcKsobH-VT2RuD7wQXMo828c"  # <--- TOKEN YOZING
ADMIN_ID = 589746530              # <--- ID RAQAMINGIZNI YOZING

# --- MA'LUMOTLAR BAZASI (IN-MEMORY) ---
users_db = {}  
tests_db = {}  # Strukturasi: {"test_nomi": {"correct_answers": "...", "finished": False}}
active_test = None 

# --- STATE MASHINALARI ---
class UserStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_surname = State()
    waiting_for_answers = State()
    profile_edit_name = State()
    profile_edit_surname = State()

class AdminStates(StatesGroup):
    waiting_for_test_name = State()
    waiting_for_correct_answers = State()

# --- BOT VA DISPATCHER ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- YORDAMCHI FUNKSIYALAR ---

def check_if_user_registered(user_id):
    return user_id in users_db and "name" in users_db[user_id]

def get_main_user_keyboard():
    kb = [
        [KeyboardButton(text="📝 Testni boshlash")],
        [KeyboardButton(text="📊 Natijalarim")],
        [KeyboardButton(text="🏆 Top-10")],
        [KeyboardButton(text="👤 Profil")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_admin_keyboard():
    kb = [
        [KeyboardButton(text="🚀 Start"), KeyboardButton(text="➕ Yangi test")],
        [KeyboardButton(text="▶️ Testni boshlash"), KeyboardButton(text="🛑 Testni yakunlash")],
        [KeyboardButton(text="📂 Testlar"), KeyboardButton(text="🏆 Top-10")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def parse_answers(answer_string: str) -> dict:
    """ '1a2b3c' -> {'1': 'a', '2': 'b', '3': 'c'} """
    result = {}
    i = 0
    while i < len(answer_string):
        if answer_string[i].isdigit():
            num = ""
            while i < len(answer_string) and answer_string[i].isdigit():
                num += answer_string[i]
                i += 1
            if i < len(answer_string) and answer_string[i].isalpha():
                letter = answer_string[i].lower()
                result[num] = letter
                i += 1
        else:
            i += 1
    return result

def calculate_grade(percentage: float) -> str:
    if percentage >= 90: return "A+"
    elif percentage >= 80: return "A"
    elif percentage >= 70: return "B+"
    elif percentage >= 60: return "B"
    elif percentage >= 50: return "C+"
    else: return "C"

def calculate_results(correct_ans_str: str):
    correct_dict = parse_answers(correct_ans_str)
    total_questions = len(correct_dict)
    results = []

    for uid, data in users_db.items():
        if "answers" not in data or not data["answers"]:
            continue
        
        user_answers = data["answers"]
        correct_count = 0
        wrong_questions = []

        for q_num, correct_val in correct_dict.items():
            user_val = user_answers.get(q_num, "").lower()
            if user_val == correct_val:
                correct_count += 1
            else:
                wrong_questions.append(q_num)
        
        if total_questions > 0:
            percentage = (correct_count / total_questions) * 100
        else:
            percentage = 0
            
        grade = calculate_grade(percentage)
        
        results.append({
            "uid": uid,
            "name": f"{data.get('name', '')} {data.get('surname', '')}",
            "percentage": round(percentage, 2),
            "grade": grade,
            "wrong_questions": wrong_questions,
            "time": data.get("submission_time", datetime.datetime.now())
        })
    
    results.sort(key=lambda x: (-x['percentage'], x['time']))
    return results

# --- ADMIN HANDLERS ---

@dp.message(Command("start"), F.from_user.id == ADMIN_ID)
async def admin_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Admin paneliga xush kelibsiz!", reply_markup=get_admin_keyboard())

@dp.message(F.text == "🚀 Start", F.from_user.id == ADMIN_ID)
async def admin_start_btn(message: types.Message):
    await message.answer("Bot ishga tushirildi.", reply_markup=get_admin_keyboard())

@dp.message(F.text == "➕ Yangi test", F.from_user.id == ADMIN_ID)
async def new_test_start(message: types.Message, state: FSMContext):
    await message.answer("Yangi test nomi kiriting:")
    await state.set_state(AdminStates.waiting_for_test_name)

@dp.message(AdminStates.waiting_for_test_name, F.from_user.id == ADMIN_ID)
async def get_test_name(message: types.Message, state: FSMContext):
    test_name = message.text.strip()
    if not test_name:
        await message.answer("Nom bo'sh bo'lishi mumkin emas.")
        return
    await state.update_data(test_name=test_name)
    await message.answer(f"Test nomi: {test_name}. Endi to'g'ri javoblarni yuboring.\nFormat: 1a2b3c")
    await state.set_state(AdminStates.waiting_for_correct_answers)

@dp.message(AdminStates.waiting_for_correct_answers, F.from_user.id == ADMIN_ID)
async def get_correct_answers(message: types.Message, state: FSMContext):
    answers = message.text.strip()
    data = await state.get_data()
    test_name = data.get('test_name')
    
    # Testni saqlash va finished=False deb belgilash
    tests_db[test_name] = {
        "correct_answers": answers,
        "status": "ready",
        "finished": False 
    }
    await message.answer(f"✅ '{test_name}' testi saqlandi.", reply_markup=get_admin_keyboard())
    await state.clear()

@dp.message(F.text == "📂 Testlar", F.from_user.id == ADMIN_ID)
async def show_tests_list(message: types.Message):
    if not tests_db:
        await message.answer("Hozircha testlar yo'q.")
        return
    
    buttons = []
    for name in tests_db.keys():
        buttons.append([
            InlineKeyboardButton(text=f"▶️ {name} ni boshlash", callback_data=f"start_test_{name}"),
            InlineKeyboardButton(text=f"❌ {name} ni o'chirish", callback_data=f"delete_test_{name}")
        ])
        
    await message.answer("Mavjud testlar ro'yxati:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("start_test_"))
async def start_selected_test(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    test_name = callback.data.replace("start_test_", "")
    global active_test
    
    if test_name not in tests_db:
        await callback.message.answer("⚠️ Xatolik: Test bazada topilmadi.")
        await callback.answer()
        return

    active_test = test_name
    # Test boshlanganda finished=False ekanligiga ishonch hosil qilamiz
    tests_db[active_test]["finished"] = False
    
    await callback.message.answer(f"✅ '{test_name}' testi boshlandi!")
    
    count = 0
    for uid in users_db:
        try:
            await bot.send_message(uid, f"⚡️ YANGI TEST: {test_name}\n'Testni boshlash' tugmasini bosing.")
            count += 1
        except:
            pass
            
    if count == 0:
        await callback.message.answer("Eslatma: Hozircha ro'yxatdan o'tgan foydalanuvchilar yo'q.")
        
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_test_"))
async def delete_selected_test(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    test_name = callback.data.replace("delete_test_", "")
    
    if test_name in tests_db:
        del tests_db[test_name]
        global active_test
        if active_test == test_name:
            active_test = None
        await callback.message.answer(f"🗑 '{test_name}' testi o'chirildi.")
    else:
        await callback.message.answer("Test topilmadi.")
    await callback.answer()

@dp.message(F.text == "▶️ Testni boshlash", F.from_user.id == ADMIN_ID)
async def start_test_general(message: types.Message):
    global active_test
    if active_test and active_test not in tests_db:
        active_test = None

    if active_test:
        await message.answer(f"ℹ️ Hozirda '{active_test}' testi faol. Yakunlash uchun '🛑 Testni yakunlash' ni bosing.")
    else:
        await show_tests_list(message)

@dp.message(F.text == "🛑 Testni yakunlash", F.from_user.id == ADMIN_ID)
async def finish_test(message: types.Message):
    global active_test
    
    if not active_test:
        await message.answer("Faol test yo'q.")
        return
    
    if active_test not in tests_db:
        await message.answer(f"⚠️ Xatolik: '{active_test}' bazada yo'q. Holat tozalandi.")
        active_test = None
        return

    # MUHIM: Testni yakunlangan deb belgilaymiz
    tests_db[active_test]["finished"] = True

    correct_answers_str = tests_db[active_test]["correct_answers"]
    results = calculate_results(correct_answers_str)
    
    report_text = f"🏁 TEST YAKUNLANDI: {active_test}\n\n"
    report_text += f"Jami ishtirokchilar: {len(results)}\n\n"
    
    if not results:
        report_text += "Hech kim javob yubormadi."
        await message.answer(report_text)
        active_test = None
        return

    top_10 = results[:10]
    for i, res in enumerate(top_10, 1):
        report_text += f"{i}. {res['name']} - {res['percentage']}% ({res['grade']})\n"
        
    await message.answer(report_text)
    
    # TXT fayl
    file_content = f"TEST NATIJALARI: {active_test}\nSana: {datetime.datetime.now()}\n\n"
    file_content += f"{'№':<5} {'Ism Familiya':<30} {'Foiz':<10} {'Daraja':<10} {'Xato savollar'}\n"
    file_content += "-" * 80 + "\n"
    
    for i, res in enumerate(results, 1):
        wrongs = ", ".join(res['wrong_questions']) if res['wrong_questions'] else "Yo'q"
        file_content += f"{i:<5} {res['name']:<30} {res['percentage']:<10} {res['grade']:<10} {wrongs}\n"
        
    bio = io.BytesIO(file_content.encode('utf-8'))
    bio.name = f"results_{active_test}.txt"
    await bot.send_document(message.chat.id, bio)
    
    # Shaxsiy xabarlar
    sent_count = 0
    for res in results:
        try:
            user_rank = next((i for i, x in enumerate(results, 1) if x['uid'] == res['uid']), None)
            wrongs = ", ".join(res['wrong_questions']) if res['wrong_questions'] else "Yo'q"
            
            msg = (
                f"📊 Sizning natijangiz ({active_test}):\n"
                f"Ism: {res['name']}\n"
                f"Foiz: {res['percentage']}%\n"
                f"DARAJA: {res['grade']}\n"
                f"O'rin: {user_rank} / {len(results)}\n"
                f"Xato savollar: {wrongs}"
            )
            await bot.send_message(res['uid'], msg)
            sent_count += 1
        except Exception as e:
            print(f"User {res['uid']} ga yubora olmadi: {e}")
            
    active_test = None
    await message.answer(f"Natijalar {sent_count} ta foydalanuvchiga yuborildi.")


# --- FOYDALANUVCHI HANDLERS ---

@dp.message(Command("start"))
async def user_start(message: types.Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await admin_start(message, state)
        return

    await state.clear()

    if check_if_user_registered(message.from_user.id):
        await message.answer(f"Qaytib xush kelibsiz, {users_db[message.from_user.id]['name']}!", reply_markup=get_main_user_keyboard())
    else:
        await message.answer("Salom! Ro'yxatdan o'tish uchun ismingizni kiriting:")
        await state.set_state(UserStates.waiting_for_name)

@dp.message(UserStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID: return
    
    users_db.setdefault(message.from_user.id, {})
    users_db[message.from_user.id]['name'] = message.text.strip()
    await message.answer("Familiyangizni kiriting:")
    await state.set_state(UserStates.waiting_for_surname)

@dp.message(UserStates.waiting_for_surname)
async def process_surname(message: types.Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID: return
    
    users_db[message.from_user.id]['surname'] = message.text.strip()
    users_db[message.from_user.id]['registration_date'] = datetime.datetime.now()
    await message.answer("✅ Ro'yxatdan o'tdingiz!", reply_markup=get_main_user_keyboard())
    await state.clear()

@dp.message(F.text == "👤 Profil")
async def user_profile(message: types.Message):
    if not check_if_user_registered(message.from_user.id):
        await user_start(message, FSMContext(bot=bot, dispatcher=dp, storage=dp.storage))
        return
    
    data = users_db[message.from_user.id]
    kb = [
        [InlineKeyboardButton(text="✏️ Ismni o'zgartirish", callback_data="edit_name")],
        [InlineKeyboardButton(text="✏️ Familiyani o'zgartirish", callback_data="edit_surname")],
        [InlineKeyboardButton(text="🗑 Profilni o'chirish", callback_data="delete_profile")]
    ]
    text = f"👤 Profilingiz:\nIsm: {data['name']}\nFamiliya: {data['surname']}"
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "edit_name")
async def edit_name_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Yangi ismingizni kiriting:")
    await state.set_state(UserStates.profile_edit_name)
    await callback.answer()

@dp.message(UserStates.profile_edit_name)
async def save_new_name(message: types.Message, state: FSMContext):
    users_db[message.from_user.id]['name'] = message.text.strip()
    await message.answer("Ism o'zgartirildi.", reply_markup=get_main_user_keyboard())
    await state.clear()

@dp.callback_query(F.data == "edit_surname")
async def edit_surname_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Yangi familiyangizni kiriting:")
    await state.set_state(UserStates.profile_edit_surname)
    await callback.answer()

@dp.message(UserStates.profile_edit_surname)
async def save_new_surname(message: types.Message, state: FSMContext):
    users_db[message.from_user.id]['surname'] = message.text.strip()
    await message.answer("Familiya o'zgartirildi.", reply_markup=get_main_user_keyboard())
    await state.clear()

@dp.callback_query(F.data == "delete_profile")
async def delete_profile(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid in users_db:
        del users_db[uid]
        await callback.message.answer("Profil o'chirildi. /start ni bosing.")
    await callback.answer()

@dp.message(F.text == "📝 Testni boshlash")
async def start_test_user(message: types.Message, state: FSMContext):
    if not check_if_user_registered(message.from_user.id):
        await user_start(message, state)
        return
    
    global active_test
    
    if not active_test:
        await message.answer("Hozirda faol test yo'q.")
        return
        
    if active_test not in tests_db:
        active_test = None
        await message.answer("Test bekor qilindi yoki o'chirildi.")
        return

    if "answers" in users_db[message.from_user.id] and users_db[message.from_user.id].get("test_name") == active_test:
        await message.answer("Siz allaqachon bu testga javob yuborgansiz.")
        return

    await message.answer(f"📝 '{active_test}' testi boshlandi.\nJavoblarni yuboring (1a2b3c...):")
    await state.set_state(UserStates.waiting_for_answers)

@dp.message(UserStates.waiting_for_answers)
async def receive_answers(message: types.Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID: return
    
    answer_text = message.text.strip()
    parsed = parse_answers(answer_text)
    
    if not parsed:
        await message.answer("Noto'g'ri format. 1a2b3c ko'rinishida yuboring.")
        return
        
    users_db[message.from_user.id]['answers'] = parsed
    users_db[message.from_user.id]['test_name'] = active_test
    users_db[message.from_user.id]['submission_time'] = datetime.datetime.now()
    
    await message.answer("✅ Javob qabul qilindi. Natija admin yakunlagach chiqadi.", reply_markup=get_main_user_keyboard())
    await state.clear()

@dp.message(F.text == "📊 Natijalarim")
async def my_results(message: types.Message):
    user_id = message.from_user.id
    
    if not check_if_user_registered(user_id):
        await user_start(message, FSMContext(bot=bot, dispatcher=dp, storage=dp.storage))
        return
    
    if "answers" not in users_db[user_id]:
        await message.answer("Siz hali hech qanday testda qatnashmagansiz.")
        return
    
    user_data = users_db[user_id]
    test_name = user_data.get("test_name")
    
    if not test_name or test_name not in tests_db:
        await message.answer("Siz qatnashgan test hozirda mavjud emas.")
        return
    
    # --- ASOSIY O'ZGARISH: Test yakunlanganmi? ---
    if not tests_db[test_name].get("finished", False):
        await message.answer("⏳ Test hali davom etmoqda. Natijalar admin testni yakunlagach ko'rinadi.")
        return
    # ------------------------------------------
    
    correct_answers_str = tests_db[test_name]["correct_answers"]
    results = calculate_results(correct_answers_str)
    
    user_result = None
    for res in results:
        if res['uid'] == user_id:
            user_result = res
            break
    
    if not user_result:
        await message.answer("Sizning natijangiz topilmadi.")
        return
    
    user_rank = next((i for i, x in enumerate(results, 1) if x['uid'] == user_id), None)
    wrongs = ", ".join(user_result['wrong_questions']) if user_result['wrong_questions'] else "Yo'q"
    
    # To'g'ri javoblar sonini hisoblash
    total_q = len(parse_answers(correct_answers_str))
    correct_q = total_q - len(user_result['wrong_questions'])

    msg = (
        f"📊 Sizning natijangiz:\n\n"
        f"Test: {test_name}\n"
        f"Ism: {user_result['name']}\n"
        f"To'g'ri javoblar: {correct_q} ta\n"
        f"Foiz: {user_result['percentage']}%\n"
        f"DARAJA: {user_result['grade']}\n"
        f"O'rin: {user_rank} / {len(results)}\n"
        f"Xato savollar: {wrongs}"
    )
    
    await message.answer(msg)

@dp.message(F.text == "🏆 Top-10")
async def show_top_10(message: types.Message):
    if not active_test or active_test not in tests_db:
        await message.answer("Hozirda faol test yo'q.")
        return
        
    # Top-10 ni faqat test yakunlangandan keyin ko'rsatish maqsadga muvofiq
    if not tests_db[active_test].get("finished", False):
         await message.answer("⏳ Test hali davom etmoqda. Reyting admin testni yakunlagach ko'rinadi.")
         return

    correct_answers_str = tests_db[active_test]["correct_answers"]
    results = calculate_results(correct_answers_str)
    
    if not results:
        await message.answer("Hozircha natijalar yo'q.")
        return
        
    text = f"🏆 TOP-10 ({active_test}):\n\n"
    for i, res in enumerate(results[:10], 1):
        text += f"{i}. {res['name']} - {res['percentage']}% ({res['grade']})\n"
        
    await message.answer(text)

# --- DEBUG BUYRUG'I ---
@dp.message(Command("status"), F.from_user.id == ADMIN_ID)
async def debug_status(message: types.Message):
    global active_test
    text = f"📊 TIZIM HOLATI:\n\n"
    # SyntaxError oldini olish uchun qo'shtirnoqlarga e'tibor berildi
    text += f"🔹 Faol test: {active_test or 'Mavjud emas'}\n"
    text += f"🔹 Bazadagi testlar soni: {len(tests_db)}\n"
    text += f"🔹 Ro'yxatdan o'tganlar: {len(users_db)}\n\n"
    
    if tests_db:
        text += "Mavjud testlar:\n"
        for name, data in tests_db.items():
            status = "✅ FAOL" if name == active_test else "⏸️ Tayyor"
            fin_status = "Yakunlangan" if data.get("finished") else "Davom etmoqda"
            text += f"  • {name} ({status}) - {fin_status}\n"
            
    await message.answer(text)

# --- ASOSIY ISHGA TUSHIRISH ---
async def main():
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())