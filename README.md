# Apteka API

Проект контейнеризирован и готов к переносу на сервер.

## Что добавлено
- `Dockerfile` для сборки FastAPI-приложения с Chromium и ChromeDriver (для Selenium).
- `docker-compose.yml` для запуска API за Nginx в Docker.
- `nginx/default.conf` с ограничением доступа только для IP `31.47.189.42`.
- Параметризация путей браузера через переменные `CHROME_BIN` и `CHROMEDRIVER_PATH`.

## Быстрый запуск

```bash
docker compose up --build -d
```

После запуска:
- Nginx публикуется на порту `8080` хоста по умолчанию.
- FastAPI доступен только через Nginx.
- Доступ к сервису разрешён только с IP `31.47.189.42`.

Открывать сервис:
- `http://<IP_СЕРВЕРА>:8080/`
- `http://<IP_СЕРВЕРА>:8080/health`

## Если порт 8080 нужно изменить

Можно задать порт через переменную окружения:

```bash
NGINX_HOST_PORT=8090 docker compose up --build -d
```

Тогда доступ будет по `http://<IP_СЕРВЕРА>:8090`.

## Ошибка `address already in use`

Если видите ошибку вида `failed to bind host port ... address already in use`, это значит, что выбранный порт уже занят на сервере.

Проверьте и освободите порт либо выберите другой через `NGINX_HOST_PORT`.

## Проверка

С разрешённого IP:

```bash
curl http://<IP_СЕРВЕРА>:8080/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

С любого другого IP Nginx вернёт `403 Forbidden`.

## Перенос на сервер

1. Скопируйте репозиторий на сервер.
2. Убедитесь, что установлены Docker и Docker Compose plugin.
3. Выполните:
   ```bash
   docker compose up --build -d
   ```
4. Убедитесь, что в firewall открыт только порт `80` (и при необходимости `22` для SSH).

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

Для Selenium внутри контейнера:
- `CHROME_BIN=/usr/bin/chromium`
- `CHROMEDRIVER_PATH=/usr/bin/chromedriver`
