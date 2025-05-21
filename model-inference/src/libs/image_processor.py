import logging
from typing import Dict, Any
import numpy as np
from PIL import Image
import io
import torch
from ultralytics import YOLO

class ImageProcessor:
    def __init__(self):
        self.model = YOLO('yolov8n.pt')
        logging.info("Image processor initialized with YOLOv8 model")

    async def process_image(self, image_data: bytes) -> Dict[str, Any]:
        """Обрабатывает изображение и возвращает результат классификации"""
        try:
            # Преобразование байтов в изображение
            image = Image.open(io.BytesIO(image_data))
            
            # Выполнение инференса
            results = self.model(image)
            
            # Обработка результатов
            result = results[0]
            boxes = result.boxes
            
            # Подсчет объектов
            cat_count = 0
            dog_count = 0
            
            for box in boxes:
                cls = int(box.cls[0])
                conf = float(box.conf[0])
                
                # Проверяем, является ли объект кошкой (класс 15) или собакой (класс 16)
                if cls == 15 and conf > 0.5:  # Кошка
                    cat_count += 1
                elif cls == 16 and conf > 0.5:  # Собака
                    dog_count += 1
            
            return {
                'cat_count': cat_count,
                'dog_count': dog_count,
                'total_objects': len(boxes)
            }
            
        except Exception as e:
            logging.error(f"Error processing image: {e}")
            raise 