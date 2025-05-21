from dataclasses import dataclass
from typing import List

@dataclass
class KafkaConfig:
    bootstrap_servers: List[str]
    topic_inference: str = "image_inference"
    topic_results: str = "inference_results"
    group_id: str = "telegram_bot_group"
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = True
    session_timeout_ms: int = 10000
    heartbeat_interval_ms: int = 3000
    request_timeout_ms: int = 30000
    security_protocol: str = "PLAINTEXT"
    client_id: str = "telegram-bot-client"

    @property
    def consumer_config(self):
        """Конфигурация для потребителя Kafka"""
        return {
            'bootstrap_servers': self.bootstrap_servers,
            'group_id': self.group_id,
            'auto_offset_reset': self.auto_offset_reset,
            'enable_auto_commit': self.enable_auto_commit,
            'session_timeout_ms': self.session_timeout_ms,
            'heartbeat_interval_ms': self.heartbeat_interval_ms,
            'request_timeout_ms': self.request_timeout_ms,
            'security_protocol': self.security_protocol,
            'client_id': self.client_id
        }

    @property
    def producer_config(self):
        """Конфигурация для производителя Kafka"""
        return {
            'bootstrap_servers': self.bootstrap_servers,
            'request_timeout_ms': self.request_timeout_ms,
            'security_protocol': self.security_protocol,
            'client_id': self.client_id
        } 