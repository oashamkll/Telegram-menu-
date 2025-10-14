import asyncio
import json
import sys
import re
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text as RichText
from rich import box
from rich.live import Live
import questionary
from questionary import Separator

from telethon.sync import TelegramClient
from telethon.tl.types import Channel, User, Chat
from telethon.errors.rpcerrorlist import (
    SlowModeWaitError, FloodWaitError, SessionPasswordNeededError,
    ApiIdInvalidError, PhoneNumberInvalidError, PeerIdInvalidError
)

CONSOLE = Console()
ACCOUNTS_FILE = Path('accounts.json')
SESSIONS_DIR = Path('sessions')
SESSIONS_DIR.mkdir(exist_ok=True)

CUSTOM_STYLE = questionary.Style([
    ('qmark', 'fg:#4fc3f7 bold'),
    ('question', 'bold fg:#29b6f6'),
    ('selected', 'fg:#ff7043'),
    ('pointer', 'fg:#0288d1 bold'),
    ('answer', 'fg:#4fc3f7 bold'),
])

EMOJI = {
    'успех': '[✅]',
    'ошибка': '[❌]',
    'внимание': '[⚠️]',
    'информация': '[ℹ️]',
    'спам': '[🧨]',
    'рассылка': '[📨]',
    'выход': '[🚪]',
    'удалить': '[🗑️]',
    'пользователь': '[👤]',
    'бот': '[🤖]',
    'группа': '[👥]',
    'канал': '[📢]',
    'авторизация': '[🔑]',
    'стоп': '[🛑]',
    'пуск': '[🚀]',
    'назад': '[🔙]'
}

@dataclass
class Аккаунт:
    api_id: int
    api_hash: str
    телефон: str
    имя_сессии: str

class КонтроллерСпама:
    def __init__(self):
        self.запущен = False
        self.отправлено = 0
        self.цель: Optional[str] = None
        self.сообщение: Optional[str] = None

class МенеджерАккаунтов:
    def __init__(self):
        self.аккаунты: List[Аккаунт] = self._загрузить()

    def _загрузить(self) -> List[Аккаунт]:
        if not ACCOUNTS_FILE.exists():
            return []
        try:
            with ACCOUNTS_FILE.open('r', encoding='utf-8') as f:
                данные = json.load(f)
                return [Аккаунт(**акк) for акк in данные]
        except (json.JSONDecodeError, IOError, TypeError):
            CONSOLE.print(Panel(f"{EMOJI['ошибка']} [bold red]Ошибка: Не удалось прочитать файл 'accounts.json'[/bold red]", border_style="red"))
            return []

    def _сохранить(self):
        try:
            with ACCOUNTS_FILE.open('w', encoding='utf-8') as f:
                json.dump([акк.__dict__ for акк in self.аккаунты], f, indent=4, ensure_ascii=False)
        except IOError as e:
            CONSOLE.print(Panel(f"{EMOJI['ошибка']} [bold red]Не удалось сохранить аккаунты: {e}[/bold red]", border_style="red"))

    async def выбрать(self) -> Optional[Аккаунт]:
        CONSOLE.clear()
        заголовок = f"\n{EMOJI['пользователь']} [bold #29b6f6]Менеджер аккаунтов Telegram[/bold #29b6f6]\n"
        CONSOLE.print(Panel(заголовок, style="bold #0288d1", padding=(1, 2), expand=False))

        if not self.аккаунты:
            CONSOLE.print(f"\n{EMOJI['внимание']} [yellow]Нет сохранённых аккаунтов.[/yellow]")
            if await questionary.confirm("Добавить новый аккаунт?", style=CUSTOM_STYLE).ask_async():
                return await self.добавить()
            return None

        варианты = [
            {"name": f"{EMOJI['пользователь']} {акк.телефон}", "value": акк} for акк in self.аккаунты
        ] + [
            Separator(),
            {"name": f"{EMOJI['пуск']} Добавить новый аккаунт", "value": "добавить"},
            {"name": f"{EMOJI['удалить']} Удалить аккаунт", "value": "удалить"},
            Separator(),
            {"name": f"{EMOJI['выход']} Выход", "value": "выход"}
        ]

        действие = await questionary.select("Выберите действие:", choices=варианты, style=CUSTOM_STYLE).ask_async()
        if действие == "выход" or действие is None:
            return None
        elif действие == "добавить":
            return await self.добавить()
        elif действие == "удалить":
            await self.удалить()
            return await self.выбрать()
        else:
            return действие

    async def добавить(self) -> Optional[Аккаунт]:
        CONSOLE.clear()
        CONSOLE.print(Panel(f"{EMOJI['пуск']} [cyan]Добавление нового аккаунта[/cyan]", border_style="cyan", padding=(1, 2)))

        try:
            api_id = await questionary.text("API ID:", style=CUSTOM_STYLE).ask_async()
            api_hash = await questionary.text("API Hash:", style=CUSTOM_STYLE).ask_async()
            телефон = await questionary.text("Номер телефона (с +):", style=CUSTOM_STYLE).ask_async()

            if not all([api_id, api_hash, телефон]):
                raise ValueError("Все поля обязательны")

            api_id = int(api_id)
            имя_сессии = f"session_{телефон.replace('+', '').replace(' ', '')}"
            новый_аккаунт = Аккаунт(api_id, api_hash, телефон, имя_сессии)
            self.аккаунты.append(новый_аккаунт)
            self._сохранить()
            CONSOLE.print(Panel(f"{EMOJI['успех']} [bold green]Аккаунт {телефон} успешно добавлен![/bold green]", border_style="green"))
            await asyncio.sleep(1.5)
            return новый_аккаунт

        except (ValueError, TypeError):
            CONSOLE.print(Panel(f"{EMOJI['ошибка']} [bold red]Ошибка: Неверный формат данных.[/bold red]", border_style="red"))
            await asyncio.sleep(2)
            return None

    async def удалить(self):
        if not self.аккаунты:
            CONSOLE.print(Panel(f"{EMOJI['внимание']} [yellow]Нет аккаунтов для удаления.[/yellow]", border_style="yellow"))
            await asyncio.sleep(2)
            return

        варианты = [{"name": акк.телефон, "value": акк} for акк in self.аккаунты] + [{"name": f"{EMOJI['назад']} Отмена", "value": None}]
        акк = await questionary.select("Выберите аккаунт для удаления:", choices=варианты, style=CUSTOM_STYLE).ask_async()
        if акк and await questionary.confirm(f"Удалить {акк.телефон} и сессию?", style=CUSTOM_STYLE).ask_async():
            файл_сессии = SESSIONS_DIR / f"{акк.имя_сессии}.session"
            файл_сессии.unlink(missing_ok=True)
            self.аккаунты.remove(акк)
            self._сохранить()
            CONSOLE.print(Panel(f"{EMOJI['успех']} [green]Аккаунт удалён.[/green]", border_style="green"))
            await asyncio.sleep(1.5)

def создать_3d_баннер():
    ширина = CONSOLE.width
    текст = "TELEGA"
    цвета = ["#01579b", "#0288d1", "#29b6f6", "#4fc3f7", "#29b6f6", "#0288d1", "#01579b"]
    
    строки = []
    for i, символ in enumerate(текст):
        цвет = цвета[i % len(цвета)]
        строки.append(f"[{цвет}]{символ}[/{цвет}]")
    
    строка = "".join(строки)
    отступ = max(0, (ширина - len(текст) * 2) // 2)
    отступ_пробелы = " " * отступ
    
    баннер = f"""
{отступ_пробелы}[#01579b]T[/#01579b][#0288d1]E[/#0288d1][#29b6f6]L[/#29b6f6][#4fc3f7]E[/#4fc3f7][#29b6f6]G[/#29b6f6][#0288d1]A[/#0288d1]
{отступ_пробелы} [#0288d1]T[/#0288d1][#29b6f6]E[/#29b6f6][#4fc3f7]L[/#4fc3f7][#29b6f6]E[/#29b6f6][#0288d1]G[/#0288d1][#01579b]A[/#01579b]
{отступ_пробелы}  [#29b6f6]T[/#29b6f6][#4fc3f7]E[/#4fc3f7][#29b6f6]L[/#29b6f6][#0288d1]E[/#0288d1][#01579b]G[/#01579b][#0288d1]A[/#0288d1]
{отступ_пробелы}   [#4fc3f7]T[/#4fc3f7][#29b6f6]E[/#29b6f6][#0288d1]L[/#0288d1][#01579b]E[/#01579b][#0288d1]G[/#0288d1][#29b6f6]A[/#29b6f6]
"""
    return баннер.strip()

class ПриложениеТелеграм:
    def __init__(self, аккаунт: Аккаунт):
        self.аккаунт = аккаунт
        путь_сессии = SESSIONS_DIR / аккаунт.имя_сессии
        self.клиент = TelegramClient(str(путь_сессии), аккаунт.api_id, аккаунт.api_hash)
        self.я = None
        self.текущее_действие = "Ожидание"
        self.контроллер_спама = КонтроллерСпама()

    def _вывести_заголовок(self):
        CONSOLE.clear()
        строки = []

        if self.я:
            имя = f"{self.я.first_name or ''} {self.я.last_name or ''}".strip() or self.я.username or "Пользователь"
            строки.append(f"{EMOJI['пользователь']} [bold #4fc3f7]{имя}[/bold #4fc3f7]")
            строки.append(f"📱 Телефон: [cyan]{self.аккаунт.телефон}[/cyan]")
        else:
            строки.append(f"📱 Аккаунт: [cyan]{self.аккаунт.телефон}[/cyan]")

        строки.append(f"⚙️ Действие: [bold #29b6f6]{self.текущее_действие}[/bold #29b6f6]")

        if self.контроллер_спама.запущен:
            строки.append(f"{EMOJI['спам']} [bold red]СПАМ АКТИВЕН[/bold red] | Отправлено: {self.контроллер_спама.отправлено}")

        CONSOLE.print(Panel("\n".join(строки), style="bold #0288d1", padding=(1, 2), expand=False))

    async def подключиться(self) -> bool:
        self.текущее_действие = "Подключение к Telegram..."
        self._вывести_заголовок()

        try:
            await self.клиент.connect()
            if not await self.клиент.is_user_authorized():
                CONSOLE.print(f"\n{EMOJI['авторизация']} Требуется авторизация для {self.аккаунт.телефон}")
                await self.клиент.send_code_request(self.аккаунт.телефон)
                код = await questionary.text("Код из Telegram:", style=CUSTOM_STYLE).ask_async()
                if not код:
                    return False
                try:
                    await self.клиент.sign_in(self.аккаунт.телефон, код)
                except SessionPasswordNeededError:
                    пароль = await questionary.password("Пароль двухфакторной авторизации:", style=CUSTOM_STYLE).ask_async()
                    if пароль:
                        await self.клиент.sign_in(password=пароль)
                    else:
                        return False

            self.я = await self.клиент.get_me()
            return True

        except (ApiIdInvalidError, PhoneNumberInvalidError) as e:
            CONSOLE.print(Panel(f"{EMOJI['ошибка']} [bold red]Ошибка конфигурации: {e}[/bold red]", border_style="red"))
        except Exception as e:
            CONSOLE.print(Panel(f"{EMOJI['ошибка']} [bold red]Ошибка подключения: {e}[/bold red]", border_style="red"))
        return False

    async def запустить(self):
        while True:
            self.текущее_действие = "Главное меню"
            self._вывести_заголовок()

            меню = [
                Separator(f" {EMOJI['информация']} Просмотр "),
                f"{EMOJI['канал']} Список каналов",
                f"{EMOJI['группа']} Список групп",
                f"{EMOJI['пользователь']} Список личных чатов",
                f"{EMOJI['бот']} Список ботов",

                Separator(f" {EMOJI['рассылка']} Рассылка "),
                f"{EMOJI['рассылка']} Рассылка в личные чаты",
                f"{EMOJI['рассылка']} Рассылка в группы",

                Separator(f" {EMOJI['спам']} Спам "),
                f"{EMOJI['пуск']} Начать спам",
                f"{EMOJI['стоп']} Остановить спам",

                Separator(f" {EMOJI['удалить']} Удаление "),
                f"{EMOJI['выход']} Покинуть все каналы",
                f"{EMOJI['выход']} Покинуть все группы",
                f"{EMOJI['удалить']} Удалить личные чаты",
                f"{EMOJI['удалить']} Удалить ботов",

                Separator(f" {EMOJI['пользователь']} Аккаунт "),
                f"{EMOJI['назад']} Сменить аккаунт",
                f"{EMOJI['выход']} Выход"
            ]

            выбор = await questionary.select("Выберите действие:", choices=меню, style=CUSTOM_STYLE).ask_async()
            if выбор is None or "Выход" in выбор:
                sys.exit(0)
            elif "Сменить аккаунт" in выбор:
                return

            await self._обработать_выбор(выбор)

    async def _обработать_выбор(self, выбор: str):
        сопоставление = {
            "Список каналов": ("показать_диалоги", "каналы"),
            "Список групп": ("показать_диалоги", "группы"),
            "Список личных чатов": ("показать_диалоги", "личные"),
            "Список ботов": ("показать_диалоги", "боты"),
            "Рассылка в личные чаты": ("выполнить_массовое_действие", "рассылка_личные"),
            "Рассылка в группы": ("выполнить_массовое_действие", "рассылка_группы"),
            "Начать спам": ("начать_спам", None),
            "Остановить спам": ("остановить_спам", None),
            "Покинуть все каналы": ("выполнить_массовое_действие", "покинуть_каналы"),
            "Покинуть все группы": ("выполнить_массовое_действие", "покинуть_группы"),
            "Удалить личные чаты": ("выполнить_массовое_действие", "удалить_личные"),
            "Удалить ботов": ("выполнить_массовое_действие", "удалить_ботов"),
        }

        чистый_выбор = re.sub(r'^[^\s]+\s*', '', выбор)
        if чистый_выбор in сопоставление:
            имя_метода, арг = сопоставление[чистый_выбор]
            метод = getattr(self, имя_метода)
            self.текущее_действие = чистый_выбор
            self._вывести_заголовок()
            if арг:
                await метод(арг)
            else:
                await метод()
            if not self.контроллер_спама.запущен:
                await questionary.press_any_key_to_continue("Нажмите любую клавишу для возврата...").ask_async()

    async def показать_диалоги(self, тип: str):
        названия = {
            'каналы': f"{EMOJI['канал']} Каналы",
            'группы': f"{EMOJI['группа']} Группы",
            'личные': f"{EMOJI['пользователь']} Личные чаты",
            'боты': f"{EMOJI['бот']} Боты"
        }

        диалоги = []
        async for диалог in self.клиент.iter_dialogs():
            сущность = диалог.entity
            if тип == 'каналы' and isinstance(сущность, Channel) and not сущность.megagroup:
                диалоги.append((сущность.title or "Без названия", str(сущность.id)))
            elif тип == 'группы' and (isinstance(сущность, Chat) or (isinstance(сущность, Channel) and сущность.megagroup)):
                диалоги.append((сущность.title or "Без названия", str(сущность.id)))
            elif тип == 'личные' and isinstance(сущность, User) and not сущность.bot and not сущность.is_self:
                имя = f"{сущность.first_name or ''} {сущность.last_name or ''}".strip() or "Без имени"
                диалоги.append((имя, str(сущность.id)))
            elif тип == 'боты' and isinstance(сущность, User) and сущность.bot:
                диалоги.append((сущность.first_name or "Бот", str(сущность.id)))

        if диалоги:
            таблица = Table(title=названия[тип], box=box.ROUNDED, header_style="bold #29b6f6")
            таблица.add_column("#", style="dim", width=4)
            таблица.add_column("Название", min_width=20, max_width=CONSOLE.width - 30)
            таблица.add_column("ID", justify="right")
            for i, (название, id_) in enumerate(диалоги, 1):
                таблица.add_row(str(i), название, id_)
            CONSOLE.print(таблица)
        else:
            CONSOLE.print(Panel(f"{EMOJI['внимание']} Нет данных для отображения.", border_style="yellow"))

    async def начать_спам(self):
        if self.контроллер_спама.запущен:
            CONSOLE.print(Panel(f"{EMOJI['внимание']} Спам уже запущен!", border_style="yellow"))
            await asyncio.sleep(1.5)
            return

        выбор_чата = await questionary.select("Как выбрать чат?", choices=[
            "Ввести ID вручную",
            "Из каналов", "Из групп", "Из ботов", "Из личных чатов", "Отмена"
        ], style=CUSTOM_STYLE).ask_async()

        if выбор_чата == "Отмена":
            return

        id_чата = await self._получить_id_чата(выбор_чата)
        if not id_чата:
            return

        сообщение = await self._получить_сообщение_для_спама()
        if not сообщение:
            return

        задержка_str = await questionary.text(
            "Задержка между сообщениями (сек, поддержка миллисекунд: 0.1, 0.05 и т.д.):",
            default="1.0",
            style=CUSTOM_STYLE
        ).ask_async()

        try:
            задержка = float(задержка_str)
            if задержка <= 0:
                raise ValueError("Задержка должна быть > 0")
        except ValueError:
            CONSOLE.print(Panel(f"{EMOJI['ошибка']} Неверный формат задержки! Используйте положительное число (например: 0.1).", border_style="red"))
            return

        if задержка < 0.5:
            CONSOLE.print(Panel(
                f"{EMOJI['внимание']} [bold yellow]Внимание![/bold yellow] Задержка < 0.5 секунд сильно повышает риск [bold red]ограничений[/bold red] или блокировки аккаунта!",
                border_style="yellow"
            ))
            if not await questionary.confirm("Продолжить несмотря на риск?", default=False, style=CUSTOM_STYLE).ask_async():
                return

        if not await questionary.confirm(f"Начать спам в чат {id_чата}?", style=CUSTOM_STYLE).ask_async():
            return

        self.контроллер_спама.запущен = True
        self.контроллер_спама.цель = id_чата
        self.контроллер_спама.сообщение = сообщение
        self.контроллер_спама.отправлено = 0

        CONSOLE.print(Panel(f"{EMOJI['пуск']} [green]Спам запущен! Используйте 'Остановить спам' в меню.[/green]", border_style="green"))
        asyncio.create_task(self._цикл_спама(задержка))

    async def _получить_id_чата(self, метод: str) -> Optional[str]:
        if метод == "Ввести ID вручную":
            raw = await questionary.text("ID чата:", style=CUSTOM_STYLE).ask_async()
            return raw.strip() if raw else None

        карта_типов = {"Из каналов": "каналы", "Из групп": "группы", "Из ботов": "боты", "Из личных чатов": "личные"}
        тип = карта_типов[метод]
        диалоги = []

        async for диалог in self.клиент.iter_dialogs():
            сущность = диалог.entity
            условия = {
                "каналы": isinstance(сущность, Channel) and not сущность.megagroup,
                "группы": isinstance(сущность, Chat) or (isinstance(сущность, Channel) and сущность.megagroup),
                "боты": isinstance(сущность, User) and сущность.bot,
                "личные": isinstance(сущность, User) and not сущность.bot and not сущность.is_self
            }
            if условия[тип]:
                название = getattr(сущность, 'title', None) or getattr(сущность, 'first_name', '???')
                диалоги.append((название, str(сущность.id)))

        if not диалоги:
            CONSOLE.print(Panel(f"{EMOJI['внимание']} Нет подходящих чатов.", border_style="yellow"))
            return None

        варианты = [f"{название} (ID: {id_})" for название, id_ in диалоги] + ["Отмена"]
        выбранный = await questionary.select("Выберите чат:", choices=варианты, style=CUSTOM_STYLE).ask_async()
        if выбранный == "Отмена":
            return None
        совпадение = re.search(r'ID:\s*(\d+)', выбранный)
        return совпадение.group(1) if совпадение else None

    async def _получить_сообщение_для_спама(self) -> Optional[str]:
        источник = await questionary.select("Источник сообщения:", choices=[
            "Ввести текст", "Из Избранного", "Отмена"
        ], style=CUSTOM_STYLE).ask_async()
        if источник == "Отмена":
            return None
        elif источник == "Ввести текст":
            return await questionary.text("Текст сообщения:", style=CUSTOM_STYLE).ask_async()
        else:
            сообщения = await self.клиент.get_messages('me', limit=1)
            if сообщения and сообщения[0].text:
                return сообщения[0].text
            else:
                CONSOLE.print(Panel(f"{EMOJI['внимание']} В Избранном нет текстовых сообщений.", border_style="yellow"))
                return None

    async def _цикл_спама(self, задержка: float):
        время_старта = time.time()
        текст = RichText(f"{EMOJI['спам']} [bold red]Спам активен...[/bold red]\n", style="bold")
        текст.append(f"Цель: {self.контроллер_спама.цель}\n")
        текст.append(f"Задержка: {задержка:.3f} сек\n")
        текст.append(f"Отправлено: 0 сообщений\n")
        текст.append(f"Прошло: 0 сек")

        with Live(текст, refresh_per_second=4, console=CONSOLE) as live:
            try:
                while self.контроллер_спама.запущен:
                    try:
                        цель = int(self.контроллер_спама.цель)
                        await self.клиент.send_message(цель, self.контроллер_спама.сообщение)
                        self.контроллер_спама.отправлено += 1
                    except (ValueError, PeerIdInvalidError):
                        CONSOLE.print(f"\n{EMOJI['ошибка']} Неверный ID чата: {self.контроллер_спама.цель}")
                        break
                    except FloodWaitError as e:
                        CONSOLE.print(f"\n{EMOJI['внимание']} Ограничение: ждём {e.seconds} сек...")
                        await asyncio.sleep(e.seconds)
                    except SlowModeWaitError as e:
                        CONSOLE.print(f"\n{EMOJI['внимание']} Медленный режим: ждём {e.seconds} сек...")
                        await asyncio.sleep(e.seconds)
                    except Exception as e:
                        CONSOLE.print(f"\n{EMOJI['ошибка']} Ошибка: {e}")
                        break

                    прошло = time.time() - время_старта
                    текст = RichText(f"{EMOJI['спам']} [bold red]Спам активен...[/bold red]\n", style="bold")
                    текст.append(f"Цель: {self.контроллер_спама.цель}\n")
                    текст.append(f"Задержка: {задержка:.3f} сек\n")
                    текст.append(f"Отправлено: {self.контроллер_спама.отправлено} сообщений\n")
                    текст.append(f"Прошло: {прошло:.1f} сек")
                    live.update(текст)

                    await asyncio.sleep(задержка)
            finally:
                self.контроллер_спама.запущен = False
                CONSOLE.print(f"\n{EMOJI['стоп']} [bold green]Спам остановлен. Всего отправлено: {self.контроллер_спама.отправлено}[/bold green]")

    async def остановить_спам(self):
        if self.контроллер_спама.запущен:
            self.контроллер_спама.запущен = False
            CONSOLE.print(Panel(f"{EMOJI['стоп']} [green]Запрос на остановку отправлен. Ожидание завершения текущей итерации...[/green]", border_style="green"))
        else:
            CONSOLE.print(Panel(f"{EMOJI['внимание']} Спам не запущен.", border_style="yellow"))
        await asyncio.sleep(1.5)

    async def выполнить_массовое_действие(self, тип_действия: str):
        # Получаем список целей
        цели = []
        if тип_действия in ("рассылка_личные", "удалить_личные"):
            async for диалог in self.клиент.iter_dialogs():
                if isinstance(диалог.entity, User) and not диалог.entity.bot and not диалог.entity.is_self:
                    цели.append(диалог.id)
        elif тип_действия in ("рассылка_группы", "покинуть_группы"):
            async for диалог in self.клиент.iter_dialogs():
                сущность = диалог.entity
                if isinstance(сущность, Chat) or (isinstance(сущность, Channel) and сущность.megagroup):
                    цели.append(диалог.id)
        elif тип_действия == "покинуть_каналы":
            async for диалог in self.клиент.iter_dialogs():
                if isinstance(диалог.entity, Channel) and not диалог.entity.megagroup:
                    цели.append(диалог.id)
        elif тип_действия == "удалить_ботов":
            async for диалог in self.клиент.iter_dialogs():
                if isinstance(диалог.entity, User) and диалог.entity.bot:
                    цели.append(диалог.id)

        if not цели:
            CONSOLE.print(Panel(f"{EMOJI['внимание']} Нет подходящих чатов для действия.", border_style="yellow"))
            await asyncio.sleep(2)
            return

        if тип_действия.startswith("рассылка"):
            сообщение = await self._получить_сообщение_для_спама()
            if not сообщение:
                return
            if not await questionary.confirm(f"Отправить сообщение {len(целям)} чатам?", style=CUSTOM_STYLE).ask_async():
                return
            await self._рассылка(цели, сообщение)
        elif тип_действия.startswith("покинуть"):
            if not await questionary.confirm(f"Покинуть {len(цели)} чатов?", style=CUSTOM_STYLE).ask_async():
                return
            await self._покинуть_чаты(цели)
        elif тип_действия.startswith("удалить"):
            if not await questionary.confirm(f"Удалить {len(цели)} чатов?", style=CUSTOM_STYLE).ask_async():
                return
            await self._удалить_чаты(цели)

    async def _рассылка(self, цели: List[int], сообщение: str):
        CONSOLE.print(Panel(f"{EMOJI['рассылка']} [cyan]Начинаю рассылку...[/cyan]", border_style="cyan"))
        успешных = 0
        for idx, цель in enumerate(цели, 1):
            try:
                await self.клиент.send_message(цель, сообщение)
                успешных += 1
                CONSOLE.print(f"[{idx}/{len(цели)}] Отправлено в {цель}")
            except FloodWaitError as e:
                CONSOLE.print(f"{EMOJI['внимание']} FloodWait: ждём {e.seconds} сек...")
                await asyncio.sleep(e.seconds)
                # Повторить?
            except Exception as e:
                CONSOLE.print(f"{EMOJI['ошибка']} Ошибка при отправке в {цель}: {e}")
            await asyncio.sleep(1)  # Минимальная задержка
        CONSOLE.print(Panel(f"{EMOJI['успех']} Рассылка завершена. Успешно: {успешных}/{len(цели)}", border_style="green"))
        await asyncio.sleep(2)

    async def _покинуть_чаты(self, цели: List[int]):
        CONSOLE.print(Panel(f"{EMOJI['выход']} [yellow]Покидаем чаты...[/yellow]", border_style="yellow"))
        успешных = 0
        for idx, цель in enumerate(цели, 1):
            try:
                await self.клиент.delete_dialog(цель)
                успешных += 1
                CONSOLE.print(f"[{idx}/{len(цели)}] Покинут {цель}")
            except Exception as e:
                CONSOLE.print(f"{EMOJI['ошибка']} Ошибка при выходе из {цель}: {e}")
            await asyncio.sleep(1)
        CONSOLE.print(Panel(f"{EMOJI['успех']} Выход завершён. Успешно: {успешных}/{len(цели)}", border_style="green"))
        await asyncio.sleep(2)

    async def _удалить_чаты(self, цели: List[int]):
        CONSOLE.print(Panel(f"{EMOJI['удалить']} [red]Удаляем чаты...[/red]", border_style="red"))
        успешных = 0
        for idx, цель in enumerate(цели, 1):
            try:
                await self.клиент.delete_dialog(цель)
                успешных += 1
                CONSOLE.print(f"[{idx}/{len(цели)}] Удалён {цель}")
            except Exception as e:
                CONSOLE.print(f"{EMOJI['ошибка']} Ошибка при удалении {цель}: {e}")
            await asyncio.sleep(1)
        CONSOLE.print(Panel(f"{EMOJI['успех']} Удаление завершено. Успешно: {успешных}/{len(цели)}", border_style="green"))
        await asyncio.sleep(2)

async def основная_функция():
    баннер = создать_3d_баннер()
    описание = f"[bold #29b6f6]           [🧨] Инструмент для массовых рассылок и спама в Telegram [🧨][/bold #29b6f6]"
    
    ширина = CONSOLE.width
    отступ_описания = max(0, (ширина - len("           [🧨] Инструмент для массовых рассылок и спама в Telegram [🧨]")) // 2)
    описание = " " * отступ_описания + описание.strip()
    
    полный_баннер = f"{баннер}\n{описание}"
    CONSOLE.print(Panel(полный_баннер, style="bold #0288d1", padding=(1, 2)))

    менеджер = МенеджерАккаунтов()
    while True:
        аккаунт = await менеджер.выбрать()
        if not аккаунт:
            sys.exit(0)

        приложение = ПриложениеТелеграм(аккаунт)
        if await приложение.подключиться():
            await приложение.запустить()
        else:
            await asyncio.sleep(2)

if __name__ == "__main__":
    try:
        asyncio.run(основная_функция())
    except KeyboardInterrupt:
        CONSOLE.print(f"\n{EMOJI['выход']} [bold yellow]Выход по запросу пользователя.[/bold yellow]")
        sys.exit(0)
