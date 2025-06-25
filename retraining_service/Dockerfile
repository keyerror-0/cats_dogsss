# Используем официальный образ Python
FROM python:3.9-slim

# Устанавливаем зависимости
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости Python
RUN pip install -r requirements.txt

# Копируем исходный код и веса модели
COPY retraining_service.py .
COPY model_weights.pth .

# Запускаем сервис
CMD ["python", "retraining_service.py"]