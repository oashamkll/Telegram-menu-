import asyncio
import time
import json
import os
import sys

# --- Библиотеки для красивого интерфейса ---
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

# --- Библиотеки для работы с Telegram ---
from telethon.sync import TelegramClient
from telethon.tl.types import Channel, User, Chat
from telethon.errors.rpcerrorlist import SlowModeWaitError, FloodWaitError

# --- Глобальные переменные и константы ---
CONSOLE = Console()
CONFIG_FILE = 'config.json'
SESSION_NAME = 'telegram_manager_session'


def setup_credentials():
    """Запрашивает у пользователя API ID/Hash и сохраняет их в config.json."""
    CONSOLE.print(Panel("[bold yellow]API ID и API Hash не найдены. Запускаю первоначальную настройку...[/bold yellow]", border_style="yellow"))
    try:
        api_id = int(Prompt.ask("[bold]Введите ваш API ID[/bold]"))
        api_hash = Prompt.ask("[bold]Введите ваш API Hash[/bold]")
    except ValueError:
        CONSOLE.print(Panel("[bold red]Ошибка: API ID должен быть числом.[/bold red]", border_style="red")); return False
    config_data = {'api_id': api_id, 'api_hash': api_hash}
    try:
        with open(CONFIG_FILE, 'w') as f: json.dump(config_data, f, indent=4)
        CONSOLE.print(Panel("[bold green]Учетные данные успешно сохранены в 'config.json'.[/bold green]", border_style="green")); return True
    except IOError as e:
        CONSOLE.print(Panel(f"[bold red]Не удалось сохранить файл конфигурации: {e}[/bold red]", border_style="red")); return False

def load_credentials():
    """Загружает учетные данные из config.json."""
    if not os.path.exists(CONFIG_FILE): return None, None
    try:
        with open(CONFIG_FILE, 'r') as f: config_data = json.load(f)
        return config_data.get('api_id'), config_data.get('api_hash')
    except (json.JSONDecodeError, IOError) as e:
        CONSOLE.print(Panel(f"[bold red]Ошибка чтения файла 'config.json': {e}[/bold red]", border_style="red")); return None, None

def handle_reauth():
    """Удаляет файлы конфигурации и сессии для повторной авторизации."""
    CONSOLE.print(Panel("[bold yellow]Эта опция удалит сохраненные API ключи и файл сессии для полной повторной авторизации.[/bold yellow]", border_style="yellow"))
    if Prompt.ask("[bold]Вы уверены? (yes/no)[/bold]", choices=["yes", "no"], default="no") == "yes":
        files_to_delete = [CONFIG_FILE, f"{SESSION_NAME}.session"]
        deleted_files = [f for f in files_to_delete if os.path.exists(f) and (os.remove(f) or True)]
        if deleted_files: CONSOLE.print(Panel(f"[bold green]Удалены файлы: {', '.join(deleted_files)}.\nПерезапустите скрипт.[/bold green]", border_style="green"))
        else: CONSOLE.print(Panel("[bold]Файлы для удаления не найдены.[/bold]"))
        return True
    else:
        CONSOLE.print("[green]Действие отменено.[/green]"); time.sleep(1); return False

def print_main_menu():
    """Отображает главное меню."""
    CONSOLE.clear(home=True)
    menu_panel = Panel(
        "[bold green]--- Просмотр (безопасно) ---[/bold green]\n"
        "[cyan]1.[/cyan] Посмотреть список Каналов\n"
        "[cyan]2.[/cyan] Посмотреть список Групп\n"
        "[cyan]3.[/cyan] Посмотреть список Личных чатов\n"
        "[cyan]4.[/cyan] Посмотреть список Ботов\n\n"
        "[bold yellow]!! РАССЫЛКА (РИСК БЛОКИРОВКИ) !![/bold yellow]\n"
        "[yellow]5.[/yellow] Разослать сообщение во ВСЕ личные чаты\n"
        "[yellow]6.[/yellow] Разослать сообщение во ВСЕ группы\n\n"
        "[bold red]!!! УДАЛЕНИЕ (НЕОБРАТИМО) !!![/bold red]\n"
        "[red]7.[/red] Покинуть ВСЕ телеграм-каналы\n"
        "[red]8.[/red] Покинуть ВСЕ телеграм-группы\n"
        "[red]9.[/red] Удалить ВСЕ личные чаты\n"
        "[red]10.[/red] Удалить и заблокировать ВСЕХ ботов\n\n"
        "[bold blue]--- Настройки ---[/bold blue]\n"
        "[cyan]11.[/cyan] Сменить аккаунт / Авторизоваться заново\n\n"
        "[bold]q.[/bold] Выход",
        title="[bold blue_violet]Меню управления Telegram[/bold blue_violet]", border_style="blue_violet", padding=(1, 2))
    CONSOLE.print(menu_panel)

async def list_dialogs(client, dialog_type):
    # Эта функция без изменений
    dialogs_list, title = [], ""
    title_map = {'channels': "Каналов", 'groups': "Групп", 'private': "Личных чатов", 'bots': "Ботов"}
    spinner = Spinner("dots", text="[yellow]Загрузка списка диалогов...")
    with Live(spinner, console=CONSOLE, transient=True, refresh_per_second=20):
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if dialog_type == 'channels' and isinstance(entity, Channel) and not entity.megagroup:
                dialogs_list.append((entity.title, str(entity.id)))
            elif dialog_type == 'groups' and (isinstance(entity, Chat) or (isinstance(entity, Channel) and entity.megagroup)):
                dialogs_list.append((entity.title, str(entity.id)))
            elif dialog_type == 'private' and isinstance(entity, User) and not entity.bot and not entity.is_self:
                dialogs_list.append((f"{entity.first_name} {entity.last_name or ''}".strip(), str(entity.id)))
            elif dialog_type == 'bots' and isinstance(entity, User) and entity.bot:
                dialogs_list.append((entity.first_name, str(entity.id)))
    if dialogs_list:
        table = Table(title=f"[bold magenta]Список ваших Telegram {title_map[dialog_type]}[/bold magenta]", header_style="bold blue")
        table.add_column("№", style="dim", width=5); table.add_column("Название / Имя", min_width=30); table.add_column("ID", justify="right")
        for i, (name, entity_id) in enumerate(dialogs_list, 1): table.add_row(str(i), name, entity_id)
        CONSOLE.print(table)
    else: CONSOLE.print(Panel(f"[bold red]Диалоги типа '{title_map[dialog_type]}' не найдены.[/bold red]", border_style="red"))
    Prompt.ask("\n[bold]Нажмите Enter, чтобы вернуться в меню[/bold]")

async def perform_mass_action(client, action_type, **kwargs):
    """Выполняет массовое действие (удаление, рассылка) после подтверждения."""
    # Общая логика для всех опасных действий
    action_config = {
        'leave_channels': {'filter': lambda e: isinstance(e, Channel) and not e.megagroup, 'action_name': 'покинуть все каналы', 'confirm_phrase': 'да я хочу покинуть все каналы'},
        'leave_groups': {'filter': lambda e: isinstance(e, Chat) or (isinstance(e, Channel) and e.megagroup), 'action_name': 'покинуть все группы', 'confirm_phrase': 'да я хочу покинуть все группы'},
        'delete_private': {'filter': lambda e: isinstance(e, User) and not e.bot and not e.is_self, 'action_name': 'удалить все личные чаты', 'confirm_phrase': 'да я хочу удалить все чаты'},
        'delete_bots': {'filter': lambda e: isinstance(e, User) and e.bot, 'action_name': 'удалить и заблокировать всех ботов', 'confirm_phrase': 'да я хочу удалить всех ботов'},
        'mail_private': {'filter': lambda e: isinstance(e, User) and not e.bot and not e.is_self, 'action_name': 'начать рассылку во все личные чаты', 'confirm_phrase': 'да я хочу начать рассылку в чаты'},
        'mail_groups': {'filter': lambda e: isinstance(e, Chat) or (isinstance(e, Channel) and e.megagroup), 'action_name': 'начать рассылку во все группы', 'confirm_phrase': 'да я хочу начать рассылку в группы'}
    }
    config = action_config[action_type]
    
    # --- Специфическая логика для рассылки ---
    message_to_send = None
    if action_type.startswith('mail_'):
        CONSOLE.print("[cyan]Получаю последнее сообщение из 'Избранного'...")
        messages = await client.get_messages('me', limit=1)
        if not messages:
            CONSOLE.print(Panel("[bold red]В 'Избранном' нет сообщений для рассылки. Действие отменено.[/bold red]", border_style="red")); time.sleep(3); return
        message_to_send = messages[0]
        
        # Показываем, что будет отправлено
        preview_text = f"Тип: [bold]{message_to_send.media.__class__.__name__ if message_to_send.media else 'Текст'}[/bold]"
        if message_to_send.text:
            preview_text += f'\nТекст: "[italic]{message_to_send.text}[/italic]"'
        CONSOLE.print(Panel(preview_text, title="[bold yellow]Сообщение для рассылки[/bold yellow]", border_style="yellow"))
    # ----------------------------------------
    
    CONSOLE.print(Panel(f"[bold red]ВНИМАНИЕ![/bold red] Вы собираетесь [u]{config['action_name']}[/u].\nЭто действие [bold]НЕОБРАТИМО[/bold] и может привести к [bold]БЛОКИРОВКЕ АККАУНТА[/bold].", title="[bold red]ПРЕДУПРЕЖДЕНИЕ[/bold red]", border_style="red"))
    if Prompt.ask("[bold]Вы абсолютно уверены? (yes/no)[/bold]", choices=["yes", "no"], default="no") != "yes":
        CONSOLE.print("[green]Действие отменено.[/green]"); time.sleep(2); return

    CONSOLE.print(f"\nДля окончательного подтверждения, введите точную фразу: [bold yellow]{config['confirm_phrase']}[/bold yellow]")
    if Prompt.ask("[bold]Введите подтверждающую фразу[/bold]").strip().lower() != config['confirm_phrase']:
        CONSOLE.print("[bold red]Фраза не совпадает. Действие отменено.[/bold red]"); time.sleep(3); return
        
    spinner = Spinner("dots", text="[yellow]Обработка диалогов...")
    with Live(spinner, console=CONSOLE, transient=False, refresh_per_second=10) as live:
        dialogs_to_process = [d async for d in client.iter_dialogs() if config['filter'](d.entity)]
        total = len(dialogs_to_process)
        for i, dialog in enumerate(dialogs_to_process, 1):
            live.update(Text(f"[{i}/{total}] Обработка: {dialog.name}..."))
            try:
                if action_type.startswith('mail_'):
                    await client.send_message(dialog.entity, message_to_send)
                    await asyncio.sleep(1.5) # Увеличенная задержка для рассылки
                else:
                    await client.delete_dialog(dialog.entity)
                    if action_type == 'delete_bots':
                        await client.block_user(dialog.entity)
                    await asyncio.sleep(1)
            except (SlowModeWaitError, FloodWaitError) as e:
                live.update(Text(f"[yellow]Превышен лимит запросов. Жду {e.seconds} сек...[/yellow]")); await asyncio.sleep(e.seconds)
            except Exception as e:
                live.update(Text(f"[red]Не удалось обработать '{dialog.name}': {e}[/red]")); await asyncio.sleep(1)
    CONSOLE.print(Panel("[bold green]Операция успешно завершена![/bold green]", border_style="green"))
    Prompt.ask("\n[bold]Нажмите Enter, чтобы вернуться в меню[/bold]")

async def main_async(api_id, api_hash):
    """Основная асинхронная логика программы."""
    try:
        async with TelegramClient(SESSION_NAME, api_id, api_hash) as client:
            while True:
                print_main_menu()
                choice = Prompt.ask("[bold]Выберите опцию[/bold]", choices=[str(i) for i in range(1, 12)] + ["q"], default="q")
                
                if   choice == '1': await list_dialogs(client, 'channels')
                elif choice == '2': await list_dialogs(client, 'groups')
                elif choice == '3': await list_dialogs(client, 'private')
                elif choice == '4': await list_dialogs(client, 'bots')
                elif choice == '5': await perform_mass_action(client, 'mail_private')
                elif choice == '6': await perform_mass_action(client, 'mail_groups')
                elif choice == '7': await perform_mass_action(client, 'leave_channels')
                elif choice == '8': await perform_mass_action(client, 'leave_groups')
                elif choice == '9': await perform_mass_action(client, 'delete_private')
                elif choice == '10': await perform_mass_action(client, 'delete_bots')
                elif choice == '11':
                    if handle_reauth(): break
                elif choice.lower() == 'q':
                    CONSOLE.print("[bold yellow]Выход из программы...[/bold yellow]"); break
    except Exception as e:
        CONSOLE.print(Panel(f"[bold red]Произошла критическая ошибка:\n{e}[/bold red]", border_style="red"))
        CONSOLE.print("[yellow]Попробуйте опцию '11' для повторной авторизации.[/yellow]")

if __name__ == "__main__":
    api_id, api_hash = load_credentials()
    if not api_id or not api_hash:
        if not setup_credentials(): sys.exit(1)
        CONSOLE.print("\n[bold]Перезапустите скрипт, чтобы использовать сохраненные учетные данные.[/bold]"); sys.exit(0)
    
    try:
        asyncio.run(main_async(api_id, api_hash))
    except KeyboardInterrupt:
        CONSOLE.print("\n[bold yellow]Программа прервана пользователем.[/bold yellow]")
