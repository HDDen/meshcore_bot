import json
# import asyncio

async def example_pm_callback(bot_instance, event, last_rx_packet: dict = {}):
    result = True

    # инфо о пути сообщения
    pathinfo = bot_instance.get_latest_pathinfo()
    # дебаг-данные
    #debug_data = dict(vars(event))
    # дополним данными о пути пакета
    #debug_data = {**dict(vars(event)), **pathinfo}
    debug_data = {
        "event": dict(vars(event)),
        "pathinfo": dict(pathinfo)
    }
    print("Дамп полученного пакета:\n", json.dumps(debug_data, indent=4, ensure_ascii=False, default=str))

    payload = event.payload
    msg_text = payload.get("text", "")
    pubkey = payload.get("pubkey_prefix")
    contact = None
    contact_name = ""
    contact_pubkey = ""

    # нам необходимо узнать, можем ли мы доверять данным из последнего проверенного пакета.
    # сравним path_len и SNR из payload и из последнего пакета
    rxlog_packet_is_trusted = False
    if payload.get('SNR') == pathinfo.get('SNR'):
        if int(payload.get('path_len')) > 64 and bot_instance.pm_mode: # фикс payload path_len = 255
            rxlog_packet_is_trusted = True
        elif payload.get('path_len') == pathinfo.get('path_len'):
            rxlog_packet_is_trusted = True
        else:
            rxlog_packet_is_trusted = False

    # подготовим финальный надежный набор данных, из которого будем строить сообщение
    final_data = {}
    final_data['path_len'] = payload.get('path_len', None)
    final_data['SNR'] = payload.get('SNR', None)
    final_data['RSSI'] = None
    final_data['nodes'] = None
    if rxlog_packet_is_trusted:
        final_data['RSSI'] = pathinfo.get('RSSI', None)
        final_data['nodes'] = pathinfo.get('nodes', None)
        if isinstance(final_data['nodes'], list) and not final_data['path_len']:
            final_data['path_len'] = len(final_data['nodes'])
        # иногда в payload личных сообщений path_len прилетает = 255 
        if isinstance(final_data['path_len'], int) and final_data['path_len'] > 64 and pathinfo.get('path_len', None) is not None:
            final_data['path_len'] = pathinfo.get('path_len')

    # убедимся, что работаем в режиме личных сообщений, и продолжим работу
    if bot_instance.pm_mode:
        # работаем в режиме личных сообщений
        if pubkey:
            contact = bot_instance.meshcore.get_contact_by_key_prefix(pubkey)
            if contact:
                contact_name = contact.get('adv_name')
                contact_pubkey = contact.get('public_key')
        
        # отправим ответ
        if contact and (contact_pubkey[:12] == "012345678000"):

            #result = await bot_instance.meshcore.commands.send_msg(contact, "Hello from Python!")
            # отправка с попытками и запросом доставки
            result = await bot_instance.meshcore.commands.send_msg_with_retry(contact, "Hello from Python!")

    return result