import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

logger = logging.getLogger(__name__)

def register_message_handlers(dp):
    """Регистрация обработчиков сообщений"""
    logger.info("Регистрация обработчиков сообщений...")
    router = Router()
    
    @router.message(Command("start"))
    async def cmd_start(message: Message):
        """Обработка команды /start"""
        try:
            logger.info(f"Получена команда /start от пользователя {message.from_user.id}")
            logger.info(f"Текст сообщения: {message.text}")
            logger.info(f"Тип сообщения: {message.content_type}")
            
            response = (
                "Привет! Я бот для определения кошек и собак на фотографиях. "
                "Просто отправь мне фотографию, и я найду на ней кошек и собак."
            )
            await message.answer(response)
            logger.info(f"Ответ на команду /start успешно отправлен пользователю {message.from_user.id}")
        except Exception as e:
            logger.error(f"Ошибка при обработке команды /start: {e}", exc_info=True)
            await message.answer("Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже.")

    @router.message(Command("help"))
    async def cmd_help(message: Message):
        """Обработка команды /help"""
        try:
            logger.info(f"Получена команда /help от пользователя {message.from_user.id}")
            help_text = (
                "Я могу определять кошек и собак на фотографиях.\n\n"
                "Доступные команды:\n"
                "/start - Начать работу с ботом\n"
                "/help - Показать это сообщение\n\n"
                "Как использовать:\n"
                "1. Отправь мне фотографию\n"
                "2. Дождись результата обработки\n"
                "3. Получи фотографию с отмеченными кошками и собаками"
            )
            await message.answer(help_text)
            logger.info(f"Ответ на команду /help успешно отправлен пользователю {message.from_user.id}")
        except Exception as e:
            logger.error(f"Ошибка при обработке команды /help: {e}", exc_info=True)
            await message.answer("Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже.")

    @router.message(F.text & ~F.command) 
    async def handle_other_messages(message: Message):
        """Обработка остальных сообщений"""
        try:
            logger.info(f"Получено сообщение от пользователя {message.from_user.id}: {message.text}")
            await message.answer(
                "Пожалуйста, отправьте фотографию для определения кошек и собак. "
                "Используйте /help для получения справки."
            )
            logger.info(f"Ответ на текстовое сообщение успешно отправлен пользователю {message.from_user.id}")
        except Exception as e:
            logger.error(f"Ошибка при обработке текстового сообщения: {e}", exc_info=True)
            await message.answer("Произошла ошибка при обработке сообщения. Пожалуйста, попробуйте позже.")

    dp.include_router(router)
    logger.info("Обработчики сообщений успешно зарегистрированы") 