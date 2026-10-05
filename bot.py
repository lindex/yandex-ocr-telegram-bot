"""Telegram-бот: текст с картинок и PDF (Vision OCR), голос -> текст и текст -> голос (SpeechKit).

Работает по MTProto (Telethon), поэтому может ходить в Telegram через MTProto-прокси (tg://proxy?...).
"""
import base64
import io
import json
import logging
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlparse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from telethon import Button, TelegramClient, events
from telethon.network.connection import (
    ConnectionTcpFull,
    ConnectionTcpMTProxyIntermediate,
    ConnectionTcpMTProxyRandomizedIntermediate,
)
from TelethonFakeTLS import ConnectionTcpMTProxyFakeTLS
from yandex_ai_studio_sdk import AsyncAIStudio


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tg_token: SecretStr
    tg_api_id: int  # https://my.telegram.org -> API development tools
    tg_api_hash: SecretStr
    tg_proxy: SecretStr | None = None  # tg://proxy?server=...&port=...&secret=... или https://t.me/proxy?...
    yc_api_key: SecretStr
    yc_folder_id: str
    tts_voice: str = "alena"
    tg_admins: Annotated[list[int], NoDecode] = []  # ID админов через запятую
    access_mode: Literal["private", "public"] = "private"  # private — только админы и те, кого они пустили
    data_dir: Path = Path("data")  # сессия Telegram и список пользователей; в Docker — volume /data

    @field_validator("tg_admins", mode="before")
    @classmethod
    def split_ids(cls, value: str | list) -> list:
        return [x.strip() for x in value.split(",") if x.strip()] if isinstance(value, str) else value


class Users:
    """Пользователи, которых пустил админ. Хранятся в JSON, чтобы переживать рестарты."""

    def __init__(self, path: Path):
        self.path = path
        self.ids: set[int] = set(json.loads(path.read_text())) if path.exists() else set()

    def add(self, user_id: int) -> None:
        self.ids.add(user_id)
        self._save()

    def remove(self, user_id: int) -> bool:
        if user_id not in self.ids:
            return False
        self.ids.discard(user_id)
        self._save()
        return True

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(self.ids)))
        tmp.replace(self.path)


MAX_FILE_SIZE = 20 * 1024 * 1024
TG_TEXT_LIMIT = 4096
TTS_TEXT_LIMIT = 5000
STT_FORMATS = {"audio/ogg": "OGG_OPUS", "audio/opus": "OGG_OPUS", "audio/mpeg": "MP3", "audio/mp3": "MP3",
               "audio/wav": "WAV", "audio/x-wav": "WAV"}
HELP = ("Пришлите:\n"
        "• картинку или PDF — верну текст с них;\n"
        "• голосовое или аудио — расшифрую в текст;\n"
        "• текст — озвучу голосовым.")
ADMIN_HELP = ("\n\nКоманды админа:\n"
              "/users — у кого есть доступ\n"
              "/allow ID — дать доступ\n"
              "/deny ID — забрать доступ")

log = logging.getLogger("ocr_bot")


def parse_proxy(link: str) -> tuple[type, tuple[str, int, str]]:
    """tg://proxy-ссылка -> (класс соединения Telethon, (host, port, secret)) по типу секрета."""
    query = {k: v[0] for k, v in parse_qs(urlparse(link).query).items()}
    host, port, secret = query["server"], int(query["port"]), query["secret"]
    try:
        raw = bytes.fromhex(secret)
    except ValueError:
        raw = base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))
    if raw[0] == 0xEE:  # fake-TLS: 16 байт ключа + домен маскировки
        return ConnectionTcpMTProxyFakeTLS, (host, port, raw[1:].hex())
    if raw[0] == 0xDD:
        return ConnectionTcpMTProxyRandomizedIntermediate, (host, port, raw.hex())
    return ConnectionTcpMTProxyIntermediate, (host, port, raw.hex())


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
users = Users(settings.data_dir / "users.json")
sdk = AsyncAIStudio(folder_id=settings.yc_folder_id, auth=settings.yc_api_key.get_secret_value())
ocr = sdk.vision.ocr(language_codes=["ru", "en"], model="page")
tts = sdk.speechkit.tts(voice=settings.tts_voice, audio_format="OGG_OPUS", single_chunk_mode=True)

connection, proxy = (parse_proxy(settings.tg_proxy.get_secret_value()) if settings.tg_proxy
                     else (ConnectionTcpFull, None))
client = TelegramClient(str(settings.data_dir / "bot"), settings.tg_api_id, settings.tg_api_hash.get_secret_value(),
                        connection=connection, proxy=proxy)
client.parse_mode = None


async def reply_text(event, text: str) -> None:
    text = text.strip() or "Ничего не распознано."
    for i in range(0, len(text), TG_TEXT_LIMIT):
        await event.reply(text[i:i + TG_TEXT_LIMIT])


async def recognize_image(event, mime: str) -> None:
    async with client.action(event.chat_id, "typing"):
        pages = await ocr.run(await event.download_media(bytes), mime_type=mime, timeout=120)
        await reply_text(event, "\n\n".join(p.full_text for p in pages))


async def recognize_speech(event, audio_format: str) -> None:
    async with client.action(event.chat_id, "typing"):
        stt = sdk.speechkit.stt(audio_format=audio_format, language_codes=["ru-RU", "en-US"], text_normalization=True)
        result = await stt.run(await event.download_media(bytes), timeout=300)
        await reply_text(event, (result.final_refinement_text or result.final_text) if result.channels else "")


async def synthesize(event) -> None:
    if len(event.raw_text) > TTS_TEXT_LIMIT:
        await event.reply(f"Слишком длинный текст: максимум {TTS_TEXT_LIMIT} символов.")
        return
    async with client.action(event.chat_id, "record-voice"):
        voice = io.BytesIO((await tts.run(event.raw_text, timeout=120)).data)
        voice.name = "voice.ogg"
        await event.reply(file=voice, voice_note=True)


def is_admin(user_id: int) -> bool:
    return user_id in settings.tg_admins


def is_allowed(user_id: int) -> bool:
    return settings.access_mode == "public" or is_admin(user_id) or user_id in users.ids


async def describe(user_id: int) -> str:
    try:
        user = await client.get_entity(user_id)
    except Exception:
        return str(user_id)
    name = " ".join(filter(None, [user.first_name, user.last_name]))
    return f"{name} @{user.username} ({user_id})" if user.username else f"{name} ({user_id})"


requested: set[int] = set()  # ponytail: в памяти — после рестарта админ может получить повторный запрос


async def request_access(event) -> None:
    await event.reply("Бот приватный. Запрос на доступ отправлен администратору.")
    if event.sender_id in requested:
        return
    requested.add(event.sender_id)
    buttons = [Button.inline("✅ Разрешить", f"allow:{event.sender_id}"),
               Button.inline("❌ Отклонить", f"reject:{event.sender_id}")]
    text = f"Запрос доступа: {await describe(event.sender_id)}"
    for admin in settings.tg_admins:
        try:
            await client.send_message(admin, text, buttons=buttons)
        except Exception:
            log.warning("Не удалось уведомить админа %s — он должен сначала написать боту", admin)


async def grant(user_id: int) -> None:
    users.add(user_id)
    requested.discard(user_id)
    try:
        await client.send_message(user_id, "Доступ открыт.\n\n" + HELP)
    except Exception:
        log.warning("Не удалось уведомить пользователя %s о доступе", user_id)


async def admin_command(event) -> None:
    command, _, arg = event.raw_text.partition(" ")
    command, arg = command.split("@")[0], arg.strip()
    if command == "/users":
        lines = [await describe(uid) for uid in sorted(users.ids)]
        await event.reply("Есть доступ:\n" + "\n".join(lines) if lines else "Пока никого, кроме админов.")
    elif command in ("/allow", "/deny") and arg.lstrip("-").isdigit():
        user_id = int(arg)
        if command == "/allow":
            await grant(user_id)
            await event.reply(f"Доступ выдан: {await describe(user_id)}")
        elif users.remove(user_id):
            await event.reply(f"Доступ забран: {await describe(user_id)}")
        else:
            await event.reply("Такого пользователя нет в списке.")
    else:
        await event.reply(HELP + ADMIN_HELP)


@client.on(events.CallbackQuery(pattern=rb"(allow|reject):(-?\d+)"))
async def on_access_button(event) -> None:
    if not is_admin(event.sender_id):
        await event.answer("Только для админа.")
        return
    action, user_id = event.pattern_match.group(1).decode(), int(event.pattern_match.group(2))
    if action == "allow":
        await grant(user_id)
        await event.edit(f"✅ Доступ выдан: {await describe(user_id)}")
    else:
        await event.edit(f"❌ Отклонено: {await describe(user_id)}")


@client.on(events.NewMessage(incoming=True))
async def on_message(event) -> None:
    if not is_allowed(event.sender_id):
        await request_access(event)
        return
    if event.raw_text.startswith("/") and is_admin(event.sender_id):
        await admin_command(event)
        return
    mime = event.file.mime_type if event.file else ""
    try:
        if event.file and event.file.size and event.file.size > MAX_FILE_SIZE:
            await event.reply("Файл больше 20 МБ — пришлите поменьше.")
        elif event.photo:
            await recognize_image(event, "image/jpeg")
        elif event.document and (mime.startswith("image/") or mime == "application/pdf"):
            await recognize_image(event, mime)
        elif event.voice:
            await recognize_speech(event, "OGG_OPUS")
        elif event.audio and mime in STT_FORMATS:
            await recognize_speech(event, STT_FORMATS[mime])
        elif event.raw_text.startswith("/"):
            await event.reply(HELP)
        elif event.raw_text and not event.media:
            await synthesize(event)
        else:
            await event.reply("Поддерживаются картинки, PDF, голосовые, аудио OGG/MP3/WAV и текст.")
    except Exception:
        log.exception("Ошибка обработки сообщения")
        await event.reply("Не получилось обработать, попробуйте ещё раз.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info("Доступ: %s, админов: %d, пользователей: %d", settings.access_mode, len(settings.tg_admins),
             len(users.ids))
    log.info("Подключение к Telegram %s", f"через {connection.__name__}" if proxy else "напрямую")
    client.start(bot_token=settings.tg_token.get_secret_value())
    log.info("Бот запущен")
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
