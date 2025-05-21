import asyncio
import logging
from libs.kafka_consumer import KafkaConsumerWrapper
from libs.kafka_producer import KafkaProducerWrapper
from libs.kafka_config import KafkaConfig
from libs.image_processor import ImageProcessor
from libs.minio_client import MinioClient
import os
from dotenv import load_dotenv
import cv2

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class InferenceService:
    def __init__(self):
        # Создаем временную директорию
        os.makedirs("/app/temp", exist_ok=True)
        
        self.image_processor = ImageProcessor()
        self.minio_client = MinioClient(
            endpoint=os.getenv("MINIO_ENDPOINT"),
            access_key=os.getenv("MINIO_ACCESS_KEY"),
            secret_key=os.getenv("MINIO_SECRET_KEY"),
            secure=os.getenv("MINIO_SECURE", "false").lower() == "true"
        )
        
        self.kafka_config = KafkaConfig(
            bootstrap_servers=os.getenv("KAFKA_BROKERS", "kafka:9092").split(","),
            topic_inference=os.getenv("KAFKA_TOPIC_REQUESTS", "image_requests"),
            topic_results=os.getenv("KAFKA_TOPIC_RESULTS", "image_results"),
            group_id=os.getenv("KAFKA_GROUP_ID", "model_inference_group")
        )
        
        self.consumer = KafkaConsumerWrapper(
            topic=self.kafka_config.topic_inference,
            config=self.kafka_config
        )
        
        self.producer = KafkaProducerWrapper(
            bootstrap_servers=self.kafka_config.bootstrap_servers,
            config=self.kafka_config
        )

    async def process_messages(self):
        while True:
            try:
                async for msg in self.consumer:
                    temp_path = None
                    result_path = None
                    try:
                        file_id = msg["image_id"]
                        user_id = msg["user_id"]
                        
                        # Загрузка изображения
                        temp_path = f"/app/temp/{file_id}.jpg"
                        success = await self.minio_client.download_file(
                            object_name=file_id,
                            file_path=temp_path
                        )
                        
                        if not success:
                            logger.error(f"Failed to download image {file_id}")
                            continue
                        
                        # Обработка изображения
                        with open(temp_path, 'rb') as f:
                            image_data = f.read()
                        
                        result = await self.image_processor.process_image(image_data)
                        
                        if not result["success"]:
                            logger.error(f"Failed to process image: {result['error']}")
                            continue
                        
                        # Сохранение результата
                        result_path = f"/app/temp/{file_id}_result.jpg"
                        self.draw_boxes(temp_path, result["detections"], result_path)
                        
                        # Загрузка результата в MinIO
                        result_object = f"{file_id}_result.jpg"
                        await self.minio_client.upload_file(
                            file_path=result_path,
                            object_name=result_object
                        )
                        
                        # Отправка результата
                        await self.producer.send_message(
                            topic=self.kafka_config.topic_results,
                            message={
                                "image_id": file_id,
                                "user_id": user_id,
                                "result_path": result_object,
                                "detections": result["detections"]
                            }
                        )
                        
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                    finally:
                        # Очистка временных файлов
                        for path in [temp_path, result_path]:
                            if path and os.path.exists(path):
                                try:
                                    os.remove(path)
                                except Exception as e:
                                    logger.error(f"Error removing temporary file {path}: {e}")
            except Exception as e:
                logger.error(f"Error in message processing loop: {e}")
                await asyncio.sleep(5)

    def draw_boxes(self, image_path: str, detections: list, output_path: str):
        """Отрисовка боксов на изображении"""
        try:
            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"Could not load image: {image_path}")

            for det in detections:
                x1, y1, x2, y2 = map(int, det["bbox"])
                conf = det["confidence"]
                class_name = det["class_name"]
                
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label = f"{class_name}: {conf:.2f}"
                cv2.putText(image, label, (x1, y1 - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            cv2.imwrite(output_path, image)
            logger.info(f"Image with boxes saved to: {output_path}")

        except Exception as e:
            logger.error(f"Error drawing boxes: {e}")
            raise

async def main():
    try:
        service = InferenceService()
        await service.process_messages()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())