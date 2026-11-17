"""Interface strings in Kazakh, Russian and English."""

LANGUAGES = ("kk", "ru", "en")
DEFAULT_LANG = "kk"

TEXTS: dict[str, dict[str, str]] = {
    "kk": {
        "app_title": "Қолдау қызметі",
        "new_ticket": "Жаңа өтінім",
        "title": "Тақырып",
        "description": "Сипаттама",
        "requester": "Өтініш беруші",
        "priority": "Басымдық",
        "status": "Мәртебе",
        "created": "Құрылды",
        "response_due": "Жауап мерзімі",
        "resolve_due": "Шешу мерзімі",
        "submit": "Жіберу",
        "tickets": "Өтінімдер",
        "no_tickets": "Өтінімдер жоқ",
        "breached": "SLA бұзылды",
        "change_status": "Мәртебені өзгерту",
        "back": "Артқа",
        "new": "Жаңа",
        "in_progress": "Жұмыста",
        "resolved": "Шешілді",
        "closed": "Жабылды",
    },
    "ru": {
        "app_title": "Служба поддержки",
        "new_ticket": "Новая заявка",
        "title": "Тема",
        "description": "Описание",
        "requester": "Заявитель",
        "priority": "Приоритет",
        "status": "Статус",
        "created": "Создана",
        "response_due": "Срок реакции",
        "resolve_due": "Срок решения",
        "submit": "Отправить",
        "tickets": "Заявки",
        "no_tickets": "Заявок нет",
        "breached": "SLA нарушен",
        "change_status": "Сменить статус",
        "back": "Назад",
        "new": "Новая",
        "in_progress": "В работе",
        "resolved": "Решена",
        "closed": "Закрыта",
    },
    "en": {
        "app_title": "Helpdesk",
        "new_ticket": "New ticket",
        "title": "Title",
        "description": "Description",
        "requester": "Requester",
        "priority": "Priority",
        "status": "Status",
        "created": "Created",
        "response_due": "Response due",
        "resolve_due": "Resolve due",
        "submit": "Submit",
        "tickets": "Tickets",
        "no_tickets": "No tickets",
        "breached": "SLA breached",
        "change_status": "Change status",
        "back": "Back",
        "new": "New",
        "in_progress": "In progress",
        "resolved": "Resolved",
        "closed": "Closed",
    },
}


def get_texts(lang: str | None) -> tuple[str, dict[str, str]]:
    lang = lang if lang in LANGUAGES else DEFAULT_LANG
    return lang, TEXTS[lang]
