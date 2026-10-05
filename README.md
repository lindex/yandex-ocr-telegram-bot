# OCR Bot Yandex

Telegram-бот, который превращает картинки и голос в текст, а текст — в голос. Под капотом — сервисы Yandex AI Studio.

| Что прислать боту | Что он ответит | Сервис |
|---|---|---|
| Фото, картинку файлом или PDF | Распознанный текст (русский и английский) | Vision OCR |
| Голосовое или аудио (OGG/Opus, MP3, WAV) | Расшифровку речи | SpeechKit STT |
| Текст (до 5000 символов) | Голосовое сообщение | SpeechKit TTS |

**Зачем он нужен:** быстро вытащить текст со скриншота, документа или фото доски; прочитать голосовое, когда слушать неудобно; озвучить текст.

Бот подключается к Telegram по MTProto (Telethon), а не через Bot API. Поэтому он работает через MTProto-прокси там, где `api.telegram.org` заблокирован: Bot API — это HTTPS, и MTProto-прокси для него не подходит.

## Стек

Python 3.13 · [Telethon](https://github.com/LonamiWebs/Telethon) · [yandex-ai-studio-sdk](https://pypi.org/project/yandex-ai-studio-sdk/) · pydantic-settings · uv · Docker

## Настройка

### 1. Yandex Cloud

1. В [консоли](https://console.yandex.cloud) создайте сервисный аккаунт (например, `recognizer-bot-sa`) и назначьте ему роль **`ai.editor`** на каталог.
2. На странице аккаунта: **Создать новый ключ → Создать API-ключ**. Если предложат область действия, выберите `yc.ai.speechkitStt.execute`, `yc.ai.speechkitTts.execute`, `yc.ai.vision.execute`.
3. Скопируйте **секретный ключ** (`AQVN…`) — он показывается один раз. Это `YC_API_KEY`.
4. ID каталога (`b1g…`) — со страницы каталога или из адреса `console.yandex.cloud/folders/<id>`. Это `YC_FOLDER_ID`.

Платно по тарифам [SpeechKit](https://aistudio.yandex.ru/docs/ru/speechkit/pricing) и [Vision OCR](https://aistudio.yandex.ru/docs/ru/ai-studio/pricing), поэтому по умолчанию бот приватный (см. «Доступ»).

### 2. Telegram

1. Создайте бота у [@BotFather](https://t.me/BotFather) командой `/newbot` и возьмите токен — `TG_TOKEN`.
2. На [my.telegram.org](https://my.telegram.org) → **API development tools** создайте приложение и возьмите `api_id` и `api_hash` — `TG_API_ID`, `TG_API_HASH`. Они нужны Telethon для MTProto; бот всё равно входит по своему токену, а не под вашим аккаунтом.
3. Если Telegram на сервере заблокирован — укажите ссылку MTProto-прокси в `TG_PROXY` как есть: `tg://proxy?server=…&port=…&secret=…` (подходят и `https://t.me/proxy?…`). Секрет может быть обычным, `dd…` или `ee…` (fake-TLS): из него берётся ключ, и бот подключается в режиме `dd`. Прокси-сервер должен разрешать этот режим (в telemt — включённый `secure`).

### 3. Доступ

| Режим | Кто может пользоваться |
|---|---|
| `ACCESS_MODE=private` (по умолчанию) | Админы из `TG_ADMINS` и те, кого админ пустил |
| `ACCESS_MODE=public` | Все |

Доступом управляет админ прямо в боте, перезапуск не нужен:

1. Посторонний пишет боту — бот отвечает, что запрос отправлен, а админ получает сообщение с именем, username, ID и кнопками **✅ Разрешить** / **❌ Отклонить**.
2. После «Разрешить» пользователь получает уведомление и может пользоваться ботом.
3. Команды админа:
   - `/users` — у кого есть доступ;
   - `/allow ID` — дать доступ по ID;
   - `/deny ID` — забрать доступ.

Свой Telegram ID для `TG_ADMINS` можно узнать у [@userinfobot](https://t.me/userinfobot). Админ должен хотя бы раз написать боту (`/start`), иначе Telegram не даст боту отправить ему запрос.

Список пользователей и сессия Telegram хранятся в `DATA_DIR` (в Docker — `/data`). Подключите туда постоянный том, иначе после передеплоя список обнулится.

### 4. Переменные окружения

| Переменная | Обязательна | Описание |
|---|---|---|
| `TG_TOKEN` | да | Токен бота от @BotFather |
| `TG_API_ID` | да | `api_id` с my.telegram.org |
| `TG_API_HASH` | да | `api_hash` с my.telegram.org |
| `YC_API_KEY` | да | Секретный API-ключ сервисного аккаунта |
| `YC_FOLDER_ID` | да | ID каталога Yandex Cloud |
| `TG_PROXY` | нет | Ссылка MTProto-прокси |
| `TG_ADMINS` | нет* | ID админов через запятую: `123456789,987654321`. *В режиме `private` без админов ботом никто не сможет пользоваться |
| `ACCESS_MODE` | нет | `private` (по умолчанию) или `public` |
| `DATA_DIR` | нет | Папка для сессии и списка пользователей, по умолчанию `data` (в Docker — `/data`) |
| `TTS_VOICE` | нет | Голос синтеза, по умолчанию `alena`. [Документация SpeechKit TTS](https://aistudio.yandex.ru/docs/ru/speechkit/tts/index) |

Шаблон — [`.env.example`](.env.example).

## Запуск

Локально (нужен [uv](https://docs.astral.sh/uv/)):

```bash
cp .env.example .env   # и заполнить
uv run python bot.py
```

В Docker:

```bash
docker build -t ocr-bot-yandex .
docker run -d --restart unless-stopped --env-file .env -v ocr-bot-data:/data ocr-bot-yandex
```

В Coolify: приложение из этого репозитория, Build Pack **Dockerfile**, домен не нужен (бот сам ходит в Telegram, входящих подключений нет). Переменные — в **Environment Variables** (блок Production, не Preview). В **Persistent Storage** — том с путём `/data`.

Самопроверка разбора прокси-ссылок и прав доступа:

```bash
uv run python test_bot.py
```

## Ограничения

- Файлы больше 20 МБ не принимаются.
- Пока админ не ответил на запрос, повторные сообщения от того же человека новых запросов не создают. После рестарта бота запрос может прийти ещё раз.
