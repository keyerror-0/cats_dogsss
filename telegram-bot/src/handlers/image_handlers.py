import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
import os
from libs.kafka_config import KafkaConfig
from collections import defaultdict
import time
from PIL import Image
import io
from dotenv import load_dotenv

load_dotenv()

router = Router()
logger = logging.getLogger(__name__)

# Ограничения
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_REQUESTS_PER_MINUTE = 5
ALLOWED_FORMATS = ['JPEG', 'PNG']

# Счетчик запросов пользователей
user_requests = defaultdict(list)

# Проверка существования директории
if not os.path.exists('temp'):
    os.makedirs('temp')

def is_rate_limited(user_id: int) -> bool:
    """Проверяет, не превышен ли лимит запросов"""
    current_time = time.time()
    # Удаляем старые запросы
    user_requests[user_id] = [t for t in user_requests[user_id] if current_time - t < 60]
    return len(user_requests[user_id]) >= MAX_REQUESTS_PER_MINUTE

def register_image_handlers(dp, kafka_producer, minio_client, kafka_config):
    """Регистрация обработчиков изображений"""
    @router.message(F.photo)
    async def handle_photo(message: Message):
        """Обработка загруженного фото"""
        user_id = message.from_user.id
        
        # Проверка лимита запросов
        if is_rate_limited(user_id):
            await message.reply("Слишком много запросов. Пожалуйста, подождите минуту.")
            return

        try:
            # Получаем файл фото
            photo = message.photo[-1]
            file = await message.bot.get_file(photo.file_id)
            
            # Скачиваем фото
            file_path = f"temp/{photo.file_id}.jpg"
            await message.bot.download_file(file.file_path, file_path)
            
            # Загружаем в MinIO
            minio_path = f"uploads/{photo.file_id}.jpg"
            if not await minio_client.upload_file(file_path, minio_path):
                await message.answer("Ошибка при загрузке изображения")
                return
            
            # Отправляем в Kafka
            await kafka_producer.send_message(
                topic=kafka_config.topic_inference,
                value={
                    "user_id": message.from_user.id,
                    "image_path": minio_path
                }
            )
            
            await message.answer("Изображение получено, обрабатываю...")
            
        except Exception as e:
            logger.error(f"Error processing photo: {e}")
            await message.answer("Произошла ошибка при обработке изображения")
        finally:
            # Удаляем временный файл
            if os.path.exists(file_path):
                os.remove(file_path)

    dp.include_router(router) 