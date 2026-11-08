"""Настройки Superset для локального стенда СППР."""
import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = "sqlite:////app/superset_home/superset.db"
# Витрина практики №6 - файл SQLite; разрешаем такое подключение только на локальном стенде
PREVENT_UNSAFE_DB_CONNECTIONS = False
BABEL_DEFAULT_LOCALE = "ru"
LANGUAGES = {"ru": {"flag": "ru", "name": "Русский"}, "en": {"flag": "us", "name": "English"}}
TALISMAN_ENABLED = False
WTF_CSRF_ENABLED = True
