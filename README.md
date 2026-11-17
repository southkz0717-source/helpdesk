# Helpdesk — қолдау қызметі

Учебный проект по курсу «АТ-жобаларды басқару» (4 курс, осень 2026).
Сервис заявок в техподдержку с приоритетами P1–P4 и сроками SLA.

## Что умеет

- создание заявки с темой, заявителем, приоритетом и описанием;
- автоматический расчёт сроков реакции и решения по приоритету;
- статусы `new → in_progress → resolved → closed`, повторное открытие решённой заявки;
- отметка о нарушении SLA;
- интерфейс на трёх языках: қазақша, русский, English (`?lang=kk|ru|en`);
- JSON API и страница `/docs` (Swagger).

### SLA по приоритетам (лекция 11, слайд 22)

| Приоритет | Что это | Реакция | Решение |
|---|---|---|---|
| P1 — критический | Система недоступна, данные потеряны или искажены | 15 минут | 8 часов |
| P2 — высокий | Ключевой сценарий не работает, есть обходной путь | 2 часа | 2 дня |
| P3 — средний | Неудобство, есть обходной путь | 1 день | 14 дней (ближайший релиз) |
| P4 — низкий | Косметика, редкий сценарий | без обязательств | без обязательств |

## Стек

Python 3.13, FastAPI, SQLite, Jinja2. Тесты на pytest, линтер ruff.

## Запуск локально

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Откройте http://localhost:8000. Документация API доступна по адресу http://localhost:8000/docs.

## Тесты и линтер

```bash
pytest
ruff check .
```

## Docker

```bash
docker build -t helpdesk .
docker run -d --name helpdesk -p 8000:8000 -v helpdesk-data:/data helpdesk
```

> **Обязательно `-v helpdesk-data:/data`.** Без тома все заявки пропадают при пересоздании
> контейнера, то есть при каждом обновлении (инцидент на v0.3.0). Проверка: `GET /health`
> возвращает `"persistent_storage": true`.

Стенд из опубликованного образа (том уже настроен):

```bash
docker compose up -d                             # последняя версия
HELPDESK_VERSION=0.3.0 docker compose up -d      # конкретная версия или откат
```

## CI/CD и DORA (ЗС 10)

| Workflow | Когда запускается | Что делает |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | PR и push в `main` | ruff → pytest → Trivy (зависимости) и gitleaks → сборка Docker-образа, smoke-тест `/health`, Trivy (образ) → артефакт; на `main` публикует образ в GHCR |
| [`release.yml`](.github/workflows/release.yml) | тег `vX.Y.Z` | тесты → образ `:X.Y.Z` и `:latest` в GHCR → GitHub Release (это и есть «деплой» для DORA) |
| [`dora.yml`](.github/workflows/dora.yml) | каждый понедельник или вручную | считает 4 метрики DORA по GitHub API, выкладывает дашборд как артефакт |

- Определения метрик и уровни: [docs/dora.md](docs/dora.md)
- Текущие значения, уровни и 2 улучшения: [docs/dora-analysis.md](docs/dora-analysis.md), дашборд: [docs/dora/dashboard.png](docs/dora/dashboard.png)
- Защита ветки `main`: [docs/branch-protection.md](docs/branch-protection.md)
- План релизов, окна, чек-лист и откат: [docs/release-plan.md](docs/release-plan.md)
- Шаблоны issue: **Release** (чек-лист релиза) и **Incident** (ставит метку `incident` для DORA)

Выпуск релиза:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/health` | Проверка работоспособности |
| POST | `/api/tickets` | Создать заявку |
| GET | `/api/tickets?status=&priority=` | Список заявок |
| GET | `/api/tickets/{id}` | Одна заявка |
| POST | `/api/tickets/{id}/status` | Сменить статус |
| GET | `/api/stats` | Открытые заявки по приоритетам, число нарушений SLA |
