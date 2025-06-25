import os
import json
import logging
import asyncio
from minio import Minio
from confluent_kafka import Consumer
from telegram import Bot
from telegram.error import TelegramError

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Инициализация клиентов
minio_client = Minio(
    os.getenv("MINIO_ENDPOINT"),
    access_key=os.getenv("MINIO_ACCESS_KEY"),
    secret_key=os.getenv("MINIO_SECRET_KEY"),
    secure=False
)

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))

dictionary={0:"🐱 Кошка", 1:"🐶 Собака", 2: "❌ Не кошка, не собака"}

async def send_result(user_id: int, processed_file: str, predicted_class: int):
    try:
        # Загрузка изображения из MinIO
        response = minio_client.get_object("processed", processed_file)
        image_data = response.read()
        
        # Отправка через Telegram
        await bot.send_photo(
            chat_id=user_id,
            photo=image_data,
            caption=f"✅ Обработанное изображение\n"+str(dictionary[predicted_class])
        )
        logger.info(f"Отправлен результат пользователю {user_id}")
    except TelegramError as e:
        logger.error(f"Ошибка Telegram: {e}")
    except Exception as e:
        logger.error(f"Общая ошибка: {e}")
    finally:
        response.close()
        response.release_conn()

async def consume_messages():
    """Асинхронная обработка сообщений из Kafka"""
    consumer = Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS"),
        "group.id": "notification-group",
        "auto.offset.reset": "earliest"
    })
    consumer.subscribe(["processing-results"])

    logger.info("Слушаем результаты обработки...")
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            await asyncio.sleep(1)
            continue
        if msg.error():
            logger.error(f"Ошибка Kafka: {msg.error()}")
            continue
        
        try:
            result = json.loads(msg.value().decode("utf-8"))
            await send_result(
                result["user_id"],
                result["processed_file"],
                result["predicted_class"]
            )
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка декодирования JSON: {e}")
        except KeyError as e:
            logger.error(f"Отсутствует поле в сообщении: {e}")
        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")

if __name__ == "__main__":
    # Создание бакета при необходимости
    if not minio_client.bucket_exists("processed"):
        minio_client.make_bucket("processed")

    # Запуск асинхронного цикла
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(consume_messages())
    except KeyboardInterrupt:
        logger.info("Остановка сервиса...")
    finally:
        loop.close()