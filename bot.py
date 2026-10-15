import asyncio
import logging
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "8804208066:AAGbH3fOrC3czsszp_im9XwFoaJpslsU5ss"  # Вставь сюда токен, который дал BotFather
SITE_URL = "https://www.tspk-mo.ru/student/timetable"

# База данных пользователей в памяти
# Структура: { user_id: "Корпус" }
users_db = {}

# Хранилище последних отправленных ссылок, чтобы не дублировать рассылку
last_schedules = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

logging.basicConfig(level=logging.INFO)

# ================= КЛАВИАТУРЫ =================
def get_buildings_keyboard():
    builder = ReplyKeyboardBuilder()
    # При необходимости можно скорректировать названия корпусов под ваш колледж
    builder.button(text="Корпус 1")
    builder.button(text="Корпус 2")
    builder.button(text="Корпус 3")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# ================= ХЕНДЛЕРЫ БОТА =================
@dp.message(CommandStart())
async def start_handler(message: types.Message):
    welcome_text = (
        "👋 **Привет!**\n\n"
        "🔔 **ВАЖНО:** Пожалуйста, **включите уведомления** для этого бота, "
        "чтобы вовремя получать свежее расписание на завтра!\n\n"
        "Выберите ваш корпус ниже 👇"
    )
    
    await message.answer(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_buildings_keyboard()
    )

@dp.message(F.text.in_({"Корпус 1", "Корпус 2", "Корпус 3"}))
async def select_building_handler(message: types.Message):
    user_id = message.from_user.id
    selected_building = message.text
    
    users_db[user_id] = selected_building
    
    await message.answer(
        f"✅ Выбран корпус: **{selected_building}**\n"
        "Ищу актуальное расписание...",
        parse_mode="Markdown"
    )
    
    await check_and_send_schedule_for_user(user_id, selected_building)

async def check_and_send_schedule_for_user(user_id: int, building: str):
    schedule_data = fetch_schedule_from_site(building)
    
    if schedule_data:
        file_url, _ = schedule_data
        caption_text = "Расписание!"
        
        try:
            if file_url.lower().endswith(('.png', '.jpg', '.jpeg')):
                await bot.send_photo(chat_id=user_id, photo=file_url, caption=caption_text)
            else:
                await bot.send_document(chat_id=user_id, document=file_url, caption=caption_text)
        except Exception as e:
            logging.error(f"Ошибка отправки файла пользователю {user_id}: {e}")
            await bot.send_message(user_id, f"Найдено расписание: {file_url}\n\nРасписание!")
    else:
        await bot.send_message(
            user_id, 
            "⚠️ На сайте пока нет свежего расписания на завтра."
        )

# ================= ПАРСИНГ САЙТА =================
def fetch_schedule_from_site(building: str):
    """
    Парсит страницу расписания колледжа и ищет файл на завтрашний день.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(SITE_URL, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Дата завтрашнего дня в формате ДД.ММ
        tomorrow = datetime.now() + timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%d.%m")
        
        links = soup.find_all('a', href=True)
        
        # Сначала ищем строго по завтрашней дате и корпусу
        for link in links:
            href = link['href']
            text = link.get_text()
            
            if building.lower() in text.lower() or building.lower() in href.lower():
                if tomorrow_str in text or tomorrow_str in href:
                    full_url = href if href.startswith('http') else f"https://www.tspk-mo.ru{href}"
                    return full_url, text.strip()
                    
        # Запасной вариант: ищем актуальный файл по корпусу, если по дате точного совпадения нет
        for link in links:
            href = link['href']
            text = link.get_text()
            if building.lower() in text.lower() and (any(ext in href.lower() for ext in ['.pdf', '.jpg', '.png', '.docx'])):
                full_url = href if href.startswith('http') else f"https://www.tspk-mo.ru{href}"
                return full_url, text.strip()

    except Exception as e:
        logging.error(f"Ошибка при парсинге сайта: {e}")
        
    return None

# ================= АВТОМАТИЧЕСКАЯ ПРОВЕРКА =================
async def auto_check_schedules():
    """Фоновая задача: проверяет обновления каждые 15 минут."""
    logging.info("Фоновая проверка расписания...")
    
    active_buildings = set(users_db.values())
    
    for building in active_buildings:
        schedule_data = fetch_schedule_from_site(building)
        if schedule_data:
            file_url, _ = schedule_data
            
            # Если ссылка изменилась (появилось новое расписание)
            if last_schedules.get(building) != file_url:
                last_schedules[building] = file_url
                
                # Рассылаем всем пользователям этого корпуса
                for user_id, user_building in users_db.items():
                    if user_building == building:
                        try:
                            caption_text = "Расписание!"
                            if file_url.lower().endswith(('.png', '.jpg', '.jpeg')):
                                await bot.send_photo(chat_id=user_id, photo=file_url, caption=caption_text)
                            else:
                                await bot.send_document(chat_id=user_id, document=file_url, caption=caption_text)
                        except Exception as e:
                            logging.error(f"Ошибка авторассылки для {user_id}: {e}")

# ================= ЗАПУСК =================
async def main():
    scheduler.add_job(auto_check_schedules, 'interval', minutes=15)
    scheduler.start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
