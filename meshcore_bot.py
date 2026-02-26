#!/usr/bin/env python3
# 1) pip install meshcore
# 2) pip install meshcore-cli
# 3) связать ноду с ПК по bluetooth
# 4) узнать ble-адрес устройства - выполнить в терминале 
# meshcore-cli -S
# 5) переписать адрес нужного устройства в конфиг и запуститься (start.bat или командой "python ./meshcore_bot.py"). Будет создан первоначальный конфиг - заполнить его и перезапустить скрипт
# 5.1) возможна проблема, когда при перезапуске скрипта не удается возобновить соединение с нодой - в таком случае необходимо физически переподключить bluetooth-адаптер на ПК, либо попробовать воспользоваться скриптом ./utils/restart-bt-win.py, заменив в нём имя bluetooth-адаптера на действительное
# 5.2) известна проблема, когда нода не выводит в ответном сообщении SNR - такое происходит в случае, если нода была перезапущена и первое подключение к ней происходило с ПК - из-за этого нода устанавливает пониженную версию протокола до следующей своей перезагрузки. В этом случае необходимо перезагрузить ноду, подключиться к ней с телефона, отключиться, затем подключаться с ПК и работать.
"""
"""
import asyncio
import os
import importlib.util
import sys
import json
import urllib.request
import urllib.error
import time
import re
import logging
import requests
import urllib3
import traceback
import copy
import hashlib
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from copy import deepcopy
from functools import partial
from meshcore import MeshCore
from meshcore.events import EventType
from typing import Any, Dict, Optional, Iterable, List, Union
from datetime import datetime

# Путь к конфигу рядом со скриптом
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "meshcore_config.json")

# Значения по умолчанию (создаются при первом запуске, если конфига нет)
# Не редактируйте этот конфиг здесь! Запустите скрипт, и он создаст json-файл рядом со скриптом, редактируйте его!
DEFAULT_CONFIG = {
    "HTTP_TIMEOUT_SECONDS": 10, # общая опция, таймаут для http-запросов
    "BLE_ADDRESS": "SO:ME:AD:DR:ES:S!", # адрес вашего устройства
    "HTTP_ADDRESS": "0.0.0.0", # TCP-адрес вашего устройства
    "HTTP_PORT": "5000", # TCP-порт вашего устройства
    "LOG_PACKETS_TO_FILE": False, # логировать mesh-сообщения в файл
    "LOG_PACKETS_TO_CLI": False, # отображать mesh-сообщения в cli
    "LOG_PM_PACKETS_TO_FILE": False, # логировать личные mesh-сообщения в файл
    "SCAN_CHANNELS_LIMIT": 10, # сколько каналов сканировать через ноду при запуске
    # массив воркеров. Каждая секция { ... }, { ... } отвечает за свой Mesh-канал, имя которого совпадает с указанным в секции в параметре TARGET_CHANNEL_NAME - например, Public
    "WORK_ON": [
        {
            "TARGET_CHANNEL_NAME": "MyChannel", # имя mesh-канала, в который и из которого пересылаем сообщения
            "TG_TARGET_CHANNEL_ID": "", # id группы, для которой предназначаются сообщения из mesh, например -100555555555 или @username. Нужно для tg
            "WORK_ON_BROADCAST_MESH_CHANNEL": False, # если индекс mesh-канала будет равен 0, это сработает как дополнительная проверка, не дающая пересылать сообщения из внешней системы в него
            "HTTP_TOKEN": "", # токен для HTTP-запросов, передается внутри POST в json {"token": "..."}
            "HTTP_PREPOLL_URL": [ # эти коллбэки выполняются перед запуском скрипта. Выполняется POST-запрос с json {"token": "..."}
                # "https://domain.ru/any/path/prepollCallbackOne.php", 
                # "https://domain.ru/any/path/prepollCallbackTwo.php"
            ],
            "HTTP_POLL_URL": "https://domain.ru/any/path/getMsgs.php", # POST с токеном внутри. Отсюда забираем сообщения от внешнего источника, можно оставить пустым. Ожидается ответ вида {"messages":[{"name":"Alice","date":"18.01 19:44","msg":"Foo","chat_id": "-10055555555"},{"name":"Bob","date":"18.01 19:44","msg":"Bar","chat_id": "-10055555555"}]}
            "HTTP_SEND_URL": "https://domain.ru/any/path/sendMsgs.php", # на этот url отправляются полученные из mesh сообщения, можно оставить пустым. Отправляется POST с телом {"token": "...", "msg": "Foobar2", "channel_id": -100123456789}, массив сообщений не поддерживается - отправляем по одному
            "HTTP_POLL_PERIOD_SECONDS": 30, # период, с которым опрашивается HTTP_POLL_URL
            "HTTP_IGNORE_SSL_ERRORS": False,
            "IGNORED_POLL_NAMES": [ # не пересылать сообщения от пользователей с такими именами извне в mesh
                # "SomeOtherUser"
            ],
            "POLLED_MESSAGE_MAXLENGTH": 130, # количество байт в кодировке UTF-8 (не символов!) в сообщениях для Mesh. Эмодзи - 4 байта, кириллица - 2, латиница и знаки препинания - 1. Протестировано до 142, дальше 100% что-то бьётся
            "TRY_TRIM_NODENAME": True, # вырезать имя ноды из пересылаемого во внешнюю систему сообщения
            "TG_REMOVE_TGNAMES_VOWEL": True, # при пересылке сообщения извне в mesh удалять из ника отправителя гласные, для экономии полезного пространства в сообщении
            "TG_SHORT_TGNAMES": True, # сокращать внешние ники до 4 символов
            "TG_SHORT_DATE": True, # сокращать дату внешнего сообщения до времени
            "TG_SKIP_DATE": True, # полностью удалять дату
            "TG_TRANSLITERATE_TO_MESH": True, # включить транслитерацию сообщений извне в mesh
            "TG_TRANSLITERATE_ON_OVERLIMIT": True, # но транслитеровать только если мы вышли из лимита
            "REPLY_TO_MESH_MSG": False, # отправлять ответное сообщение при получении сообщения через mesh
            "REPLY_TO_MESH_MSG_TXT": "", # текст ответного сообщения. Если включено и пусто, будет отправлено количество хопов в виде эмодзи и SNR
            "REPLY_TO_MESH_MSG_REGEX_ENABLED": False, # отвечать только если сообщение подпадает под regexp
            "REPLY_TO_MESH_MSG_REGEX_PATTERN": "^(ping|пинг|test|тест)(\\s+\\d+)?$", # шаблон regexp
            "REPLY_TO_MESH_MSG_REGEX_FLAGS": "IGNORECASE", # флаги для regexp
            "REPLY_TO_MESH_MSG_DELAY_SECONDS": 3.0, # отсрочка ответа, для предотвращения флуда
            # внешняя подключаемая логика. Включение коллбэков зависит от MESH_MESSAGES_CALLBACK_ENABLED
            "MESH_MESSAGES_CALLBACK_ENABLED": False,
            "MESH_MESSAGES_CALLBACK_FILE": "callbacks.py", # путь к файлу с коллбэками. Должен лежать либо рядом со скриптом, либо во вложенной папке
            "MESH_MESSAGES_CALLBACK_LIST": ["example_callback"], # массив имен коллбэков, которые будут подписаны на получение сообщений. Логика ответа не зависит от regexp выше, и должна реализовываться самостоятельно! Проверяется только соответствие канала полученного сообщения целевому
        },

    ],
    "WORK_ON_PRIVATE_MSGS": False, # работать на личных сообщениях
    "PRIVATE_MSGS_CFG": {
        # внешняя подключаемая логика.
        "MESH_MESSAGES_CALLBACK_ENABLED": False,
        "MESH_MESSAGES_CALLBACK_FILE": "callbacks_pm.py",
        "MESH_MESSAGES_CALLBACK_LIST": ["example_pm_callback"], # фильтрация "кому отвечать" должна реализовываться в самом коллбэке
    }
}

def load_or_create_config(path: str) -> dict:
    """
    Загружает конфиг или создаёт файл с примерами и завершает выполнение,
    чтобы пользователь мог заполнить корректные значения.
    """
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        print(f"[INFO] Создан пример конфигурации: {path}")
        print("       Отредактируйте его и запустите скрипт снова.")
        sys.exit(0)

    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Подставим недостающие ключи дефолтами (без перезаписи)
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg

# загрузка конфига
_config = load_or_create_config(CONFIG_PATH)

# Присваиваем значения (с запасными значениями из DEFAULT_CONFIG)
HTTP_TIMEOUT_SECONDS = int(_config.get("HTTP_TIMEOUT_SECONDS", DEFAULT_CONFIG["HTTP_TIMEOUT_SECONDS"]))
BLE_ADDRESS = _config.get("BLE_ADDRESS", DEFAULT_CONFIG["BLE_ADDRESS"])
HTTP_ADDRESS = _config.get("HTTP_ADDRESS", DEFAULT_CONFIG["HTTP_ADDRESS"])
HTTP_PORT = _config.get("HTTP_PORT", DEFAULT_CONFIG["HTTP_PORT"])
LOG_PACKETS_TO_FILE = bool(_config.get("LOG_PACKETS_TO_FILE", DEFAULT_CONFIG["LOG_PACKETS_TO_FILE"]))
LOG_PACKETS_TO_CLI = bool(_config.get("LOG_PACKETS_TO_CLI", DEFAULT_CONFIG["LOG_PACKETS_TO_CLI"]))
LOG_PM_PACKETS_TO_FILE = bool(_config.get("LOG_PM_PACKETS_TO_FILE", DEFAULT_CONFIG["LOG_PM_PACKETS_TO_FILE"]))
SCAN_CHANNELS_LIMIT = int(_config.get("SCAN_CHANNELS_LIMIT", DEFAULT_CONFIG["SCAN_CHANNELS_LIMIT"]))
WORK_ON = _config.get("WORK_ON", DEFAULT_CONFIG["WORK_ON"]) or None
WORK_ON_PRIVATE_MSGS = bool(_config.get("WORK_ON_PRIVATE_MSGS", DEFAULT_CONFIG["WORK_ON_PRIVATE_MSGS"]))
PRIVATE_MSGS_CFG = _config.get("PRIVATE_MSGS_CFG", DEFAULT_CONFIG["PRIVATE_MSGS_CFG"]) or None

logger = logging.getLogger("meshcore_client")
meshcore = None

# сюда сохраним активные воркеры
WORKERS: list["MeshcoreBot"] = []

# сюда - последний пакет воркера, т.к. в self хранить не удастся, он не апдейтится
WORKERS_LAST_RX_PACKETS = {}

# основной рабочий класс
class MeshcoreBot:
    def __init__(self, meshcore, worker_index, config) -> None:
        self.worker_index = worker_index
        self.config = copy.deepcopy(config)

        self.meshcore = meshcore

        # нужно разобрать настройки

        self.selfcheck_is_correct = False
        self.http_token = self.config.get("HTTP_TOKEN", "")
        self.http_prepoll_url = self.config.get("HTTP_PREPOLL_URL", [])
        self.http_poll_period_seconds = int(self.config.get("HTTP_POLL_PERIOD_SECONDS", 30))
        self.target_channel_name = self.config.get("TARGET_CHANNEL_NAME", "DummyRandomChannelNameDontChangeItHere")
        self.target_channel_id = None
        self.work_on_broadcast_mesh_channel = bool(self.config.get("WORK_ON_BROADCAST_MESH_CHANNEL", False))
        self.http_send_url = self.config.get("HTTP_SEND_URL", "")
        self.http_poll_url = self.config.get("HTTP_POLL_URL", "")
        self.http_ignore_ssl_errors = self.config.get("HTTP_IGNORE_SSL_ERRORS", "")
        self.ignored_poll_names = set(
            str(x) for x in self.config.get(
                "IGNORED_POLL_NAMES", []
            )
        )
        self.polled_message_maxlength = int(self.config.get("POLLED_MESSAGE_MAXLENGTH", 130))
        self.tg_target_channel_id = str(self.config.get("TG_TARGET_CHANNEL_ID", ""))
        self.try_trim_nodename = bool(self.config.get("TRY_TRIM_NODENAME", True))
        self.tg_remove_tgnames_vowel = bool(self.config.get("TG_REMOVE_TGNAMES_VOWEL", True))
        self.tg_short_tgnames = bool(self.config.get("TG_SHORT_TGNAMES", True))
        self.tg_short_date = bool(self.config.get("TG_SHORT_DATE", True))
        self.tg_skip_date = bool(self.config.get("TG_SKIP_DATE", True))
        self.tg_transliterate_to_mesh = bool(self.config.get("TG_TRANSLITERATE_TO_MESH", True))
        self.tg_transliterate_on_overlimit = bool(self.config.get("TG_TRANSLITERATE_ON_OVERLIMIT", True))
        self.reply_to_mesh_msg = bool(self.config.get("REPLY_TO_MESH_MSG", False))
        self.reply_to_mesh_msg_txt = str(self.config.get("REPLY_TO_MESH_MSG_TXT", "+"))
        self.reply_to_mesh_msg_regex_enabled = bool(self.config.get("REPLY_TO_MESH_MSG_REGEX_ENABLED", False))
        self.reply_to_mesh_msg_regex_pattern = self.config.get("REPLY_TO_MESH_MSG_REGEX_PATTERN", None)
        self.reply_to_mesh_msg_regex_flags = self.config.get("REPLY_TO_MESH_MSG_REGEX_FLAGS", 0)
        self.reply_to_mesh_msg_delay_seconds = float(self.config.get("REPLY_TO_MESH_MSG_DELAY_SECONDS", 2.0))
        # коллбэки
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.mesh_messages_callback_enabled = bool(self.config.get("MESH_MESSAGES_CALLBACK_ENABLED", False))
        self.mesh_messages_callback_file = str(self.config.get("MESH_MESSAGES_CALLBACK_FILE", ""))
            # строим целый путь до скрипта
        if self.mesh_messages_callback_file:
            self.mesh_messages_callback_file = os.path.join(self.script_dir, self.mesh_messages_callback_file)

        self.mesh_messages_callback_list = set(
            str(x) for x in self.config.get(
                "MESH_MESSAGES_CALLBACK_LIST", []
            )
        )
        self.external_callbacks = [] # здесь храним коллбэки
        # переключатель режима обработки прямых сообщений
        self.pm_mode = bool(self.config.get("WORK_ON_PRIVATE_MSGS", False))

        # нужно проверить существование токена
        # закомментируем, т.к. на конфигах с только mesh-каналами и ботами для них токен задан не будет, соотв. воркер не стартанет
        # if not self.http_token:
        #     print(f"self.http_token не задан, не стартуем воркер")
        #     self.selfcheck_is_correct = False
        #     return None
        
        self.selfcheck_is_correct = True

        # cache of already sent poll messages to avoid duplicates
        self.sent_messages_cache: set[str] = set()

        # выполним предзагрузочный url
        self.prepoll_cbk()

        # Инициализация класса прошла
        print(f"Ok. Создан экземпляр {self.worker_index} = \n", json.dumps(self.config, indent=4, ensure_ascii=False, default=str))

    async def async_init(self):
        result = False

        if not self.selfcheck_is_correct:
            result = False
            print(f"async_init(): не выполняем загрузку, self.selfcheck_is_correct == False, async_init от worker #{self.worker_index}")
            return result

        # получить каналы, найти целевой
        target_chid = await self.search_target_ch_idx(meshcore)

        if target_chid is not None:
            self.target_channel_id = int(target_chid)
        else:
            print("async_init(): Не удалось найти индекс канала с целевым именем, завершаемся")
            result = False
            return result
            #raise RuntimeError("Прерываем выполнение")

        # работаем, только если есть self.target_channel_id
        if self.target_channel_id is not None:

            if self.target_channel_id == 0 and self.work_on_broadcast_mesh_channel is not True:
                print(f"\nasync_init(): Worker #{self.worker_index}: self.target_channel_id = 0, but self.work_on_broadcast_mesh_channel != true. Exit")
                result = False
            else:
                # установка внешних коллбэков

                # проверим, что опция включена, и что задано имя файла
                if self.mesh_messages_callback_enabled == True and isinstance(self.mesh_messages_callback_file, str) and self.mesh_messages_callback_file:
                    
                    # проверим ,что файл существует и доступен для чтения
                    if os.path.isfile(self.mesh_messages_callback_file) and os.access(self.mesh_messages_callback_file, os.R_OK):
                        if isinstance(self.mesh_messages_callback_list, set) and len(self.mesh_messages_callback_list):
                            loaded = self.load_callbacks_from_file()
                            logger.info(f"async_init(): Результат self.load_callbacks_from_file(): {loaded}")
                        else:
                            logger.warning("async_init(): Файл %s прочитан, но не имеет коллбэков", self.mesh_messages_callback_file)
                    else:
                        logger.warning("async_init(): Невозможно загрузить внешние коллбэки - файл %s недоступен для чтения или не существует", self.mesh_messages_callback_file)


                # Subscribe to channel messages
                self.channel_subscription = meshcore.subscribe(EventType.CHANNEL_MSG_RECV, self.message_callback, attribute_filters={"channel_idx": self.target_channel_id},)

                print(f"\nasync_init(): Worker #{self.worker_index}: Subscribed to events:")
                print(f"- Channel messages (target ch_id (real) = {target_chid}, ch_name (from config) = {self.target_channel_name})")

                # Запускаем фоновую задачу опроса poll_url
                asyncio.create_task(self.extmsngr_poll_task(meshcore))

                result = True
        
        # Инициализация класса прошла
        print(f"async_init() Ok. Выполнена async_init от worker #{self.worker_index}")
        
        return result
    
    async def async_init_pm(self):
        result = False

        if not self.selfcheck_is_correct:
            result = False
            print(f"async_init(): не выполняем загрузку, self.selfcheck_is_correct == False, async_init_pm от worker #{self.worker_index}")
            return result
        
        # работаем только в режиме приватных сообщений
        if not self.pm_mode:
            result = False
            print(f"async_init(): pm-worker - не выполняем загрузку, self.pm_mode == False, async_init_pm от worker #{self.worker_index}")
            return result
        
        # кэш отправленных сообщений из poll в tg для дедупликации
        self.received_pm_cache: Dict[str, float] = {}
        self.received_pm_cache_ttl = 300

        # установка внешних коллбэков
        # проверим, что опция включена, и что задано имя файла
        if self.mesh_messages_callback_enabled == True and isinstance(self.mesh_messages_callback_file, str) and self.mesh_messages_callback_file:
            
            # проверим ,что файл существует и доступен для чтения
            if os.path.isfile(self.mesh_messages_callback_file) and os.access(self.mesh_messages_callback_file, os.R_OK):
                if isinstance(self.mesh_messages_callback_list, set) and len(self.mesh_messages_callback_list):
                    loaded = self.load_callbacks_from_file()
                    logger.info(f"async_init_pm(): Результат self.load_callbacks_from_file(): {loaded}")
                else:
                    logger.warning("async_init_pm(): Файл %s прочитан, но не имеет коллбэков", self.mesh_messages_callback_file)
            else:
                logger.warning("async_init_pm(): Невозможно загрузить внешние коллбэки - файл %s недоступен для чтения или не существует", self.mesh_messages_callback_file)

        # Get your contacts
        contacts_raw_result = await meshcore.commands.get_contacts()
        if contacts_raw_result.type == EventType.ERROR:
            print(f"Error getting contacts: {contacts_raw_result.payload}")
        else:
            self.contacts = contacts_raw_result.payload
            print(f"Found {len(self.contacts)} contacts")
        
        # Subscribe to private messages
        self.channel_subscription = meshcore.subscribe(EventType.CONTACT_MSG_RECV, self.pm_callback)

        print(f"\nasync_init_pm(): Worker #{self.worker_index}: Subscribed to private msgs")

        result = True
        
        # Инициализация класса прошла
        print(f"async_init_pm() Ok. Выполнена async_init_pm от pm-worker #{self.worker_index}")
        
        return result
    
    def load_callbacks_from_file(self, file_path=None):
        result = False

        if file_path is None:
            if self.mesh_messages_callback_file:
                self.mesh_messages_callback_file = os.path.join(self.script_dir, self.mesh_messages_callback_file)
                file_path = self.mesh_messages_callback_file
        
        # перепроверим права
        if os.path.isfile(file_path) and os.access(file_path, os.R_OK):
            if isinstance(self.mesh_messages_callback_list, set) and len(self.mesh_messages_callback_list):
                # перебор коллбэков

                # Создаем спецификацию модуля, создаем модуль из спецификации
                spec = importlib.util.spec_from_file_location(f"meshcorebot_external_callbacks_{self.worker_index}", file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module) # Исполняем модуль (загружаем его в память)

                for cbk_index, cbk_name in enumerate(self.mesh_messages_callback_list):
                    
                    # Ищем функцию внутри модуля
                    if hasattr(module, cbk_name):
                        prepared_cbk = getattr(module, cbk_name)

                        # Подписываем найденную функцию
                        if callable(prepared_cbk):
                            self.external_callbacks.append(prepared_cbk)
                            print(f"Воркер #{self.worker_index} Подписана функция: {prepared_cbk.__name__}")
                            result = True
                        else:
                            print(f"Ошибка: Переданный объект '{cbk_name}' не является функцией.")
                    else:
                        print(f"Функция '{cbk_name}' не найдена в файле {file_path}")
            else:
                logger.warning("load_callbacks_from_file(): повторная проверка - %s прочитан, но не имеет коллбэков", file_path)
                result = False
        else:
            logger.warning("load_callbacks_from_file(): повторная проверка файла с коллбэками - %s недоступен", file_path)
            result = False

        return result

    # коллбэк на получение сообщения
    def async_event_callback_on_done(self, task: asyncio.Task, callable_func_name = ""):
        try:
            result = task.result()
            print(f"            Результат вызова {callable_func_name} = {result}")
        except Exception as e:
            print(f"            Результат вызова {callable_func_name} = ошибка: \n{e}")

    async def message_callback(self, event):

        msg_text = event.payload['text']
        ch_id = event.payload.get('channel_idx', None)
        pathinfo = WORKERS_LAST_RX_PACKETS

        print(f"\n\n\n*************************************************************\nReceived message: \n{msg_text}\n\n")
        print(f"Type: {event.payload['type']}")
        print(f"From: {event.payload.get('pubkey_prefix', 'channel')}")
        print(f"Channel_idx: {ch_id}")
        print(f"Pathinfo: \n{pathinfo}")

        dt = datetime.fromtimestamp(event.payload['sender_timestamp'])
        print(f"Timestamp: {dt.strftime("%d.%m.%Y %H:%M:%S")} ({event.payload['sender_timestamp']})")

        #debug_data = dict(vars(event))
        debug_data = {**dict(vars(event)), **pathinfo}

        if LOG_PACKETS_TO_FILE:
            self.log_packet_to_file(debug_data)

        if LOG_PACKETS_TO_CLI:
            print("Дамп полученного пакета:\n", json.dumps(debug_data, indent=4, ensure_ascii=False, default=str))

        # переназначение переменной - ниже, если включен режим regexp и сообщение не удовлетворит, self.reply_to_mesh_msg сбросится в False, что воспрепятствует отправке ответов на следующие сообщения. Такой вот костыль, надо переделать
        self.reply_to_mesh_msg = bool(self.config.get("REPLY_TO_MESH_MSG", False))

        # перепроверка целевого канала и постинг в телеграм
        if ch_id is not None and int(ch_id) == self.target_channel_id:

            send_result = False # дефолт

            if self.http_send_url is not None and self.http_send_url != "":
                send_result = self.send_to_extmsngr(msg_text)
            else:
                if self.reply_to_mesh_msg:
                    print("self.http_send_url пуста (не отправляем во внешнюю систему), но self.reply_to_mesh_msg включено (требуется реакция на полученное сообщение) - выставляем send_result в true")
                    send_result = True

            # проверка необходимости ответа, завязанная на опцию REPLY_TO_MESH_MSG
            if send_result == True and self.reply_to_mesh_msg == True:
                # отправим ответную реакцию

                # проверка режима регулярного выражения
                if self.reply_to_mesh_msg_regex_enabled == True and self.reply_to_mesh_msg_regex_pattern:
                    try:
                        # преобразуем строковые флаги в re-флаги
                        reaction_regex_flags_str = self.reply_to_mesh_msg_regex_flags
                        flags = 0
                        if reaction_regex_flags_str:
                            for name in reaction_regex_flags_str.split("|"):
                                name = name.strip().upper()
                                if hasattr(re, name):
                                    flags |= getattr(re, name)
                        reaction_regex = re.compile(self.reply_to_mesh_msg_regex_pattern, flags)

                        logger.info("Reaction regex enabled: %s", self.reply_to_mesh_msg_regex_pattern)
                    except re.error as exc:
                        logger.exception("Неверный regex pattern: %s", exc)
                        self.reply_to_mesh_msg_regex_enabled = False
                        tb = traceback.format_exc()
                        print(tb)
                
                # перепроверка
                if self.reply_to_mesh_msg_regex_enabled:

                    # проверка
                    formatted_name = self.remove_node_name_from_msg(msg_text)
                    if not reaction_regex.match(formatted_name):
                        # не совпало, не отправляем
                        self.reply_to_mesh_msg = False
                        logger.info("Включен режим ответа на сообщения, удовлетворяющие регулярному выражению, и сообщение не подпадает под него - не реагируем")

                # далее решаем, как быть с отправкой ответа
                if self.reply_to_mesh_msg == True:

                    # сперва сравним канал и разрешение на широковещательный режим
                    if int(self.target_channel_id) == 0 and self.work_on_broadcast_mesh_channel is False:
                        print("\nОтправка ответа на сообщение из mesh: self.target_channel_id определен как 0, но self.work_on_broadcast_mesh_channel установлен в false - не отвечаем\n")
                    else:
                        # вывести в функцию, с передачей debug_data в качестве исходного пакета
                        if self.reply_to_mesh_msg_delay_seconds:
                            print(f"Выжидаем {self.reply_to_mesh_msg_delay_seconds} перед отправкой ответа")
                            time.sleep(float(self.reply_to_mesh_msg_delay_seconds))
                            #await asyncio.sleep(float(self.reply_to_mesh_msg_delay_seconds))

                        reply_result = await self.send_channel_reply(self.target_channel_id, self.reply_to_mesh_msg_txt, debug_data.copy(), msg_text)

                        if reply_result.type == EventType.ERROR:
                            print(f"\nError sending reply: {reply_result.payload}", reply_result, "\n")
                        else:
                            print("\nReply sent", reply_result, "\n")
            else:
                print("Сообщение получено, но реакция не была отправлена")

            # а теперь - обработка внешних коллбэков, завязана на опцию MESH_MESSAGES_CALLBACK_ENABLED
            if self.mesh_messages_callback_enabled == True and isinstance(self.external_callbacks, list) and len(self.external_callbacks):
                for external_cbk in self.external_callbacks:
                    # external_cbk_result = await external_cbk(self, event)
                    # print(f"            Результат вызова {external_cbk.__name__} = {external_cbk_result}")
                    asyncio.create_task(external_cbk(self, event)).add_done_callback(partial(self.async_event_callback_on_done, callable_func_name=external_cbk.__name__))

        else:
            print(f"Сообщение «{msg_text}» получено в канал с отличающимся ch_id ({ch_id} / {self.target_channel_id}), пропускаем его")

    async def pm_callback(self, event):
        msg_text = event.payload['text']
        pathinfo = WORKERS_LAST_RX_PACKETS

        data = event.payload
        contact = self.meshcore.get_contact_by_key_prefix(data['pubkey_prefix'])

        print(f"\n\n\n*************************************************************")
        if contact:
            print(f"Received Private message from «{contact['adv_name']}»: ")
        else:
            print(f"Received Private message from unknown: ")
        print(f"\n{msg_text}\n")
        print(f"From (pubkey prefix): {data['pubkey_prefix']}")
        print(f"Type: {event.payload['type']}")
        print(f"Pathinfo: \n{pathinfo}")

        dt = datetime.fromtimestamp(event.payload['sender_timestamp'])
        print(f"Timestamp: {dt.strftime("%d.%m.%Y %H:%M:%S")} ({event.payload['sender_timestamp']})")

        #debug_data = dict(vars(event))
        debug_data = {**dict(vars(event)), **pathinfo}

        if LOG_PM_PACKETS_TO_FILE:
            debug_data['Timestamp'] = str(dt.strftime("%d.%m.%Y %H:%M:%S")) + " ({event.payload['sender_timestamp']})"
            # добавить данные о контакте - ключ и имя
            if contact:
                debug_data['contact'] = copy.deepcopy(contact)
            self.log_packet_to_file(debug_data, "meshcore_packets_pms.log")

        if LOG_PACKETS_TO_CLI:
            print("Дамп полученного пакета:\n", json.dumps(debug_data, indent=4, ensure_ascii=False, default=str))

        # врезка для дедупликации - иногда приходят одни и те же копии сообщения по нескольку раз, с одной временной меткой и текстом
        already_sent = False
        msg_key = self.make_message_key(dict(vars(event)))

        # проверка в кэше
        await self.cleanup_received_pm_cache()

        if msg_key in self.received_pm_cache:
            # Сообщение уже отправлялось
            already_sent = True

        # резервируем ключ заранее, чтобы другие корутины не отправили дубль
        self.received_pm_cache[msg_key] = time.time()
        
        # если проверка на кэш не прошла, уведомим пользователя и не будем обрабатывать сообщение коллбэками
        if already_sent:
            print(f"Сообщение уже обрабатывалось - пропускаем его")
            return False

        # а теперь - обработка внешних коллбэков, завязана на опцию MESH_MESSAGES_CALLBACK_ENABLED
        if self.mesh_messages_callback_enabled == True and isinstance(self.external_callbacks, list) and len(self.external_callbacks):
            for external_cbk in self.external_callbacks:
                # external_cbk_result = await external_cbk(self, event)
                # print(f"            Результат вызова {external_cbk.__name__} = {external_cbk_result}")
                asyncio.create_task(external_cbk(self, event)).add_done_callback(partial(self.async_event_callback_on_done, callable_func_name=external_cbk.__name__))

    # возвращает хэш сообщения из chat_id, даты и текста
    def make_message_key(self, msg_dict: dict) -> str:
        
        try:
            # if sent_to_tg_cache_key_elems:
            #     fields = sent_to_tg_cache_key_elems
            # else:
            #     fields = ['chat_id', 'msg']
            #     print(f"sent_to_tg_cache_key_elems пуст, сбросили до дефолтного \n{fields}")
            fields = ['pubkey_prefix', 'text', 'sender_timestamp']
            payload = msg_dict.get("payload", None)
            if not payload:
                return ""

            raw = "|".join(str(payload.get(field, "")) for field in fields)
            normalized = " ".join(raw.split())
            return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        except Exception as e:
            print(f"make_message_key(): ошибка", e)
            return ""

    # функция для поиска и удаления устаревших хэшей из кэша отправленных в tg сообщений
    async def cleanup_received_pm_cache(self):
        now = time.time()
        expired_keys = [
            key for key, ts in self.received_pm_cache.items()
            if now - ts > self.received_pm_cache_ttl
        ]
        for key in expired_keys:
            del self.received_pm_cache[key]

    # отправляет в канал ответное сообщение
    async def send_channel_reply(self, channel_id: int, text: str, packet: dict, received_msg_text: str):
        final_send_text = text

        if text == "" and packet and packet.get("payload"):
            # если у нас пустой текст - отправим количество хопов
            logger.info("Ответ на mesh-сообщение включен, но текст не задан - вернём количество хопов")
            payload = packet.get("payload", {})
            final_send_text = payload.get('path_len', '')
            if final_send_text == "":
                final_send_text = "?hops"
            else:
                # преобразование числа в integer
                final_send_text = self.number_to_emoji(final_send_text)
            
            # и добавим SNR
            if final_send_text:
                final_send_text += ""
                if "SNR" in payload:
                    final_send_text += " SNR ко мне " + str(payload["SNR"])
                else:
                    final_send_text += " SNR ко мне неизвестен" # "I'm received with last SNR ?"

            # и добавим ссылку, на чей запрос отвечаем
            if received_msg_text:
                nodename = self.get_node_name_from_msg(received_msg_text)
                if nodename:
                    final_send_text = "@[" + nodename + "] " + final_send_text # @[имя_ноды] сообщение 


        reply_result = await meshcore.commands.send_chan_msg(channel_id, final_send_text)
        return reply_result
    
    # преобразовывает число в эмодзи. Лимит - от 0 до 100
    def number_to_emoji(self, num_str: str) -> str:
        digit_map = {
            "0": "0️⃣",
            "1": "1️⃣",
            "2": "2️⃣",
            "3": "3️⃣",
            "4": "4️⃣",
            "5": "5️⃣",
            "6": "6️⃣",
            "7": "7️⃣",
            "8": "8️⃣",
            "9": "9️⃣",
        }

        try:
            n = int(num_str)
        except ValueError:
            tb = traceback.format_exc()
            print(tb)
            return num_str  # не число — возвращаем как есть

        if not (0 <= n <= 100):
            return num_str

        if n == 100:
            return "💯"

        return "".join(digit_map[d] for d in str(n))
    
    def remove_node_name_from_msg(self, text: str):
        if self.try_trim_nodename == True:
            # Если включён self.try_trim_nodename — пытаемся удалить префикс до первого ": "
            original_text = text  # сохраним для возможного fallback
            # Разбиваем по разделителю ": " (все вхождения), удаляем первую часть,
            # потом соединяем оставшиеся частями через ": " обратно.
            parts = original_text.split(": ")
            if len(parts) >= 2:
                new_text = ": ".join(parts[1:]).strip()
                if new_text:
                    text = new_text
                    # логируем факт трима (коротко)
                    print("[DBG] Trimmed nodename prefix from message.")
                else:
                    # fallback к оригиналу
                    text = original_text
                    print("[DBG] Trim resulted empty -> fallback to original text.")
        return text
    
    def get_node_name_from_msg(self, text: str):
        result = ""

        # Разбиваем строку по первому вхождению ": "
        parts = text.split(": ")
        
        if len(parts) >= 2:
            # Берем только самый первый элемент (то, что было до ": ")
            node_name = parts[0].strip()
            
            if node_name:
                result = node_name
        return result
    
    def send_to_extmsngr(self, text: str) -> None:
        """Отправка входящего сообщения Mesh во внешнюю систему через HTTP POST."""
        
        result = False

        if not self.http_send_url or not self.tg_target_channel_id:
            logger.debug(
                "self.http_send_url или self.tg_target_channel_id не заданы — отправка во внешнюю систему пропущена."
            )
            return result
        
        if not self.http_token:
            logger.debug(
                "self.http_token не задан — отправка во внешнюю систему пропущена."
            )
            return result
        
        # обрезка имени ноды
        text = self.remove_node_name_from_msg(text)

        payload = {
            "token": self.http_token,
            "msg": text,
            "channel_id": self.tg_target_channel_id,
        }

        try:

            # выведем инфо в консоль - для этого скопируем payload, чтобы не показывать токен
            payload_for_log = protect_dict_values(payload, ["token"])

            # выведем в консоль инфу о ноде
            logger.info("Отправка сообщения во внешнюю систему: %s, обрезка имени = %s", payload_for_log, self.try_trim_nodename)

            verify_ssl = not self.http_ignore_ssl_errors

            # выполняем запрос
            resp = do_post_request(self.http_send_url, payload, HTTP_TIMEOUT_SECONDS, verify_ssl)
            if resp:
                logger.info("Сообщение успешно отправлено во внешнюю систему.\n")
                result = True
            else:
                logger.warning(
                    "External POST вернул статус %s: %s\n",
                    resp.status_code,
                    resp.text[:200],
                )
                result = False
                
        except Exception as exc:
            logger.exception(
                "Ошибка при отправке сообщения во внешнюю систему: %s\n", exc
            )
            result = False
            tb = traceback.format_exc()
            print(tb)
        finally:
            return result
        
    def prepoll_cbk(self):
        """Блокирующий HTTP POST перед стартом основного клиента."""
        if not self.http_prepoll_url:
            logger.info("self.http_prepoll_url не задан — pre-poll пропущен.")
            return
        
        verify_ssl = not self.http_ignore_ssl_errors

        for poll_url in self.http_prepoll_url:
            if not poll_url:
                continue
            else:
                logger.info("Выполняется HTTP pre-poll POST -> %s", poll_url)

                # выполняем запрос
                payload = {
                    "token": self.http_token
                }
                resp = do_post_request(poll_url, payload, HTTP_TIMEOUT_SECONDS, verify_ssl)
                if resp:
                    if isinstance(resp, dict):
                        logger.info("HTTP pre-poll JSON ответ:\n%s", json.dumps(resp, ensure_ascii=False, indent=2))
                    else:
                        logger.warning("HTTP pre-poll ответ не является JSON: %s", resp)
                else:
                    logger.warning("HTTP pre-poll запрос неудачный: resp=", resp)

    def log_packet_to_file(self, debug_data: dict, log_filename: str = "") -> None:
        # logger = logging.getLogger("meshcore_client")
        try:
            if not log_filename:
                log_filename = "meshcore_packets.log"

            # добавим подпапку
            log_filename = "logs/" + log_filename

            # Папка скрипта
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(script_dir, log_filename)

            # Записываем в файл (добавление)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(debug_data, indent=4, ensure_ascii=False, default=str))
        except Exception as exc:
            logger.exception("Ошибка при записи пакета в файл: %s", exc)
            tb = traceback.format_exc()
            print(tb)

    # пытается получить и вернуть информацию о канале по его индексу
    async def get_channel_info(self, mc, idx: int):
        """Get information about a specific channel"""
        try:
            channel_idx = int(idx)
            
            # print(f"Getting info for channel {channel_idx}...")
            result = await mc.commands.get_channel(channel_idx)
            
            if result.type == EventType.CHANNEL_INFO:
                result = result.payload
            #     print(f"Channel {payload.get('channel_idx', 'Unknown')}:")
            #     print(f"  Name: {payload.get('channel_name', 'Unknown')}")
            #     print(f"  Secret: {payload.get('channel_secret', b'').hex()}")
            # elif result.type == EventType.ERROR:
            #     print(f"Error getting channel info: {result.payload}")
            # else:
            #     print(f"Unexpected response: {result.type}")

            return result
                
        except ValueError:
            # print("Invalid channel index. Please enter a number.")
            tb = traceback.format_exc()
            print(tb)
            return None
        except Exception as e:
            # print(f"Error: {e}")
            tb = traceback.format_exc()
            print(tb)
            return None
        # print()

    # Перебирает каналы, ищет совпадение его имени с self.target_channel_name, вернет int(номер канала) в случае нахождения
    async def search_target_ch_idx(self, mc):
        """Just loop"""

        try:
            limit = int(SCAN_CHANNELS_LIMIT)
        except (TypeError, ValueError):
            limit = 5
            tb = traceback.format_exc()
            print(tb)

        target_id = None
        if limit > 0:
            for i in range(limit):
                res = await self.get_channel_info(mc, i)
                ch_name = ""
                if res is not None:
                    #ch_data = dict(vars(res))
                    ch_name = res.get('channel_name', None)

                if ch_name == self.target_channel_name:
                    target_id = i
                    break
        
        return target_id
    
    async def send_polled_to_mesh(self, messages: list[dict], meshcore):
        """Process list of dicts with keys 'name','date','msg' and send to mesh node.
        Avoid resending previously sent identical messages (basic cache)."""
        if not messages:
            return
        
        # сперва сравним канал и разрешение на широковещательный режим
        if int(self.target_channel_id) == 0 and self.work_on_broadcast_mesh_channel is False:
            print("send_polled_to_mesh(): TARGET_CHANNEL_ID определен как 0, но self.work_on_broadcast_mesh_channel установлен в false - не выполняем задачу пересылки сообщений из телеграм в mesh")
            return
        
        for msgobj in messages:
                try:
                    name = str(msgobj.get("name", ""))
                    date = str(msgobj.get("date", ""))
                    text = str(msgobj.get("msg", ""))
                    chat_id = str(msgobj.get("chat_id", ""))
                    if not text:
                        print("send_polled_to_mesh(): пропускаем сообщение, т.к. не задан text")
                        continue

                    if not chat_id:
                        print("send_polled_to_mesh(): пропускаем сообщение, т.к. не задан chat_id")
                        continue

                    if str(chat_id) != self.tg_target_channel_id:
                        print(f"send_polled_to_mesh(): chat_id ({chat_id}) не совпадает с self.tg_target_channel_id ({self.tg_target_channel_id}), пропускаем")
                        continue

                    if name in self.ignored_poll_names:
                        logger.info(
                            "Сообщение от '%s' пропущено (self.ignored_poll_names)",
                            name
                        )
                        continue

                    cache_key = f"{name}|{date}|{text}"
                    if cache_key in self.sent_messages_cache:
                        logger.debug("Polled message already sent, skipping: %s", cache_key)
                        continue

                    # удаление гласных из имени для экономии трафика
                    if self.tg_remove_tgnames_vowel == True:
                        logger.info("self.tg_remove_tgnames_vowel = True, удалим гласные из ника")
                        vowels = set("aeiouyAEIOUYаеёиоуыэюяАЕЁИОУЫЭЮЯ")
                        name = name[0] + "".join(c for c in name[1:] if c not in vowels and c != " ")

                    # сокращение ника до 4 символов
                    if self.tg_short_tgnames == True:
                        name = name[:4]

                    # сокращение даты до времени
                    if self.tg_short_date == True:
                        date = date.split(" ")[-1]

                    if self.tg_skip_date == True:
                        date = ""

                    if self.tg_transliterate_to_mesh == True:
                        if self.tg_transliterate_on_overlimit == True:
                            if len(text.encode("utf-8")) > self.polled_message_maxlength:
                                logger.info("self.tg_transliterate_on_overlimit = True, и длина сообщения выше лимита - транслитеруем входящее из TG")
                                text = self.transliterate(text)

                        else:
                            logger.info("self.tg_transliterate_to_mesh = True, транслитеруем входящее из HTTP сообщение")
                            text = self.transliterate(text)

                    parts = self.split_message_with_header(name, date, text, self.polled_message_maxlength)

                    if self.target_channel_id is not None:
                        # short delay to avoid flooding
                        time.sleep(2)
                        #await asyncio.sleep(2)

                        for part in parts:
                            try:
                                logger.info("Отправка polled message в channelIndex=%s: \n\n%s", self.target_channel_id, part)
                                
                                # сама отправка
                                result = await meshcore.commands.send_chan_msg(self.target_channel_id, part)

                                if result.type == EventType.ERROR:
                                    print(f"\nError sending to Mesh: {result.payload}", result, "\n")
                                else:
                                    print("\nMsg translated to Mesh", result, "\n")
                                
                                # short delay to avoid flooding
                                time.sleep(4)
                                #await asyncio.sleep(4)

                            except Exception as exc:
                                logger.exception("\nОшибка при отправке polled message: %s", exc, "\n")
                                tb = traceback.format_exc()
                                print(tb)

                    # mark as sent
                    self.sent_messages_cache.add(cache_key)

                except Exception as exc:
                    logger.exception("Ошибка при обработке polled message: %s", exc)
                    tb = traceback.format_exc()
                    print(tb)

    # Разбивает сообщение на куски по лимиту байтов.
    def split_message_with_header(self, name: str, date: str, msg: str, max_total: int = 130) -> List[str]:
        """Split msg into parts so that final constructed message doesn't exceed max_total bytes (UTF-8).

        Format per part when pagination is needed:
            "{name} ({date}): {part} {a}/{b}"
        If message fits in one part, pagination is omitted:
            "{name} ({date}): {msg}"

        Все измерения и ограничения — в байтах UTF-8.
        """

        def byte_len(s: str) -> int:
            return len(s.encode("utf-8"))

        def truncate_to_byte_limit(s: str, limit: int) -> str:
            """Return the longest prefix of s whose UTF-8 encoded length <= limit."""
            if limit <= 0:
                return ""
            # Fast path if whole string fits
            bs = s.encode("utf-8")
            if len(bs) <= limit:
                return s
            # Otherwise build prefix by iterating characters (safe w.r.t. codepoints)
            acc = 0
            out_chars = []
            for ch in s:
                ch_b = ch.encode("utf-8")
                ch_bl = len(ch_b)
                if acc + ch_bl > limit:
                    break
                out_chars.append(ch)
                acc += ch_bl
            return "".join(out_chars)

        # prepare header
        header = f"{name} ({date}): " if date != "" else f"{name}: "
        header_blen = byte_len(header)

        # quick single-part test (no pagination suffix)
        if header_blen + byte_len(msg) <= max_total:
            return [f"{header}{msg}"]

        # greedy split that accounts for payload limit in bytes
        def greedy_split(text: str, payload_limit_bytes: int) -> List[str]:
            """Split text into parts where each part's byte length <= payload_limit_bytes.
            Splitting is word-aware (by whitespace) and falls back to hard-splitting long words
            preserving UTF-8 codepoint boundaries.
            """
            words = text.split()
            parts: List[str] = []
            cur = ""
            cur_blen = 0

            for w in words:
                w_blen = byte_len(w)
                if cur == "":
                    # start a new part with w (or hard-split w if too large)
                    if w_blen <= payload_limit_bytes:
                        cur = w
                        cur_blen = w_blen
                    else:
                        # hard split the word into several pieces each <= payload_limit_bytes
                        rest = w
                        while rest:
                            piece = truncate_to_byte_limit(rest, payload_limit_bytes)
                            if not piece:  # single character exceeds limit (shouldn't happen with limit>=1)
                                break
                            parts.append(piece)
                            rest = rest[len(piece):]
                        cur = ""
                        cur_blen = 0
                else:
                    # try to append " " + w
                    sep_blen = 1  # space is ASCII -> 1 byte
                    if cur_blen + sep_blen + w_blen <= payload_limit_bytes:
                        cur = cur + " " + w
                        cur_blen = cur_blen + sep_blen + w_blen
                    else:
                        # flush current
                        parts.append(cur)
                        # start new with w (or hard split)
                        if w_blen <= payload_limit_bytes:
                            cur = w
                            cur_blen = w_blen
                        else:
                            rest = w
                            while rest:
                                piece = truncate_to_byte_limit(rest, payload_limit_bytes)
                                if not piece:
                                    break
                                parts.append(piece)
                                rest = rest[len(piece):]
                            cur = ""
                            cur_blen = 0

            if cur:
                parts.append(cur)
            return parts

        # iterative approach to account for pagination suffix length which depends on number of parts
        max_iter = 99
        previous_parts = None
        # start with an upper-bound suffix length for safety (e.g. " 10/10")
        suffix_len = byte_len(" 10/10")
        parts: List[str] = []

        for _ in range(max_iter):
            payload_limit = max_total - header_blen - suffix_len
            if payload_limit < 1:
                # impossible to fit anything with pagination suffix; fallback to raw byte-chunks (after header)
                raw_parts = []
                remaining = msg
                chunk_size = max_total - header_blen
                while remaining:
                    piece = truncate_to_byte_limit(remaining, chunk_size)
                    if not piece:
                        # can't make progress; break to avoid infinite loop
                        break
                    raw_parts.append(piece)
                    remaining = remaining[len(piece):]
                # attach numeric suffixes
                n = len(raw_parts) if raw_parts else 1
                return [f"{header}{p} {i+1}/{n}" for i, p in enumerate(raw_parts)]

            parts = greedy_split(msg, payload_limit)
            if previous_parts is not None and len(parts) == len(previous_parts):
                # stable
                break
            previous_parts = parts
            n = len(parts)
            suffix_len = byte_len(f" {n}/{n}")

        else:
            # didn't converge within max_iter — accept current parts
            n = len(parts)

        # construct final messages; ensure each part fits with its exact suffix (trim if necessary)
        final: List[str] = []
        for i, p in enumerate(parts):
            suffix = f" {i+1}/{n}"
            allowed_payload = max_total - header_blen - byte_len(suffix)
            if allowed_payload < 0:
                # very pathological: can't fit header+suffix; fallback to minimal
                trimmed_p = ""
            else:
                if byte_len(p) <= allowed_payload:
                    trimmed_p = p
                else:
                    trimmed_p = truncate_to_byte_limit(p, allowed_payload)
            final.append(f"{header}{trimmed_p}{suffix}")

        return final
    
    # Транслитерация
    def transliterate(self, text: str) -> str:
        table = {
            'а': 'a',  'б': 'b',  'в': 'v',  'г': 'g',  'д': 'd',
            'е': 'e',  'ё': 'e', 'ж': 'zh', 'з': 'z',  'и': 'i',
            'й': 'y',  'к': 'k',  'л': 'l',  'м': 'm',  'н': 'n',
            'о': 'o',  'п': 'p',  'р': 'r',  'с': 's',  'т': 't',
            'у': 'u',  'ф': 'f',  'х': 'h',  'ц': 'ts', 'ч': 'ch',
            'ш': 'sh', 'щ': 'sch','ъ': '',   'ы': 'y',  'ь': '',
            'э': 'e',  'ю': 'yu', 'я': 'ya',
        }

        result = []
        for ch in text:
            lower = ch.lower()
            if lower in table:
                tr = table[lower]
                # сохраняем регистр
                result.append(tr.capitalize() if ch.isupper() else tr)
            else:
                result.append(ch)

        return "".join(result)
    
    async def extmsngr_poll_task(self, meshcore):
        """
        Фоновая задача: отправка сообщения в mesh и опрос HTTP endpoint.
        """

        # сперва сравним канал и разрешение на широковещательный режим
        if int(self.target_channel_id) == 0 and self.work_on_broadcast_mesh_channel is False:
            print("self.target_channel_id определен как 0, но self.work_on_broadcast_mesh_channel установлен в false - не выполняем задачу пересылки сообщений из телеграм в mesh")
            return

        if int(self.http_poll_period_seconds) < 5:
            self.http_poll_period_seconds = 10

        verify_ssl = not self.http_ignore_ssl_errors

        logger.info("Запуск фоновой задачи: интервал = %s сек.", self.http_poll_period_seconds)

        while True:
            # выполняем действие
            try:
                if not self.http_poll_url:
                    logger.debug("self.http_poll_url не задан. Пропускаем попытку.")
                else:
                    logger.debug("HTTP POST -> %s", self.http_poll_url)

                    # выполняем запрос
                    payload = {
                        "token": self.http_token,
                        "chat_id": self.tg_target_channel_id
                    }
                    resp = do_post_request(self.http_poll_url, payload, HTTP_TIMEOUT_SECONDS, verify_ssl)
                    if resp:
                        if isinstance(resp, dict):
                            # успешный запрос к poll-url, и получили json
                            logger.debug("HTTP POST для poll-URL: %s", json.dumps(resp, ensure_ascii=False)[:1000])

                            # если есть messages внутри полученного json, продолжаем работу
                            if "messages" in resp and isinstance(resp["messages"], list) and resp["messages"]:
                                # вызов функции с отправкой текста в meshcore-канал
                                print("\n\n\n*************************************************************\nПолучены сообщения из HTTP, передаем в send_polled_to_mesh() на дальнейшую проверку")
                                await self.send_polled_to_mesh(resp["messages"], meshcore)
                            else:
                                logger.debug("JSON не содержит 'messages' как список — ничего не отправляем.")
                        else:
                            # успешный запрос к poll-url, но получили что-то другое
                            logger.warning("HTTP POST для poll-URL ответ не является JSON: %s", resp)
                    else:
                        # неуспешный запрос к poll-url
                        logger.warning("HTTP POST для poll-URL %s завершился неудачей", self.http_poll_url)
                            
            except Exception as exc:
                logger.exception("Ошибка при HTTP POST для poll-URL: %s", exc)
                tb = traceback.format_exc()
                print(tb)

            # ждём
            # time.sleep(self.http_poll_period_seconds)
            await asyncio.sleep(self.http_poll_period_seconds)

    def get_latest_pathinfo(self):
        result = {}

        try:
            result = WORKERS_LAST_RX_PACKETS
        except Exception as e:
            print(f"Произошла ошибка: {e}")
            tb = traceback.format_exc()
            print(tb)
        
        return result

    def unsubscribe(self):
        if self.channel_subscription:
            self.meshcore.unsubscribe(self.channel_subscription)
            print(f"Unsubscribed channel events on worker #{self.worker_index}")

# заменяет значения переданных ключей в плоском объекте на плейсхолдер, полезно для последующего вывода в лог
def protect_dict_values(src_dict: dict, keys_list: list, placeholder: str = "***"):

    for_log = src_dict.copy()

    if keys_list:
        for index, item in enumerate(keys_list):
            for_log[item] = '***'
    
    return for_log

# выполняет POST-запрос, отправляет переданный json, при успехе возвращает ответ в виде dict
# При ошибке возвращает None
def do_post_request(url: str, payload: Optional[dict] = None, timeout: int = 10, verify_ssl: bool = True) -> Optional[Union[dict, str]]:

    result = None

    if payload is None:
        payload = {}

    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=timeout,
            verify=verify_ssl
        )
        resp.raise_for_status() # проверка if resp.status_code == 200: не нужна, raise_for_status() выбрасывает исключение requests.exceptions.HTTPError, если статус-код 4xx или 5xx (ошибка клиента или сервера).

        try:
            result = resp.json()
        except ValueError:
            print("do_post_request(): ответ не является JSON: %s", resp.text[:500])
            result = resp.text

    except Exception as e:
        print(f"do_post_request(): POST завершился с ошибкой или таймаутом: \n{e}")
        result = None

    return result

async def handle_rx_log_data(event):
    global WORKERS_LAST_RX_PACKETS

    rx = event.payload or {}
    raw = rx.get("payload")  # use 'payload' (not 'raw_hex') for this parser
    snr = rx.get("snr", None)
    rssi = rx.get("rssi", None)
    if not raw:
        return

    parsed = parse_rx_log_data(raw)
    parsed['SNR'] = snr
    parsed['RSSI'] = rssi

    if parsed:
        WORKERS_LAST_RX_PACKETS = format_pathinfo(parsed)

def parse_rx_log_data(payload: Any) -> dict[str, Any]:
    """Parse RX_LOG event payload to extract LoRa packet details.

    Expected format (hex):
    byte0: header
    byte1: path_len
    next path_len bytes: path nodes
    next byte: channel_hash (optional)
    """
    result: dict[str, Any] = {}

    try:
        hex_str = None

        if isinstance(payload, dict):
            hex_str = payload.get("payload") or payload.get("raw_hex")
        elif isinstance(payload, (str, bytes)):
            hex_str = payload

        if not hex_str:
            return result

        if isinstance(hex_str, bytes):
            hex_str = hex_str.hex()

        hex_str = str(hex_str).lower().replace(" ", "").replace("\n", "").replace("\r", "")

        if len(hex_str) < 4:
            return result

        result["header"] = hex_str[0:2]

        try:
            path_len = int(hex_str[2:4], 16)
            result["path_len"] = path_len
        except ValueError:
            return {}

        path_start = 4
        path_end = path_start + (path_len * 2)

        if len(hex_str) < path_end:
            return {}

        path_hex = hex_str[path_start:path_end]
        result["path"] = path_hex
        result["path_nodes"] = [path_hex[i:i + 2] for i in range(0, len(path_hex), 2)]

        if len(hex_str) >= path_end + 2:
            result["channel_hash"] = hex_str[path_end:path_end + 2]

    except Exception as ex:
        logger.debug(f"Error parsing RX_LOG data: {ex}")

    return result

def format_pathinfo(parsed: dict[str, Any]) -> str:
    """Return obj in format"""

    result = {
        "path_len": None,
        "nodes": None,
        "SNR": None,
        "RSSI": None,
    }

    path_len = parsed.get("path_len", None)
    nodes = parsed.get("path_nodes", None)
    snr = parsed.get("SNR", None)
    rssi = parsed.get("RSSI", None)

    if path_len:
        result["path_len"] = path_len
    if path_len == 0:
        result["path_len"] = 0

    if isinstance(nodes, list):
        result["nodes"] = nodes

    result["SNR"] = snr
    result["RSSI"] = rssi

    return result

async def main():
    # parser = argparse.ArgumentParser(description="MeshCore Pub-Sub Example")
    # parser.add_argument(
    #     "--port", "-p", help="Serial port", required=True
    # )
    # parser.add_argument(
    #     "--baud", "-b", type=int, help="Baud rate", default=115200
    # )
    # args = parser.parse_args()

    # print(f"Connecting to {args.port} at {args.baud} baud...")
    
    # # Create MeshCore instance with serial connection
    # meshcore = await MeshCore.create_serial(args.port, args.baud, debug=True)

    global meshcore
    
    if BLE_ADDRESS != _config.get("BLE_ADDRESS", DEFAULT_CONFIG["BLE_ADDRESS"]) and BLE_ADDRESS != "":
        meshcore = await MeshCore.create_ble(BLE_ADDRESS)

        if meshcore.is_connected:
            device_name = meshcore.self_info.get('name')
            print(f"Connected to MeshCore device {device_name} via BLE ({BLE_ADDRESS})")
        else:
            print("Failed to connect to MeshCore device via BLE {BLE_ADDRESS}")

    if meshcore is None and HTTP_ADDRESS and HTTP_PORT:
        meshcore = await MeshCore.create_tcp(
            HTTP_ADDRESS, HTTP_PORT,
            auto_reconnect=True,
            max_reconnect_attempts=5)

        if meshcore.is_connected:
            device_name = meshcore.self_info.get('name')
            print(f"Connected to MeshCore device {device_name} via TCP ({HTTP_ADDRESS}:{HTTP_PORT})")
        else:
            print("Failed to connect to MeshCore device via TCP {HTTP_ADDRESS}:{HTTP_PORT}")

    if not meshcore.is_connected:
        return
    
    # # Subscribe to connection events
    # async def on_connected(event):
    #     print(f"Connected: {event.payload}")
    #     if event.payload.get('reconnected'):
    #         print("Successfully reconnected!")
    #
    # async def on_disconnected(event):
    #     print(f"Disconnected: {event.payload['reason']}")
    #     if event.payload.get('max_attempts_exceeded'):
    #         print("Max reconnection attempts exceeded")
    #
    # meshcore.subscribe(EventType.CONNECTED, on_connected)
    # meshcore.subscribe(EventType.DISCONNECTED, on_disconnected)

    # выведем в консоль инфу о ноде
    device_info = meshcore.self_info.copy()
    
    # удалим некоторые ключи из вывода
    keys_to_remove = (
        'radio_freq',
        'radio_bw',
        'radio_sf',
        'radio_cr',
    )
    # for key in keys_to_remove:
    #     device_info.pop(key, None)
    # или просто перепишем их
    for key in keys_to_remove:
        device_info[key] = '***'

    # если в инфе о ноде нет public_key или name - не стартуем, т.к. подключение нерабочее, нужно перезапустить bluetooth-адаптер!
    if not device_info.get("public_key") or not device_info.get("name"):
        logger.error(f"Не удалось подключиться к устройству - перезапустите Bluetooth вручную")
        # Disconnect
        await meshcore.disconnect()
        meshcore.stop()

        # стопим asyncio
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        return
    
    # после успешного подключения выведем инфу о ноде
    print("Информация о ноде: \n")
    print(json.dumps(device_info, indent=4, ensure_ascii=False))
    
    # # Get device information to verify connection
    # res = await meshcore.commands.send_device_query()

    # Get contacts
    # result = await meshcore.commands.get_contacts()
    # if result.type == EventType.ERROR:
    #     print(f"Error fetching contacts: {result.payload}")
    #     return
    # contacts = result.payload
    # if contacts:
    #     print(f"\nFound {len(contacts)} contacts:")
    #     for name, contact in contacts.items():
    #         print(f"- {name}")

    # здесь должны обойти список конфигов, создать экземпляры и по идее дальше уже работать с конкретными экземплярами класса
    if WORK_ON:
        for worker_index, worker_cfg in enumerate(WORK_ON):
            try:
                # создадим экземпляр воркера
                bot = MeshcoreBot(meshcore, worker_index, worker_cfg)
                if getattr(bot, "selfcheck_is_correct", False):
                    await bot.async_init()
                    WORKERS.insert(worker_index, bot)
                else:
                    print(f"У воркера #{worker_index} selfcheck_is_correct не равен true, пропускаем")
            except Exception as e:
                print(f"Произошла ошибка: {e}")
                tb = traceback.format_exc()
                print(tb)
    
    # поддержка личных сообщений
    if WORK_ON_PRIVATE_MSGS:
        try:
            # создадим экземпляр воркера
            global PRIVATE_MSGS_CFG
            PRIVATE_MSGS_CFG['WORK_ON_PRIVATE_MSGS'] = WORK_ON_PRIVATE_MSGS
            bot = MeshcoreBot(meshcore, len(WORKERS), PRIVATE_MSGS_CFG)
            if getattr(bot, "selfcheck_is_correct", False):
                await bot.async_init_pm()
                WORKERS.append(bot)
            else:
                print(f"Воркер приватных сообщений #{worker_index} selfcheck_is_correct не равен true, пропускаем")
        except Exception as e:
            print(f"Произошла ошибка: {e}")
            tb = traceback.format_exc()
            print(tb)
    
    # Subscribe to rx_log
    rxlogdata_evt_handler = meshcore.subscribe(EventType.RX_LOG_DATA, handle_rx_log_data)
    
    # работаем дальше
    await meshcore.commands.send_advert(flood=True)
    
    # Subscribe to private messages
    # private_subscription = meshcore.subscribe(EventType.CONTACT_MSG_RECV, message_callback)
    
    # Subscribe to advertisements
    # advert_subscription = meshcore.subscribe(EventType.ADVERTISEMENT, advertisement_callback)
    
    await meshcore.start_auto_message_fetching()
    
    # print("\nSubscribed to events:")
    # # print("- Private messages")
    # # print("- Advertisements")
    
    print("\nWaiting for events. Press Ctrl+C to exit...\n")
    
    # # Get device info
    # device_info = await meshcore.commands.send_device_query()
    # if device_info:
    #     print(f"Device info: {device_info}")
        
    # # Get time from the device
    # device_time = await meshcore.commands.get_time()
    # print(f"Device time: {device_time}")
    
    # # Access current time through the property
    # print(f"Current time (property): {meshcore.time}")
    
    try:
        while True:
            # Wait for messages
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        meshcore.stop()
        print("\nExiting...")
    except asyncio.CancelledError:
        # Handle task cancellation from KeyboardInterrupt in asyncio.run()
        print("\nTask cancelled - cleaning up...")
    finally:
        # Clean up subscriptions
        for worket_index, worker_entity in enumerate(WORKERS):
            worker_entity.unsubscribe()

        rxlogdata_evt_handler.unsubscribe()
        
        # Stop auto-message fetching
        await meshcore.stop_auto_message_fetching()
        
        # Disconnect
        await meshcore.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # This prevents the KeyboardInterrupt traceback from being shown
        print("\nExited cleanly")
    except Exception as e:
        print(f"Error: {e}")
