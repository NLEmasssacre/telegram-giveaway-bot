# Быстрая инструкция по отправке на GitHub

## Вариант 1: Через терминал (самый простой)

Выполните эти команды по порядку:

### 1. Создайте репозиторий на GitHub:
   - Откройте https://github.com/new
   - Название: `telegram-giveaway-bot`
   - НЕ добавляйте README, .gitignore, license
   - Нажмите "Create repository"

### 2. Выполните команды (замените USERNAME на ваш GitHub username):

```bash
cd /Users/danial/Desktop/розыгрыш

# Подключите репозиторий (ЗАМЕНИТЕ USERNAME!)
git remote add origin https://github.com/USERNAME/telegram-giveaway-bot.git

# Отправьте код
git branch -M main
git push -u origin main
```

**Если потребуется авторизация:**
- GitHub попросит ввести username и password
- НО пароль не подойдет - нужен Personal Access Token

### 3. Создайте Personal Access Token:
   1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
   2. Generate new token (classic)
   3. Выберите scope: `repo` (полный доступ к репозиториям)
   4. Скопируйте токен
   5. При запросе пароля введите этот токен

---

## Вариант 2: Через GitHub Desktop

1. Скачайте GitHub Desktop: https://desktop.github.com
2. Войдите в свой аккаунт
3. File → Add Local Repository → выберите папку `/Users/danial/Desktop/розыгрыш`
4. Publish repository
5. Готово!

---

## Вариант 3: Я подготовлю одну команду

Скажите мне ваш GitHub username, и я подготовлю готовую команду, которую вы просто скопируете и вставите в терминал.

