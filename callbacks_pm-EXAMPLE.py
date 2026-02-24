import json
# import asyncio

async def example_pm_callback(bot_instance, event):
    result = True

    debug_data = dict(vars(event))
    print("Дамп полученного пакета:\n", json.dumps(debug_data, indent=4, ensure_ascii=False, default=str))

    payload = event.payload
    msg_text = payload.get("text", "")
    pubkey = payload.get("pubkey_prefix")
    contact = None
    contact_name = ""
    contact_pubkey = ""

    if bot_instance.pm_mode:
        # работаем в режиме личных сообщений
        if pubkey:
            contact = bot_instance.meshcore.get_contact_by_key_prefix(pubkey)
            if contact:
                contact_name = contact.get('adv_name')
                contact_pubkey = contact.get('public_key')
        
        # отправим ответ
        if contact and (contact_pubkey[:12] == "012345678000"):

            result = await bot_instance.meshcore.commands.send_msg(contact, "Hello from Python!")

    return result