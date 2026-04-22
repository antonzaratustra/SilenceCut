#!/bin/bash

VENV_DIR="venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Первый запуск: Создание виртуального окружения..."
    python3 -m venv $VENV_DIR
fi

source $VENV_DIR/bin/activate

echo "Проверка зависимостей..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

python3 silencecut.py "$@"
