import asyncio
import psycopg2
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# === НАСТРОЙКИ ===
BOT_TOKEN = "9182369541:AAFQmdHzz1hDmtJMPLJ0YAhE9bLgO2OKXIw"
ADMIN_ID = 7371686176  # Твой ID
ADMIN_USERNAME = "@NEX_03" 
RATE_PER_100K = 12.0  # Ставка $12 за 100 000 просмотров
MIN_VIEWS_LIMIT = 50000 # Минимальный порог просмотров

# Твоя готовая строка подключения из Supabase (пароль уже внутри: 12345)
DATABASE_URL = "postgresql://postgres.yhyyzpmnmgdfencdqgxf:ENH:Qp68tCgTEM-@aws-1-eu-west-3.pooler.supabase.com:6543/postgres"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === ПОДКЛЮЧЕНИЕ К SUPABASE (POSTGRESQL) ===
db_conn = psycopg2.connect(DATABASE_URL, sslmode='require')
db_conn.autocommit = True
cursor = db_conn.cursor()

# Создание таблиц в облаке (если еще не созданы)
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    total_views BIGINT DEFAULT 0,
    total_paid NUMERIC DEFAULT 0.0
);
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    url TEXT UNIQUE,
    screenshot_file_id TEXT,
    status TEXT DEFAULT 'Аккаунт на проверке, ждите'
);
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS payouts (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    account_url TEXT,
    views BIGINT,
    amount NUMERIC,
    video_url TEXT,
    status TEXT DEFAULT 'pending'
);
""")

# === СОСТОЯНИЯ (FSM) ===
class AddAccount(StatesGroup):
    waiting_for_url = State()
    waiting_for_screenshot = State()
    confirm_data = State()

class SubmitPayout(StatesGroup):
    choosing_account = State()
    waiting_for_views = State()
    waiting_for_video = State()
    confirm_data = State()

class AdminPayoutConfirm(StatesGroup):
    waiting_for_payment_screenshot = State()

admin_payout_storage = {}

# === КЛАВИАТУРЫ ===
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 Отправить на выплату")],
            [KeyboardButton(text="➕ Добавить аккаунт"), KeyboardButton(text="📂 Мои аккаунты")],
            [KeyboardButton(text="📊 Моя статистика"), KeyboardButton(text="💬 Поддержка")]
        ],
        resize_keyboard=True
    )

def confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, всё верно", callback_data="confirm_yes"),
            InlineKeyboardButton(text="❌ Заполнить заново", callback_data="confirm_no")
        ]
    ])

# === СТАРТ ===
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name

    cursor.execute(
        "INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username",
        (user_id, username)
    )

    await message.answer(
        "👋 Привет! Это панель управления аккаунтами и выплатами.\n"
        f"По всем вопросам пиши администратору: {ADMIN_USERNAME}\n\n"
        "Выбери действие в меню ниже:",
        reply_markup=main_menu()
    )

@dp.message(F.text == "💬 Поддержка")
async def support_info(message: types.Message):
    await message.answer(f"💬 По всем вопросам и проблемам обращайся напрямую к администратору: {ADMIN_USERNAME}")

# === ДОБАВЛЕНИЕ АККАУНТА ===
@dp.message(F.text == "➕ Добавить аккаунт")
async def add_acc_start(message: types.Message, state: FSMContext):
    await message.answer("🔗 Отправь ссылку на свой TikTok-аккаунт (обязательно через `@`, например: `https://www.tiktok.com/@username`):", parse_mode="Markdown")
    await state.set_state(AddAccount.waiting_for_url)

@dp.message(AddAccount.waiting_for_url)
async def add_acc_url_entered(message: types.Message, state: FSMContext):
    url = message.text.strip()
    
    if "tiktok.com" not in url or "/@" not in url:
        await message.answer("❌ Это не ссылка на профиль TikTok! Ссылка должна содержать знак `@` и имя пользователя. Попробуй еще раз:")
        return

    cursor.execute("SELECT user_id FROM accounts WHERE url = %s", (url,))
    existing = cursor.fetchone()
    if existing:
        await message.answer("❌ **Этот аккаунт уже зарегистрирован в системе!** Используй другой свой аккаунт.")
        return

    await state.update_data(url=url)
    await message.answer("📸 Теперь отправь **скриншот** профиля, подтверждающий, что это твой аккаунт:")
    await state.set_state(AddAccount.waiting_for_screenshot)

@dp.message(AddAccount.waiting_for_screenshot, F.photo)
async def add_acc_photo_entered(message: types.Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id
    await state.update_data(screenshot=photo_file_id)
    
    data = await state.get_data()
    await message.answer(
        f"📋 **Проверь данные аккаунта:**\n\n"
        f"📱 Ссылка: {data['url']}\n"
        f"📸 Скриншот прикреплен.\n\n"
        f"Всё верно?",
        parse_mode="HTML",
        reply_markup=confirm_keyboard()
    )
    await state.set_state(AddAccount.confirm_data)

@dp.message(AddAccount.waiting_for_screenshot)
async def add_acc_photo_required(message: types.Message):
    await message.answer("❌ Пожалуйста, отправь именно скриншот (картинку) профиля:")

@dp.callback_query(AddAccount.confirm_data, F.data == "confirm_yes")
async def add_acc_confirmed(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    user_id = callback.from_user.id
    url = data["url"]
    photo_id = data["screenshot"]

    try:
        cursor.execute(
            "INSERT INTO accounts (user_id, url, screenshot_file_id) VALUES (%s, %s, %s) RETURNING id",
            (user_id, url, photo_id)
        )
        acc_id = cursor.fetchone()[0]
    except Exception:
        await callback.message.edit_text("❌ Ошибка: этот аккаунт уже был добавлен кем-то ранее.")
        await state.clear()
        return

    await state.clear()
    await callback.message.edit_text("✅ Заявка на добавление аккаунта отправлена администратору! Жди проверки.")
    await callback.message.answer("Главное меню:", reply_markup=main_menu())

    username = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить аккаунт", callback_data=f"acc_ok_{acc_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"acc_no_{acc_id}")
    ]])
    
    await bot.send_photo(
        ADMIN_ID,
        photo=photo_id,
        caption=f"🆕 <b>Новый аккаунт на проверку</b>\n\n"
                f"👤 От редактора: {username} (ID: <code>{user_id}</code>)\n"
                f"📱 Ссылка: <a href='{url}'>{url}</a>",
        parse_mode="HTML",
        reply_markup=kb
    )

@dp.callback_query(AddAccount.confirm_data, F.data == "confirm_no")
async def add_acc_cancelled(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ Отменено. Начни заново через меню «➕ Добавить аккаунт».")
    await callback.message.answer("Главное меню:", reply_markup=main_menu())

# === МОИ АККАУНТЫ ===
@dp.message(F.text == "📂 Мои аккаунты")
async def list_accounts(message: types.Message):
    cursor.execute("SELECT id, url, status FROM accounts WHERE user_id = %s", (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        await message.answer("У тебя пока нет добавленных аккаунтов. Нажми «➕ Добавить аккаунт».")
        return

    await message.answer("📂 <b>Твои аккаунты:</b>", parse_mode="HTML")
    for acc_id, url, status in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Удалить этот аккаунт", callback_data=f"del_acc_{acc_id}")
        ]])
        await message.answer(
            f"📱 <a href='{url}'>{url}</a>\nСтатус: <i>{status}</i>",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=kb
        )

@dp.callback_query(F.data.startswith("del_acc_"))
async def delete_my_account(callback: types.CallbackQuery):
    await callback.answer()
    acc_id = int(callback.data.split("_")[2])
    cursor.execute("SELECT user_id, url FROM accounts WHERE id = %s", (acc_id,))
    row = cursor.fetchone()
    
    if not row or row[0] != callback.from_user.id:
        await callback.answer("Этот аккаунт уже удален.", show_alert=True)
        return

    url = row[1]
    cursor.execute("DELETE FROM accounts WHERE id = %s", (acc_id,))
    await callback.message.edit_text(f"🗑 Аккаунт <s>{url}</s> успешно удален.", parse_mode="HTML")

# === СТАТИСТИКА ===
@dp.message(F.text == "📊 Моя статистика")
async def my_stats(message: types.Message):
    cursor.execute("SELECT total_views, total_paid FROM users WHERE user_id = %s", (message.from_user.id,))
    row = cursor.fetchone()
    views, paid = row if row else (0, 0.0)

    await message.answer(
        f"📊 <b>Твоя статистика за всё время:</b>\n\n"
        f"👁 Одобрено просмотров: <b>{views:,}</b>\n"
        f"💵 Выплачено всего: <b>${float(paid):.2f}</b>",
        parse_mode="HTML"
    )

# === ОТПРАВКА ЗАЯВКИ НА ВЫПЛАТУ ===
@dp.message(F.text == "📤 Отправить на выплату")
async def payout_start(message: types.Message, state: FSMContext):
    cursor.execute("SELECT id, url FROM accounts WHERE user_id = %s AND status = '✅ Одобрен'", (message.from_user.id,))
    accounts = cursor.fetchall()
    if not accounts:
        await message.answer("⚠️ У тебя нет одобренных аккаунтов для выплат. Дождись проверки аккаунта администратором.")
        return

    buttons = [[InlineKeyboardButton(text=url, callback_data=f"sel_acc_{acc_id}")] for acc_id, url in accounts]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выбери аккаунт, с которого подаешь отчет:", reply_markup=kb)
    await state.set_state(SubmitPayout.choosing_account)

@dp.callback_query(SubmitPayout.choosing_account, F.data.startswith("sel_acc_"))
async def payout_account_chosen(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    acc_id = int(callback.data.split("_")[2])
    cursor.execute("SELECT url FROM accounts WHERE id = %s", (acc_id,))
    row = cursor.fetchone()
    if not row:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return
    acc_url = row[0]

    await state.update_data(account_url=acc_url)
    await callback.message.edit_text(
        f"Выбран аккаунт: {acc_url}\n\n"
        f"🔢 Введи количество просмотров (минимальный порог — <b>{MIN_VIEWS_LIMIT:,}</b>):",
        parse_mode="HTML"
    )
    await state.set_state(SubmitPayout.waiting_for_views)

@dp.message(SubmitPayout.waiting_for_views)
async def payout_views_entered(message: types.Message, state: FSMContext):
    digits = message.text.replace(" ", "").replace(",", "")
    if not digits.isdigit():
        await message.answer("❌ Введи только число просмотров (например: 50000):")
        return

    views = int(digits)
    if views < MIN_VIEWS_LIMIT:
        await message.answer(
            f"❌ Меньше {MIN_VIEWS_LIMIT:,} просмотров отправлять нельзя!\n"
            f"Твой результат: {views:,}. Введи значение от {MIN_VIEWS_LIMIT:,}:"
        )
        return

    await state.update_data(views=views)
    await message.answer("🔗 Отправь ссылку на **конкретный ролик** (или напиши «пачка» / список видео):")
    await state.set_state(SubmitPayout.waiting_for_video)

@dp.message(SubmitPayout.waiting_for_video)
async def payout_video_entered(message: types.Message, state: FSMContext):
    video_input = message.text.strip()
    
    if "tiktok.com" in video_input and "/@" in video_input:
        await message.answer("❌ Это ссылка на профиль, а не на видео! Отправь ссылку на конкретный ролик либо напиши «пачка»:")
        return

    await state.update_data(video_url=video_input)

    data = await state.get_data()
    amount = round((data["views"] / 100_000) * RATE_PER_100K, 2)

    await message.answer(
        f"📋 <b>Проверь заявку на выплату:</b>\n\n"
        f"📱 Аккаунт: {data['account_url']}\n"
        f"👁 Просмотры: <b>{data['views']:,}</b>\n"
        f"💵 К выплате: <b>${amount:.2f}</b>\n"
        f"🎬 Ссылка: {video_input}\n\n"
        f"Всё верно?",
        parse_mode="HTML",
        reply_markup=confirm_keyboard()
    )
    await state.set_state(SubmitPayout.confirm_data)

@dp.callback_query(SubmitPayout.confirm_data, F.data == "confirm_yes")
async def payout_confirmed(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    user_id = callback.from_user.id
    views = data["views"]
    acc_url = data["account_url"]
    video_url = data["video_url"]
    amount = round((views / 100_000) * RATE_PER_100K, 2)

    cursor.execute(
        "INSERT INTO payouts (user_id, account_url, views, amount, video_url) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (user_id, acc_url, views, amount, video_url)
    )
    payout_id = cursor.fetchone()[0]
    await state.clear()

    await callback.message.edit_text(f"✅ Заявка на выплату #{payout_id} успешно отправлена администратору!")
    await callback.message.answer("Главное меню:", reply_markup=main_menu())

    username = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"pay_ok_{payout_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pay_no_{payout_id}")
    ]])
    
    await bot.send_message(
        ADMIN_ID,
        f"💰 <b>Запрос на выплату #{payout_id}</b>\n\n"
        f"👤 Редактор: {username} (ID: <code>{user_id}</code>)\n"
        f"📱 Аккаунт: <a href='{acc_url}'>{acc_url}</a>\n"
        f"🎬 Ссылка: {video_url}\n"
        f"👁 Просмотры: <b>{views:,}</b>\n"
        f"💵 К выплате: <b>${amount:.2f}</b>",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=kb
    )

@dp.callback_query(SubmitPayout.confirm_data, F.data == "confirm_no")
async def payout_cancelled(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ Отменено. Можешь отправить заявку заново.")
    await callback.message.answer("Главное меню:", reply_markup=main_menu())

# === АДМИН-ПАНЕЛЬ: АККАУНТЫ ===
@dp.callback_query(F.data.startswith("acc_"))
async def admin_account_decision(callback: types.CallbackQuery):
    await callback.answer()
    if callback.from_user.id != ADMIN_ID:
        return
    action, acc_id = callback.data.split("_")[1], int(callback.data.split("_")[2])
    cursor.execute("SELECT user_id, url FROM accounts WHERE id = %s", (acc_id,))
    row = cursor.fetchone()
    if not row:
        return
    user_id, url = row

    if action == "ok":
        new_status = "✅ Одобрен"
        await bot.send_message(user_id, f"🎉 Твой аккаунт {url} одобрен администратором! Теперь ты можешь отправлять отчеты на выплату.")
    else:
        new_status = "❌ Отклонен"
        await bot.send_message(user_id, f"⚠️ Твой аккаунт {url} отклонен администратором.")

    cursor.execute("UPDATE accounts SET status = %s WHERE id = %s", (new_status, acc_id))
    await callback.message.edit_caption(
        caption=f"{callback.message.caption}\n\nСтатус: <b>{new_status}</b>",
        parse_mode="HTML"
    )

# === АДМИН-ПАНЕЛЬ: ВЫПЛАТЫ ===
@dp.callback_query(F.data.startswith("pay_"))
async def admin_payout_decision(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id != ADMIN_ID:
        return
    
    action, payout_id = callback.data.split("_")[1], int(callback.data.split("_")[2])
    cursor.execute("SELECT user_id, views, amount, status FROM payouts WHERE id = %s", (payout_id,))
    row = cursor.fetchone()
    if not row or row[3] != "pending":
        await callback.answer("Эта заявка уже обработана.", show_alert=True)
        return

    if action == "ok":
        admin_payout_storage[ADMIN_ID] = payout_id
        await state.set_state(AdminPayoutConfirm.waiting_for_payment_screenshot)
        await callback.message.answer(
            f"📸 Отправь мне **скриншот перевода (или подтверждение)** для выплаты #{payout_id}. "
            "Я перешлю его редактору для финального подтверждения."
        )
    else:
        cursor.execute("UPDATE payouts SET status = 'rejected' WHERE id = %s", (payout_id,))
        user_id = row[0]
        views = row[1]
        await callback.message.edit_text(f"{callback.message.text}\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML")
        await bot.send_message(user_id, f"❌ Твоя заявка на выплату ({views:,} просмотров) была отклонена.")

@dp.message(AdminPayoutConfirm.waiting_for_payment_screenshot, F.photo)
async def admin_sent_payment_screenshot(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    payout_id = admin_payout_storage.get(ADMIN_ID)
    if not payout_id:
        await state.clear()
        await message.answer("❌ Ошибка: ID выплаты не найден. Попробуй нажать кнопку одобрения заново.")
        return

    photo_file_id = message.photo[-1].file_id

    cursor.execute("SELECT user_id, views, amount FROM payouts WHERE id = %s", (payout_id,))
    row = cursor.fetchone()
    if not row:
        await state.clear()
        await message.answer("❌ Заявка не найдена в базе данных.")
        return

    user_id, views, amount = row

    cursor.execute("UPDATE payouts SET status = 'approved' WHERE id = %s", (payout_id,))
    cursor.execute(
        "UPDATE users SET total_views = total_views + %s, total_paid = total_paid + %s WHERE user_id = %s",
        (views, amount, user_id)
    )
    await state.clear()

    await bot.send_photo(
        user_id,
        photo=photo_file_id,
        caption=f"✅ <b>Выплата одобрена и отправлена!</b>\n"
                f"Засчитано: <b>{views:,}</b> просмотров.\n"
                f"Сумма: <b>${float(amount):.2f}</b>.",
        parse_mode="HTML"
    )

    await message.answer(f"✅ Скриншот успешно отправлен редактору! Выплата #{payout_id} закрыта.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
