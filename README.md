# Twitch Virtual Viewer — 1 аккаунт

Это однопользовательская версия проекта. Она сохраняет ту же общую архитектуру:
Twitch → ContextBuilder → Scheduler → Ollama/Qwen → Twitch.

## Что нужно заполнить

### 1. `config/twitch_accounts.json`

Нужно указать данные ОДНОГО Twitch-аккаунта:

- `nick` — точный логин Twitch-аккаунта;
- `access_token` — OAuth access token этого же аккаунта;
- `client_id` — Client ID вашего Twitch-приложения.

Пример:

```json
[
  {
    "name": "account01",
    "nick": "my_twitch_bot",
    "access_token": "oauth:ВАШ_ТОКЕН",
    "client_id": "ВАШ_CLIENT_ID"
  }
]
```

Не публикуйте OAuth token и не добавляйте его в Git.

### 2. `.env`

Минимально:

```env
TWITCH_CHANNEL=имя_канала
TWITCH_ACCOUNTS_CONFIG_PATH=config/twitch_accounts.json
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_LLM_MODEL=qwen3:14b
```

`TWITCH_CHANNEL` — канал, в чат которого аккаунт должен подключиться, без `#`.

### 3. `config/bots.json`

Здесь находится личность единственного виртуального зрителя. Меняйте `style`,
чтобы задать характер и манеру общения.

## Запуск

1. Установить зависимости:
   `pip install -r requirements.txt`
2. Запустить Ollama и убедиться, что модель доступна:
   `ollama run qwen3:14b`
3. Создать `.env` по образцу `.env.example`.
4. Заполнить `config/twitch_accounts.json`.
5. Заполнить `TWITCH_CHANNEL`.
6. Запустить:
   `python main.py`

## Что должно произойти

В логах появится подключение вида:

`Twitch подключён: аккаунт='my_twitch_bot', канал=#имя_канала`

После этого аккаунт читает сообщения чата. Scheduler периодически формирует
контекст, Qwen генерирует реплику, и она отправляется в тот же чат от имени
реального Twitch-аккаунта.

Для первого теста рекомендуется поставить в `bots.json` высокий cooldown и
небольшую вероятность ответа, а затем написать в чат несколько сообщений.

## Важно

Используйте автоматизацию в соответствии с актуальными правилами Twitch.
Не используйте её для спама, искусственной накрутки зрителей или обхода
ограничений платформы.
