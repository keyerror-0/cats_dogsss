FROM python:3.9-slim

WORKDIR /app

# Создание директорий
RUN mkdir -p /app/temp

# Копирование и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY src/ ./src/

# Установка прав на директории
RUN chmod -R 777 /app/temp

# Создание точки монтирования для временных файлов
VOLUME ["/app/temp"]

CMD ["python", "src/main.py"]

