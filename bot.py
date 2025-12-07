import asyncio
import logging
import os
import time

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    AIORateLimiter,
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Настройка логирования (на сервере логи могут идти в stdout)
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=getattr(logging, log_level, logging.INFO),
    handlers=[
        logging.StreamHandler()  # Для серверных платформ логи идут в stdout
    ]
)
# Добавляем файловый лог только если файл доступен для записи
try:
    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(file_handler)
except (PermissionError, OSError):
    pass  # На некоторых серверах файловые логи недоступны, используем только stdout

logger = logging.getLogger(__name__)

TARGET_CHAT = "@torgovlya_kfu"
CHAT_URL = "https://t.me/torgovlya_kfu"
TARGET_CHANNEL = "@kfu_torgovlya"
CHANNEL_URL = "https://t.me/kfu_torgovlya"
# Ссылка на пост с розыгрышем (будет обновлена позже)
GIVEAWAY_POST_URL = "https://t.me/torgovlya_kfu/1"  # TODO: заменить на реальную ссылку
# Дата итогов розыгрыша (будет обновлена позже)
GIVEAWAY_END_DATE = ""  # TODO: указать дату итогов розыгрыша
# Путь к изображению для сторис (афиша розыгрыша)
STORY_IMAGE_PATH = "story_image.png"  # Изображение для сторис

# Callback data константы
CHECK_SUBSCRIPTION = "check_subscription"
REQUIRED_STORY = "required_story"  # Обязательное условие - сторис с афишей
BOOST_CHANCE = "boost_chance"
SOCIAL_TELEGRAM = "social_telegram"
SOCIAL_WHATSAPP = "social_whatsapp"
SOCIAL_INSTAGRAM = "social_instagram"
BACK_TO_MAIN = "back_to_main"
MY_TICKETS = "my_tickets"  # Просмотр своих билетов
NEXT_PAGE = "next_page"  # Кнопка "Далее" для перехода к следующему окну
NEXT_TO_SUBSCRIPTION = "next_to_subscription"  # Переход к окну проверки подписки
NEXT_TO_REQUIRED = "next_to_required"  # Переход к окну обязательного условия
NEXT_TO_BOOST = "next_to_boost"  # Переход к окну увеличения шансов

# Кэш для проверки подписки: {user_id: (is_member: bool, timestamp: float)}
_subscription_cache: dict[int, tuple[bool, float]] = {}
CACHE_TTL = 300  # 5 минут кэш

# Хранилище билетов пользователей: {user_id: количество_билетов}
_user_tickets: dict[int, int] = {}

# Хранилище обязательных условий: {user_id: выполнено_ли_обязательное_условие}
_required_condition_done: dict[int, bool] = {}

# Хранилище выбранной соцсети для обязательного условия: {user_id: название_соцсети}
_required_social: dict[int, str] = {}

# Хранилище использованных соцсетей для дополнительных билетов: {user_id: set[название_соцсети]}
_used_boost_socials: dict[int, set[str]] = {}

# Кэш изображения для сторис (загружается один раз при первом использовании)
_story_image_bytes: bytes | None = None


def get_user_tickets(user_id: int) -> int:
    """Возвращает количество билетов пользователя"""
    return _user_tickets.get(user_id, 0)


def add_ticket(user_id: int, count: int = 1) -> int:
    """Добавляет билет(ы) пользователю и возвращает новое количество"""
    current = _user_tickets.get(user_id, 0)
    _user_tickets[user_id] = current + count
    return _user_tickets[user_id]


def has_required_condition(user_id: int) -> bool:
    """Проверяет, выполнено ли обязательное условие"""
    return _required_condition_done.get(user_id, False)


def set_required_condition(user_id: int, done: bool = True) -> None:
    """Устанавливает статус обязательного условия"""
    _required_condition_done[user_id] = done


def get_required_social(user_id: int) -> str | None:
    """Возвращает выбранную соцсеть для обязательного условия"""
    return _required_social.get(user_id)


def set_required_social(user_id: int, social: str) -> None:
    """Устанавливает выбранную соцсеть для обязательного условия"""
    _required_social[user_id] = social


def get_used_boost_socials(user_id: int) -> set[str]:
    """Возвращает множество использованных соцсетей для дополнительных билетов"""
    return _used_boost_socials.get(user_id, set())


def add_used_boost_social(user_id: int, social: str) -> None:
    """Добавляет соцсеть в список использованных для дополнительных билетов"""
    if user_id not in _used_boost_socials:
        _used_boost_socials[user_id] = set()
    _used_boost_socials[user_id].add(social)


def get_remaining_socials(user_id: int) -> list[tuple[str, str, str]]:
    """Возвращает список оставшихся соцсетей (название, callback, эмодзи)
    Исключает соцсеть для обязательного условия и уже использованные для дополнительных билетов"""
    required = get_required_social(user_id)
    used_boost = get_used_boost_socials(user_id)
    all_socials = [
        ("Telegram", SOCIAL_TELEGRAM, "📱"),
        ("WhatsApp", SOCIAL_WHATSAPP, "💬"),
        ("Instagram", SOCIAL_INSTAGRAM, "📸"),
    ]
    # Исключаем обязательную соцсеть и уже использованные для дополнительных билетов
    return [
        (name, callback, emoji) 
        for name, callback, emoji in all_socials 
        if name != required and name not in used_boost
    ]


def get_welcome_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для первого окна приветствия (только кнопка Далее)"""
    buttons = [
        [
            InlineKeyboardButton("➡️ Далее", callback_data=NEXT_TO_SUBSCRIPTION),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def get_subscription_check_keyboard(is_subscribed: bool) -> InlineKeyboardMarkup:
    """Клавиатура для окна проверки подписки"""
    buttons = []
    if not is_subscribed:
        buttons.append([
            InlineKeyboardButton("✅ Проверить подписку", callback_data=CHECK_SUBSCRIPTION),
        ])
        buttons.append([
            InlineKeyboardButton("🔗 Вступить в чат", url=CHAT_URL),
        ])
        buttons.append([
            InlineKeyboardButton("📢 Подписаться на канал", url=CHANNEL_URL),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("➡️ Далее", callback_data=NEXT_TO_REQUIRED),
        ])
    buttons.append([
        InlineKeyboardButton("↩️ Назад", callback_data=BACK_TO_MAIN),
    ])
    return InlineKeyboardMarkup(buttons)


def get_required_condition_keyboard(has_required: bool) -> InlineKeyboardMarkup:
    """Клавиатура для окна обязательного условия"""
    buttons = []
    if not has_required:
        buttons.append([
            InlineKeyboardButton("📸 Выполнить обязательное условие", callback_data=REQUIRED_STORY),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("➡️ Далее", callback_data=NEXT_TO_BOOST),
        ])
    buttons.append([
        InlineKeyboardButton("↩️ Назад", callback_data=NEXT_TO_SUBSCRIPTION),
    ])
    return InlineKeyboardMarkup(buttons)


def get_profile_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура только с кнопкой Профиль"""
    buttons = [
        [
            InlineKeyboardButton("👤 Профиль", callback_data=MY_TICKETS),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def get_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Главное меню с билетами, ID, именем и кнопкой увеличить шанс"""
    # Проверяем, есть ли еще доступные соцсети
    remaining_socials = get_remaining_socials(user_id)
    
    if remaining_socials:
        # Есть доступные соцсети - показываем кнопку "Увеличить шанс"
        buttons = [
            [
                InlineKeyboardButton("🎁 Увеличить шанс", callback_data=BOOST_CHANCE),
            ],
        ]
    else:
        # Все соцсети использованы - показываем только кнопку "Профиль"
        buttons = [
            [
                InlineKeyboardButton("👤 Профиль", callback_data=MY_TICKETS),
            ],
        ]
    return InlineKeyboardMarkup(buttons)


def get_boost_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для окна увеличения шансов - показывает только оставшиеся соцсети"""
    buttons = []
    
    # Получаем оставшиеся соцсети (исключая ту, что использована для обязательного условия)
    remaining_socials = get_remaining_socials(user_id)
    
    if remaining_socials:
        # Показываем кнопки для оставшихся соцсетей
        for name, callback, emoji in remaining_socials:
            buttons.append([
                InlineKeyboardButton(f"{emoji} {name}", callback_data=callback),
            ])
    
    buttons.append([
        InlineKeyboardButton("↩️ Назад", callback_data="back_to_main_menu"),
    ])
    return InlineKeyboardMarkup(buttons)


def get_main_keyboard(show_check_button: bool = True, user_id: int = None) -> InlineKeyboardMarkup:
    """Возвращает главную клавиатуру"""
    buttons = []
    if show_check_button:
        buttons.append([
            InlineKeyboardButton("✅ Проверить подписку", callback_data=CHECK_SUBSCRIPTION),
        ])
    
    # Проверяем обязательное условие - кнопка "Повысить шанс" только после выполнения обязательного условия
    if user_id is not None:
        if not has_required_condition(user_id):
            # Обязательное условие не выполнено - показываем только кнопку для его выполнения
            buttons.append([
                InlineKeyboardButton("📸 Выполнить обязательное условие", callback_data=REQUIRED_STORY),
            ])
        else:
            # Обязательное условие выполнено - можно повышать шанс
            buttons.append([
                InlineKeyboardButton("🎁 Повысить шанс", callback_data=BOOST_CHANCE),
            ])
            buttons.append([
                InlineKeyboardButton(f"🎫 Мои билеты: {get_user_tickets(user_id)}", callback_data=MY_TICKETS),
            ])
    # Если user_id не передан, не показываем кнопку "Повысить шанс" (безопасность)
    
    return InlineKeyboardMarkup(buttons)


def get_subscribe_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой вступления в чат"""
    buttons = [
        [
            InlineKeyboardButton("🔗 Вступить в чат", url=CHAT_URL),
        ],
        [
            InlineKeyboardButton("✅ Проверить подписку", callback_data=CHECK_SUBSCRIPTION),
        ],
        [
            InlineKeyboardButton("↩️ Назад", callback_data=BACK_TO_MAIN),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def get_social_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора соцсети"""
    buttons = [
        [
            InlineKeyboardButton("📱 Telegram", callback_data=SOCIAL_TELEGRAM),
        ],
        [
            InlineKeyboardButton("💬 WhatsApp", callback_data=SOCIAL_WHATSAPP),
            InlineKeyboardButton("📸 Instagram", callback_data=SOCIAL_INSTAGRAM),
        ],
        [
            InlineKeyboardButton("↩️ Назад", callback_data=BACK_TO_MAIN),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def check_single_subscription(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: str
) -> bool:
    """Проверяет подписку пользователя на один чат/канал"""
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return (
            member.status == ChatMemberStatus.MEMBER or
            member.status == ChatMemberStatus.ADMINISTRATOR or
            member.status == ChatMemberStatus.RESTRICTED
        )
    except Exception as exc:
        error_msg = str(exc).lower()
        if "user not found" in error_msg or "chat member not found" in error_msg or "member not found" in error_msg:
            return False
        logger.error(f"❌ Ошибка при проверке подписки {chat_id}: {exc}")
        return False


async def is_member_cached(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, use_cache: bool = True
) -> bool:
    """Проверяет подписку на чат И канал с кэшированием"""
    current_time = time.time()
    
    # Проверяем кэш
    if use_cache and user_id in _subscription_cache:
        is_member, cached_time = _subscription_cache[user_id]
        if current_time - cached_time < CACHE_TTL:
            return is_member
        # Кэш устарел, удаляем
        del _subscription_cache[user_id]
    
    # Делаем API запрос (параллельно проверяем чат и канал)
    try:
        # Параллельная проверка подписки на чат и канал для ускорения
        is_chat_member, is_channel_member = await asyncio.gather(
            check_single_subscription(context, user_id, TARGET_CHAT),
            check_single_subscription(context, user_id, TARGET_CHANNEL),
            return_exceptions=False
        )
        
        # Пользователь должен быть подписан на ОБА
        is_member = is_chat_member and is_channel_member
        
        # Сохраняем в кэш
        _subscription_cache[user_id] = (is_member, current_time)
        return is_member
        
    except Exception as exc:
        logger.error(f"❌ Ошибка при проверке подписки пользователя {user_id}: {exc}")
        
        # В случае ошибки используем кэш, если есть
        if user_id in _subscription_cache:
            return _subscription_cache[user_id][0]
        return False


async def check_subscription_in_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверяет подписку пользователя при отправке сообщения в чат"""
    message = update.message
    if not message or not message.chat or not message.from_user:
        return
    
    # Быстрые проверки для раннего выхода
    if message.chat.type not in ("group", "supergroup") or message.from_user.is_bot:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Проверяем подписку (с кэшем)
    if not await is_member_cached(context, user_id):
        try:
            username = message.from_user.username or 'Пользователь'
            warning_text = (
                f"👋 @{username}\n\n"
                f"⚠️ Для участия в чате необходимо вступить в чат {TARGET_CHAT} и подписаться на канал {TARGET_CHANNEL}.\n\n"
                f"🔗 Вступи в чат и подпишись на канал, затем попробуй снова."
            )
            
            # Параллельно удаляем сообщение и отправляем предупреждение
            delete_task = message.delete()
            warning_task = context.bot.send_message(chat_id=chat_id, text=warning_text)
            
            # Выполняем параллельно
            results = await asyncio.gather(delete_task, warning_task, return_exceptions=True)
            
            # Удаляем предупреждение через 10 секунд (не блокируем)
            warning = results[1] if len(results) > 1 and not isinstance(results[1], Exception) else None
            if warning and hasattr(warning, 'chat_id'):
                asyncio.create_task(
                    _delete_message_after_delay(context, warning.chat_id, warning.message_id, 10)
                )
        except Exception as exc:
            logger.exception("Failed to handle non-subscriber: %s", exc)


async def _delete_message_after_delay(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int
) -> None:
    """Удаляет сообщение через указанное время (не блокирует)"""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass  # Игнорируем ошибки удаления (сообщение уже удалено или нет прав)


async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает новых участников чата и проверяет их подписку"""
    if not update.message or not update.message.new_chat_members:
        return
    
    chat_id = update.message.chat.id
    tasks = []
    
    for new_member in update.message.new_chat_members:
        # Пропускаем бота
        if new_member.is_bot and new_member.id == context.bot.id:
            continue
        
        user_id = new_member.id
        
        # Проверяем подписку (без кэша для новых участников)
        if not await is_member_cached(context, user_id, use_cache=False):
            try:
                # Удаляем пользователя из чата
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
                
                # Отправляем предупреждение
                warning = await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"👋 @{new_member.username or 'Пользователь'}\n\n"
                         f"❌ Был удалён из чата.\n\n"
                         f"⚠️ Для участия необходимо вступить в чат {TARGET_CHAT} и подписаться на канал {TARGET_CHANNEL}.\n"
                         f"🔗 После вступления попробуй присоединиться снова.",
                )
                # Удаляем предупреждение через 30 секунд
                asyncio.create_task(
                    _delete_message_after_delay(context, warning.chat_id, warning.message_id, 30)
                )
            except Exception as exc:
                logger.exception("Failed to remove non-subscriber from chat: %s", exc)
        else:
            # Пользователь подписан - отправляем приветствие
            try:
                welcome = await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"👋 Добро пожаловать, @{new_member.username or 'Пользователь'}!\n\n"
                         f"✅ Вступление в чат подтверждено.\n\n"
                         f"🎉 Приятного общения!",
                )
                # Удаляем приветствие через 10 секунд
                asyncio.create_task(
                    _delete_message_after_delay(context, welcome.chat_id, welcome.message_id, 10)
                )
            except Exception:
                pass  # Игнорируем ошибки приветствия


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start - показывает первое окно приветствия"""
    text = (
        "🎉 Добро пожаловать на розыгрыш iPhone 17 Pro Max!\n\n"
        "📱 От Торговли КФУ совместно с 9:41 store"
    )
    await update.message.reply_text(text, reply_markup=get_welcome_keyboard())


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    if not query:
        return

    try:
        await query.answer()
        user_id = query.from_user.id
        callback_data = query.data

        if callback_data == CHECK_SUBSCRIPTION:
            # Очищаем кэш для этого пользователя, чтобы проверить актуальный статус
            if user_id in _subscription_cache:
                del _subscription_cache[user_id]
            
            # Проверяем подписку (без кэша для актуальной проверки)
            if await is_member_cached(context, user_id, use_cache=False):
                text = (
                    "✅ Отлично! Ты подписан на чат и канал.\n\n"
                    "Нажми «Далее», чтобы перейти к следующему шагу."
                )
                await query.edit_message_text(
                    text,
                    reply_markup=get_subscription_check_keyboard(is_subscribed=True),
                )
            else:
                await query.edit_message_text(
                    "❌ Ты ещё не подписан на чат и канал.",
                    reply_markup=get_subscription_check_keyboard(is_subscribed=False),
                )
            return

        if callback_data == NEXT_TO_SUBSCRIPTION:
            # Окно 2: Проверка подписки
            user_id = query.from_user.id
            # Очищаем кэш для актуальной проверки
            if user_id in _subscription_cache:
                del _subscription_cache[user_id]
            is_subscribed = await is_member_cached(context, user_id, use_cache=False)
            
            if is_subscribed:
                text = (
                    "✅ Отлично! Ты подписан на чат и канал.\n\n"
                    "Нажми «Далее», чтобы перейти к следующему шагу."
                )
            else:
                text = "Для участия нужно подписаться"
            
            await query.edit_message_text(
                text,
                reply_markup=get_subscription_check_keyboard(is_subscribed),
            )
            return

        if callback_data == NEXT_TO_REQUIRED:
            # Окно 3: Обязательное условие
            user_id = query.from_user.id
            has_required = has_required_condition(user_id)
            
            if has_required:
                # Если условие выполнено, переходим к окну увеличения шансов
                tickets = get_user_tickets(user_id)
                remaining_socials = get_remaining_socials(user_id)
                required_social = get_required_social(user_id)
                
                text = (
                    f"✅ Обязательное условие уже выполнено!\n\n"
                    f"🎫 Твои билеты: {tickets}\n\n"
                )
                
                if required_social:
                    remaining_names = [name for name, _, _ in remaining_socials]
                    text += (
                        f"✅ Обязательное условие выполнено в {required_social}\n\n"
                        f"📋 Можешь повысить шанс:\n"
                        f"• Выложи истории в оставшихся соцсетях: {', '.join(remaining_names)}\n"
                        f"• Каждая история = +1 билет\n\n"
                    )
                else:
                    text += (
                        "📋 Можешь повысить шанс:\n"
                        "• Отправь скриншот репоста в любой соцсети\n"
                        "• Каждый репост = +1 билет\n\n"
                    )
                
                text += "✨ Чем больше билетов, тем выше шанс выиграть!"
                
                await query.edit_message_text(
                    text,
                    reply_markup=get_boost_keyboard(user_id),
                )
            else:
                # Отправляем изображение для сторис с текстом и кнопками
                text = (
                    "📸 Афиша розыгрыша для Stories\n\n"
                    "Для участия в розыгрыше нужно:\n\n"
                    "1️⃣ Скачай это изображение и выложи в Stories (Telegram/WhatsApp/Instagram)\n"
                    "2️⃣ Добавь ссылку на наш чат: t.me/torgovlya_kfu\n\n"
                    "3️⃣ Нажми кнопку «📸 Выполнить обязательное условие» и выбери соцсеть\n"
                    "4️⃣ Отправь скриншот своего Stories сюда\n\n"
                    "✅ После выполнения получишь 1 билет (обязательное условие)\n"
                    "🎁 Затем сможешь повысить шанс дополнительными репостами!"
                )
                
                try:
                    if os.path.exists(STORY_IMAGE_PATH):
                        # Редактируем сообщение, заменяя его на фото с подписью
                        with open(STORY_IMAGE_PATH, "rb") as photo:
                            await query.edit_message_media(
                                media=InputMediaPhoto(
                                    media=photo,
                                    caption=text,
                                ),
                                reply_markup=get_required_condition_keyboard(has_required),
                            )
                    else:
                        # Если файла нет, показываем обычный текст
                        logger.warning(f"⚠️ Файл изображения {STORY_IMAGE_PATH} не найден. Добавьте изображение для сторис.")
                        await query.edit_message_text(
                            text,
                            reply_markup=get_required_condition_keyboard(has_required),
                        )
                except Exception as e:
                    logger.error(f"❌ Ошибка при отправке изображения: {e}")
                    # Если ошибка, показываем обычный текст
                    await query.edit_message_text(
                        text,
                        reply_markup=get_required_condition_keyboard(has_required),
                    )
            return

        if callback_data == NEXT_TO_BOOST:
            # Окно 4: Увеличение шансов
            user_id = query.from_user.id
            tickets = get_user_tickets(user_id)
            
            # Получаем оставшиеся соцсети
            remaining_socials = get_remaining_socials(user_id)
            required_social = get_required_social(user_id)
            
            text = (
                f"🎫 Твои билеты: {tickets}\n\n"
            )
            
            if required_social:
                remaining_names = [name for name, _, _ in remaining_socials]
                text += (
                    f"✅ Обязательное условие выполнено в {required_social}\n\n"
                    f"📋 Можешь повысить шанс:\n"
                    f"• Выложи истории в оставшихся соцсетях: {', '.join(remaining_names)}\n"
                    f"• Каждая история = +1 билет\n\n"
                )
            else:
                text += (
                    "📋 Можешь повысить шанс:\n"
                    "• Отправь скриншот репоста в любой соцсети\n"
                    "• Каждый репост = +1 билет\n\n"
                )
            
            text += "✨ Чем больше билетов, тем выше шанс выиграть!"
            
            await query.edit_message_text(
                text,
                reply_markup=get_boost_keyboard(user_id),
            )
            return

        if callback_data == REQUIRED_STORY:
            try:
                # Проверяем подписку
                if not await is_member_cached(context, user_id):
                    await query.edit_message_text(
                        "⚠️ Сначала нужно вступить в чат!\n\n"
                        "Вернись к шагу проверки подписки.",
                        reply_markup=get_subscription_check_keyboard(is_subscribed=False),
                    )
                    return
                
                # Окно выбора соцсети
                text = (
                    "📸 Выбери соцсеть, где выложишь сторис:\n\n"
                    "💡 Выбери одну из соцсетей ниже"
                )
                context.user_data["awaiting_required_story"] = True
                buttons = [
                    [
                        InlineKeyboardButton("📱 Telegram", callback_data=SOCIAL_TELEGRAM),
                    ],
                    [
                        InlineKeyboardButton("💬 WhatsApp", callback_data=SOCIAL_WHATSAPP),
                        InlineKeyboardButton("📸 Instagram", callback_data=SOCIAL_INSTAGRAM),
                    ],
                    [
                        InlineKeyboardButton("↩️ Назад", callback_data=NEXT_TO_REQUIRED),
                    ],
                ]
                
                # Если текущее сообщение - это медиа (фото), используем edit_message_media, иначе edit_message_text
                try:
                    if query.message.photo:
                        # Если сообщение с фото, пытаемся отредактировать медиа
                        await query.edit_message_caption(
                            caption=text,
                            reply_markup=InlineKeyboardMarkup(buttons),
                        )
                    else:
                        # Обычное текстовое сообщение
                        await query.edit_message_text(
                            text,
                            reply_markup=InlineKeyboardMarkup(buttons),
                        )
                except Exception as edit_exc:
                    # Если не удалось отредактировать, пробуем отправить новое сообщение
                    logger.error(f"❌ Ошибка при редактировании сообщения: {edit_exc}")
                    await query.message.reply_text(
                        text,
                        reply_markup=InlineKeyboardMarkup(buttons),
                    )
                    try:
                        await query.message.delete()
                    except:
                        pass
                
                return
            except Exception as e:
                logger.exception(f"❌ Ошибка в обработчике REQUIRED_STORY: {e}")
                await query.answer("Произошла ошибка. Попробуй ещё раз.", show_alert=True)

        if callback_data == MY_TICKETS:
            tickets = get_user_tickets(user_id)
            
            user = query.from_user
            user_name = user.first_name or "Пользователь"
            if user.last_name:
                user_name += f" {user.last_name}"
            user_id_display = user.id
            
            text = (
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Имя: {user_name}\n"
                f"🆔 ID: {user_id_display}\n"
                f"🎫 Билетов: {tickets}\n"
            )
            
            if GIVEAWAY_END_DATE:
                text += f"📅 Дата итогов: {GIVEAWAY_END_DATE}\n"
            
            text += f"━━━━━━━━━━━━━━━━━━━━"
            
            await query.edit_message_text(
                text,
                reply_markup=get_main_menu_keyboard(user_id),
            )
            return

        if callback_data == BOOST_CHANCE:
            # Проверяем подписку
            if not await is_member_cached(context, user_id):
                await query.edit_message_text(
                    "⚠️ Сначала нужно вступить в чат!\n\n"
                    "Вернись к шагу проверки подписки.",
                    reply_markup=get_subscription_check_keyboard(is_subscribed=False),
                )
                return
            
            # Проверяем обязательное условие - ОБЯЗАТЕЛЬНО перед повышением шанса
            if not has_required_condition(user_id):
                await query.edit_message_text(
                    "⚠️ Сначала нужно выполнить обязательное условие!\n\n"
                    "📸 Выложи в Stories афишу розыгрыша с ссылкой на пост.\n"
                    "После выполнения обязательного условия ты получишь 1 билет и сможешь повысить шанс дополнительными репостами.\n\n"
                    "💡 Обязательное условие = 1 билет (минимум для участия)\n"
                    "🎁 Дополнительные репосты = +1 билет за каждый",
                    reply_markup=get_required_condition_keyboard(has_required=False),
                )
                return
            
            # Показываем окно с выбором оставшихся соцсетей
            tickets = get_user_tickets(user_id)
            remaining_socials = get_remaining_socials(user_id)
            required_social = get_required_social(user_id)
            
            if not remaining_socials:
                # Все соцсети использованы - показываем только кнопку Профиль
                user = query.from_user
                user_name = user.first_name or "Пользователь"
                if user.last_name:
                    user_name += f" {user.last_name}"
                user_id_display = user.id
                
                await query.edit_message_text(
                    f"🎉 Ты использовал все доступные соцсети!\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 Имя: {user_name}\n"
                    f"🆔 ID: {user_id_display}\n"
                    f"🎫 Билетов: {tickets}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"✨ Удачи в розыгрыше!",
                    reply_markup=get_profile_keyboard(),
                )
                return
            
            remaining_names = [name for name, _, _ in remaining_socials]
            text = (
                f"📋 Выбери соцсеть для увеличения шанса:\n\n"
                f"💡 Доступные соцсети: {', '.join(remaining_names)}\n"
                f"🎫 Каждая история = +1 билет\n\n"
                f"✨ Чем больше билетов, тем выше шанс выиграть!"
            )
            
            await query.edit_message_text(
                text,
                reply_markup=get_boost_keyboard(user_id),
            )
            return
        
        if callback_data == "back_to_main_menu":
            # Возврат в главное меню
            user = query.from_user
            user_name = user.first_name or "Пользователь"
            if user.last_name:
                user_name += f" {user.last_name}"
            user_id_display = user.id
            tickets = get_user_tickets(user_id)
            
            text = (
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Имя: {user_name}\n"
                f"🆔 ID: {user_id_display}\n"
                f"🎫 Билетов: {tickets}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎁 Нажми «Увеличить шанс», чтобы получить дополнительные билеты!"
            )
            
            await query.edit_message_text(
                text,
                reply_markup=get_main_menu_keyboard(user_id),
            )
            return

        if callback_data == SOCIAL_TELEGRAM:
            try:
                context.user_data["selected_social"] = "Telegram"
                is_required = context.user_data.get("awaiting_required_story", False)
                
                if is_required:
                    # Сохраняем выбранную соцсеть для обязательного условия
                    set_required_social(user_id, "Telegram")
                    context.user_data["awaiting_required_story"] = True
                    text = (
                        "📱 Соцсеть выбрана: Telegram\n\n"
                        "📸 Отправь скриншот своего Stories с афишей розыгрыша.\n\n"
                        "💡 Убедись, что на скриншоте видно:\n"
                        "• Твой профиль\n"
                        "• Афиша розыгрыша\n"
                        f"• Ссылка на чат: t.me/torgovlya_kfu\n\n"
                        "✅ После отправки получишь 1 билет (обязательное условие)!"
                    )
                    buttons = [
                        [
                            InlineKeyboardButton("↩️ Назад", callback_data=REQUIRED_STORY),
                        ],
                    ]
                    keyboard = InlineKeyboardMarkup(buttons)
                else:
                    # Проверяем, что это не та же соцсеть, что для обязательного условия и не использована для дополнительных билетов
                    required_social = get_required_social(user_id)
                    used_boost = get_used_boost_socials(user_id)
                    if required_social == "Telegram" or "Telegram" in used_boost:
                        await query.answer("❌ Ты уже использовал Telegram. Выбери другую соцсеть!", show_alert=True)
                        return
                    context.user_data["awaiting_screenshot"] = True
                    text = (
                        "📱 Выбрана соцсеть: Telegram\n\n"
                        "📸 Отправь скриншот репоста поста в Telegram Stories или чате.\n\n"
                        "💡 Убедись, что на скриншоте видно:\n"
                        "• Твой профиль\n"
                        "• Репост нашего поста\n\n"
                        "🎫 За каждый репост получишь +1 билет!"
                    )
                    keyboard = get_boost_keyboard(user_id)
                
                # Пытаемся отредактировать сообщение (поддерживаем и медиа, и текст)
                try:
                    if query.message.photo:
                        # Если сообщение с фото, редактируем подпись
                        await query.edit_message_caption(
                            caption=text,
                            reply_markup=keyboard,
                        )
                    else:
                        # Обычное текстовое сообщение
                        await query.edit_message_text(
                            text,
                            reply_markup=keyboard,
                        )
                except Exception as edit_exc:
                    # Если не удалось отредактировать, отправляем новое сообщение
                    logger.error(f"❌ Ошибка при редактировании сообщения: {edit_exc}")
                    await query.message.reply_text(
                        text,
                        reply_markup=keyboard,
                    )
                    try:
                        await query.message.delete()
                    except:
                        pass
                
                return
            except Exception as e:
                logger.exception(f"❌ Ошибка в обработчике SOCIAL_TELEGRAM: {e}")
                await query.answer("Произошла ошибка. Попробуй ещё раз.", show_alert=True)

        if callback_data == SOCIAL_WHATSAPP:
            context.user_data["selected_social"] = "WhatsApp"
            is_required = context.user_data.get("awaiting_required_story", False)
            
            if is_required:
                # Сохраняем выбранную соцсеть для обязательного условия
                set_required_social(user_id, "WhatsApp")
                context.user_data["awaiting_required_story"] = True
                text = (
                    "💬 Соцсеть выбрана: WhatsApp\n\n"
                    "📸 Отправь скриншот своего Status с афишей розыгрыша.\n\n"
                    "💡 Убедись, что на скриншоте видно:\n"
                    "• Твой профиль\n"
                    "• Афиша розыгрыша\n"
                    f"• Ссылка на чат: t.me/torgovlya_kfu\n\n"
                    "✅ После отправки получишь 1 билет (обязательное условие)!"
                )
                buttons = [
                    [
                        InlineKeyboardButton("↩️ Назад", callback_data=REQUIRED_STORY),
                    ],
                ]
                keyboard = InlineKeyboardMarkup(buttons)
            else:
                # Проверяем, что это не та же соцсеть, что для обязательного условия и не использована для дополнительных билетов
                required_social = get_required_social(user_id)
                used_boost = get_used_boost_socials(user_id)
                if required_social == "WhatsApp" or "WhatsApp" in used_boost:
                    await query.answer("❌ Ты уже использовал WhatsApp. Выбери другую соцсеть!", show_alert=True)
                    return
                context.user_data["awaiting_screenshot"] = True
                text = (
                    "💬 Выбрана соцсеть: WhatsApp\n\n"
                    "📸 Отправь скриншот репорта поста в WhatsApp Status.\n\n"
                    "💡 Убедись, что на скриншоте видно:\n"
                    "• Твой профиль\n"
                    "• Репост нашего поста\n\n"
                    "🎫 За каждый репост получишь +1 билет!"
                )
                keyboard = get_boost_keyboard(user_id)
            await query.edit_message_text(
                text,
                reply_markup=keyboard,
            )
            return

        if callback_data == SOCIAL_INSTAGRAM:
            context.user_data["selected_social"] = "Instagram"
            is_required = context.user_data.get("awaiting_required_story", False)
            
            if is_required:
                # Сохраняем выбранную соцсеть для обязательного условия
                set_required_social(user_id, "Instagram")
                context.user_data["awaiting_required_story"] = True
                text = (
                    "📸 Соцсеть выбрана: Instagram\n\n"
                    "📸 Отправь скриншот своего Stories с афишей розыгрыша.\n\n"
                    "💡 Убедись, что на скриншоте видно:\n"
                    "• Твой профиль\n"
                    "• Афиша розыгрыша\n"
                    f"• Ссылка на чат: t.me/torgovlya_kfu\n\n"
                    "✅ После отправки получишь 1 билет (обязательное условие)!"
                )
                buttons = [
                    [
                        InlineKeyboardButton("↩️ Назад", callback_data=REQUIRED_STORY),
                    ],
                ]
                keyboard = InlineKeyboardMarkup(buttons)
            else:
                # Проверяем, что это не та же соцсеть, что для обязательного условия и не использована для дополнительных билетов
                required_social = get_required_social(user_id)
                used_boost = get_used_boost_socials(user_id)
                if required_social == "Instagram" or "Instagram" in used_boost:
                    await query.answer("❌ Ты уже использовал Instagram. Выбери другую соцсеть!", show_alert=True)
                    return
                context.user_data["awaiting_screenshot"] = True
                text = (
                    "📸 Выбрана соцсеть: Instagram\n\n"
                    "📸 Отправь скриншот репоста поста в Instagram Stories.\n\n"
                    "💡 Убедись, что на скриншоте видно:\n"
                    "• Твой профиль\n"
                    "• Репост нашего поста\n\n"
                    "🎫 За каждый репост получишь +1 билет!"
                )
                keyboard = get_boost_keyboard(user_id)
            await query.edit_message_text(
                text,
                reply_markup=keyboard,
            )
            return

        if callback_data == BACK_TO_MAIN:
            # Возвращаем в первое окно приветствия
            text = (
                "🎉 Добро пожаловать на розыгрыш iPhone 17 Pro Max!\n\n"
                "📱 От Торговли КФУ совместно с 9:41 store"
            )
            await query.edit_message_text(
                text,
                reply_markup=get_welcome_keyboard(),
            )
            return

    except Exception as exc:
        logger.exception(f"Error in handle_buttons: {exc}")
        try:
            await query.answer("Произошла ошибка. Попробуй ещё раз.", show_alert=True)
        except:
            pass


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик фото"""
    user_id = update.message.from_user.id
    is_subscribed = await is_member_cached(context, user_id)
    
    # Проверяем, это обязательное условие или дополнительный репост
    is_required = context.user_data.get("awaiting_required_story", False)
    is_boost = context.user_data.get("awaiting_screenshot", False)
    
    if not (is_required or is_boost):
        await update.message.reply_text(
            "📸 Я жду скриншот только после выбора действия.\n\n"
            "Выбери действие через кнопки меню.",
            reply_markup=get_main_keyboard(show_check_button=not is_subscribed, user_id=user_id),
        )
        return

    selected_social = context.user_data.get("selected_social", "соцсети")
    
    if is_required:
        # Обязательное условие выполнено
        context.user_data["awaiting_required_story"] = False
        # Сохраняем выбранную соцсеть (уже сохранена при выборе)
        set_required_condition(user_id, True)
        tickets = add_ticket(user_id, 1)  # +1 билет за обязательное условие
        
        # Получаем информацию о пользователе
        user = update.message.from_user
        user_name = user.first_name or "Пользователь"
        if user.last_name:
            user_name += f" {user.last_name}"
        user_id_display = user.id
        
        # Показываем главное меню
        text = (
            f"✅ Отлично! Обязательное условие выполнено!\n\n"
            f"📸 Скриншот Stories из {selected_social} получен.\n\n"
            f"🎫 Ты получил 1 билет (обязательное условие)!\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Имя: {user_name}\n"
            f"🆔 ID: {user_id_display}\n"
            f"🎫 Билетов: {tickets}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎁 Нажми «Увеличить шанс», чтобы получить дополнительные билеты!"
        )
        
        # Показываем главное меню
        keyboard = get_main_menu_keyboard(user_id)
    else:
        # Дополнительный репост
        # Проверяем, что это не та же соцсеть, что для обязательного условия и не использована для дополнительных билетов
        required_social = get_required_social(user_id)
        used_boost = get_used_boost_socials(user_id)
        
        if (required_social and selected_social == required_social) or selected_social in used_boost:
            await update.message.reply_text(
                f"❌ Ты уже использовал {selected_social}.\n\n"
                f"📱 Выбери другую соцсеть из оставшихся.",
                reply_markup=get_boost_keyboard(user_id),
            )
            return
        
        # Сохраняем использованную соцсеть для дополнительных билетов
        add_used_boost_social(user_id, selected_social)
        context.user_data["awaiting_screenshot"] = False
        context.user_data["selected_social"] = None
        tickets = add_ticket(user_id, 1)  # +1 билет за дополнительный репост
        
        # Получаем информацию о пользователе
        user = update.message.from_user
        user_name = user.first_name or "Пользователь"
        if user.last_name:
            user_name += f" {user.last_name}"
        user_id_display = user.id
        
        # Получаем оставшиеся соцсети
        remaining_socials = get_remaining_socials(user_id)
        
        text = (
            f"✅ Отлично! Скриншот из {selected_social} получен!\n\n"
            f"🎫 Ты получил +1 билет!\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Имя: {user_name}\n"
            f"🆔 ID: {user_id_display}\n"
            f"🎫 Билетов: {tickets}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        
        if remaining_socials:
            remaining_names = [name for name, _, _ in remaining_socials]
            text += (
                f"💡 Можешь отправить ещё скриншоты из оставшихся соцсетей: {', '.join(remaining_names)}\n"
                f"✨ Чем больше билетов, тем выше шанс выиграть!"
            )
            # Возвращаемся в главное меню
            keyboard = get_main_menu_keyboard(user_id)
        else:
            text += (
                f"🎉 Ты использовал все доступные соцсети!\n"
                f"✨ Удачи в розыгрыше!"
            )
            # Все соцсети использованы - показываем только кнопку Профиль
            keyboard = get_profile_keyboard()
    
    await update.message.reply_text(
        text,
        reply_markup=keyboard,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    user_id = update.message.from_user.id
    is_subscribed = await is_member_cached(context, user_id)
    has_required = has_required_condition(user_id)
    tickets = get_user_tickets(user_id)
    
    if is_subscribed:
        if has_required:
            text = (
                "👋 Используй кнопки ниже для взаимодействия с ботом:\n\n"
                f"🎫 Твои билеты: {tickets}\n\n"
                "• «🎁 Повысить шанс» — отправь скриншот репоста (+1 билет)\n"
                "• «🎫 Мои билеты» — посмотри количество билетов"
            )
            keyboard = get_boost_keyboard(user_id)
        else:
            text = (
                "👋 Используй кнопки ниже для взаимодействия с ботом:\n\n"
                "• «📸 Выполнить обязательное условие» — сторис с афишей (обязательно)\n"
                "• После выполнения сможешь повысить шанс дополнительными репостами"
            )
            keyboard = get_required_condition_keyboard(has_required=False)
    else:
        text = (
            "👋 Используй кнопки ниже для взаимодействия с ботом:\n\n"
            "• «✅ Проверить подписку» — проверь вступление в чат\n"
            "• После вступления выполни обязательное условие"
        )
        keyboard = get_subscription_check_keyboard(is_subscribed=False)
    
    await update.message.reply_text(
        text,
        reply_markup=keyboard,
    )


def build_application(token: str) -> Application:
    """Создает и настраивает приложение бота"""
    return (
        Application.builder()
        .token(token)
        .rate_limiter(AIORateLimiter())
        .concurrent_updates(True)  # Разрешаем параллельную обработку обновлений
        .build()
    )


async def check_bot_permissions(application: Application) -> None:
    """Проверяет права бота в целевом чате при запуске"""
    try:
        bot = application.bot
        logger.info(f"🔍 Проверяю права бота в {TARGET_CHAT}...")
        
        # Проверяем, может ли бот получить информацию о чате
        chat = await bot.get_chat(TARGET_CHAT)
        logger.info(f"✅ Чат найден: {chat.title} (тип: {chat.type})")
        
        # Проверяем статус бота в чате
        bot_member = await bot.get_chat_member(TARGET_CHAT, bot.id)
        status_name = bot_member.status.name if hasattr(bot_member.status, 'name') else str(bot_member.status)
        logger.info(f"🤖 Статус бота в чате: {status_name}")
        
        if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
            logger.warning(f"⚠️ Бот НЕ является администратором в {TARGET_CHAT}!")
            logger.warning(f"💡 Добавь бота как администратора с правами:")
            logger.warning(f"   - Просмотр участников (View members)")
            logger.warning(f"   - Просмотр информации о канале (View channel info)")
        else:
            logger.info(f"✅ Бот является администратором в {TARGET_CHAT}")
            
        # Тестовая проверка подписки (проверяем самого бота)
        try:
            test_member = await bot.get_chat_member(TARGET_CHAT, bot.id)
            logger.info(f"✅ Тестовая проверка подписки прошла успешно")
        except Exception as test_exc:
            logger.error(f"❌ Тестовая проверка подписки не удалась: {test_exc}")
            logger.error(f"💡 Бот не может проверять подписки. Убедись в правах администратора.")
            
    except Exception as exc:
        error_msg = str(exc).lower()
        logger.error(f"❌ Не могу проверить права бота: {exc}")
        
        if "chat not found" in error_msg or "chat_id_invalid" in error_msg:
            logger.error(f"💡 Чат {TARGET_CHAT} не найден!")
            logger.error(f"💡 Убедись, что:")
            logger.error(f"   1. Username чата правильный: {TARGET_CHAT}")
            logger.error(f"   2. Бот добавлен в чат")
            logger.error(f"   3. Бот является администратором")
        elif "not enough rights" in error_msg or "forbidden" in error_msg:
            logger.error(f"💡 У бота нет доступа к {TARGET_CHAT}")
            logger.error(f"💡 Добавь бота в чат и сделай его администратором")
        else:
            logger.exception("Неожиданная ошибка при проверке прав")


def main() -> None:
    """Главная функция запуска бота"""
    load_dotenv()
    
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Set BOT_TOKEN env variable or create .env file with BOT_TOKEN=your_token"
        )

    application = build_application(token)
    
    # Проверяем права бота при запуске
    async def post_init(app: Application) -> None:
        await check_bot_permissions(app)
    
    application.post_init = post_init
    
    # Оптимизированный порядок обработчиков (от более специфичных к общим)
    # 1. Команды (самые специфичные)
    application.add_handler(CommandHandler("start", start))
    
    # 2. Callback queries (кнопки) - должны быть перед MessageHandler
    application.add_handler(CallbackQueryHandler(handle_buttons))
    
    # 3. Новые участники (специфичный статус)
    application.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members)
    )
    
    # 4. Проверка подписки в группах (только группы, не команды)
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & ~filters.COMMAND,
            check_subscription_in_chat
        )
    )
    
    # 5. Фото в личных чатах
    application.add_handler(
        MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_photo)
    )
    
    # 6. Текст в личных чатах (самый общий, последний)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            handle_text
        )
    )

    logger.info("Bot starting...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,  # Игнорируем старые обновления при запуске
    )


if __name__ == "__main__":
    main()
