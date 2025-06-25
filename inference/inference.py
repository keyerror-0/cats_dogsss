import os
import io
import json
import logging
import numpy as np
from minio import Minio
from confluent_kafka import Consumer, Producer
from PIL import Image
import torch
import torch.nn as nn
from torchvision import transforms, models
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Конфигурация
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
MODEL_WEIGHTS_PATH = "mobilenetv2_weights.pth"
MODEL_WEIGHTS_BUCKET = "model-weights"  # Бакет для хранения весов
CLASS_NAMES = ["кошка", "собака", "не животное"]

# Инициализация клиентов
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

kafka_producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})

# Переменная для хранения времени последнего обновления весов
last_weights_update = None

def load_latest_weights():
    """Загружает последние веса модели из MinIO"""
    global last_weights_update
    try:
        # Проверяем существование бакета
        if not minio_client.bucket_exists(MODEL_WEIGHTS_BUCKET):
            logger.warning(f"Bucket {MODEL_WEIGHTS_BUCKET} does not exist")
            return False

        # Получаем список всех файлов весов
        objects = minio_client.list_objects(MODEL_WEIGHTS_BUCKET, recursive=True)
        weight_files = [obj.object_name for obj in objects]
        
        if not weight_files:
            logger.warning("No weights found in MinIO bucket")
            return False
        
        # Сортируем по имени (предполагаем, что в имени есть timestamp)
        latest_weights = sorted(weight_files)[-1]
        
        # Скачиваем файл
        minio_client.fget_object(
            MODEL_WEIGHTS_BUCKET,
            latest_weights,
            MODEL_WEIGHTS_PATH
        )
        
        last_weights_update = datetime.now()
        logger.info(f"Loaded latest weights from MinIO: {latest_weights}")
        return True
    except Exception as e:
        logger.error(f"Failed to load weights from MinIO: {e}")
        return False

def check_and_update_weights():
    """Проверяет и обновляет веса модели, если прошло достаточно времени"""
    global last_weights_update, model
    
    # Если веса никогда не обновлялись или прошло больше 5 минут с последнего обновления
    if last_weights_update is None or (datetime.now() - last_weights_update) > timedelta(seconds=1):
        logger.info("Checking for updated model weights...")
        if load_latest_weights():
            try:
                # Перезагружаем модель с новыми весами
                model.load_state_dict(torch.load(MODEL_WEIGHTS_PATH))
                model.eval()
                logger.info("Model weights updated successfully")
            except Exception as e:
                logger.error(f"Failed to reload model with new weights: {e}")

# Инициализация модели
try:
    logger.info("Initializing MobileNetV2 model...")
    for param in model.features.parameters():
        param.requires_grad = False
    model = models.mobilenet_v2(weights=None)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, 3)
    
    # Пытаемся загрузить веса из MinIO
    if load_latest_weights() or os.path.exists(MODEL_WEIGHTS_PATH):
        model.load_state_dict(torch.load(MODEL_WEIGHTS_PATH))
        logger.info("Model weights loaded successfully")
    else:
        logger.warning("No pretrained weights found, using random initialization")
    
    model.eval()
    logger.info("Model initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize model: {e}")
    exit(1)

# Трансформеры для изображений
transform = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

def get_predicted_class(image_tensor):
    """Определяет класс изображения с помощью MobileNetV2"""
    with torch.no_grad():
        outputs = model(image_tensor.unsqueeze(0))
        _, predicted = torch.max(outputs, 1)
        return predicted.item()

def process_image(file_name: str, bucket: str, user_id: int):
    try:
        # Проверяем обновления весов перед обработкой
        check_and_update_weights()
        
        # Загрузка изображения
        response = minio_client.get_object(bucket, file_name)
        image_data = response.read()
        image = Image.open(io.BytesIO(image_data))
        
        # Преобразование изображения
        image_tensor = transform(image)
        
        # Классификация
        predicted_class = get_predicted_class(image_tensor)
        
        # Создание аннотированного изображения (просто подпись)
        img_pil = image.copy()
        
        # Сохранение результата
        output_name = f"processed_{file_name}"
        img_byte_arr = io.BytesIO()
        img_pil.save(img_byte_arr, format='JPEG')
        img_byte_arr.seek(0)
        
        minio_client.put_object(
            bucket_name="processed",
            object_name=output_name,
            data=img_byte_arr,
            length=img_byte_arr.getbuffer().nbytes,
            content_type='image/jpeg'
        )
        
        # Отправка результата обработки
        processing_result = {
            "user_id": user_id,
            "original_file": file_name,
            "processed_file": output_name,
            "predicted_class": predicted_class,
            "class_name": CLASS_NAMES[predicted_class]
        }
        kafka_producer.produce(
            "processing-results",
            value=json.dumps(processing_result).encode("utf-8")
        )
        
        # Отправка запроса на обратную связь
        feedback_request = {
            "user_id": user_id,
            "file_name": file_name,
            "predicted_class": predicted_class,
            "class_name": CLASS_NAMES[predicted_class]
        }
        kafka_producer.produce(
            "feedback-requests",
            value=json.dumps(feedback_request).encode("utf-8")
        )
        
        kafka_producer.flush()
        logger.info(f"Обработано: {file_name}, класс: {CLASS_NAMES[predicted_class]}")
    except Exception as e:
        logger.error(f"Ошибка обработки {file_name}: {e}")
    finally:
        response.close()
        response.release_conn()

def main():
    # Создание необходимых бакетов
    for bucket in ["uploads", "processed"]:
        if not minio_client.bucket_exists(bucket):
            minio_client.make_bucket(bucket)
    
    # Создаем бакет для весов, если его нет
    if not minio_client.bucket_exists(MODEL_WEIGHTS_BUCKET):
        minio_client.make_bucket(MODEL_WEIGHTS_BUCKET)

    # Конфигурация Kafka Consumer
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "group.id": "inference-group",
        "auto.offset.reset": "earliest"
    })
    consumer.subscribe(["detection-tasks"])

    logger.info("Слушаем задачи из Kafka...")
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            logger.error(f"Ошибка Kafka: {msg.error()}")
            continue
        
        try:
            task = json.loads(msg.value().decode("utf-8"))
            process_image(
                task["file_name"],
                task["bucket"],
                task["user_id"])
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")

if __name__ == "__main__":
    main()