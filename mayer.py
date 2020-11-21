#!/usr/bin/python3
import configparser
import datetime
import inspect
import logging
import os
import sqlite3
import sys
from logging.handlers import RotatingFileHandler
from time import sleep

import ccxt


class ExchangeConfig:
    def __init__(self):
        config = configparser.ConfigParser()
        config.read(INSTANCE + ".txt")

        try:
            props = dict(config.items('config'))
            self.exchange = str(props['exchange']).strip('"').lower()
            self.api_key = str(props['api_key']).strip('"')
            self.api_secret = str(props['api_secret']).strip('"')
            self.db_name = str(props['db_name']).strip('"')
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('Invalid configuration for ' + INSTANCE)


def function_logger(console_level: int, log_file: str, file_level: int = None):
    function_name = inspect.stack()[1][3]
    logger = logging.getLogger(function_name)
    # By default log all messages
    logger.setLevel(logging.DEBUG)

    # StreamHandler logs to console
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter('%(asctime)s: %(message)s', '%Y-%m-%d %H:%M:%S'))
    logger.addHandler(ch)

    if file_level:
        fh = RotatingFileHandler("{}.log".format(log_file), mode='a', maxBytes=5 * 1024 * 1024, backupCount=4,
                                 encoding=None, delay=False)
        fh.setLevel(file_level)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(lineno)4d - %(levelname)-8s - %(message)s'))
        logger.addHandler(fh)
    return logger


def connect_to_exchange():
    exchanges = {}
    for ex in ccxt.exchanges:
        exchange = getattr(ccxt, ex)
        exchanges[ex] = exchange

    return exchanges[CONF.exchange]({
        'enableRateLimit': True,
        'apiKey': CONF.api_key,
        'secret': CONF.api_secret,
        # 'verbose': True,
    })


def get_current_price(tries: int = 0):
    """
    Fetches the current BTC/USD exchange rate
    In case of failure, the function calls itself again until the max retry limit of 10 is reached
    :param tries:
    :return: int current market price
    """
    if tries > 10:
        LOG.error('Failed fetching current price, giving up after 10 attempts')
        return None
    try:
        return float(EXCHANGE.fetch_ticker('BTC/USD')['bid'])

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.debug('Got an error %s %s, retrying in 10 seconds...', type(error).__name__, str(error.args))
        sleep(10)
        get_current_price(tries + 1)


def init_database():
    conn = sqlite3.connect(CONF.db_name)
    curs = conn.cursor()
    curs.execute("CREATE TABLE IF NOT EXISTS rates (date TEXT NOT NULL PRIMARY KEY, count INTEGER, price FLOAT)")
    conn.commit()
    curs.close()
    conn.close()


def get_last_rate():
    """
    Fetches the last rate from the database
    :return: The fetched rate
    """
    conn = sqlite3.connect(CONF.db_name, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    curs = conn.cursor()
    try:
        return curs.execute("SELECT DISTINCT price FROM rates ORDER BY date DESC").fetchone()
    finally:
        curs.close()
        conn.close()


def get_average():
    """
    Calculates the average price of the past 200 days
    :return: The average price
    """
    today = datetime.datetime.utcnow().date()
    dd_days_ago = today - datetime.timedelta(days=200)
    yesterday = today - datetime.timedelta(days=1)
    conn = sqlite3.connect(CONF.db_name, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    curs = conn.cursor()
    try:
        return curs.execute("SELECT AVG(price) FROM rates WHERE date BETWEEN '{}' AND '{}'".format(dd_days_ago, yesterday)).fetchone()
    finally:
        curs.close()
        conn.close()


def delete_oldest():
    """
    Deletes rates older than 200 days from the database
    """
    our_days = datetime.datetime.utcnow().date() - datetime.timedelta(days=200)
    conn = sqlite3.connect(CONF.db_name, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    curs = conn.cursor()
    query = "DELETE FROM rates WHERE date < '{}'".format(our_days)
    try:
        curs.execute(query)
        conn.commit()
    finally:
        curs.close()
        conn.close()
        LOG.info(query)


def persist_rate(price: float):
    """
    Adds either the current market price with the actual date to the database or updates today's average
    :param price: The price to be persisted
    """
    today = datetime.datetime.utcnow().date()
    conn = sqlite3.connect(CONF.db_name)
    curs = conn.cursor()
    current = curs.execute("SELECT count, price FROM rates WHERE date = '{}'".format(today)).fetchone()
    try:
        if not current:
            query = "INSERT INTO rates VALUES ('{}', 1, {})".format(today, price)
        else:
            avg = calculate_daily_average(current, price)
            query = "UPDATE rates SET count = count+1, price = {} WHERE date = '{}'".format(avg, today)
    finally:
        curs.execute(query)
        conn.commit()
        curs.close()
        conn.close()
        LOG.info(query)


def calculate_daily_average(current: [tuple], price: float):
    return (price + (current[0] * current[1])) / (current[0] + 1)


def write_control_file():
    with open(INSTANCE + '.pid', 'w') as file:
        file.write(str(os.getpid()) + ' ' + INSTANCE)


def write_average_file(avg: float):
    with open(INSTANCE + '.avg', 'w') as file:
        file.write(str(avg))


def update_rates():
    """
    Fetches the current market price, persists it and waits a minute.
    It is called from the main loop every hour
    If the current market price can not be fetched, then it writes the previous price with the actual datetime,
    preventing gaps in the database.
    """
    rate = get_current_price()
    if rate is None:
        rate = get_last_rate()[0]
    persist_rate(rate)
    sleep(60)


def update_average():
    delete_oldest()
    avg = get_average()[0]
    LOG.info(avg)
    write_average_file(avg)
    sleep(60)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        INSTANCE = os.path.basename(sys.argv[1])
    else:
        INSTANCE = os.path.basename(input('Filename with API Keys (mayer): ') or 'mayer')

    LOG = function_logger(logging.DEBUG, INSTANCE, logging.INFO)
    LOG.info('-------------------------------')
    write_control_file()
    CONF = ExchangeConfig()
    EXCHANGE = connect_to_exchange()

    init_database()

    while 1:
        NOW = datetime.datetime.utcnow()
        if NOW.minute == 1:
            update_rates()
            if NOW.hour == 0:
                update_average()
        sleep(55)
