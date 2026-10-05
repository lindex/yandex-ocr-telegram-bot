"""Telegram-бот: текст с картинок и PDF (Vision OCR), голос -> текст и текст -> голос (SpeechKit)."""
import asyncio
import logging
import socket

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, Message
from aiogram.utils.chat_action import ChatActionSender
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from yandex_ai_studio_sdk import AsyncAIStudio


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tg_token: SecretStr
    yc_api_key: SecretStr
    yc_folder_id: str
    tts_voice: str = "alena"
    telegram_proxy: str | None = None  # socks5://user:pass@host:1080 или http://...
    telegram_api_ip: str | None = None  # обход DNS-блокировки api.telegram.org


settings = Settings()
log = logging.getLogger("ocr_bot")
dp = Dispatcher()
sdk = AsyncAIStudio(folder_id=settings.yc_folder_id, auth=settings.yc_api_key.get_secret_value())
ocr = sdk.vision.ocr(language_codes=["ru", "en"], model="page")
tts = sdk.speechkit.tts(voice=settings.tts_voice, audio_format="OGG_OPUS", single_chunk_mode=True)

TG_FILE_LIMIT = 20 * 1024 * 1024  # Bot API не отдаёт файлы больше 20 МБ
TG_TEXT_LIMIT = 4096
TTS_TEXT_LIMIT = 5000
STT_FORMATS = {"audio/ogg": "OGG_OPUS", "audio/opus": "OGG_OPUS", "audio/mpeg": "MP3", "audio/mp3": "MP3",
               "audio/wav": "WAV", "audio/x-wav": "WAV"}


async def answer_text(message: Message, text: str) -> None:
    text = text.strip() or "Ничего не распознано."
    for i in range(0, len(text), TG_TEXT_LIMIT):
        await message.reply(text[i:i + TG_TEXT_LIMIT], parse_mode=None)


async def download(message: Message, file_id: str, size: int | None) -> bytes | None:
    if size and size > TG_FILE_LIMIT:
        await message.reply("Файл больше 20 МБ — Telegram не даёт ботам такие скачивать.")
        return None
    return (await message.bot.download(file_id)).read()


async def recognize_image(message: Message, file_id: str, size: int | None, mime: str) -> None:
    async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
        if data := await download(message, file_id, size):
            pages = await ocr.run(data, mime_type=mime, timeout=120)
            await answer_text(message, "\n\n".join(p.full_text for p in pages))


async def recognize_speech(message: Message, file_id: str, size: int | None, audio_format: str) -> None:
    async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
        if data := await download(message, file_id, size):
            stt = sdk.speechkit.stt(audio_format=audio_format, language_codes=["ru-RU", "en-US"],
                                    text_normalization=True)
            result = await stt.run(data, timeout=300)
            text = (result.final_refinement_text or result.final_text) if result.channels else ""
            await answer_text(message, text)


@dp.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(
        "Пришлите:\n"
        "• картинку или PDF — верну текст с них;\n"
        "• голосовое или аудио — расшифрую в текст;\n"
        "• текст — озвучу голосовым."
    )


@dp.message(F.photo)
async def on_photo(message: Message) -> None:
    photo = message.photo[-1]
    await recognize_image(message, photo.file_id, photo.file_size, "image/jpeg")


@dp.message(F.document.mime_type.startswith("image/") | (F.document.mime_type == "application/pdf"))
async def on_document(message: Message) -> None:
    doc = message.document
    await recognize_image(message, doc.file_id, doc.file_size, doc.mime_type)


@dp.message(F.voice)
async def on_voice(message: Message) -> None:
    await recognize_speech(message, message.voice.file_id, message.voice.file_size, "OGG_OPUS")


@dp.message(F.audio)
async def on_audio(message: Message) -> None:
    audio = message.audio
    if fmt := STT_FORMATS.get(audio.mime_type or ""):
        await recognize_speech(message, audio.file_id, audio.file_size, fmt)
    else:
        await message.reply("Поддерживаются аудио в форматах OGG/Opus, MP3 и WAV.")


@dp.message(F.text)
async def on_text(message: Message) -> None:
    if len(message.text) > TTS_TEXT_LIMIT:
        await message.reply(f"Слишком длинный текст: максимум {TTS_TEXT_LIMIT} символов.")
        return
    async with ChatActionSender.record_voice(bot=message.bot, chat_id=message.chat.id):
        result = await tts.run(message.text, timeout=120)
        await message.reply_voice(BufferedInputFile(result.data, "voice.ogg"))


@dp.message()
async def on_other(message: Message) -> None:
    await message.reply("Пришлите картинку, PDF, голосовое или текст.")


@dp.error()
async def on_error(event) -> bool:
    log.exception("Ошибка обработки апдейта", exc_info=event.exception)
    if message := event.update.message:
        await message.reply("Не получилось обработать, попробуйте ещё раз.")
    return True


def patch_telegram_dns(ip: str) -> None:
    original = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        return original(ip if host == "api.telegram.org" else host, *args, **kwargs)

    socket.getaddrinfo = getaddrinfo


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if settings.telegram_api_ip:
        patch_telegram_dns(settings.telegram_api_ip)
    session = AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else None
    bot = Bot(settings.tg_token.get_secret_value(), session=session)
    await bot.delete_webhook()  # polling не работает при активном вебхуке
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
