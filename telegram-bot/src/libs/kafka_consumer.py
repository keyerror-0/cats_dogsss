from kafka import KafkaConsumer as KafkaConsumerClient
from kafka.errors import KafkaError
import json
import logging
from typing import Dict, Any, AsyncGenerator, Optional
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

    def _validate_message(self, message: Dict[str, Any]) -> bool:
        """Проверка валидности сообщения"""
        required_fields = ['image_id', 'user_id', 'result_path', 'detections']
        return all(field in message for field in required_fields)

    def _deserialize_message(self, message) -> Optional[Dict[str, Any]]:
        """Безопасная десериализация сообщения"""
        try:
            return json.loads(message.value.decode('utf-8'))
        except json.JSONDecodeError as e:
            logging.error(f"Failed to decode message: {e}")
            return None
        except Exception as e:
            logging.error(f"Error deserializing message: {e}")
            return None

    async def get_message(self, timeout_ms: int = 30000) -> Optional[Dict[str, Any]]:
        """Получает одно сообщение с таймаутом"""
        try:
            message = self.consumer.poll(timeout_ms=timeout_ms)
            if message:
                deserialized = self._deserialize_message(message)
                if deserialized and self._validate_message(deserialized):
                    return deserialized
            return None
        except Exception as e:
            logging.error(f"Error getting message: {e}")
            return None

    async def __aiter__(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Асинхронный итератор для получения сообщений"""
        while True:
            try:
                for message in self.consumer:
                    deserialized = self._deserialize_message(message)
                    if deserialized and self._validate_message(deserialized):
                        yield deserialized
            except Exception as e:
                logging.error(f"Error consuming message: {e}")
                await asyncio.sleep(1)

    async def close(self):
        """Закрывает соединение с Kafka"""
        try:
            self.consumer.close()
            logging.info("Kafka Consumer closed")
        except Exception as e:
            logging.error(f"Error closing Kafka Consumer: {e}") 