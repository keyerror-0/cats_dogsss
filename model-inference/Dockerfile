FROM python:3.9-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Создание директорий
RUN mkdir -p /app/temp /app/model

# Копирование и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Скачивание модели YOLOv8
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

# Копирование исходного кода
COPY src/ .

# Установка прав на директории
RUN chmod -R 777 /app/temp

# Создание точек монтирования
VOLUME ["/app/temp", "/app/model"]

CMD ["python", "main.py"]

