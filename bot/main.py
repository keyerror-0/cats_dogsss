import os
import json
import logging
import asyncio
import threading
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from minio import Minio
from confluent_kafka import Producer, Consumer

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# Инициализация клиентов
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

kafka_producer = Producer({
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
    'message.send.max.retries': 3
})

# Инициализация бота
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Клавиатура для обратной связи
feedback_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🐶 Собака")],
        [KeyboardButton(text="🐱 Кошка")],
        [KeyboardButton(text="❌ Не кошка, не собака")],
        [KeyboardButton(text="🤷 Не знаю")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Состояния пользователей
user_states = {}

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer("Отправьте фото животного для детекции!")

@dp.message(lambda msg: msg.photo)
async def handle_photo(message: types.Message):
    try:
        file_id = message.photo[-1].file_id
        file = await bot.get_file(file_id)
        
        if file.file_size > MAX_FILE_SIZE:
            await message.answer("❌ Изображение слишком большое (макс. 5МБ)")
            return
        
        downloaded = await bot.download_file(file.file_path)
        image_bytes = downloaded.read()
        
        # Сохранение в MinIO
        file_name = f"user_{message.from_user.id}_{file_id}.jpg"
        minio_client.put_object(
            bucket_name="uploads",
            object_name=file_name,
            data=io.BytesIO(image_bytes),
            length=len(image_bytes),
            content_type='image/jpeg'
        )
        
        # Отправка задачи в Kafka
        task = {
            "user_id": message.from_user.id,
            "file_name": file_name,
            "bucket": "uploads"
        }
        kafka_producer.produce(
            "detection-tasks",
            value=json.dumps(task).encode("utf-8")
        )
        kafka_producer.flush()
        
        # Сохраняем состояние пользователя
        user_states[message.from_user.id] = {
            "file_name": file_name,
            "awaiting_feedback": True
        }
        
        await message.answer(
            "🔄 Изображение принято в обработку!\n"
            "После получения результата, пожалуйста, укажите что изображено на фото:",
            reply_markup=feedback_keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки изображения: {e}")
        await message.answer("❌ Ошибка обработки изображения")

@dp.message(F.text.in_(["🐶 Собака", "🐱 Кошка", "❌ Не кошка, не собака", "🤷 Не знаю"]))
async def handle_feedback(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_states or not user_states[user_id]["awaiting_feedback"]:
        await message.answer("Пожалуйста, сначала отправьте изображение")
        return
    
    file_name = user_states[user_id]["file_name"]
    
    # Определяем класс на основе выбора пользователя
    if message.text == "🐶 Собака":
        true_class = 1
    elif message.text == "🐱 Кошка":
        true_class = 0
    elif message.text == "❌ Не кошка, не собака":
        true_class = 2
    else:  # "🤷 Не знаю"
        await message.answer(
            "Спасибо! Ваш ответ не будет использован для обучения модели.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        del user_states[user_id]
        return
    
    # Отправка обратной связи в Kafka
    feedback = {
        "user_id": user_id,
        "file_name": file_name,
        "true_class": true_class,
        "is_correction": True  # Всегда считаем это коррекцией
    }
    
    kafka_producer.produce(
        "feedback-tasks",
        value=json.dumps(feedback).encode("utf-8")
    )
    kafka_producer.flush()
    
    await message.answer(
        "Спасибо за обратную связь! Ваши данные помогут улучшить модель.",
        reply_markup=types.ReplyKeyboardRemove()
    )
    del user_states[user_id]

async def main():
    # Создание бакетов
    for bucket in ["uploads"]:
        if not minio_client.bucket_exists(bucket):
            minio_client.make_bucket(bucket)
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())