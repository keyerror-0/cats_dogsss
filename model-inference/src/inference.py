from ultralytics import YOLO
from libs.minio_client import MinioClient
from libs.kafka_producer import KafkaProducerWrapper
from libs.kafka_consumer import KafkaConsumerWrapper
import torch
import cv2
import numpy as np
from typing import List, Dict, Any
import logging
import os
import asyncio
import time

logger = logging.getLogger(__name__)

async def wait_for_kafka(max_retries: int = 5, retry_delay: int = 5):
    """Ожидание готовности Kafka"""
    for i in range(max_retries):
        try:
            # Здесь можно добавить проверку доступности Kafka
            await asyncio.sleep(retry_delay)
            logger.info(f"Попытка подключения к Kafka {i + 1}/{max_retries}")
        except Exception as e:
            logger.error(f"Ошибка при подключении к Kafka: {e}")
            if i == max_retries - 1:
                raise
            await asyncio.sleep(retry_delay)

async def process_image(image_path: str, model: YOLO) -> List[Dict[str, Any]]:
    """Обработка изображения с помощью модели YOLO"""
    try:
        results = model(image_path)
        detections = []
        
        # Классы для кошек и собак в YOLOv8
        CAT_CLASS = 15  # индекс класса кошки
        DOG_CLASS = 16  # индекс класса собаки
        
        for pred in results[0].boxes.data:
            x1, y1, x2, y2, conf, cls = pred.tolist()
            class_id = int(cls)
            
            # Обрабатываем только кошек и собак
            if class_id in [CAT_CLASS, DOG_CLASS]:
                detections.append({
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "confidence": float(conf),
                    "class": class_id,
                    "class_name": "cat" if class_id == CAT_CLASS else "dog"
                })
        
        return detections
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        raise

class InferenceService:
    def __init__(self):
        self.model = YOLO('/app/models/yolov8n.pt')
        self.minio = MinioClient(
            endpoint=os.getenv("MINIO_ENDPOINT"),
            access_key=os.getenv("MINIO_ACCESS_KEY"),
            secret_key=os.getenv("MINIO_SECRET_KEY"),
            secure=os.getenv("MINIO_SECURE", "false").lower() == "true"
        )
        
        # Инициализация Kafka с повторными попытками
        max_retries = 3
        retry_delay = 5
        
        for i in range(max_retries):
            try:
                self.consumer = KafkaConsumerWrapper(
                    topic="image_inference",
                    bootstrap_servers=[os.getenv("KAFKA_BROKERS", "kafka:9092")],
                    group_id="model_inference_group"
                )
                self.producer = KafkaProducerWrapper(
                    bootstrap_servers=[os.getenv("KAFKA_BROKERS", "kafka:9092")]
                )
                break
            except Exception as e:
                logger.error(f"Ошибка при инициализации Kafka (попытка {i + 1}/{max_retries}): {e}")
                if i == max_retries - 1:
                    raise
                time.sleep(retry_delay)

    async def process_messages(self):
        while True:
            try:
                async for msg in self.consumer:
                    try:
                        file_id = msg["image_id"]
                        user_id = msg["user_id"]
                        
                        # Загрузка изображения
                        temp_path = f"/app/temp/{file_id}.jpg"
                        success = await self.minio.download_file(
                            object_name=file_id,
                            file_path=temp_path
                        )
                        
                        if not success:
                            logger.error(f"Failed to download image {file_id}")
                            continue
                        
                        # Обработка
                        detections = await process_image(temp_path, self.model)
                        
                        # Сохранение результатов
                        result_path = f"/app/temp/{file_id}_result.jpg"
                        self.draw_boxes(temp_path, detections, result_path)
                        
                        # Загрузка результата в MinIO
                        result_object = f"{file_id}_result.jpg"
                        await self.minio.upload_file(
                            file_path=result_path,
                            object_name=result_object
                        )
                        
                        # Отправка результата в Kafka
                        await self.producer.send_message(
                            topic="inference_results",
                            message={
                                "image_id": file_id,
                                "user_id": user_id,
                                "result_path": result_object,
                                "detections": detections
                            }
                        )
                        
                        # Очистка временных файлов
                        os.remove(temp_path)
                        os.remove(result_path)
                        
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
            except Exception as e:
                logger.error(f"Error in message processing loop: {e}")
                await asyncio.sleep(5)  # Пауза перед повторной попыткой

    def draw_boxes(self, image_path: str, detections: List[Dict[str, Any]], output_path: str):
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
    # Ждем готовности Kafka
    await wait_for_kafka()
    
    service = InferenceService()
    await service.process_messages()

if __name__ == "__main__":
    asyncio.run(main())