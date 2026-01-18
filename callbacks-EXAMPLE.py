import json
import re
import asyncio
import time
from datetime import datetime
from meshcore import MeshCore, EventType

async def example_callback(bot_instance, event):
    """
    Эта функция будет вызвана из основного скрипта.
    """
    result = True

    print(f"\nexample_callback(): ⚡ Внешний модуль перехватил событие!")

    # отправка сообщения
    # target_msg = "Hello!"
    # time.sleep(2) # await asyncio.sleep(2) # добавим задержку перед отправкой, добавляет стабильности
    # send_result = await bot_instance.meshcore.commands.send_chan_msg(bot_instance.target_channel_id, target_msg) # отправляем сообщение
    # # проверка результатов отправки. При успехе может вернуться EventType.MSG_SENT или EventType.OK - документация не сходится, поэтому отталкиваемся от ошибки
    # if send_result is None or send_result.type == EventType.ERROR:
    #     print("example_callback(): Ошибка при отправке сообщения в Mesh - уведомим пользователя", send_result)
    #     time.sleep(2) # await asyncio.sleep(2) # снова ждём
    #     send_result = await bot_instance.meshcore.commands.send_chan_msg(bot_instance.target_channel_id, "«Hello»-message maybe wasnt sent...")
    #     result = False
    #     # далее можем попробовать переотправить исходный ответ еще раз, но лучше если пользователь просто еще раз выполнит команду, иначе может оказаться, что мы дважды УСПЕШНО его отправим
    #     # send_result = await bot_instance.meshcore.commands.send_chan_msg(bot_instance.target_channel_id, target_msg)
    #     # if send_result is None or send_result.type == EventType.ERROR:
    #     #     print("example_callback(): Ошибка при отправке сообщения со второй попытки", send_result)
    #     #     result = False
    #     # elif send_result.type == EventType.MSG_SENT or send_result.type == EventType.OK:
    #     #     print("example_callback(): Сообщение успешно отправлено со второй попытки", send_result)
    #     #     result = True
    #     # else:
    #     #     print("example_callback(): Даже со второй попытки результат отправки в Mesh неясен", send_result)
    #     #     result = False
    # elif send_result.type == EventType.MSG_SENT or send_result.type == EventType.OK:
    #     print("example_callback(): Сообщение успешно отправлено в Mesh", send_result)
    #     result = True
    # else:
    #     print("example_callback(): Результат отправки в Mesh неясен", send_result)
    #     result = False


    msg_text = event.payload['text']
    ch_id = event.payload.get('channel_idx', None)

    print(f"\nexample_callback(): Received message: {msg_text}")
    print(f"Type: {event.payload['type']}")
    print(f"From: {event.payload.get('pubkey_prefix', 'channel')}")
    print(f"Channel_idx: {ch_id}")

    dt = datetime.fromtimestamp(event.payload['sender_timestamp'])
    print(f"Timestamp: {dt.strftime("%d.%m.%Y %H:%M:%S")} ({event.payload['sender_timestamp']})")

    debug_data = dict(vars(event))

    print("Дамп полученного пакета:\n", json.dumps(debug_data, indent=4, ensure_ascii=False, default=str))

    ######
    # Проверим полученное сообщение на соответствие регулярному выражению
    ######

    # обрезка имени ноды из полученного сообщения
    msg_text = bot_instance.remove_node_name_from_msg(msg_text)

    pattern = r"^(Погода)(\s(сейчас|сегодня|завтра))?$"

    # Используем re.IGNORECASE для игнорирования регистра
    match = re.match(pattern, msg_text, re.IGNORECASE)
    if match:
        print("example_callback(): Отправитель интересовался погодой")

        # match.group(3) — это третья группа (сейчас|сегодня|завтра)
        second_word = match.group(3)
        if second_word:
            print("Дата погоды:", second_word)
        else:
            print("Дата погоды: не указана, значит текущая")
    else:
        print("example_callback(): Сообщение, судя по всему, не является погодным запросом")

    return result

# показывает help по боту
async def show_help_callback(bot_instance, event):
    result = True

    msg_text = event.payload['text']
    ch_id = event.payload.get('channel_idx', None)

    debug_data = dict(vars(event))

    ######
    # Проверим полученное сообщение на соответствие регулярному выражению
    ######

    # обрезка имени ноды из полученного сообщения
    msg_text = bot_instance.remove_node_name_from_msg(msg_text)
    nodename = bot_instance.get_node_name_from_msg(msg_text)

    pattern = r"^(\!help|help)$"

    # Используем re.IGNORECASE для игнорирования регистра
    match = re.match(pattern, msg_text, re.IGNORECASE)
    if match:
        print("\nshow_help_callback(): Отправитель интересовался справкой по боту")

        result_msg = "Ping[ 1..n]\nПинг[ 1..n]\nПогода[ сейчас|сегодня|завтра]\nPogoda[ now|seychas|today|segodnya|tomorrow|zavtra]"

        # отправка сообщения
        time.sleep(2) # await asyncio.sleep(2) # добавим задержку перед отправкой, добавляет стабильности
        send_result = await bot_instance.meshcore.commands.send_chan_msg(bot_instance.target_channel_id, result_msg)
        # проверка результатов отправки. При успехе может вернуться EventType.MSG_SENT или EventType.OK - документация не сходится, поэтому отталкиваемся от ошибки
        if send_result is None or send_result.type == EventType.ERROR:
            print("show_help_callback(): Ошибка при отправке сообщения в Mesh")
            result = False
            time.sleep(2) # await asyncio.sleep(2) # снова ждём
            send_result = await bot_instance.meshcore.commands.send_chan_msg(bot_instance.target_channel_id, "Help: При отправке получен error - вероятно, нужно повторить запрос") # отправим информационное сообщение, не проверяя доставку
        elif send_result.type == EventType.MSG_SENT or send_result.type == EventType.OK:
            print("show_help_callback(): Сообщение успешно отправлено в Mesh")
            result = True
        else:
            print("show_help_callback(): Результат отправки в Mesh неясен", send_result)
            result = False
            
    else:
        print("show_help_callback(): Сообщение, судя по всему, не является подходящим запросом")

    return result