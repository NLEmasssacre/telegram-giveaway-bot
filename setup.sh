#!/bin/bash
# Скрипт быстрой установки бота на VPS сервер

echo "🚀 Начинаю установку Telegram бота..."

# Обновление системы
echo "📦 Обновляю систему..."
apt update && apt upgrade -y

# Установка Python и зависимостей
echo "🐍 Устанавливаю Python и зависимости..."
apt install -y python3 python3-pip python3-venv git

# Переход в домашнюю директорию
cd ~

# Клонирование проекта (ЗАМЕНИТЕ на ваш репозиторий!)
echo "📥 Клонирую проект..."
# git clone https://github.com/ВАШ_USERNAME/розыгрыш.git
# cd розыгрыш

# Если проект уже есть, просто переходим в него
if [ ! -d "розыгрыш" ]; then
    echo "❌ Папка 'розыгрыш' не найдена!"
    echo "💡 Создайте папку и скопируйте туда файлы проекта"
    exit 1
fi

cd розыгрыш

# Создание виртуального окружения
echo "🔧 Создаю виртуальное окружение..."
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
echo "📚 Устанавливаю зависимости Python..."
pip install -r requirements.txt

# Создание .env файла (если его нет)
if [ ! -f ".env" ]; then
    echo "📝 Создаю .env файл..."
    read -p "Введите BOT_TOKEN: " BOT_TOKEN
    echo "BOT_TOKEN=$BOT_TOKEN" > .env
    echo "✅ .env файл создан"
else
    echo "✅ .env файл уже существует"
fi

# Получаем абсолютный путь к проекту
PROJECT_DIR=$(pwd)
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"

# Создание systemd сервиса
echo "⚙️ Создаю systemd сервис..."
cat > /etc/systemd/system/telegram-bot.service << EOF
[Unit]
Description=Telegram Giveaway Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/venv/bin"
ExecStart=$VENV_PYTHON bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Активация сервиса
echo "🔄 Активирую сервис..."
systemctl daemon-reload
systemctl enable telegram-bot.service
systemctl start telegram-bot.service

# Проверка статуса
echo "📊 Проверяю статус..."
sleep 2
systemctl status telegram-bot.service --no-pager

echo ""
echo "✅ Установка завершена!"
echo ""
echo "📋 Полезные команды:"
echo "  • Просмотр логов: sudo journalctl -u telegram-bot.service -f"
echo "  • Перезапуск: sudo systemctl restart telegram-bot.service"
echo "  • Остановка: sudo systemctl stop telegram-bot.service"
echo "  • Статус: sudo systemctl status telegram-bot.service"

