#!/usr/bin/python3
import configparser
import datetime
import inspect
import json
import logging
import os
import random
import sqlite3
import sys
import time
from logging.handlers import RotatingFileHandler

import ccxt
import requests


class ExchangeConfig:
    def __init__(self):
        config = configparser.ConfigParser()
        config.read(INSTANCE + '.txt')
        self.backup_mayer = ''
        self.mayer_file = INSTANCE + '.avg'

        try:
            props = dict(config.items('config'))
            self.exchange = str(props['exchange']).strip('"').lower()
            self.db_name = str(props['db_name']).strip('"')
            if config.has_option(INSTANCE, 'backup_mayer'):
                self.backup_mayer = str(props['backup_mayer']).strip('"')
            if config.has_option(INSTANCE, 'mayer_file'):
                self.mayer_file = str(props['mayer_file']).strip('"')
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
        sleep_for(10, 12)
        get_current_price(tries + 1)


def init_database():
    conn = sqlite3.connect(CONF.db_name)
    curs = conn.cursor()
    curs.execute("CREATE TABLE IF NOT EXISTS rates (date TEXT NOT NULL PRIMARY KEY, count INTEGER, price FLOAT)")
    conn.commit()
    curs.close()
    conn.close()
    check_data()


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
    dd_days_ago = today - datetime.timedelta(days=199)
    conn = sqlite3.connect(CONF.db_name, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    curs = conn.cursor()
    try:
        return curs.execute(
            "SELECT AVG(price) FROM rates WHERE date BETWEEN '{}' AND '{}'".format(dd_days_ago, today)).fetchone()
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
        curs.execute(query)
        conn.commit()
    finally:
        curs.close()
        conn.close()
        LOG.info(query)


def calculate_daily_average(current: [tuple], price: float):
    return (price + (current[0] * current[1])) / (current[0] + 1)


def write_control_file():
    with open(INSTANCE + '.mid', 'w') as file:
        file.write(str(os.getpid()) + ' ' + INSTANCE)


def write_average_file(avg: float):
    with open(CONF.mayer_file, 'w') as file:
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
    sleep_for(60)


def update_average():
    avg = get_average()[0]
    LOG.info("-- NEW AVG %s", avg)
    write_average_file(avg)
    sleep_for(60)


def sleep_for(greater: int, less: int = None):
    if less:
        seconds = round(random.uniform(greater, less), 3)
    else:
        seconds = greater
    time.sleep(seconds)


def check_data():
    last_entry = get_last_date() if get_last_date() else '2021-01-01'
    last_date = datetime.datetime.strptime(last_entry, '%Y-%m-%d').date()
    if last_date < datetime.datetime.utcnow().date():
        if CONF.backup_mayer:
            complete_data(last_date)
        else:
            LOG.warning('Detected missing data, last data is from %s', last_date)


def complete_data(last_date: datetime.date):
    rates = fetch_rates()
    fill_missing_rates(rates, last_date)


def fetch_rates(tries: int = 0):
    try:
        req = requests.get(CONF.backup_mayer)
        if req.text:
            rates = json.loads(req.text)
            return rates[-200:]
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ReadTimeout,
            ValueError) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
    if tries < 4:
        sleep_for(4, 6)
        return fetch_rates(tries + 1)
    LOG.warning('Failed to fetch missing rates, giving up after 4 attempts')
    sys.exit(1)


def get_last_date():
    """
    Fetches the last date from the database
    :return: The fetched date
    """
    conn = sqlite3.connect(CONF.db_name, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    curs = conn.cursor()
    try:
        return curs.execute("SELECT MAX(date) FROM rates").fetchone()[0]
    finally:
        curs.close()
        conn.close()


def fill_missing_rates(rates: [], last_date: datetime.date):
    """
    Persists missing daily average prices
    """
    for entry in rates:
        if datetime.datetime.strptime(entry['Date'], '%Y-%m-%d').date() > last_date:
            add_entry(entry['Date'], entry['Price'])


def add_entry(date: datetime.date, price: float):
    conn = sqlite3.connect(CONF.db_name)
    curs = conn.cursor()
    try:
        query = "INSERT INTO rates VALUES ('{}', 1, {})".format(date, price)
        curs.execute(query)
        conn.commit()
    finally:
        LOG.info(query)
        curs.close()
        conn.close()


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
            update_average()
            if NOW.hour == 0:
                delete_oldest()
        sleep_for(55)
