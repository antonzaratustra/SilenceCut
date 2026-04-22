@echo off
set VENV_DIR=venv

if not exist %VENV_DIR% (
    echo Первый запуск: Создание виртуального окружения...
    python -m venv %VENV_DIR%
)

call %VENV_DIR%\Scripts\activate

echo Проверка зависимостей...
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo Запуск сервера SilenceCut на http://localhost:8765...
set PYTHONPATH=%PYTHONPATH%;.
python web/app.py
pause
