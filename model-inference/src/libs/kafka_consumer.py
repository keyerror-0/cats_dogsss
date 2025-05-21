from kafka import KafkaConsumer as KafkaConsumerClient
from kafka.errors import KafkaError
import json
import logging
from typing import Dict, Any, AsyncGenerator
import asyncio
from .kafka_config import KafkaConfig

class KafkaConsumerWrapper:
    def __init__(self, topic: str, bootstrap_servers: list = None, group_id: str = None, config: KafkaConfig = None):
        self.config = config or KafkaConfig(bootstrap_servers=bootstrap_servers or ['kafka:9092'])
        if group_id:
            self.config.group_id = group_id
            
        self.consumer = KafkaConsumerClient(
            topic,
            **self.config.consumer_config
        )
        logging.info(f"Kafka Consumer initialized for topic: {topic}")

    async def __aiter__(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Асинхронный итератор для получения сообщений"""
        while True:
            try:
                for message in self.consumer:
                    # Десериализуем сообщение из JSON
                    value = json.loads(message.value.decode('utf-8'))
                    yield value
            except Exception as e:
                logging.error(f"Error consuming message: {e}")
                await asyncio.sleep(1)  # Пауза перед повторной попыткой

    async def close(self):
        """Закрывает соединение с Kafka"""
        try:
            self.consumer.close()
            logging.info("Kafka Consumer closed")
        except Exception as e:
            logging.error(f"Error closing Kafka Consumer: {e}") 