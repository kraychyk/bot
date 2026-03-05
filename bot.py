import os
import json
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


# ---------------- Storage ----------------
DATA_DIR = Path("./data")
DATA_DIR.mkdir(exist_ok=True)

def user_file(user_id: int) -> Path:
    return DATA_DIR / f"{user_id}.json"

def load_user(user_id: int) -> Dict[str, Any]:
    p = user_file(user_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {
        "habits": [],                # list[str]
        "done_dates": {},            # habit -> list[ISO date]
        "quiz_score": None,          # int | None
        "reminder_time": None,       # "HH:MM" | None
        "tz_offset": 3,              # just keep simple default MSK-like (+3)
    }

def save_user(user_id: int, data: Dict[str, Any]) -> None:
    user_file(user_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def today_iso() -> str:
    return date.today().isoformat()

def parse_iso(d: str) -> date:
    return date.fromisoformat(d)

def calc_streak(done_isos: List[str]) -> int:
    """Consecutive-day streak ending today (or yesterday if today not done)."""
    if not done_isos:
        return 0
    done = sorted({parse_iso(x) for x in done_isos})
    s = 0
    cur = date.today()
    done_set = set(done)
    # streak must end today (strict). If not done today -> 0.
    while cur in done_set:
        s += 1
        cur -= timedelta(days=1)
    return s


# ---------------- Screens / FSM ----------------
class Screens(StatesGroup):
    quiz_q1 = State()
    quiz_q2 = State()
    quiz_q3 = State()
    reminder_time = State()


# ---------------- UI: Inline keyboards ----------------
def kb_main():
    kb = InlineKeyboardBuilder()
    kb.button(text="🧩 Мини-квиз", callback_data="main:quiz")
    kb.button(text="✅ Привычки", callback_data="main:habits")
    kb.button(text="📊 Статистика", callback_data="main:stats")
    kb.button(text="💡 Советы", callback_data="main:tips")
    kb.button(text="⏰ Напоминание", callback_data="main:reminder")
    kb.button(text="ℹ️ О боте", callback_data="main:about")
    kb.button(text="❓ Помощь", callback_data="main:help")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()

def kb_back(to: str = "main:menu"):
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=to)
    return kb.as_markup()

def kb_abc():
    kb = InlineKeyboardBuilder()
    kb.button(text="A", callback_data="quiz:A")
    kb.button(text="B", callback_data="quiz:B")
    kb.button(text="C", callback_data="quiz:C")
    kb.adjust(3)
    return kb.as_markup()

HABIT_OPTIONS = [
    "🚰 Пить из своей бутылки",
    "🛍️ Эко-пакет",
    "🔌 Выключать из розетки",
    "🚯 Сортировать мусор",
]

def kb_habits():
    kb = InlineKeyboardBuilder()
    for h in HABIT_OPTIONS:
        kb.button(text=h, callback_data=f"habit:pick:{h}")
    kb.button(text="✅ Отметить сегодня", callback_data="habit:today")
    kb.button(text="⬅️ Назад", callback_data="main:menu")
    kb.adjust(1, 1, 1, 1, 1, 1)
    return kb.as_markup()

TIP_MAP = {
    "💡 Энергия": [
        "Выключайте приборы из розетки — режим ожидания тоже потребляет.",
        "Поставьте LED-лампы: меньше расход, реже замена.",
    ],
    "💧 Вода": [
        "Поставьте аэратор на кран — расход ниже без потери комфорта.",
        "Закрывайте воду при чистке зубов и намыливании.",
    ],
    "🚯 Отходы": [
        "Начните с 1 фракции (бумага/пластик) — легче закрепить привычку.",
        "Собирайте батарейки отдельно и сдавайте раз в месяц.",
    ],
}

def kb_tips_sections():
    kb = InlineKeyboardBuilder()
    for section in TIP_MAP.keys():
        kb.button(text=section, callback_data=f"tips:sec:{section}")
    kb.button(text="⬅️ Назад", callback_data="main:menu")
    kb.adjust(2, 1)
    return kb.as_markup()

def kb_two_tips(section: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="1", callback_data=f"tips:item:{section}:0")
    kb.button(text="2", callback_data=f"tips:item:{section}:1")
    kb.button(text="⬅️ Назад", callback_data="main:tips")
    kb.adjust(2, 1)
    return kb.as_markup()


# ---------------- Bot ----------------
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Я EcoHabit 🌿\n"
        "Помогаю прокачать эко-привычки: мини-квиз, трекер, советы и статистика.\n\n"
        "Выберите действие 👇",
        reply_markup=kb_main(),
    )

@dp.callback_query(F.data == "main:menu")
async def main_menu(call: CallbackQuery):
    await call.message.edit_text(
        "Главное меню 👇",
        reply_markup=kb_main(),
    )
    await call.answer()

# ---------- Quiz ----------
@dp.callback_query(F.data == "main:quiz")
async def quiz_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(Screens.quiz_q1)
    await state.update_data(quiz_score=0)
    await call.message.edit_text(
        "🧩 Мини-квиз (1/3)\n\n"
        "Как часто вы сортируете отходы?\n"
        "A) Никогда\nB) Иногда\nC) Часто",
        reply_markup=kb_abc(),
    )
    await call.answer()

@dp.callback_query(Screens.quiz_q1, F.data.startswith("quiz:"))
async def quiz_q1(call: CallbackQuery, state: FSMContext):
    ans = call.data.split(":")[1]
    data = await state.get_data()
    score = int(data.get("quiz_score", 0))
    score += 1 if ans == "B" else 2 if ans == "C" else 0
    await state.update_data(quiz_score=score)
    await state.set_state(Screens.quiz_q2)
    await call.message.edit_text(
        "🧩 Мини-квиз (2/3)\n\n"
        "Как вы экономите воду дома?\n"
        "A) Никак\nB) Иногда\nC) Постоянно",
        reply_markup=kb_abc(),
    )
    await call.answer()

@dp.callback_query(Screens.quiz_q2, F.data.startswith("quiz:"))
async def quiz_q2(call: CallbackQuery, state: FSMContext):
    ans = call.data.split(":")[1]
    data = await state.get_data()
    score = int(data.get("quiz_score", 0))
    score += 1 if ans == "B" else 2 if ans == "C" else 0
    await state.update_data(quiz_score=score)
    await state.set_state(Screens.quiz_q3)
    await call.message.edit_text(
        "🧩 Мини-квиз (3/3)\n\n"
        "Как часто вы выбираете пешком/общественный транспорт?\n"
        "A) Почти никогда\nB) Иногда\nC) Часто",
        reply_markup=kb_abc(),
    )
    await call.answer()

@dp.callback_query(Screens.quiz_q3, F.data.startswith("quiz:"))
async def quiz_q3(call: CallbackQuery, state: FSMContext):
    ans = call.data.split(":")[1]
    data = await state.get_data()
    score = int(data.get("quiz_score", 0))
    score += 1 if ans == "B" else 2 if ans == "C" else 0

    u = load_user(call.from_user.id)
    u["quiz_score"] = score
    save_user(call.from_user.id, u)

    if score <= 1:
        level = "🌱 Старт"
        tip = "Возьмите 1 привычку: бутылка + пакет. Отмечайте 7 дней."
    elif score <= 3:
        level = "🌿 Уверенный"
        tip = "Добавьте сортировку 1 фракции и поставьте напоминание."
    else:
        level = "🌳 Продвинутый"
        tip = "Попробуйте «день без отходов» раз в неделю."

    await state.clear()
    await call.message.edit_text(
        f"✅ Готово!\n\nРезультат: {level}\nБаллы: {score}/6\n\nСовет: {tip}\n\nМеню 👇",
        reply_markup=kb_main(),
    )
    await call.answer()

# ---------- Habits ----------
@dp.callback_query(F.data == "main:habits")
async def habits(call: CallbackQuery):
    u = load_user(call.from_user.id)
    current = u["habits"][-1] if u["habits"] else "не выбрана"
    await call.message.edit_text(
        f"✅ Привычки\n\nТекущая: {current}\n"
        "Выберите привычку (она добавится в ваш список):",
        reply_markup=kb_habits(),
    )
    await call.answer()

@dp.callback_query(F.data.startswith("habit:pick:"))
async def habit_pick(call: CallbackQuery):
    habit = call.data.split("habit:pick:", 1)[1]
    u = load_user(call.from_user.id)
    if habit not in u["habits"]:
        u["habits"].append(habit)
        u["done_dates"].setdefault(habit, [])
        save_user(call.from_user.id, u)
    await call.message.edit_text(
        f"✅ Выбрано: {habit}\n\n"
        "Теперь можно нажать «✅ Отметить сегодня».",
        reply_markup=kb_habits(),
    )
    await call.answer("Привычка выбрана")

@dp.callback_query(F.data == "habit:today")
async def habit_today(call: CallbackQuery):
    u = load_user(call.from_user.id)
    if not u["habits"]:
        await call.answer("Сначала выберите привычку", show_alert=True)
        return
    habit = u["habits"][-1]
    d = today_iso()
    lst = u["done_dates"].setdefault(habit, [])
    if d not in lst:
        lst.append(d)
        save_user(call.from_user.id, u)

    streak = calc_streak(u["done_dates"].get(habit, []))
    await call.message.edit_text(
        f"✅ Отметил сегодня!\n\n"
        f"Привычка: {habit}\nДата: {d}\nСерия: {streak} дней подряд\n\n"
        "Хотите посмотреть общую статистику?",
        reply_markup=InlineKeyboardBuilder()
            .button(text="📊 Статистика", callback_data="main:stats")
            .button(text="⬅️ Назад", callback_data="main:habits")
            .as_markup(),
    )
    await call.answer()

# ---------- Stats ----------
@dp.callback_query(F.data == "main:stats")
async def stats(call: CallbackQuery):
    u = load_user(call.from_user.id)
    if not u["habits"]:
        await call.message.edit_text(
            "📊 Статистика\n\nПока нет привычек. Зайдите в «✅ Привычки» и выберите первую.",
            reply_markup=kb_main(),
        )
        await call.answer()
        return

    lines = ["📊 Ваша статистика:\n"]
    for h in u["habits"]:
        done = u["done_dates"].get(h, [])
        total = len(set(done))
        streak = calc_streak(done)
        lines.append(f"• {h}\n  выполнено: {total}\n  серия: {streak} дней\n")

    quiz = u.get("quiz_score")
    if quiz is not None:
        lines.append(f"🧩 Последний квиз: {quiz}/6")

    await call.message.edit_text("\n".join(lines), reply_markup=kb_main())
    await call.answer()

# ---------- Tips ----------
@dp.callback_query(F.data == "main:tips")
async def tips(call: CallbackQuery):
    await call.message.edit_text(
        "💡 Советы\n\nВыберите раздел:",
        reply_markup=kb_tips_sections(),
    )
    await call.answer()

@dp.callback_query(F.data.startswith("tips:sec:"))
async def tips_section(call: CallbackQuery):
    section = call.data.split("tips:sec:", 1)[1]
    items = TIP_MAP.get(section, [])
    await call.message.edit_text(
        "💡 Советы\n\n" +
        "\n".join([f"{i+1}) {t}" for i, t in enumerate(items)]) +
        "\n\nНажмите номер, чтобы открыть карточку:",
        reply_markup=kb_two_tips(section),
    )
    await call.answer()

@dp.callback_query(F.data.startswith("tips:item:"))
async def tips_item(call: CallbackQuery):
    _, section, idx_s = call.data.split(":", 2)[1].split(":", 1)[0], None, None  # dummy (kept for safety)

    # parse safely:
    # format: tips:item:{section}:{idx}
    parts = call.data.split(":")
    section = parts[2]
    idx = int(parts[3])

    items = TIP_MAP.get(section, [])
    if not (0 <= idx < len(items)):
        await call.answer("Нет такого совета", show_alert=True)
        return

    await call.message.edit_text(
        f"📌 {section}\n\nСовет #{idx+1}:\n{items[idx]}",
        reply_markup=InlineKeyboardBuilder()
            .button(text="⬅️ К разделам", callback_data="main:tips")
            .button(text="🏠 В меню", callback_data="main:menu")
            .as_markup(),
    )
    await call.answer()

# ---------- Reminder ----------
@dp.callback_query(F.data == "main:reminder")
async def reminder(call: CallbackQuery, state: FSMContext):
    u = load_user(call.from_user.id)
    cur = u.get("reminder_time") or "не задано"
    await state.set_state(Screens.reminder_time)
    await call.message.edit_text(
        f"⏰ Напоминание\n\nТекущее время: {cur}\n"
        "Отправьте время в формате HH:MM (например 20:30).\n"
        "Или напишите 0 чтобы выключить.",
        reply_markup=kb_back("main:menu"),
    )
    await call.answer()

@dp.message(Screens.reminder_time)
async def reminder_set(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    u = load_user(message.from_user.id)

    if txt == "0":
        u["reminder_time"] = None
        save_user(message.from_user.id, u)
        await state.clear()
        await message.answer("Напоминание выключено ✅", reply_markup=kb_main())
        return

    try:
        t = datetime.strptime(txt, "%H:%M").time()
    except ValueError:
        await message.answer("Неверный формат. Пример: 20:30 или 0 чтобы выключить.")
        return

    u["reminder_time"] = f"{t.hour:02d}:{t.minute:02d}"
    save_user(message.from_user.id, u)
    await state.clear()
    await message.answer(f"Напоминание установлено на {u['reminder_time']} ✅", reply_markup=kb_main())

# ---------- About / Help ----------
@dp.callback_query(F.data == "main:about")
async def about(call: CallbackQuery):
    await call.message.edit_text(
        "ℹ️ О боте\n\n"
        "EcoHabit 🌿 — бот про эко-привычки.\n"
        "Функции: мини-квиз, трекер привычек, советы, статистика, напоминания.\n",
        reply_markup=kb_main(),
    )
    await call.answer()

@dp.callback_query(F.data == "main:help")
async def help_msg(call: CallbackQuery):
    await call.message.edit_text(
        "❓ Помощь\n\n"
        "• 🧩 Мини-квиз — оценка и персональный совет\n"
        "• ✅ Привычки — выберите и отмечайте выполнение\n"
        "• 📊 Статистика — прогресс и серия\n"
        "• 💡 Советы — быстрые подсказки\n"
        "• ⏰ Напоминание — ежедневный пинг\n\n"
        "Команда: /start — главное меню",
        reply_markup=kb_main(),
    )
    await call.answer()

@dp.message()
async def unknown(message: Message):
    await message.answer("Не понял 🙈 Нажмите /start чтобы вернуться в меню.")


# ---------------- Reminder background loop ----------------
async def reminder_loop(bot: Bot):
    """
    Простая проверка раз в минуту:
    если у пользователя задано reminder_time и сейчас совпадает (по локальному времени ПК),
    отправляем напоминание.
    """
    last_sent: Dict[int, str] = {}  # user_id -> ISO date when sent
    while True:
        now = datetime.now()
        hhmm = f"{now.hour:02d}:{now.minute:02d}"
        for file in DATA_DIR.glob("*.json"):
            try:
                user_id = int(file.stem)
            except ValueError:
                continue
            u = load_user(user_id)
            rt = u.get("reminder_time")
            if not rt:
                continue
            if rt == hhmm:
                sent_key = f"{today_iso()}_{hhmm}"
                if last_sent.get(user_id) != sent_key:
                    last_sent[user_id] = sent_key
                    await bot.send_message(
                        user_id,
                        "⏰ Напоминание EcoHabit: отметь привычку сегодня ✅\n"
                        "Зайди в «✅ Привычки» и нажми «✅ Отметить сегодня».",
                        reply_markup=kb_main(),
                    )
        await asyncio.sleep(60)


async def main():
    token = "8723504058:AAFxzNqVOFlGwLkb4Tlag96P1OFiBluFDAg"
    if not token:
        raise RuntimeError("Не найден BOT_TOKEN. В PowerShell: $env:BOT_TOKEN='...'")

    bot = Bot(token=token)
    asyncio.create_task(reminder_loop(bot))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())