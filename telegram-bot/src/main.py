# main.py
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from handlers.image_handlers import register_image_handlers
from handlers.message_handlers import register_message_handlers
from libs.kafka_producer import KafkaProducerWrapper
from libs.kafka_consumer import KafkaConsumerWrapper
from libs.minio_client import MinioClient
from libs.kafka_config import KafkaConfig
import os
from dotenv import load_dotenv
import signal
from typing import Dict, Any

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AppState:
    bot: Bot = None
    dp: Dispatcher = None
    kafka_producer: KafkaProducerWrapper = None
    kafka_consumer: KafkaConsumerWrapper = None
    minio_client: MinioClient = None
    handlers_registered: bool = False

async def initialize_clients():
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            # Инициализация бота и диспетчера
            if not AppState.bot:
                token = os.getenv("BOT_TOKEN")
                if not token:
                    raise ValueError("BOT_TOKEN не найден в переменных окружения")
                logger.info(f"Инициализация бота с токеном: {token[:5]}...")
                AppState.bot = Bot(token=token)
                logger.info("Бот успешно инициализирован")
            
            if not AppState.dp:
                logger.info("Инициализация диспетчера...")
                AppState.dp = Dispatcher(storage=MemoryStorage())
                logger.info("Диспетчер успешно инициализирован")

            # Инициализация Kafka
            if not AppState.kafka_producer or not AppState.kafka_consumer:
                kafka_config = KafkaConfig(
                    bootstrap_servers=os.getenv("KAFKA_BROKERS").split(","),
                    topic_inference=os.getenv("KAFKA_TOPIC_REQUESTS", "image_requests"),
                    topic_results=os.getenv("KAFKA_TOPIC_RESULTS", "image_results"),
                    group_id=os.getenv("KAFKA_GROUP_ID", "telegram-bot-group")
                )
                
                AppState.kafka_producer = KafkaProducerWrapper(
                    bootstrap_servers=kafka_config.bootstrap_servers,
                    config=kafka_config
                )
                
                AppState.kafka_consumer = KafkaConsumerWrapper(
                    topic=kafka_config.topic_results,
                    bootstrap_servers=kafka_config.bootstrap_servers,
                    group_id=kafka_config.group_id,
                    config=kafka_config
                )
                logger.info("Kafka клиенты успешно инициализированы")

            # Инициализация MinIO
            if not AppState.minio_client:
                AppState.minio_client = MinioClient(
                    endpoint=os.getenv("MINIO_ENDPOINT"),
                    access_key=os.getenv("MINIO_ACCESS_KEY"),
                    secret_key=os.getenv("MINIO_SECRET_KEY"),
                    secure=os.getenv("MINIO_SECURE", "false").lower() == "true"
                )
                logger.info("MinIO клиент успешно инициализирован")

            return True
        
        except Exception as e:
            logger.error(f"Попытка {attempt+1} не удалась: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
            else:
                raise

async def register_handlers():
    """Регистрация всех обработчиков"""
    if not AppState.handlers_registered:
        # Сначала регистрируем обработчики сообщений
        register_message_handlers(AppState.dp)
        
        # Затем регистрируем обработчики изображений
        kafka_config = KafkaConfig(
            bootstrap_servers=os.getenv("KAFKA_BROKERS").split(","),
            topic_inference=os.getenv("KAFKA_TOPIC_REQUESTS", "image_requests"),
            topic_results=os.getenv("KAFKA_TOPIC_RESULTS", "image_results"),
            group_id=os.getenv("KAFKA_GROUP_ID", "telegram-bot-group")
        )
        
        register_image_handlers(
            AppState.dp,
            AppState.kafka_producer,
            AppState.minio_client,
            kafka_config
        )
        AppState.handlers_registered = True
        logger.info("Handlers registered")

async def process_results():
    while True:
        try:
            if not AppState.kafka_consumer or not AppState.minio_client or not AppState.bot:
                await initialize_clients()

            async for msg in AppState.kafka_consumer:
                try:
                    async with asyncio.timeout(30):
                        await process_single_result(msg)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
        except Exception as e:
            logger.error(f"Results loop error: {e}")
            await asyncio.sleep(5)

async def process_single_result(msg: Dict[str, Any]):
    temp_path = None
    try:
        user_id = msg["user_id"]
        result_path = msg["result_path"]
        detections = msg["detections"]

        temp_path = f"/app/temp/{result_path}"
        if not await AppState.minio_client.download_file(result_path, temp_path):
            logger.error(f"Download failed: {result_path}")
            return False

        result_text = "Результаты:\n" + "\n".join(
            f"- {d['class_name']} ({d['confidence']:.2f})" for d in detections
        )

        with open(temp_path, 'rb') as photo:
            await AppState.bot.send_photo(user_id, photo, caption=result_text)
            
        return True
    except Exception as e:
        logger.error(f"Processing error: {e}")
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

async def shutdown():
    logger.info("Shutting down...")
    try:
        if AppState.kafka_producer:
            await AppState.kafka_producer.close()
        if AppState.kafka_consumer:
            await AppState.kafka_consumer.close()
        if AppState.bot:
            await AppState.bot.session.close()
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

async def main():
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    try:
        logger.info("Запуск инициализации клиентов...")
        await initialize_clients()
        logger.info("Регистрация обработчиков...")
        await register_handlers()
        logger.info("Запуск обработки результатов...")
        results_task = asyncio.create_task(process_results())
        logger.info("Запуск поллинга бота...")
        await AppState.dp.start_polling(AppState.bot)
        await results_task
    except Exception as e:
        logger.error(f"Ошибка в main: {e}")
    finally:
        await shutdown()

if __name__ == "__main__":
    asyncio.run(main())