import os
import json
import logging
import io
import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import transforms, models
from PIL import Image
from minio import Minio
from confluent_kafka import Consumer
import numpy as np
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Проверка переменных окружения
def get_env_var(name):
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"Environment variable {name} is not set")
    return value

# Конфигурация
try:
    MINIO_ENDPOINT = get_env_var("MINIO_ENDPOINT")
    MINIO_ACCESS_KEY = get_env_var("MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY = get_env_var("MINIO_SECRET_KEY")
    KAFKA_BOOTSTRAP_SERVERS = get_env_var("KAFKA_BOOTSTRAP_SERVERS")
    MODEL_WEIGHTS_PATH = "model_weights.pth"
    MODEL_WEIGHTS_BUCKET = "model-weights"  # Бакет для хранения весов
except ValueError as e:
    logger.error(str(e))
    exit(1)

# Инициализация клиента MinIO
try:
    minio_client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )
    
    # Создаем бакет для весов, если его нет
    if not minio_client.bucket_exists(MODEL_WEIGHTS_BUCKET):
        minio_client.make_bucket(MODEL_WEIGHTS_BUCKET)
    
    logger.info("MinIO client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize MinIO client: {e}")
    exit(1)

def save_weights_to_minio():
    """Сохраняет текущие веса модели в MinIO"""
    try:
        # Сохраняем веса во временный файл
        temp_weights_path = f"temp_{MODEL_WEIGHTS_PATH}"
        torch.save(model.state_dict(), temp_weights_path)
        
        # Генерируем уникальное имя файла с timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        remote_weights_name = f"mobilenetv2_weights_{timestamp}.pth"
        
        # Загружаем веса в MinIO
        with open(temp_weights_path, "rb") as file_data:
            file_stat = os.stat(temp_weights_path)
            minio_client.put_object(
                MODEL_WEIGHTS_BUCKET,
                remote_weights_name,
                file_data,
                file_stat.st_size,
                content_type="application/octet-stream"
            )
        
        logger.info(f"Model weights saved to MinIO as {remote_weights_name}")
        
        # Удаляем временный файл
        os.remove(temp_weights_path)
        
        return remote_weights_name
    except Exception as e:
        logger.error(f"Failed to save weights to MinIO: {e}")
        return None

def load_latest_weights_from_minio():
    """Загружает последние веса модели из MinIO"""
    try:
        # Получаем список всех весов в бакете
        objects = minio_client.list_objects(MODEL_WEIGHTS_BUCKET, recursive=True)
        weight_files = [obj.object_name for obj in objects]
        
        if not weight_files:
            logger.warning("No weights found in MinIO bucket")
            return False
        
        # Сортируем по имени (по timestamp в имени)
        latest_weights = sorted(weight_files)[-1]
        
        # Скачиваем файл
        minio_client.fget_object(
            MODEL_WEIGHTS_BUCKET,
            latest_weights,
            MODEL_WEIGHTS_PATH
        )
        
        logger.info(f"Loaded latest weights from MinIO: {latest_weights}")
        return True
    except Exception as e:
        logger.error(f"Failed to load weights from MinIO: {e}")
        return False

# Инициализация модели
try:
    logger.info("Initializing MobileNetV2 model...")
    model = models.mobilenet_v2(weights='IMAGENET1K_V2')
    for param in model.features.parameters():
        param.requires_grad = False
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, 3)
    
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

def cleanup_old_weights():
    """Удаляет все веса кроме двух последних из MinIO"""
    try:
        # Получаем список всех весов
        objects = minio_client.list_objects(MODEL_WEIGHTS_BUCKET, recursive=True)
        weight_files = sorted([obj.object_name for obj in objects])
        
        # Оставляем только 2 последних файла
        if len(weight_files) > 2:
            files_to_delete = weight_files[:-2]
            for file_name in files_to_delete:
                minio_client.remove_object(MODEL_WEIGHTS_BUCKET, file_name)
                logger.info(f"Deleted old weights: {file_name}")
    except Exception as e:
        logger.error(f"Error cleaning up old weights: {e}")

def delete_image_from_minio(bucket_name, file_name):
    """Удаляет изображение из MinIO"""
    try:
        minio_client.remove_object(bucket_name, file_name)
        logger.info(f"Deleted image: {file_name} from bucket {bucket_name}")
    except Exception as e:
        logger.error(f"Error deleting image {file_name}: {e}")

def retrain_model(batch_data):
    """Дообучает модель на новом батче данных"""
    try:
        model.train()
        images = []
        labels = []
        processed_files = []
        
        for item in batch_data:
            try:
                response = minio_client.get_object("uploads", item["file_name"])
                image_bytes = response.read()
                image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
                image_tensor = transform(image)
                images.append(image_tensor)
                labels.append(item["true_class"])
                processed_files.append(item["file_name"])
            except Exception as e:
                logger.error(f"Error processing image {item['file_name']}: {e}")
            finally:
                if 'response' in locals():
                    response.close()
                    response.release_conn()
        
        if not images:
            logger.warning("No valid images in batch")
            return

        images = torch.stack(images)
        labels = torch.tensor(labels, dtype=torch.long)
        
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.Adam(model.parameters(), lr=0.001)
        
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        
        # Сохраняем веса локально
        torch.save(model.state_dict(), MODEL_WEIGHTS_PATH)
        
        # Сохраняем веса в MinIO
        save_weights_to_minio()
        
        # Очищаем старые веса
        cleanup_old_weights()
        
        logger.info(f"Model retrained on batch of size {len(batch_data)}")
        model.eval()
        
    except Exception as e:
        logger.error(f"Error during retraining: {e}")

def consume_feedback_tasks():
    """Потребляет задачи на дообучение из Kafka"""
    try:
        consumer = Consumer({
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
            'group.id': 'retraining-group',
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False  # Отключаем авто-коммит
        })
        consumer.subscribe(['feedback-tasks'])
        
        batch_size = 1
        batch_data = []
        
        logger.info("Listening for feedback tasks...")
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                if batch_data:
                    retrain_model(batch_data)
                    batch_data = []
                    consumer.commit()  # Коммитим после успешной обработки
                continue
            
            if msg.error():
                logger.error(f"Kafka error: {msg.error()}")
                continue
            
            try:
                data = json.loads(msg.value().decode('utf-8'))
                
                if "true_class" in data and data.get("is_correction", True):
                    batch_data.append({
                        "file_name": data["file_name"],
                        "true_class": data["true_class"]
                    })
                    
                    if len(batch_data) >= batch_size:
                        retrain_model(batch_data)
                        batch_data = []
                        consumer.commit()  # Коммитим после успешной обработки
                        
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                
    except Exception as e:
        logger.error(f"Error in Kafka consumer: {e}")
    finally:
        if 'consumer' in locals():
            consumer.close()

if __name__ == "__main__":
    consume_feedback_tasks()