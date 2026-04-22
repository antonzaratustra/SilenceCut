#!/bin/bash

# Путь к виртуальному окружению
VENV_DIR="venv"

# Проверка наличия venv, если нет - создаем
if [ ! -d "$VENV_DIR" ]; then
    echo "Первый запуск: Создание виртуального окружения..."
    python3 -m venv $VENV_DIR
fi

# Активация venv
source $VENV_DIR/bin/activate

# Установка/обновление зависимостей (тихо)
echo "Проверка зависимостей..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# Запуск сервера
echo "Запуск сервера SilenceCut на http://localhost:8765..."
export PYTHONPATH=$PYTHONPATH:.
python3 web/app.py
