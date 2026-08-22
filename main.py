import os
import sys
import asyncio
import logging
from pathlib import Path
import functools
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from config import local_settings, remote_settings, testing_token
import psycopg2
import pymysql
from pymysql import Error
from contextlib import contextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from datetime import date
from dateutil.relativedelta import relativedelta
from calendar import monthrange
from date_adaptation import date_adaptation
from date_adaptation import seasons
import pandas as pd



### -------------> Настройки <-------------
interval_check_reminders = 60  # интревал работы планировщика в секундах
testing = True  # режим работы бота: тестерование
local = False  # режим работы кода: локально/удаленно
settings = local_settings if local else remote_settings  # выбор соответсвующих настроек
ml_emoji = "🚀"
tl_emoji = "📌"
rl_emoji = "⏰"
bl_emoji = "🎂"



### -------------> Диспетчер <-------------
if testing:
    bot = Bot(token=testing_token)
else:
    bot = Bot(token=settings["token"])
dp = Dispatcher()



### --------> Планировщик задач <--------
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")



### ---------> Подключение к БД <---------
def create_connection():
    connection_method = psycopg2.connect if local else pymysql.connect
    return connection_method(
        database=settings["database"],
        user=settings["user"],
        password=settings["password"],
        host=settings["host"],
        autocommit=True
    )

@contextmanager
def db_connection():
    connection = create_connection()
    try:
        yield connection
    finally:
        connection.close()

dbms = "PostgreSQL" if local else "MySQL"  # субд
try:
    with db_connection() as connection:
        connection.ping()
        print(f"Подключение к базе данных {dbms} установлено")
except Error as e:
    print(f"Ошибка при подключении к базе данных {dbms}:", e)



### ----------> Создание таблиц <----------
with db_connection() as connection:
    if local == 0:
        with connection.cursor() as cursor:
            cursor.execute("""CREATE TABLE IF NOT EXISTS users(
                first_name VARCHAR(64),
                last_name VARCHAR(64),
                username VARCHAR(32),
                user_id BIGINT PRIMARY KEY,
                language_code VARCHAR(13),
                date_registration TIMESTAMP DEFAULT 0)""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS tasks(
                task_id INT NOT NULL AUTO_INCREMENT,
                task VARCHAR(256),
                user_id BIGINT,
                PRIMARY KEY (task_id))""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS birthdays(
                birthday_id INT NOT NULL AUTO_INCREMENT,
                person VARCHAR(64),
                birthday TIMESTAMP,
                user_id BIGINT,
                PRIMARY KEY (birthday_id))""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS reminders(
                reminder_id INT NOT NULL AUTO_INCREMENT,
                task_id INT,
                remind_at TIMESTAMP,
                daily BOOLEAN,
                yearly BOOLEAN,
                user_id BIGINT,
                PRIMARY KEY (reminder_id),
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE)""")
    else:
        with connection.cursor() as cursor:  # подобная конструкция в отличие от cursor = connection.cursor() в блоке finally не будет требовать закрытия курсора
            cursor.execute("""CREATE TABLE IF NOT EXISTS users(
                first_name VARCHAR(64),
                last_name VARCHAR(64),
                username VARCHAR(32),
                user_id BIGINT PRIMARY KEY,
                language_code VARCHAR(13),
                date_registration TIMESTAMPTZ)""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS tasks(
                task_id SERIAL PRIMARY KEY,
                task VARCHAR(256),
                user_id BIGINT)""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS birthdays(
                birthday_id SERIAL PRIMARY KEY,
                person VARCHAR(64),
                birthday TIMESTAMPTZ,
                user_id BIGINT)""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS reminders(
                reminder_id SERIAL PRIMARY KEY,
                task_id INT REFERENCES tasks(task_id) ON DELETE CASCADE,
                remind_at TIMESTAMPTZ,
                daily BOOL,
                yearly BOOLEAN,
                user_id BIGINT)""")

### ----------------> main <----------------
@dp.message(Command("start"))
async def start(message: Message):
    author = message.from_user
    member = await get_member(author)
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (author.id,))
            if cursor.fetchone() is None:
                cursor.execute(f"INSERT INTO users VALUES (%s, %s, %s, %s, %s, %s)", (
                                   author.first_name if author.first_name else None,
                                   author.last_name if author.last_name else None,
                                   author.username if author.username else None,
                                   author.id,
                                   author.language_code,
                                   datetime.today()))
                extra_text = "успешно зарегистрированы!"
            else:
                extra_text = "уже зарегистрированы."
    await message.answer(f"Здравствуйте {member}! Вы {extra_text}\nКоманда /help отобразит мой функционал.")

@dp.message(Command("help"))
async def help(message: Message):
    await message.answer(f"{ml_emoji} Основные команды:\n"
                         "/start — регистрация в системе\n"
                         "/help — список команд\n"
                         "/user — информация о вас\n\n"
                         f"{tl_emoji} Команды списка задач:\n"
                         "/task_list (/tl) — отобразить список задач\n"
                         "/add_task (/at) — добавить задачу\n"
                         "/edit_task (/et) — изменить задачу\n"
                         "/delete_task (/dt) — удалить задачу\n"
                         "/clear_task_list (/ctl) — очистить список задач\n\n"
                         f"{rl_emoji} Команды напоминаний:\n"
                         "/reminder_list (/rl) — отобразить список напоминаний у задачи\n"
                         "/add_reminder (/ar) — добавить напоминание к задаче\n"
                         "/edit_reminder (/er) — изменить напоминание в задаче\n"
                         "/delete_reminder (/dr) — удалить напоминание из задачи\n"
                         "/clear_reminder_list (/crl) — очистить список напоминаний у задачи\n\n"
                         f"{bl_emoji} Команды списка дней рождения:\n"
                         "/birthday_list (/bl) — отобразить список дней рождения\n"
                         "/add_birthday (/ab) — добавить день рождения\n"
                         "/edit_birthday (/eb) — изменить день рождения\n"
                         "/delete_birthday (/db) — удалить день рождения\n"
                         "/clear_birthday_list (/cbl) — очистить список дней рождения")

@dp.message(Command("user"))
async def user(message: Message):
    author = message.from_user
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE user_id = %s", (author.id,))
            user_info = cursor.fetchone()
    if user_info:
        first_name = user_info[0] if user_info[0] else ""
        last_name = user_info[1] if user_info[1] else ""
        username = user_info[2] if user_info[2] else ""
        user_id = user_info[3]
        language_code = user_info[4]
        date_registration = user_info[5]
        await message.answer(f"*Имя*: `{first_name}`\n"
                             f"*Фамилия*: `{last_name}`\n"
                             f"*Аккаунт*: `{username}`\n"
                             f"*ID*: `{user_id}`\n"
                             f"*Языковой код*: `{language_code}`\n"
                             f"*Дата регистрации*: `{date_registration.strftime('%d.%m.%y')}`",
                             parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer("Сначала вам нужно пройти регистрацию, написав команду /start")



### ---------------> task_list <---------------
### ---> Хранение временных данных <---
class New_task(StatesGroup):  # создание дочернего класса к StatesGroup
    task_id = State()
    text = State()
    edit_text = State()
    rl = State()  # пропустить часть функционала для /rl
    ar = State()  # пропустить часть функционала для /ar
    er = State()  # пропустить часть функционала для /er
    dr = State()  # пропустить часть функционала для /dr
    crl = State()  # пропустить часть функционала для /crl
    back_to_edit_reminder = State()  # для add_reminder
    reminder_id = State()  # для edit_reminder и delete_reminder
    year = State()
    month = State()
    day = State()
    hour = State()
    minute = State()
    unit = State()
    i_unit = State()



# ### ----------> Test <----------
@dp.message(Command("test"))
async def test(message: Message, state: FSMContext):
    await state.set_data({"ar": True, "er": False, "dr": 0})
    data = await state.get_data()
    print(data)
    await state_remove_keys(state=state, keys=["ar", "dr"])
    data1 = await state.get_data()
    print(data1)

@dp.message(Command("test1"))
async def test1(message: Message, state: FSMContext):
    await state.set_data({"ar": True, "er": False, "dr": 0})
    data = await state.get_data()
    print(data)
    await state_remove_keys(state=state, keys=["ar", "dr"], all_without=True)
    data1 = await state.get_data()
    print(data1)



### ---------------> Кнопки <---------------
tlkb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Добавить задачу", callback_data="add_task"),
     InlineKeyboardButton(text="Редактировать задачу", callback_data="edit_task")],
    [InlineKeyboardButton(text="Удалить задачу", callback_data="delete_task"),
     InlineKeyboardButton(text="Очистить список задач", callback_data="clear_task_list")]
])

reminder_keyboard_first_step = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Да", callback_data="add_reminder"),
     InlineKeyboardButton(text="Нет", callback_data="dont_add_reminder")]
])

timer_keyboard_first_step = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Минута", callback_data="add_reminder_timer_unit_minute"),
     InlineKeyboardButton(text="Час", callback_data="add_reminder_timer_unit_hour"),
     InlineKeyboardButton(text="День", callback_data="add_reminder_timer_unit_day")],
    [InlineKeyboardButton(text="Неделя", callback_data="add_reminder_timer_unit_week"),
     InlineKeyboardButton(text="Месяц", callback_data="add_reminder_timer_unit_month"),
     InlineKeyboardButton(text="Год", callback_data="add_reminder_timer_unit_year")],
    [InlineKeyboardButton(text="« Назад", callback_data="add_reminder")]
])


### --------------> Колбэки <--------------
@dp.callback_query(F.data == "add_task")  # после нажатия кнопки "Добавить задачу"
async def add_task_first_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await state.set_state(New_task.text)  # объявление о готовности начала записи текста в поле text у класса New_task
    await callback.message.answer("Напишите новое задание")

@dp.message(New_task.text)  # записывает в поле у класса New_task text текст пользователя
async def add_task_second_step(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    text = message.text
    author = message.from_user
    if 1 <= len(text) <= 256:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                if local == 0:
                    cursor.execute("INSERT INTO tasks (username, task, user_id) VALUES (%s, %s, %s)", (author.username, text, author.id))
                    task_id = cursor.lastrowid
                else:
                    cursor.execute("INSERT INTO tasks (username, task, user_id) VALUES (%s, %s, %s) RETURNING task_id", (author.username, text, author.id))
                    task_id = cursor.fetchone()[0]
            await state.set_state(New_task.task_id)
            await state.update_data(task_id=task_id)
        await message.answer("Добавить напоминание об этом задании?", reply_markup=reminder_keyboard_first_step)
    else:
        await message.answer("Ваше задание должно быть описано в пределах от 1 до 256 символов включительно")
        await state.clear()  # так как точка выхода без продолжения

@dp.callback_query(F.data == "add_task_back_to_second_step")
async def add_task_back_to_second_step(callback: CallbackQuery):
    await callback.message.edit_text("Добавить напоминание об этом задании?", reply_markup=reminder_keyboard_first_step)

@dp.callback_query(F.data == "add_reminder")
async def add_task_third_step_yes(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    data = await state.get_data()
    if "reminder_id" not in data.keys():
        if "back_to_edit_reminder" not in data.keys():
            if "ar" not in data.keys():
                callback_text = "add_task_back_to_second_step"
            else:
                callback_text = "edit_task"
        else:
            callback_text = "edit_task.reminder"
    else:
        callback_text = "edit_task.reminder/edit_reminder"
    if {"year", "month", "day", "hour", "minute", "unit", "i_unit"} & data.keys():
        await state_remove_keys(state, ["year", "month", "day", "hour", "minute", "unit", "i_unit"])
    # data1 = await state.get_data()                                  # отладка
    # print(f"При возврате в блок add_reminder:\n{data1}")            # отладка
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Дата и время", callback_data="add_reminder_datetime"),
         InlineKeyboardButton(text="Таймер", callback_data="add_reminder_timer")],
        [InlineKeyboardButton(text="Ежедневное", callback_data="add_daily_task"),
         InlineKeyboardButton(text="« Назад", callback_data=f"{callback_text}")]
    ])
    await callback.message.edit_text("Какой вид напоминания добавить?", reply_markup=keyboard)

@dp.callback_query(F.data == "add_reminder_datetime")
async def add_task_fourth_step_yes_datetime_year(callback: CallbackQuery, state: FSMContext, l_year=None):  # альтернативная точка входа для добавления напоминания в блоке edit_task
    await callback.answer("")
    l_limit = datetime.today().year
    r_limit = 2150
    columns = 6
    years = columns - 2
    keyboard = InlineKeyboardBuilder()
    if l_year is None:  # первый вывод клавиатуры с нынешнего года
        l_year = l_limit
    if l_year == l_limit:  # если левый год соответствует нынешнему году, то колбэк скипается
        keyboard.add(InlineKeyboardButton(text="<<", callback_data=f"skip_callback"))
    else:
        keyboard.add(InlineKeyboardButton(text="<<", callback_data=f"add_reminder/change_year_<<{years}{l_year}"))
    for i in range(years):  # заполнение клавиатуры годами
        year = l_year + i
        keyboard.add(InlineKeyboardButton(text=f"{year}", callback_data=f"add_year_{year}"))
    if l_year + years < r_limit:  # встраивание заглушки при превышении лимита справа
        keyboard.add(InlineKeyboardButton(text=">>", callback_data=f"add_reminder/change_year_>>{years}{l_year}"))
    else:
        keyboard.add(InlineKeyboardButton(text=">>", callback_data=f"skip_callback"))
    keyboard.add(InlineKeyboardButton(text="« Назад", callback_data="add_reminder"))
    keyboard_year = keyboard.adjust(columns).as_markup()
    await callback.message.edit_text("Укажите год:", reply_markup=keyboard_year)

@dp.callback_query(F.data.startswith("add_reminder/change_year_"))
async def add_task_fourth_step_yes_datetime_change_year(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    years = int(callback.data[27:28])
    l_year = int(callback.data[28:])
    if callback.data[25:27] == ">>":
        await add_task_fourth_step_yes_datetime_year(callback, state, l_year + years)
    if callback.data[25:27] == "<<":
        await add_task_fourth_step_yes_datetime_year(callback, state, l_year - years)

@dp.callback_query(F.data.startswith("add_year_"))
async def add_task_fifth_step_yes_datetime_month(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    year = int(callback.data[9:])
    await state.set_state(New_task.year)
    await state.update_data(year=year)
    keyboard = InlineKeyboardBuilder()
    if year > datetime.today().year:
        years = 12
    else:
        years = 13 - datetime.today().month
    for i in range(years):  # доступные месяцы
        if years != 12:
            new_date = datetime.today() + relativedelta(months=i)  # новое время с прибавлением числа равного i к месяцу
        else:
            new_date = date(year, i + 1, 1)
        keyboard.add(InlineKeyboardButton(text=f"{seasons[new_date.strftime('%B')]}", callback_data=f"add_month_{new_date.month}"))
    keyboard.add(InlineKeyboardButton(text="« Назад", callback_data="add_reminder_datetime"))
    keyboard_month = keyboard.adjust(4).as_markup()
    await callback.message.edit_text("Укажите месяц:", reply_markup=keyboard_month)

@dp.callback_query(F.data.startswith("add_month_"))
async def add_task_sixth_step_yes_datetime_day(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    data = await state.get_data()
    year = data["year"]
    month = int(callback.data[10:])
    await state.set_state(New_task.month)
    await state.update_data(month=month)
    keyboard = InlineKeyboardBuilder()
    days = monthrange(year, month)[1]
    first_day = 1
    last_days = days
    if month == datetime.today().month and year == datetime.today().year:  # проверка на текущий месяц
        first_day = datetime.today().day
        last_days = days + 1 - datetime.today().day
    for i in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]:  # Заполнение метками
        keyboard.add(InlineKeyboardButton(text=f"{i}", callback_data="skip_callback"))
    for i in range(date(year, month, first_day).weekday()):  # заполнение пустыми ячейками до возможных дней
        keyboard.add(InlineKeyboardButton(text=" ", callback_data="skip_callback"))
    for i in range(last_days):  # возможные для выбора дни
        day = first_day + i
        keyboard.add(InlineKeyboardButton(text=f"{day}", callback_data=f"add_day_{day}"))
    for i in range(6 - date(year, month, day).weekday()):  # заполнение пустыми ячейками после возможных дней
        keyboard.add(InlineKeyboardButton(text=" ", callback_data="skip_callback"))
    keyboard.add(InlineKeyboardButton(text="« Назад", callback_data=f"add_year_{year}"))
    keyboard_day = keyboard.adjust(7).as_markup()
    await callback.message.edit_text("Укажите день:", reply_markup=keyboard_day)

@dp.callback_query(F.data.startswith("add_day_"))
async def add_task_fifth_step_yes_datetime_hour(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    data = await state.get_data()
    year = data["year"]
    month = data["month"]
    day = int(callback.data[8:])
    await state.set_state(New_task.day)
    await state.update_data(day=day)
    keyboard = InlineKeyboardBuilder()
    columns = 8
    first_hour = 0
    hours = 24
    if datetime.today().year == year and datetime.today().month == month and datetime.today().day == day:
        first_hour = datetime.today().hour
        hours = hours - first_hour
    for i in range(first_hour % columns):
        keyboard.add(InlineKeyboardButton(text=" ", callback_data="skip_callback"))
    for i in range(hours):  # возможные для выбора часы
        hour = first_hour + i
        keyboard.add(InlineKeyboardButton(text=f"{hour}", callback_data=f"add_hour_{hour}"))
    keyboard.add(InlineKeyboardButton(text="« Назад", callback_data=f"add_month_{month}"))
    keyboard_hour = keyboard.adjust(columns).as_markup()
    await callback.message.edit_text("Выберите час:", reply_markup=keyboard_hour)

@dp.callback_query(F.data.startswith("add_hour_"))
async def add_task_fifth_step_yes_datetime_minute(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    data = await state.get_data()
    year = data["year"]
    month = data["month"]
    day = data["day"]
    hour = int(callback.data[9:])
    await state.set_state(New_task.hour)
    await state.update_data(hour=hour)
    keyboard = InlineKeyboardBuilder()
    columns = 8
    first_minute = 0
    minutes = 60
    if datetime.today().year == year and datetime.today().month == month and datetime.today().day == day and datetime.today().hour == hour:
        first_minute = datetime.today().minute
        minutes = minutes - first_minute
    for i in range(minutes):  # доступные для выбора минуты
        minute = first_minute + i
        keyboard.add(InlineKeyboardButton(text=f"{minute}", callback_data=f"add_minute_{minute}"))
    keyboard.add(InlineKeyboardButton(text="« Назад", callback_data=f"add_day_{day}"))
    keyboard_minute = keyboard.adjust(columns).as_markup()
    await callback.message.edit_text("Выберите минуту:", reply_markup=keyboard_minute)

@dp.callback_query(F.data.startswith("add_minute_"))
async def add_task_sixth_step_yes_datetime_insert(callback: CallbackQuery, state: FSMContext):
    minute = int(callback.data[11:])
    await state.set_state(New_task.minute)
    await state.update_data(minute=minute)
    await reminder_insert_update(callback = callback, state = state, insert_type = "datetime")

@dp.callback_query(F.data == "add_reminder_timer")
async def add_task_fourth_step_yes_timer(callback: CallbackQuery):
    await callback.answer("")
    await callback.message.edit_text("Выберите единицу измерения таймера:", reply_markup=timer_keyboard_first_step)

@dp.callback_query(F.data.startswith("add_reminder_timer_unit_"))
async def add_task_fifth_step_yes_timer_unit(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    unit = callback.data[24:]
    await state.set_state(New_task.unit)
    await state.update_data(unit=unit)
    keyboard = InlineKeyboardBuilder()
    size = 28
    columns = 7
    text = date_adaptation(-1, unit)
    for i in range(size):
        keyboard.add(InlineKeyboardButton(text=f"{i + 1}", callback_data=f"add_reminder_timer_number_{i + 1}"))
    keyboard.add(InlineKeyboardButton(text="« Назад", callback_data="add_reminder_timer"))
    keyboard_unit = keyboard.adjust(columns).as_markup()
    await callback.message.edit_text(f"Укажите количество {text}:", reply_markup=keyboard_unit)

@dp.callback_query(F.data.startswith("add_reminder_timer_number_"))
async def add_task_fifth_step_yes_timer_insert(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    i_unit = int(callback.data[26:])
    await state.set_state(New_task.i_unit)
    await state.update_data(i_unit=i_unit)
    await reminder_insert_update(callback=callback, state=state, insert_type="timer")

@dp.callback_query(F.data == "add_daily_task")
async def add_daily_task_first_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    keyboard = InlineKeyboardBuilder()
    columns = 8
    first_hour = 0
    hours = 24
    for i in range(hours):  # возможные для выбора часы
        hour = first_hour + i
        keyboard.add(InlineKeyboardButton(text=f"{hour}", callback_data=f"add_daily_hour_{hour}"))
    keyboard.add(InlineKeyboardButton(text="« Назад", callback_data="add_reminder"))
    keyboard_hour = keyboard.adjust(columns).as_markup()
    await callback.message.edit_text("Выберите час:", reply_markup=keyboard_hour)

@dp.callback_query(F.data.startswith("add_daily_hour_"))
async def add_daily_task_second_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    hour = int(callback.data[15:])
    await state.update_data(hour=hour)
    keyboard = InlineKeyboardBuilder()
    columns = 8
    first_minute = 0
    minutes = 60
    for i in range(minutes):  # возможные для выбора минуты
        minute = first_minute + i
        keyboard.add(InlineKeyboardButton(text=f"{minute}", callback_data=f"add_daily_minute_{minute}"))
    keyboard.add(InlineKeyboardButton(text="« Назад", callback_data="add_daily_task"))
    keyboard_minute = keyboard.adjust(columns).as_markup()
    await callback.message.edit_text("Выберите минуту:", reply_markup=keyboard_minute)

@dp.callback_query(F.data.startswith("add_daily_minute_"))
async def add_daily_task_third_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    minute = int(callback.data[17:])
    await state.set_state(New_task.minute)
    await state.update_data(minute=minute)
    await reminder_insert_update(callback=callback, state=state, insert_type="daily")

@dp.callback_query(F.data == "dont_add_reminder")
async def add_task_third_step_no(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await state.clear()  # так как возврат к task_list
    await task_list(callback.message, callback.from_user, edit_msg=True)

@dp.callback_query(F.data == "edit_task")
async def edit_task_first_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await edit_task(callback.message, state=state, author=callback.from_user, edit_msg=True)

@dp.callback_query(F.data.startswith("edit_task_"))  # редактор задачи (Кнопки: Текст/Напоминание/«Назад)
async def edit_task_second_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await state.set_state(New_task.task_id)
    await state.update_data(task_id=int(callback.data[10:]))
    data = await state.get_data()
    if "rl" in data.keys():
        await edit_task_reminder_third_step(callback, state)
    elif "ar" in data.keys():
        await add_task_third_step_yes(callback, state)
    elif "er" in data.keys():
        await edit_task_edit_reminder_fourth_step(callback, state)
    elif "dr" in data.keys():
        await edit_task_delete_reminder_fourth_step(callback, state)
    elif "crl" in data.keys():
        await edit_task_clear_reminder_list(callback, state)
    else:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT task FROM tasks WHERE task_id = %s", (int(callback.data[10:]),))
                task = cursor.fetchone()[0]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Текст", callback_data="edit_task.text"),
             InlineKeyboardButton(text="Напоминание", callback_data="edit_task.reminder")],
            [InlineKeyboardButton(text="« Назад", callback_data="edit_task")]
        ])
        await callback.message.edit_text(f"Задача: {task}\n\nЧто редактировать в задаче?", reply_markup=keyboard)

@dp.callback_query(F.data =='edit_task.text')  # подготовка к сохранению нового текста у задачи
async def edit_task_edit_text_third_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await state.set_state(New_task.edit_text)
    await callback.message.edit_text("Напишите новое задание")

@dp.message(New_task.edit_text)  # изменение текста у задачи
async def edit_task_edit_text_fourth_step(message: Message, state: FSMContext):
    await state.update_data(edit_text=message.text)
    data = await state.get_data()
    await state.clear()  # так как возврат к task_list
    author = message.from_user
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE tasks SET task = %s WHERE task_id = %s and user_id = %s", (data["edit_text"], data["task_id"], author.id))
    await task_list(message)

@dp.callback_query(F.data =="edit_task.reminder")  # вывод всех напоминаний у задачи (кнопки: Добавить/Редактировать/Удалить/Очистить список/«Назад)
async def edit_task_reminder_third_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    data = await state.get_data()
    task_id = data["task_id"]
    if "back_to_edit_reminder" in data.keys():
        await state_remove_keys(state, ["task_id"], all_without=True)
    # print(f"edit_task.reminder (только task_id, rl, ar, er, dr, crl):\n{data}")  # отладка
    if {"rl", "ar", "er", "dr", "crl"} & data.keys():
        callback_text = "edit_task"
    else:
        callback_text = f"edit_task_{task_id}"
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT task FROM tasks WHERE task_id = %s", (task_id,))
            task = cursor.fetchone()[0]
            cursor.execute("SELECT reminder_id, remind_at, daily FROM reminders WHERE task_id = %s ORDER BY remind_at", (task_id,))
            reminders_tuple = cursor.fetchall()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить", callback_data="edit_task.reminder/add_reminder"),
         InlineKeyboardButton(text="Редактировать", callback_data="edit_task.reminder/edit_reminder")],
        [InlineKeyboardButton(text="Удалить", callback_data="edit_task.reminder/delete_reminder"),
         InlineKeyboardButton(text="Очистить список", callback_data="edit_task.reminder/clear_reminder_list")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"{callback_text}")]
    ])
    if reminders_tuple:
        reminders = []
        for i in range(len(reminders_tuple)):
            if bool(reminders_tuple[i][2]):
                text = f"{i + 1}) {reminders_tuple[i][1].strftime('%H:%M')} — ежедневное"
            else:
                text = f"{i + 1}) {reminders_tuple[i][1].strftime('%d.%m.%y %H:%M')}"
            reminders.append(text)
        await callback.message.edit_text(f"{rl_emoji} Список напоминаний для задания `{task}`:\n" + "\n".join(reminders), reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    else:
        await callback.message.edit_text(f"{rl_emoji} У данного задания нет напоминаний", reply_markup=keyboard)

@dp.callback_query(F.data == "edit_task.reminder/add_reminder")  # добавление новой задачи
async def edit_task_add_reminder_fourth_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await state.set_state(New_task.back_to_edit_reminder)
    await state.update_data(back_to_edit_reminder=True)
    await add_task_third_step_yes(callback=callback, state=state)

@dp.callback_query(F.data == "edit_task.reminder/edit_reminder")
async def edit_task_edit_reminder_fourth_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    data = await state.get_data()
    task_id = data["task_id"]
    if "reminder_id" in data.keys():
        await state_remove_keys(state, ["task_id", "er"], all_without=True)
    if "er" in data.keys():
        callback_text = "edit_task"
    else:
        callback_text = "edit_task.reminder"
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT task FROM tasks WHERE task_id = %s", (task_id,))
            task = cursor.fetchone()[0]
            cursor.execute("SELECT reminder_id, remind_at FROM reminders WHERE task_id = %s ORDER BY remind_at", (task_id,))
            reminders_tuple = cursor.fetchall()
    keyboard = InlineKeyboardBuilder()
    reminders = []
    for i in range(len(reminders_tuple)):
        if bool(reminders_tuple[i][2]):
            text = f"{i + 1}) {reminders_tuple[i][1].strftime('%H:%M')} — ежедневное"
        else:
            text = f"{i + 1}) {reminders_tuple[i][1].strftime('%d.%m.%y %H:%M')}"
        reminders.append(text)
        keyboard.add(InlineKeyboardButton(text=f"{i + 1}", callback_data=f"edit_task.reminder/edit_reminder_{reminders_tuple[i][0]}"))
    keyboard.add(InlineKeyboardButton(text=f"« Назад", callback_data=callback_text))
    await callback.message.edit_text(f"{rl_emoji} Список напоминаний для задания `{task}`:\n" + "\n".join(reminders) + "\n\nВыберите номер редактируемого напоминания:", reply_markup=keyboard.adjust(5).as_markup(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data.startswith("edit_task.reminder/edit_reminder_"))
async def edit_reminder_task_fifth_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await state.set_state(New_task.reminder_id)
    await state.update_data(reminder_id = int(callback.data[33:]))
    await add_task_third_step_yes(callback = callback, state = state)

@dp.callback_query(F.data == "edit_task.reminder/delete_reminder")
async def edit_task_delete_reminder_fourth_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    data = await state.get_data()
    task_id = data["task_id"]
    if "dr" in data.keys():
        callback_text = "edit_task"
    else:
        callback_text = "edit_task.reminder"
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT task FROM tasks WHERE task_id = %s", (task_id,))
            task = cursor.fetchone()[0]
            cursor.execute("SELECT reminder_id, remind_at FROM reminders WHERE task_id = %s ORDER BY remind_at", (task_id,))
            reminders_tuple = cursor.fetchall()
    keyboard = InlineKeyboardBuilder()
    reminders = []
    for i in range(len(reminders_tuple)):
        if bool(reminders_tuple[i][2]):
            text = f"{i + 1}) {reminders_tuple[i][1].strftime('%H:%M')} — ежедневное"
        else:
            text = f"{i + 1}) {reminders_tuple[i][1].strftime('%d.%m.%y %H:%M')}"
        reminders.append(text)
        keyboard.add(InlineKeyboardButton(text=f"{i + 1}", callback_data=f"edit_task.reminder/delete_reminder_{reminders_tuple[i][0]}"))
    keyboard.add(InlineKeyboardButton(text=f"« Назад", callback_data=callback_text))
    text = f"{rl_emoji} Список напоминаний для задания `{task}`:\n" + "\n".join(reminders) + "\n\nВыберите номер удаляемого напоминания:"
    await callback.message.edit_text(f"{text}", reply_markup=keyboard.adjust(5).as_markup(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data.startswith("edit_task.reminder/delete_reminder_"))
async def edit_task_delete_datetime_fifth_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    reminder_id = int(callback.data[35:])
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM reminders WHERE reminder_id = %s", (reminder_id,))
    await edit_task_reminder_third_step(callback = callback, state = state)

@dp.callback_query(F.data == "edit_task.reminder/clear_reminder_list")
async def edit_task_clear_reminder_list(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    data = await state.get_data()
    task_id = data["task_id"]
    if callback.message.text != f"{rl_emoji} У данного задания нет напоминаний":
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM reminders WHERE task_id = %s", (task_id,))
        await edit_task_reminder_third_step(callback=callback, state=state)

@dp.callback_query(F.data == "delete_task")
async def delete_task_first_step(callback: CallbackQuery):
    await callback.answer("")
    await delete_task(callback.message, author=callback.from_user, edit_msg=True)

@dp.callback_query(F.data.startswith("delete_task_"))
async def delete_task_second_step(callback: CallbackQuery):
    await callback.answer("")
    task_id = int(callback.data[12:])
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM tasks WHERE task_id = {task_id}")
    await task_list(callback.message, callback.from_user, edit_msg=True)

@dp.callback_query(F.data == "clear_task_list")
async def clear_task_list_first_step(callback: CallbackQuery):
    await callback.answer("")
    await clear_task_list(message=callback.message, author=callback.from_user, edit_msg=True)

@dp.callback_query(F.data == "skip_callback")
async def callback_skip(callback: CallbackQuery):
    await callback.answer("")

@dp.callback_query(F.data == "back_to_tl")
async def back_to_task_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await task_list(callback.message, author=callback.from_user, edit_msg=True)

@dp.callback_query(F.data.startswith("reminder_delete_task_"))
async def reminder_delete_task(callback: CallbackQuery):
    await callback.answer("")
    task_id = int(callback.data[21:])
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM tasks WHERE task_id = %s", (task_id,))
    await task_list(callback.message, author=callback.from_user, edit_msg=True)

@dp.callback_query(F.data == "reminder_dont_delete_task")
async def reminder_dont_delete_task(callback: CallbackQuery):
    await callback.answer("")
    await task_list(callback.message, author=callback.from_user, edit_msg=True)


### ----> Вспомогательные функции <----
async def get_member(author):
    first_name = author.first_name if author.first_name else ""
    last_name = author.last_name if author.last_name else ""
    username = author.username
    sep = "" if first_name == "" or last_name == "" else " "
    member = f"@{username}" if username else f"{first_name}{sep}{last_name}"  # обращение к пользователю
    return member

async def reminder_insert_update(callback: CallbackQuery, state: FSMContext, insert_type):
    data = await state.get_data()
    # print(f"insert_update до очистки:\n{data}")
    if {"back_to_edit_reminder", "reminder_id", "year", "month", "day", "hour", "minute", "unit", "i_unit"} & data.keys():
        await state_remove_keys(state, ["back_to_edit_reminder", "reminder_id", "year", "month", "day", "hour", "minute", "unit", "i_unit"])
    # data1 = await state.get_data()                             # отладка
    # print(f"insert_update после очистки:\n{data1}")            # отладка
    task_id = data["task_id"]
    await callback.answer("")
    if insert_type == "datetime":
        current_datetime = datetime(data["year"], data["month"], data["day"], data["hour"], data["minute"])
        text = f'Напоминание установлено на {data["day"]:02}.{data["month"]:02}.{data["year"]} {data["hour"]:02}:{data["minute"]:02}'
        daily = False
        yearly = False
    elif insert_type == "timer":
        unit = data["unit"]
        i = data["i_unit"]
        units = {"minute": relativedelta(minutes=i),
                 "hour": relativedelta(hours=i),
                 "day": relativedelta(days=i),
                 "week": relativedelta(weeks=i),
                 "month": relativedelta(months=i),
                 "year": relativedelta(years=i)}
        current_datetime = datetime.today() + units[unit]
        text = f"Таймер сработает через {date_adaptation(i, unit)}"
        daily = False
        yearly = False
    elif insert_type == "daily":
        hour = data["hour"]
        minute = data["minute"]
        current_datetime = datetime(datetime.today().year, datetime.today().month, datetime.today().day, hour, minute)
        if current_datetime < datetime.today():
            current_datetime += relativedelta(days=1)
        text = f"Ежедневное напоминание установлено на {hour:02}:{minute:02}"
        daily = True
        yearly = False
    if "reminder_id" not in data.keys():
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO reminders (task_id, remind_at, daily, yearly, user_id) VALUES (%s, %s, %s, %s, %s)",
                    (task_id, current_datetime, daily, yearly, callback.from_user.id))
        if "back_to_edit_reminder" not in data.keys() and "ar" not in data.keys():
            await state.clear()  # так как возврат к task_list
            await task_list(callback.message, callback.from_user, edit_msg=True)
            await callback.message.answer(f"{text}")
        else:
            await edit_task_reminder_third_step(callback=callback, state=state)
    else:
        reminder_id = data["reminder_id"]
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE reminders SET task_id = %s, remind_at = %s, daily = %s, yearly = %s, user_id = %s WHERE reminder_id = %s",
                    (task_id, current_datetime, daily, yearly, callback.from_user.id, reminder_id))
        await edit_task_reminder_third_step(callback=callback, state=state)

async def state_remove_keys(state: FSMContext, keys: list, all_without=False):
    data = await state.get_data()
    if all_without is False:
        await state.set_data({k: v for k, v in data.items() if k not in keys})
    else:
        await state.set_data({k: v for k, v in data.items() if k in keys})


### ------> Работа планировщика <------
async def check_reminders():  # дерьмовый обработчик
    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT reminder_id, task_id, remind_at, daily, yearly, user_id FROM reminders WHERE remind_at <= NOW()")
                reminders = cursor.fetchall()
                if reminders is not None:
                    for remind in reminders:
                        reminder_id, task_id, remind_at, daily, yearly, user_id = remind[0], remind[1], remind[2],\
                                                                                  bool(remind[3]), bool(remind[4]), remind[5]
                        cursor.execute("SELECT task FROM tasks WHERE task_id = %s", (task_id,))
                        task = cursor.fetchone()[0]
                        if daily:
                            await bot.send_message(user_id, f"{task}")
                            next_data = remind_at + relativedelta(days=1)
                            cursor.execute("UPDATE reminders SET remind_at = %s WHERE reminder_id = %s",
                                           (next_data, reminder_id))
                        elif yearly:
                            cursor.execute("SELECT task FROM tasks WHERE task_id = %s", (task_id,))
                            await bot.send_message(user_id, f"{task}")
                            next_data = remind_at + relativedelta(years=1)
                            cursor.execute("UPDATE reminders SET remind_at = %s WHERE reminder_id = %s", (next_data, reminder_id))
                        else:
                            reminder_keyboard_delete_task = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="Да", callback_data=f"reminder_delete_task_{task_id}"),
                                 InlineKeyboardButton(text="Нет", callback_data="reminder_dont_delete_task")]
                            ])
                            await bot.send_message(user_id, f"Напоминание на {remind_at.hour:02}:{remind_at.minute:02}:\n{task}\n\n"
                                                   f"Удалить задание?", reply_markup=reminder_keyboard_delete_task)
                            cursor.execute("DELETE FROM reminders WHERE reminder_id = %s", (reminder_id,))
    except Exception as e:
        print(f"Ошибка в блоке check_reminders: {e}")

### --------> Основные команды <--------
@dp.message(Command(commands=["task_list", "tl"]))
async def task_list(message: Message, author=None, edit_msg=False):
    if author is None:
        author = message.from_user
    reply_method = message.edit_text if edit_msg is True else message.answer
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (author.id,))
            is_reg = cursor.fetchone()
    if is_reg is not None:  # проверка регистрации
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT task FROM tasks WHERE user_id = %s ORDER BY task_id", (author.id,))
        task_tuple = cursor.fetchall()
        if task_tuple:
            task_list = []
            for i in range(len(task_tuple)):
                task_list.append(f"{i + 1}) {task_tuple[i][0]}")
            await reply_method(f"{tl_emoji} Список задач:\n" + '\n'.join(task_list), reply_markup=tlkb)
        else:
            await reply_method(f"{tl_emoji} Ваш список задач пуст", reply_markup=tlkb)
    else:
        await message.answer("Сначала вам нужно пройти регистрацию, написав команду /start")

@dp.message(Command(commands=["add_task", "at"]))
async def add_task(message: Message, state: FSMContext):
    author = message.from_user
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (author.id,))
            is_reg =  cursor.fetchone()
    if is_reg is not None:  # проверка на регистрацию
        await state.set_state(New_task.text)  # объявление о готовности начала записи текста в поле text у класса New_task
        await message.answer("Напишите новое задание")
    else:
        await message.answer("Сначала вам нужно пройти регистрацию, написав команду /start")

@dp.message(Command(commands=["edit_task", "et"]))
async def edit_task(message: Message, state: FSMContext, author=None, edit_msg=False):
    if author is None:
        author = message.from_user
    reply_method = message.edit_text if edit_msg is True else message.answer
    data = await state.get_data()
    if "rl" in data.keys():
        lower_text = "Выберите номер задачи, у которой нужно отобразить все напоминания:"
    elif "ar" in data.keys():
        lower_text = "Выберите номер задачи, к которой нужно добавить напоминание:"
    elif "er" in data.keys():
        lower_text = "Выберите номер задачи, у которой нужно редактировать напоминание:"
    elif "dr" in data.keys():
        lower_text = "Выберите номер задачи, у которой нужно удалить напоминание:"
    elif "crl" in data.keys():
        lower_text = "Выберите номер задачи, у которой нужно удалить все напоминания:"
    else:
        lower_text = "Выберите номер редактируемой задачи:"
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (author.id,))
            is_reg = cursor.fetchone()
    if is_reg is not None:  # проверка регистрации
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT task_id, task FROM tasks WHERE user_id = %s ORDER BY task_id", (author.id,))
                task_tuple = cursor.fetchall()
        if task_tuple:
            task_list = []
            keyboard = InlineKeyboardBuilder()
            for i in range(len(task_tuple)):
                task_list.append(f"{i + 1}) {task_tuple[i][1]}")  # форматирование списка задач
                keyboard.add(InlineKeyboardButton(text=f"{i + 1}", callback_data=f"edit_task_{task_tuple[i][0]}"))
            keyboard.add(InlineKeyboardButton(text=f"« Назад", callback_data="back_to_tl"))
            keyboard_et = keyboard.adjust(5).as_markup()  # форматирование позиций кнопок
            await reply_method(f"{tl_emoji} Список задач:\n" + '\n'.join(task_list) + "\n\n" + lower_text, reply_markup=keyboard_et)
        else:
            await reply_method(f"{tl_emoji} Ваш список задач пуст")
    else:
        await reply_method("Сначала вам нужно пройти регистрацию, написав команду /start")

@dp.message(Command(commands=["delete_task", "dt"]))
async def delete_task(message: Message, author=None, edit_msg=False):
    if author is None:
        author = message.from_user
    reply_method = message.edit_text if edit_msg is True else message.answer
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (author.id,))
            is_reg = cursor.fetchone()
    if is_reg is not None:  # проверка регистрации
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT task_id, task FROM tasks WHERE user_id = %s ORDER BY task_id", (author.id,))
                task_tuple = cursor.fetchall()
        if task_tuple:
            task_list = []
            keyboard = InlineKeyboardBuilder()
            for i in range(len(task_tuple)):
                task_list.append(f"{i + 1}) {task_tuple[i][1]}")  # форматирование списка задач
                keyboard.add(InlineKeyboardButton(text=f"{i + 1}", callback_data=f"delete_task_{task_tuple[i][0]}"))  # добавление кнопок
            keyboard.add(InlineKeyboardButton(text=f"« Назад", callback_data="back_to_tl"))
            keyboard_dt = keyboard.adjust(5).as_markup()  # форматирование позиций кнопок
            await reply_method(f"{tl_emoji} Список задач:\n" + '\n'.join(task_list) + "\n\n" + "Выберите номер удаляемой задачи:", reply_markup=keyboard_dt)
        else:
            await reply_method(f"{tl_emoji} Ваш список задач пуст", reply_markup=tlkb)
    else:
        await reply_method("Сначала вам нужно пройти регистрацию, написав команду /start")

@dp.message(Command(commands=["clear_task_list", "ctl"]))
async def clear_task_list(message: Message, author=None, edit_msg=False):
    if author is None:
        author = message.from_user
    reply_method = message.edit_text if edit_msg is True else message.answer
    if message.text != f"{tl_emoji} Ваш список задач пуст":
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (author.id,))
                if cursor.fetchone() is not None:
                    cursor.execute("SELECT 1 FROM tasks WHERE user_id = %s LIMIT 1", (author.id,))
                    if cursor.fetchone() is not None:
                        cursor.execute(f"DELETE FROM tasks WHERE user_id = %s", (author.id,))
                    await reply_method(f"{tl_emoji} Ваш список задач пуст", reply_markup=tlkb)
                else:
                    await reply_method("Сначала вам нужно пройти регистрацию, написав команду /start")



### -----------> reminder_list <-----------
@dp.message(Command(commands=["reminder_list", "rl"]))
async def reminder_list(message: Message, state: FSMContext):
    await state_remove_keys(state, ["ar", "er", "dr", "crl"])
    await state.set_state(New_task.rl)
    await state.update_data(rl=True)
    await edit_task(message=message, state=state)

@dp.message(Command(commands=["add_reminder", "ar"]))
async def add_reminder(message: Message, state: FSMContext):
    await state_remove_keys(state, ["rl", "er", "dr", "crl"])
    await state.set_state(New_task.ar)
    await state.update_data(ar=True)
    await edit_task(message=message, state=state)

@dp.message(Command(commands=["edit_reminder", "er"]))
async def edit_reminder(message: Message, state: FSMContext):
    await state_remove_keys(state, ["rl", "ar", "dr", "crl"])
    await state.set_state(New_task.er)
    await state.update_data(er=True)
    await edit_task(message=message, state=state)

@dp.message(Command(commands=["delete_reminder", "dr"]))
async def delete_reminder(message: Message, state: FSMContext):
    await state_remove_keys(state, ["rl", "ar", "er", "crl"])
    await state.set_state(New_task.dr)
    await state.update_data(dr=True)
    await edit_task(message=message, state=state)

@dp.message(Command(commands=["clear_reminder_list", "crl"]))
async def clear_reminder_list(message: Message, state: FSMContext):
    await state_remove_keys(state, ["rl", "ar", "er", "dr"])
    await state.set_state(New_task.crl)
    await state.update_data(crl=True)
    await edit_task(message=message, state=state)


### -----------> birthday_list <-----------
### ----> Хранение временных данных <----
class New_birthday(StatesGroup):  # создание дочернего класса к StatesGroup
    person = State()
    edit_person = State()
    birthday = State()
    birthday_id = State()
    reminder_datetime = State()
    year = State()
    month = State()
    day = State()
    hour = State()
    minute = State()
    unit = State()


### --------------> Кнопки <--------------
blkb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Добавить", callback_data="add_birthday"),
     InlineKeyboardButton(text="Редактировать", callback_data="edit_birthday")],
    [InlineKeyboardButton(text="Удалить", callback_data="delete_birthday"),
     InlineKeyboardButton(text="Очистить список", callback_data="clear_birthday_list")]
])


### --------------> Колбэки <--------------
@dp.callback_query(F.data == "add_birthday")
async def add_birthday_first_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await add_birthday(callback.message, state)

@dp.message(New_birthday.person)
async def add_birthday_second_step(message: Message, state: FSMContext, r_year=None, skip_text=False, edit_msg=False):
    reply_method = message.answer if edit_msg is False else message.edit_text
    flag = 0
    if skip_text is False:
        if 1 <= len(message.text) <= 64:
            if r_year is None:
                await state.update_data(person=message.text)
            flag = 1
        else:
            await reply_method("Наименование человека должно быть от 1 до 64 символов включительно")
            await state.clear()
    else:
        flag = 1
    if flag == 1:
        data = await state.get_data()
        l_limit = 1900
        r_limit = datetime.today().year
        columns = 6
        years = columns - 2
        keyboard = InlineKeyboardBuilder()
        if r_year is None:
            r_year = r_limit - 4 * years
        if r_year - years > l_limit:
            keyboard.add(
                InlineKeyboardButton(text="<<", callback_data=f"add_birthday_year_change_kb_<<{years}{r_year}"))
        else:
            keyboard.add(InlineKeyboardButton(text="<<", callback_data=f"skip_callback"))
        for i in range(years, 0, -1):
            year = r_year - i + 1
            keyboard.add(InlineKeyboardButton(text=f"{year}", callback_data=f"add_birthday_year_{year}"))
        if r_year == r_limit:
            keyboard.add(InlineKeyboardButton(text=">>", callback_data=f"skip_callback"))
        else:
            keyboard.add(InlineKeyboardButton(text=">>", callback_data=f"add_birthday_year_change_kb_>>{years}{r_year}"))
        keyboard.add(InlineKeyboardButton(text="Не указывать год", callback_data=f"add_birthday_year_1861"))  # 1861 год невозможен в системе, он используется, как обозначение пропуска года у дня рождения
        keyboard = keyboard.adjust(columns)
        if "birthday_id" in data.keys():
            keyboard.row(InlineKeyboardButton(text="« Назад", callback_data=f"edit_birthday_{data['birthday_id']}"))
        keyboard_years = keyboard.as_markup()
        await reply_method("Когда у него день рождения?\n\nВыберите год:", reply_markup=keyboard_years)

@dp.callback_query(F.data.startswith("add_birthday_year_change_kb_"))
async def add_birthday_year_change_kb(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    years = int(callback.data[30:31])
    r_year = int(callback.data[31:])
    if callback.data[28:30] == ">>":
        await add_birthday_second_step(callback.message, state, r_year + years, True, True)
    if callback.data[28:30] == "<<":
        await add_birthday_second_step(callback.message, state, r_year - years, True, True)

@dp.callback_query(F.data.startswith("add_birthday_year_"))
async def add_birthday_third_step(callback: CallbackQuery, state: FSMContext):
    await state.set_state(New_birthday.year)
    await state.update_data(year=int(callback.data[18:]))
    keyboard = InlineKeyboardBuilder()
    date = list(seasons.keys())
    for i in range(12):
        keyboard.add(InlineKeyboardButton(text=f"{seasons[date[i]]}", callback_data=f"add_birthday_month_{i + 1}"))
    keyboard.add(InlineKeyboardButton(text="« Назад", callback_data=f"add_birthday_year_change_kb_<<4{datetime.today().year-4*3}"))  # тут без привязки к columns!!!
    keyboard_month = keyboard.adjust(4).as_markup()
    await callback.message.edit_text("Выберите месяц:", reply_markup=keyboard_month)

@dp.callback_query(F.data.startswith("add_birthday_month_"))
async def add_birthday_fourth_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    data = await state.get_data()
    year = data["year"]
    month = int(callback.data[19:])
    await state.set_state(New_birthday.month)
    await state.update_data(month=month)
    current_year = datetime.today().year if month > datetime.today().month else (datetime.today() + relativedelta(years=1)).year
    keyboard = InlineKeyboardBuilder()
    days = monthrange(current_year, month)[1]
    first_day = 1
    last_days = days
    if month == datetime.today().month and current_year == datetime.today().year:  # проверка на текущий месяц
        first_day = datetime.today().day
        last_days = days + 1 - datetime.today().day
    day_targets = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i in day_targets:  # Заполнение метками
        keyboard.add(InlineKeyboardButton(text=f"{i}", callback_data="skip_callback"))
    for i in range(date(current_year, month, first_day).weekday()):  # заполнение пустыми ячейками до возможных дней
        keyboard.add(InlineKeyboardButton(text=" ", callback_data="skip_callback"))
    for i in range(last_days):  # возможные для выбора дни
        day = first_day + i
        keyboard.add(InlineKeyboardButton(text=f"{day}", callback_data=f"add_birthday_day_{day}"))
    for i in range(6 - date(current_year, month, day).weekday()):  # заполнение пустыми ячейками после возможных дней
        keyboard.add(InlineKeyboardButton(text=" ", callback_data="skip_callback"))
    keyboard.add(InlineKeyboardButton(text="« Назад", callback_data=f"add_birthday_year_{year}"))
    keyboard_day = keyboard.adjust(7).as_markup()
    await callback.message.edit_text("Теперь выберите день:", reply_markup=keyboard_day)

@dp.callback_query(F.data.startswith("add_birthday_day_"))
async def add_birthday_fifth_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    data = await state.get_data()
    await state.clear()
    year = data["year"]
    month = data["month"]
    day = int(callback.data[17:])
    birthday = datetime(year, month, day)
    with db_connection() as connection:
        with connection.cursor() as cursor:
            if "birthday_id" not in data.keys():
                person = data["person"]
                cursor.execute("INSERT INTO birthdays (person, birthday, user_id) VALUES (%s, %s, %s)", (person, birthday, callback.from_user.id))
            else:
                birthday_id = data["birthday_id"]
                cursor.execute("UPDATE birthdays SET birthday = %s, user_id = %s WHERE birthday_id = %s", (birthday, callback.from_user.id, birthday_id))
    await back_to_birthday_list(callback, state)

@dp.callback_query(F.data == "edit_birthday")
async def edit_birthday_first_step(callback: CallbackQuery):
    await callback.answer("")
    await edit_birthday(message=callback.message, author=callback.from_user, edit_msg=True)

@dp.callback_query(F.data.startswith("edit_birthday_"))
async def edit_birthday_first_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    birthday_id = int(callback.data[14:])
    await state.set_state(New_birthday.birthday_id)
    await state.update_data(birthday_id=birthday_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Человека", callback_data="edit_birthday.person"),
         InlineKeyboardButton(text="Дату", callback_data="edit_birthday.date")],
        [InlineKeyboardButton(text="« Назад", callback_data="edit_birthday")]
    ])
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT person, birthday FROM birthdays WHERE birthday_id = %s", (birthday_id,))
            birthday_tuple = cursor.fetchone()
    year = "XXXX" if birthday_tuple[1].year == 1861 else birthday_tuple[1].year
    await callback.message.edit_text(f"Человек: {birthday_tuple[0]}\nДата: {birthday_tuple[1].day:02}.{birthday_tuple[1].month:02}.{year}\n\nЧто редактировать в дне рождения?", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("edit_birthday.person"))
async def edit_birthday_person_second_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await state.set_state(New_birthday.edit_person)
    await callback.message.edit_text("Напишите, как теперь мы будем его звать:")

@dp.message(New_birthday.edit_person)
async def edit_birthday_person_third_step(message: Message, state: FSMContext):
    data = await state.get_data()
    birthday_id = data["birthday_id"]
    edit_person = message.text
    await state.update_data(edit_person=edit_person)
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE birthdays SET person = %s WHERE birthday_id = %s", (edit_person, birthday_id))
    await birthday_list(message)

@dp.callback_query(F.data.startswith("edit_birthday.date"))
async def edit_birthday_date_second_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await add_birthday_second_step(callback.message, state, None, True, True)

@dp.callback_query(F.data == "delete_birthday")
async def delete_birthday_first_step(callback: CallbackQuery):
    await callback.answer("")
    await delete_birthday(message=callback.message, author=callback.from_user, edit_msg=True)

@dp.callback_query(F.data.startswith("delete_birthday_"))
async def delete_birthday_second_step(callback: CallbackQuery):
    await callback.answer("")
    delete_birthday_id = int(callback.data[16:])
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM birthdays WHERE birthday_id = %s", (delete_birthday_id, ))
    await birthday_list(callback.message, callback.from_user, edit_msg=True)

@dp.callback_query(F.data == "clear_birthday_list")
async def clear_birthday_list_first_step(callback: CallbackQuery):
    await callback.answer("")
    await clear_birthday_list(message=callback.message, author=callback.from_user, edit_msg=True)

@dp.callback_query(F.data == "back_to_birthday_list")
async def back_to_birthday_list(callback: CallbackQuery, state: FSMContext):
    await callback.answer("")
    await state.clear()
    await birthday_list(message=callback.message, author=callback.from_user, edit_msg=True)

def get_next_birthday(birthday):
    today = date.today()
    next_birthday = date(today.year, birthday.month, birthday.day)
    if next_birthday < today:
        next_birthday = date(today.year + 1, birthday.month, birthday.day)
    return next_birthday


### ----------> Основные команды <----------
@dp.message(Command(commands=["birthday_list", "bl"]))
async def birthday_list(message: Message, author=None, edit_msg=False):
    if author is None:
        author = message.from_user
    reply_method = message.edit_text if edit_msg is True else message.answer
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (author.id,))
            is_reg = cursor.fetchone()
    if is_reg is not None:  # проверка регистрации
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM birthdays WHERE user_id = %s ORDER BY birthday", (author.id,))
                birthday_tuple = cursor.fetchall()
        if birthday_tuple:
            birthday_list = []
            sorted_birthday_tuple = sorted(birthday_tuple, key=lambda row: get_next_birthday(row[2]))
            for i in range(len(sorted_birthday_tuple)):
                birthday = sorted_birthday_tuple[i][2]
                year = birthday.year if birthday.year != 1861 else "XXXX"
                birthday_list.append(f"{i + 1}) {sorted_birthday_tuple[i][1]} ({birthday.day:02}.{birthday.month:02}.{year})")
            await reply_method(f"{bl_emoji} Список дней рождения:\n" + '\n'.join(birthday_list), reply_markup=blkb)
        else:
            await reply_method(f"{bl_emoji} Ваш список дней рождения пуст", reply_markup=blkb)
    else:
        await reply_method("Сначала вам нужно пройти регистрацию, написав команду /start")

@dp.message(Command(commands=["add_birthday", "ab"]))
async def add_birthday(message: Message, state: FSMContext):
    await state.set_state(New_birthday.person)
    await message.answer("Кто виновник торжества?")

@dp.message(Command(commands=["edit_birthday", "eb"]))
async def edit_birthday(message: Message, author=None, edit_msg=False):
    if author is None:
        author = message.from_user
    reply_method = message.edit_text if edit_msg is True else message.answer
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (author.id,))
            is_reg = cursor.fetchone()
    if is_reg is not None:  # проверка регистрации
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM birthdays WHERE user_id = %s ORDER BY birthday", (author.id,))
        birthday_tuple = cursor.fetchall()
        if birthday_tuple:
            keyboard = InlineKeyboardBuilder()
            birthday_list = []
            sorted_birthday_tuple = sorted(birthday_tuple, key=lambda row: get_next_birthday(row[2]))
            for i in range(len(sorted_birthday_tuple)):
                birthday = sorted_birthday_tuple[i][2]
                year = birthday.year if birthday.year != 1861 else "XXXX"
                birthday_list.append(f"{i + 1}) {sorted_birthday_tuple[i][1]} ({birthday.day:02}.{birthday.month:02}.{year})")
                keyboard.add(InlineKeyboardButton(text=f"{i + 1}", callback_data=f"edit_birthday_{sorted_birthday_tuple[i][0]}"))
            keyboard.add(InlineKeyboardButton(text="« Назад", callback_data="back_to_birthday_list"))
            keyboard_eb = keyboard.adjust(5).as_markup()
            await reply_method(f"{bl_emoji} Список дней рождения:\n" + '\n'.join(birthday_list) + "\n\n" + "Выберите номер редактируемого дня рождения:", reply_markup=keyboard_eb)
        else:
            await reply_method(f"{bl_emoji} Ваш список дней рождения пуст", reply_markup=blkb)
    else:
        await reply_method(f"Сначала вам нужно пройти регистрацию, написав команду /start")

@dp.message(Command(commands=["delete_birthday", "db"]))
async def delete_birthday(message: Message, author=None, edit_msg=False):
    if author is None:
        author = message.from_user
    reply_method = message.edit_text if edit_msg is True else message.answer
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (author.id,))
            is_reg = cursor.fetchone()
    if is_reg is not None:  # проверка регистрации
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM birthdays WHERE user_id = %s ORDER BY birthday", (author.id,))
        birthday_tuple = cursor.fetchall()
        if birthday_tuple:
            keyboard = InlineKeyboardBuilder()
            birthday_list = []
            sorted_birthday_tuple = sorted(birthday_tuple, key=lambda row: get_next_birthday(row[2]))
            for i in range(len(sorted_birthday_tuple)):
                birthday = sorted_birthday_tuple[i][2]
                year = birthday.year if birthday.year != 1861 else "XXXX"
                birthday_list.append(f"{i + 1}) {sorted_birthday_tuple[i][1]} ({birthday.day:02}.{birthday.month:02}.{year})")
                keyboard.add(InlineKeyboardButton(text=f"{i + 1}", callback_data=f"delete_birthday_{sorted_birthday_tuple[i][0]}"))  # добавление кнопок
            keyboard.add(InlineKeyboardButton(text="« Назад", callback_data="back_to_birthday_list"))  # добавление кнопок
            keyboard_db = keyboard.adjust(5).as_markup()  # форматирование позиций кнопок
            await reply_method(f"{bl_emoji} Список дней рождения:\n" + '\n'.join(birthday_list) + "\n\n" + "Выберите номер удаляемого дня рождения:", reply_markup=keyboard_db)
        else:
            await reply_method(f"{bl_emoji} Ваш список дней рождения пуст", reply_markup=blkb)
    else:
        await reply_method(f"Сначала вам нужно пройти регистрацию, написав команду /start")

@dp.message(Command(commands=["clear_birthday_list", "cbl"]))
async def clear_birthday_list(message: Message, author=None, edit_msg=False):
    if author is None:
        author = message.from_user
    reply_method = message.edit_text if edit_msg is True else message.answer
    if message.text != f"{bl_emoji} Ваш список дней рождения пуст":
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (author.id,))
                if cursor.fetchone() is not None:
                    cursor.execute("SELECT 1 FROM birthdays WHERE user_id = %s LIMIT 1", (author.id,))
                    if cursor.fetchone() is not None:
                        cursor.execute(f"DELETE FROM birthdays WHERE user_id = %s", (author.id,))
                    await reply_method(f"{bl_emoji} Ваш список дней рождения пуст", reply_markup=blkb)
                else:
                    await reply_method(f"Сначала вам нужно пройти регистрацию, написав команду /start")

######
@dp.message(Command(commands=["my_tasks"]))
async def my_tasks(message: Message):
    author = message.from_user
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT t.task_id, t.task, t.user_id, r.reminder_id, r.remind_at, r.daily, r.yearly FROM tasks "
                           f"AS t LEFT JOIN reminders AS r ON t.task_id = r.task_id AND t.user_id = %s", (author.id,))
            data = cursor.fetchall()
    features = ["task_id", "task", "user_id", "reminder_id", "remind_at", "daily", "yearly"]
    df = pd.DataFrame(data, columns=features)
    if 'remind_at' in df.columns:
        df['remind_at'] = pd.to_datetime(df['remind_at']).dt.tz_localize(None)
    filename = f'my_tasks_{author.id}_{message.message_id}.xlsx'
    df.to_excel(filename, index=False, engine='openpyxl')
    excel_file = FSInputFile(filename)
    await bot.send_document(chat_id=author.id, document=excel_file)
#######



### -----------> Запуск бота <-----------
async def main():
    try:
        scheduler.add_job(check_reminders, 'interval', seconds=interval_check_reminders)  # Запускаем проверку каждую минуту
        scheduler.start()
        await dp.start_polling(bot)
    finally:
        pass

if __name__ == "__main__":
    asyncio.run(main())