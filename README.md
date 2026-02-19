# Apteka API

Проект контейнеризирован и готов к переносу на сервер.

## Что добавлено
- `Dockerfile` для сборки FastAPI-приложения с Chromium и ChromeDriver (для Selenium).
- `docker-compose.yml` для быстрого запуска на сервере.
- `.dockerignore` для уменьшения контекста сборки.
- Параметризация путей браузера через переменные `CHROME_BIN` и `CHROMEDRIVER_PATH`.

## Быстрый запуск

```bash
docker compose up --build -d
```

Приложение будет доступно на `http://localhost:8000`.

## Проверка

```bash
curl http://localhost:8000/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

## Перенос на сервер

1. Скопируйте репозиторий на сервер.
2. Убедитесь, что установлены Docker и Docker Compose plugin.
3. Выполните:
   ```bash
   docker compose up --build -d
   ```
4. (Опционально) Настройте reverse proxy (Nginx/Caddy) и HTTPS.

## Полезные команды

```bash
# Логи

docker compose logs -f

# Остановить

docker compose down

# Пересобрать после изменений

docker compose up --build -d
```

## Переменные окружения

По умолчанию заданы в `docker-compose.yml`:
- `JOB_STORE=/app/job_store`
- `PARSE_TIMEOUT=10`
- `PARSE_MAX_RETRIES=10`
- `PARSE_PAUSE=3`
- `PARSE_VARIANT_SETTLE_DELAY=4.0`

Для Selenium внутри контейнера:
- `CHROME_BIN=/usr/bin/chromium`
- `CHROMEDRIVER_PATH=/usr/bin/chromedriver`
