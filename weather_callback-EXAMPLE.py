import json
import re
import asyncio
from meshcore import MeshCore, EventType
from datetime import datetime
from datetime import date, timedelta
import requests
import time
import xml.etree.ElementTree as ET

async def weather_callback(bot_instance, event, last_rx_packet: dict = {}):
    """
    Эта функция будет вызвана из основного скрипта.
    """
    result = True

    print(f"\nweather_callback(): ⚡ Внешний модуль перехватил событие!")

    msg_text = event.payload['text']
    ch_id = event.payload.get('channel_idx', None)

    dt = datetime.fromtimestamp(event.payload['sender_timestamp'])
    #print(f"Timestamp: {dt.strftime("%d.%m.%Y %H:%M:%S")} ({event.payload['sender_timestamp']})")

    debug_data = dict(vars(event))

    # print("Дамп полученного пакета:\n", json.dumps(debug_data, indent=4, ensure_ascii=False, default=str))

    ######
    # Проверим полученное сообщение на соответствие регулярному выражению
    ######

    # обрезка имени ноды из полученного сообщения
    msg_text = bot_instance.remove_node_name_from_msg(msg_text)

    pattern = r"^(Погода|pogoda|weather)(\s(сейчас|now|seychas|seichas|сегодня|today|segodnya|завтра|tomorrow|zavtra|zawtra))?$"

    # Используем re.IGNORECASE для игнорирования регистра
    match = re.match(pattern, msg_text, re.IGNORECASE)
    if match:
        print("weather_callback(): Отправитель интересовался погодой")

        # match.group(3) — это третья группа (сейчас|сегодня|завтра)
        second_word = match.group(3)
        if second_word:
            second_word = second_word.lower()
            print("Дата погоды:", second_word)
        else:
            print("Дата погоды: не указана, значит текущая")

        weather_date = ""
        weather_with_time = False
        if not second_word or second_word == "сейчас" or second_word == "now" or second_word == "seychas" or second_word == "seichas":
            weather_date = date.today().strftime("%Y-%m-%d")
            weather_with_time = True
        elif second_word == "сегодня" or second_word == "today" or second_word == "segodnya":
            weather_date = date.today().strftime("%Y-%m-%d")
        elif second_word == "завтра" or second_word == "tomorrow" or second_word == "zavtra" or second_word == "zawtra":
            weather_date = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

        if weather_date:
            weather_msg = request_and_parse_gismeteo(weather_date, weather_with_time)
            
            if not weather_msg:
                weather_msg = "Не удалось сформировать ответ"

            print(f"Итоговое собщение:\n{weather_msg}")

            # проверка на длину - должны влезать в лимит, иначе - транслит!
            if len(weather_msg.encode("utf-8")) > bot_instance.polled_message_maxlength:
                print("Длина сообщения выше лимита - транслитеруем")
                weather_msg = bot_instance.transliterate(weather_msg)
                print(f"Результат транслитерации: {weather_msg}")

            # отправка сообщения
            time.sleep(2) #await asyncio.sleep(2) # добавим задержку перед отправкой, добавляет стабильности
            send_result = await bot_instance.meshcore.commands.send_chan_msg(bot_instance.target_channel_id, weather_msg) # отправляем сообщение
            # проверка результатов отправки. При успехе может вернуться EventType.MSG_SENT или EventType.OK - документация не сходится, поэтому отталкиваемся от ошибки
            if send_result is None or send_result.type == EventType.ERROR:
                print("weather_callback(): Ошибка при отправке погоды - уведомим пользователя", send_result)
                time.sleep(2) # await asyncio.sleep(2) # снова ждём
                send_result = await bot_instance.meshcore.commands.send_chan_msg(bot_instance.target_channel_id, "☂ При отправке получен error - вероятно, нужно повторить запрос")
                result = False
                # далее можем попробовать переотправить исходный ответ еще раз, но лучше если пользователь просто еще раз выполнит команду, иначе может оказаться, что мы дважды УСПЕШНО его отправим
                # send_result = await bot_instance.meshcore.commands.send_chan_msg(bot_instance.target_channel_id, weather_msg)
                # if send_result is None or send_result.type == EventType.ERROR:
                #     print("weather_callback(): Ошибка при отправке погоды со второй попытки", send_result)
                #     result = False
                # elif send_result.type == EventType.MSG_SENT or send_result.type == EventType.OK:
                #     print("weather_callback(): Погода успешно отправлена со второй попытки", send_result)
                #     result = True
                # else:
                #     print("weather_callback(): Даже со второй попытки результат отправки погоды неясен", send_result)
                #     result = False
            elif send_result.type == EventType.MSG_SENT or send_result.type == EventType.OK:
                print("weather_callback(): Погода успешно отправлена", send_result)
                result = True
            else:
                print("weather_callback(): Результат отправки погоды в Mesh неясен", send_result)
                result = False

        else:
            print("weather_callback(): Не удалось определить дату для прогноза погоды")
            result = False
            
    else:
        print("weather_callback(): Сообщение, судя по всему, не является погодным запросом")
        result = True

    return result

def request_and_parse_gismeteo(target_date, with_time = False):

    result = ""

    url = "https://services.gismeteo.ru/inform-service/inf_chrometab/forecast/?city=5136&lang=ru"
    
    try:
        # 1. Делаем запрос к сервису
        response = requests.get(url)
        response.raise_for_status()  # Проверяем, что запрос прошел успешно (код 200)
        
        # 2. Парсим XML содержимое
        # Используем response.content, так как в XML указана кодировка utf-8
        root = ET.fromstring(response.content)

        # 3.1. Находим первый тег <location>
        location_node = root.find("location")
        location_name = location_node.get("name_r") if location_node is not None else ""
        
        # 3.2. Ищем нужный элемент <day> с атрибутом date
        # Формат поиска: найти все теги 'day' внутри 'location'
        day_element = root.find(f".//day[@date='{target_date}']")

        # строка для ответного сообщения
        temporary_str = ""
        
        if day_element is not None:
            # теперь нужно понять, ищем мы погоду на текущий момент времени, или в целом за день
            if with_time:

                # обновленный вариант - пересобираем из тега fact
                fact_node = root.find(".//fact")

                if fact_node is not None:
                    # Внутри найденного fact ищем values
                    values_node = fact_node.find("values")
                    
                    if values_node is not None:
                        fact_dict = dict(values_node.attrib)
                        
                        # если видим, в каком городе погода...
                        if location_name:

                            # если temporary_str не пуста, и удается получить описание погоды
                            if fact_dict.get("descr"):
                                temporary_str = temporary_str + str(fact_dict.get("descr")).lower()
                            else:
                                temporary_str = ""

                            # если есть текущая температура
                            if temporary_str and fact_dict.get("t"):
                                temporary_str = temporary_str + ", " + str(fact_dict.get("t")) + "°C"

                            # если есть ощущаемая температура
                            if temporary_str and fact_dict.get("tcflt"):
                                temporary_str = temporary_str + " (ощ. " + str(fact_dict.get("tcflt")) + ")"

                            # если есть скорость ветра
                            if temporary_str and fact_dict.get("ws"):
                                temporary_str = temporary_str + ", " + "💨 " + str(fact_dict.get("ws")) + "м/с"

                            # если есть порывы ветра
                            if temporary_str and fact_dict.get("gust_speed"):
                                temporary_str = temporary_str + ", порывы до " + str(fact_dict.get("gust_speed")) + "м/с"

                            # если есть осадки за день
                            if temporary_str and fact_dict.get("prflt"):
                                temporary_str = temporary_str + ", ☔ осадки " + str(fact_dict.get("prflt")) + "мм"

                            # допишем в начале метку
                            if temporary_str:
                                temporary_str = "Погода сейчас: " + temporary_str
                
                else: # если не нашли фактическую явно - построим из ближайшего предсказания

                    # нужно извлечь текущую метку времени, затем обойти forecast внутри текущего day, у каждого извлечь атрибут valid и преобразовать его в метку времени, затем сравнить, пытаясь найти такой, чтобы метка текущего времени была меньше времени из атрибута

                    now_unix = datetime.now().timestamp()
                    current_forecast_dict = None

                    # Обходим все теги <forecast> внутри найденного дня
                    for forecast in day_element.findall("forecast"):
                        valid_str = forecast.get("valid")
                        if valid_str:
                            # Преобразуем строку "2026-01-16T15:00:00" в UNIX timestamp
                            valid_dt = datetime.fromisoformat(valid_str)
                            valid_unix = valid_dt.timestamp()
                            
                            # Ищем первый прогноз, время которого еще не наступило (больше текущего)
                            if now_unix < valid_unix:
                                current_forecast_dict = dict(forecast.attrib)
                                # Дополнительно забираем данные из вложенного тега <values>
                                values_node = forecast.find("values")
                                if values_node is not None:
                                    current_forecast_dict.update(values_node.attrib)
                                break
                    
                    if current_forecast_dict:
                        # формируем инфу о текущей погоде
                        
                        # если видим, в каком городе погода...
                        if location_name:

                            # если temporary_str не пуста, и удается получить описание погоды
                            if current_forecast_dict.get("descr"):
                                temporary_str = temporary_str + str(current_forecast_dict.get("descr")).lower()
                            else:
                                temporary_str = ""

                            # если есть текущая температура
                            if temporary_str and current_forecast_dict.get("t"):
                                temporary_str = temporary_str + ", " + str(current_forecast_dict.get("t")) + "°C"

                            # если есть скорость ветра
                            if temporary_str and current_forecast_dict.get("ws"):
                                temporary_str = temporary_str + ", " + "💨 " + str(current_forecast_dict.get("ws")) + "м/с"

                            # если есть порывы ветра
                            if temporary_str and current_forecast_dict.get("gust_speed"):
                                temporary_str = temporary_str + ", порывы до " + str(current_forecast_dict.get("gust_speed")) + "м/с"

                            # если есть осадки за день
                            if temporary_str and current_forecast_dict.get("prflt"):
                                temporary_str = temporary_str + ", ☔ осадки " + str(current_forecast_dict.get("prflt")) + "мм"

                            # допишем в начале метку
                            if temporary_str:
                                temporary_str = "Погода сейчас: " + temporary_str

            else:
                # 4. Формируем объект (словарь) из атрибутов элемента

                # создадим набор данных из инфы по дню
                day_dict = dict(day_element.attrib)
                # for key, value in day_dict.items(): # заглянем внутрь
                #     print(f"  {key}: {value}")

                # соберем ответное сообщение
                # если видим, в каком городе погода...
                if location_name:

                    # Преобразуем дату
                    date_obj = datetime.strptime(target_date, "%Y-%m-%d")
                    formatted_date = date_obj.strftime("%d.%m")

                    # если удалось преобразовать дату...
                    if formatted_date:
                        temporary_str = "Погода " + str(formatted_date) + " " + location_name + ": "
                    else:
                        temporary_str = ""

                    # если temporary_str не пуста, и удается получить описание погоды
                    if temporary_str and day_dict.get("descr"):
                        temporary_str = temporary_str + str(day_dict.get("descr")).lower()
                    else:
                        temporary_str = ""

                    # если есть минимальная+максимальная температура
                    if temporary_str and day_dict.get("tmin") and day_dict.get("tmax"):
                        temporary_str = temporary_str + ", " + str(day_dict.get("tmin")) + ".." + str(day_dict.get("tmax")) + "°C"

                    # если есть минимальная+максимальная скорость ветра
                    if temporary_str and day_dict.get("wsmin") and day_dict.get("wsmax"):
                        temporary_str = temporary_str + ", " + "💨 " + str(day_dict.get("wsmin")) + "-" + str(day_dict.get("wsmax")) + "м/с"

                    # если есть порывы ветра
                    if temporary_str and day_dict.get("gust_speed"):
                        temporary_str = temporary_str + ", порывы до " + str(day_dict.get("gust_speed")) + "м/с"

                    # если есть осадки за день
                    if temporary_str and day_dict.get("prflt"):
                        temporary_str = temporary_str + ", ☔ осадки " + str(day_dict.get("prflt")) + "мм"
        
            # фиксируем собранную инфу о погоде в результате
            if temporary_str:
                result = temporary_str

        else:
            print(f"Запись на дату {target_date} не найдена в XML.")
            return result
        
        return result

    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе данных: {e}")
        return result
    except ET.ParseError as e:
        print(f"Ошибка при разборе XML: {e}")
        return result
