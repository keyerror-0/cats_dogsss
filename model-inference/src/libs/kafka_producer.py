from kafka import KafkaProducer as KafkaProducerClient, KafkaConsumer
from kafka.errors import KafkaError
import json
import logging
from typing import Dict, Any, AsyncGenerator
import asyncio
from .kafka_config import KafkaConfig

class KafkaProducerWrapper:
    def __init__(self, bootstrap_servers: list = None, config: KafkaConfig = None):
        self.config = config or KafkaConfig(bootstrap_servers=bootstrap_servers or ['kafka:9092'])
        self.producer = KafkaProducerClient(
            **self.config.producer_config
        )
        logging.info("Kafka Producer initialized")

    def send_message(self, topic: str, message: Dict[str, Any]) -> None:
        """Отправляет сообщение в Kafka"""
        try:
            # Сериализуем сообщение в JSON
            value = json.dumps(message).encode('utf-8')
            self.producer.send(topic, value=value)
            self.producer.flush()
            logging.info(f"Message sent to topic {topic}")
        except Exception as e:
            logging.error(f"Error sending message to Kafka: {e}")
            raise

    def close(self) -> None:
        """Закрывает соединение с Kafka"""
        try:
            self.producer.close()
            logging.info("Kafka Producer closed")
        except Exception as e:
            logging.error(f"Error closing Kafka Producer: {e}")

class KafkaConsumer:
    def __init__(self, topic: str, bootstrap_servers: list = None, group_id: str = None):
        self.consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers or ['kafka:9092'],
            group_id=group_id or 'model_inference_group',
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            auto_offset_reset='earliest',
            enable_auto_commit=True
        )
        logging.info(f"Kafka Consumer initialized for topic: {topic}")

    async def __aiter__(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Асинхронный итератор для получения сообщений"""
        while True:
            try:
                for message in self.consumer:
                    yield message.value
            except Exception as e:
                logging.error(f"Error consuming message: {e}")
                await asyncio.sleep(1)  # Пауза перед повторной попыткой

    async def close(self):
        """Закрывает соединение с Kafka"""
        try:
            await self.consumer.close()
            logging.info("Kafka Consumer closed")
        except Exception as e:
            logging.error(f"Error closing Kafka Consumer: {e}") 