import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils.executor import start_webhook, start_polling
from aiogram.utils.exceptions import MessageNotModified

from text_handler import handle_text
from utils import get_cancel_button, check_user
from bus_api import get_lines
from settings import TOKEN, IS_SERVER, WEBAPP_PORT, WEBAPP_HOST, WEBHOOK_PATH, PERIOD, TTL


ITERATIONS = TTL // PERIOD


@dataclass
class UserData:
    user_id: int
    station_id: int
    message_id: int
    next_station_id: Optional[int] = False
    next_message_id: Optional[int] = False
    stop_updating: bool = False


logging.basicConfig(level=logging.INFO)

storage = MemoryStorage()
bot = Bot(token=TOKEN, parse_mode=types.ParseMode.MARKDOWN)
dp = Dispatcher(bot, storage=storage)


async def update_message(user_id: int, last: bool = False) -> None:
    user_data: UserData = await dp.storage.get_data(user=user_id)
    text = await get_lines(user_data.station_id, last=last)
    kb = get_cancel_button() if not last else None
    await bot.edit_message_text(
        text,
        user_data.user_id,
        user_data.message_id,
        reply_markup=kb
    )


# TODO TEST IT
async def schedule_next_station(user_id: int, message_id: int, station_id: int) -> ...:
    """
    Scheduler for new stations. If user already subscribed for station, updates it's
    data. Runs updater, if it need.
    """
    user_data: UserData = await dp.storage.get_data(user=user_id)
    if not user_data:
        data = UserData(user_id=user_id, station_id=station_id, message_id=message_id)
        await dp.storage.set_data(user=user_id, data=data)
        await run_updater(user_id)
    else:
        user_data.next_station_id = station_id
        user_data.next_message_id = message_id
        await dp.storage.set_data(user=user_id, data=user_data)


async def run_updater(user_id: int) -> None:
    """
    Warning! Do NOT delete `station_id` from `user_data`.
    If you want to stop updater, set `user_data.stop_updating` to `True`.
    """
    for n in range(ITERATIONS):
        await asyncio.sleep(PERIOD)
        user_data: UserData = await dp.storage.get_data(user=user_id)

        if not user_data.next_station_id and not user_data.stop_updating:
            try:
                await update_message(user_id)
            except MessageNotModified:
                # If lines list not changing during iteration, just skip this iteration
                continue
        else:
            break

    user_data: UserData = await dp.storage.get_data(user=user_id)
    if user_data.next_station_id:
        await update_message(user_id, last=True)
        user_data.station_id = user_data.next_station_id
        user_data.message_id = user_data.next_message_id
        user_data.next_station_id = None
        user_data.next_message_id = None
        await dp.storage.set_data(user=user_id, data=user_data)
        return await run_updater(user_data.user_id)

    await update_message(user_id, last=True)
    await dp.storage.reset_data(user=user_id)


# /start command handler
@dp.message_handler(commands=['start'])
async def handle_start(message: types.message):
    response = 'Hi! Send me a station number!'
    await bot.send_message(message.chat.id, response)


# /help command handler
@dp.message_handler(commands=['help'])
async def handle_help(message: types.message):
    response = 'Send to the bot station\'s number, and bot will send you ' \
               'arrival times of nearest buses. The message with times will ' \
               'updating each 15 seconds for 15 minutes or until you send ' \
               'another number or will press "Stop tracking" button.\n\n' \
               'Author: @benyomin\n' \
               'Code: https://github.com/benyomin94/israel\\_bus\\_info\\_bot'
    await bot.send_message(message.chat.id, response)


# Handler for all text messages
@dp.message_handler(content_types=types.ContentTypes.TEXT)
async def text_handler(message: types.Message):
    response = await handle_text(message.text)
    keyboard = get_cancel_button() if response['ok'] else None
    msg = await bot.send_message(message.chat.id, response['data'], reply_markup=keyboard)

    if response['ok']:
        # TODO test it!
        await schedule_next_station(
            message.from_user.id,
            msg.message_id,
            response['station_id']
        )
    await check_user(message.from_user)

# Handler for "Stop tracking" Callback button
@dp.callback_query_handler(lambda callback_query: True)
async def handle_stop_query(call: types.CallbackQuery):
    await bot.edit_message_reply_markup(call.from_user.id, call.message.message_id)
    await call.answer('Will stop soon')  # TODO normal text
    user_data: UserData = await dp.storage.get_data(user=call.from_user.id)
    user_data.stop_updating = True
    await dp.storage.set_data(user=call.from_user.id, data=user_data)


if __name__ == '__main__':
    if IS_SERVER:
        start_webhook(
            dispatcher=dp,
            webhook_path=WEBHOOK_PATH,
            host=WEBAPP_HOST,
            port=WEBAPP_PORT,
            skip_updates=True
        )
    else:
        start_polling(dp)
