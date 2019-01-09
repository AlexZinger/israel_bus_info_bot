from time import time

from celery import Celery
from redis import Redis

import utils
from settings import PERIOD, rmq_user, rmq_pass, rmq_port


app = Celery(
    'tasks',
    broker=f'amqp://{rmq_user}:{rmq_pass}@localhost:{rmq_port}'
)


@app.task
def check_redis():
    r = Redis()
    keys = r.keys()
    for key in keys:
        expire = int(r.hget(key, 'expire').decode())
        updated_ts = int(r.hget(key, 'updated').decode())
        data = {
            'redis_key': key.decode(),
            'user_id': int(r.hget(key, 'id').decode()),
            'message_id': int(r.hget(key, 'message_id').decode()),
            'station': int(r.hget(key, 'station').decode())
        }
        if int(time()) < expire:
            if int(time()) - updated_ts > PERIOD:
                utils.update_last_updated_ts(key)
                update_message.delay(data)
        else:
            stop_tracking.delay(data)
            # todo delete key from redis


@app.task(name='tasks.update_message')
def update_message(data: dict):
    utils.update_message(data)
    utils.update_last_updated_ts(data['redis_key'])


@app.task
def stop_tracking(data: dict):
    utils.update_message(data, last_message=True)
    utils.delete_key_from_redis(data['redis_key'])


app.conf.beat_schedule = {
    'check-redis': {
        'task': 'tasks.check_redis',
        'schedule': 4.0
    }
}
