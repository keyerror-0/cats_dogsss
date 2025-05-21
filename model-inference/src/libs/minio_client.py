from minio import Minio
from minio.error import S3Error
import logging
from typing import Optional
import os

class MinioClient:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool = False):
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure
        )
        self.bucket_name = "images"
        self._ensure_bucket_exists()
        logging.info("MinIO client initialized")

    def _ensure_bucket_exists(self):
        """Проверяет существование бакета и создает его при необходимости"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logging.info(f"Created bucket: {self.bucket_name}")
        except S3Error as e:
            logging.error(f"Error ensuring bucket exists: {e}")
            raise

    async def upload_file(self, file_path: str, object_name: Optional[str] = None) -> Optional[str]:
        """Загружает файл в MinIO"""
        try:
            if object_name is None:
                object_name = os.path.basename(file_path)

            self.client.fput_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                file_path=file_path
            )
            logging.info(f"File {file_path} uploaded successfully as {object_name}")
            return object_name
        except S3Error as e:
            logging.error(f"Error uploading file to MinIO: {e}")
            return None

    async def download_file(self, object_name: str, file_path: str) -> bool:
        """Скачивает файл из MinIO"""
        try:
            self.client.fget_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                file_path=file_path
            )
            logging.info(f"File {object_name} downloaded successfully to {file_path}")
            return True
        except S3Error as e:
            logging.error(f"Error downloading file from MinIO: {e}")
            return False

    async def delete_file(self, object_name: str) -> bool:
        """Удаляет файл из MinIO"""
        try:
            self.client.remove_object(
                bucket_name=self.bucket_name,
                object_name=object_name
            )
            logging.info(f"File {object_name} deleted successfully")
            return True
        except S3Error as e:
            logging.error(f"Error deleting file from MinIO: {e}")
            return False 