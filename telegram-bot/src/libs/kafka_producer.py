from kafka import KafkaProducer as KafkaProducerClient
from kafka.errors import KafkaError
import json
import logging
from typing import Dict, Any
from .kafka_config import KafkaConfig

class KafkaProducerWrapper:
    def __init__(self, bootstrap_servers: list, config: KafkaConfig = None):
        self.config = config or KafkaConfig(bootstrap_servers=bootstrap_servers)
        self.producer = KafkaProducerClient(
            **self.config.producer_config
        )
        logging.info("Kafka Producer initialized")

    async def send_message(self, topic: str, message: Dict[str, Any], timeout_ms: int = 30000) -> bool:
        """Отправляет сообщение в Kafka"""
        try:
            # Сериализуем сообщение в JSON
            message_bytes = json.dumps(message).encode('utf-8')
            future = self.producer.send(topic, message_bytes)
            # Добавляем таймаут
            future.get(timeout=timeout_ms/1000)
            return True
        except KafkaError as e:
            logging.error(f"Failed to send message to Kafka: {e}")
            return False

    @staticmethod
    def _on_send_success(record_metadata):
        logging.debug(
            f"Message delivered to {record_metadata.topic} "
            f"[{record_metadata.partition}] "
            f"at offset {record_metadata.offset}"
        )

    @staticmethod
    def _on_send_error(excp):
        logging.error(f"Failed to deliver message: {excp}")

    async def close(self):
        """Закрывает соединение с Kafka"""
        try:
            self.producer.close()
            logging.info("Kafka Producer closed")
        except Exception as e:
            logging.error(f"Error closing Kafka Producer: {e}") 