#!/usr/bin/python3
import configparser
import datetime
import inspect
import logging
import os
import pickle
import random
import smtplib
import socket
import sys
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging.handlers import RotatingFileHandler
from time import sleep

import ccxt
import requests

MIN_ORDER_SIZE = 0.001
ORDER = None
EMAIL_SENT = False
EMAIL_ONLY = False
KEEP_ORDERS = False
STARTED = datetime.datetime.utcnow().replace(microsecond=0)
STOP_ERRORS = ['order_size', 'smaller', 'MIN_NOTIONAL', 'nsufficient', 'too low', 'not_enough', 'below', 'price', 'nvalid arg']
RETRY_MESSAGE = 'Got an error %s %s, retrying in about 5 seconds...'


class ExchangeConfig:
    def __init__(self):
        config = configparser.ConfigParser()
        config.read(INSTANCE + ".txt")

        try:
            props = config['config']
            self.bot_version = '0.1.14'
            self.exchange = str(props['exchange']).strip('"').lower()
            self.api_key = str(props['api_key']).strip('"')
            self.api_secret = str(props['api_secret']).strip('"')
            self.test = bool(str(props['test']).strip('"').lower() == 'true')
            self.pair = str(props['pair']).strip('"')
            self.symbol = str(props['symbol']).strip('"')
            self.crypto_quote_in_percent = abs(float(props['crypto_quote_in_percent']))
            self.auto_quote = bool(str(props['auto_quote']).strip('"').lower() == 'true')
            self.tolerance_in_percent = abs(float(props['tolerance_in_percent']))
            self.period_in_minutes = abs(float(props['period_in_minutes']))
            self.daily_report = bool(str(props['daily_report']).strip('"').lower() == 'true')
            self.trade_report = bool(str(props['trade_report']).strip('"').lower() == 'true')
            self.trade_trials = abs(int(props['trade_trials']))
            self.order_adjust_seconds = abs(int(props['order_adjust_seconds']))
            self.trade_advantage_in_percent = float(props['trade_advantage_in_percent'])
            currency = self.pair.split("/")
            self.base = currency[0]
            self.quote = currency[1]
            self.period_in_seconds = self.period_in_minutes * 60
            self.satoshi_factor = 0.00000001
            self.recipient_addresses = str(props['recipient_addresses']).strip('"').replace(' ', '').split(",")
            self.sender_address = str(props['sender_address']).strip('"')
            self.sender_password = str(props['sender_password']).strip('"')
            self.mail_server = str(props['mail_server']).strip('"')
            self.info = str(props['info']).strip('"')
            self.url = 'https://bitcoin-schweiz.ch/bot/'
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('Invalid configuration for ' + INSTANCE)


class Order:
    """
    Holds the relevant data of an order
    """
    __slots__ = 'id', 'price', 'amount', 'side', 'datetime'

    def __init__(self, ccxt_order):
        if 'id' in ccxt_order:
            self.id = ccxt_order['id']
        elif 'uuid' in ccxt_order:
            self.id = ccxt_order['uuid']

        if 'price' in ccxt_order:
            self.price = ccxt_order['price']
        elif 'info' in ccxt_order:
            self.price = ccxt_order['info']['price']

        if 'amount' in ccxt_order:
            self.amount = ccxt_order['amount']
        elif 'info' in ccxt_order:
            self.amount = ccxt_order['info']['amount']

        if 'side' in ccxt_order:
            self.side = ccxt_order['side']
        elif 'direction' in ccxt_order:
            self.side = ccxt_order['direction']
        elif 'info' in ccxt_order:
            self.side = ccxt_order['info']['direction']

        if 'datetime' in ccxt_order:
            self.datetime = ccxt_order['datetime']
        elif 'created_at' in ccxt_order:
            self.datetime = ccxt_order['created_at']
        elif 'info' in ccxt_order:
            self.datetime = ccxt_order['info']['created_at']

    def __str__(self):
        return "{} order id: {}, price: {}, amount: {}, created: {}".format(self.side, self.id, self.price,
                                                                            self.amount, self.datetime)


class Stats:
    """
    Holds the daily statistics in a ring memory (today plus the previous two)
    """

    def __init__(self, day_of_year: int, data: dict):
        self.days = []
        self.add_day(day_of_year, data)

    def add_day(self, day_of_year: int, data: dict):
        existing = self.get_day(day_of_year)
        if existing is None:
            data['day'] = day_of_year
            if len(self.days) > 2:
                self.days = sorted(self.days, key=lambda item: item['day'], reverse=True)  # desc
                self.days.pop()
            self.days.append(data)

    def get_day(self, day_of_year: int):
        matched = filter(lambda element: element['day'] == day_of_year, self.days)
        if matched:
            for day in matched:
                return day
        return None


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
                                 encoding=None, delay=0)
        fh.setLevel(file_level)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(lineno)4d - %(levelname)-8s - %(message)s'))
        logger.addHandler(fh)
    return logger


def fetch_mayer(tries: int = 0):
    try:
        req = requests.get('https://mayermultiple.info/current.json')
        if req.text:
            mayer = req.json()['data']
            return {'current': float(mayer['current_mayer_multiple']), 'average': float(mayer['average_mayer_multiple'])}
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ReadTimeout,
            ValueError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
    if tries < 4:
        sleep_for(4, 6)
        return fetch_mayer(tries + 1)
    LOG.warning('Failed to fetch Mayer multiple, giving up after 4 attempts')
    return None


def print_mayer():
    mayer = fetch_mayer()
    if mayer is None:
        return "Mayer multiple: {:>19} (n/a)".format('n/a')
    if mayer['current'] < mayer['average']:
        return "Mayer multiple: {:>19.2f} (< {:.2f} = BUY)".format(mayer['current'], mayer['average'])
    if mayer['current'] > 2.4:
        return "Mayer multiple: {:>19.2f} (> 2.4 = SELL)".format(mayer['current'])
    return "Mayer multiple: {:>19.2f} (> {:.2f} and < 2.4 = HOLD)".format(mayer['current'], mayer['average'])


def append_mayer(part: dict):
    text = print_mayer()
    part['mail'].append(text)
    part['csv'].append(text.replace('  ', '').replace(':', ':;'))


def daily_report(immediately: bool = False):
    """
    Creates a daily report email around 12:02 UTC or immediately if told to do so
    """
    global EMAIL_SENT

    if CONF.daily_report:
        now = datetime.datetime.utcnow()
        if immediately or datetime.datetime(2012, 1, 17, 12, 22).time() > now.time() \
                > datetime.datetime(2012, 1, 17, 12, 1).time() and EMAIL_SENT != now.day:
            subject = "Daily BalanceR report {}".format(INSTANCE)
            content = create_mail_content(True)
            filename_csv = INSTANCE + '.csv'
            write_csv(content['csv'], filename_csv)
            send_mail(subject, content['text'], filename_csv)
            EMAIL_SENT = now.day


def trade_report():
    """
    Creates a trade report email
    """
    if CONF.trade_report:
        subject = "RB Trade report {}".format(INSTANCE)
        content = create_mail_content()
        send_mail(subject, content['text'])


def create_mail_content(daily: bool = False):
    """
    Fetches and formats the data required for the daily report email
    :return: dict: text: str
    """
    if not daily:
        order = ORDER if ORDER else get_closed_order()
        trade_part = create_report_part_trade(order)
    performance_part = create_report_part_performance(daily)
    advice_part = create_report_part_advice()
    settings_part = create_report_part_settings()
    general_part = create_mail_part_general()

    if not daily:
        trade = ["Last trade", "----------", '\n'.join(trade_part['mail']), '\n\n']
    performance = ["Performance", "-----------",
                   '\n'.join(performance_part['mail']) + '\n* (change within 24 hours)', '\n\n']
    advice = ["Assessment / advice", "-------------------", '\n'.join(advice_part['mail']), '\n\n']
    settings = ["Your settings", "-------------", '\n'.join(settings_part['mail']), '\n\n']
    general = ["General", "-------", '\n'.join(general_part), '\n\n']

    text = '' if daily else '\n'.join(trade)

    if not CONF.info:
        text += '\n'.join(performance) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(general) + CONF.url + '\n'
    else:
        text += '\n'.join(performance) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(general) + CONF.info \
                + '\n\n' + CONF.url + '\n'

    csv = None if not daily else INSTANCE + ';' + str(datetime.datetime.utcnow().replace(microsecond=0)) + ' UTC;' + \
                                 (';'.join(performance_part['csv']) + ';' + ';'.join(advice_part['csv']) + ';' +
                                  ';'.join(settings_part['csv']) + ';' + CONF.info + '\n')

    return {'text': text, 'csv': csv}


def create_report_part_settings():
    return {'mail': ["Quote {} in %: {:>19}".format(CONF.base, CONF.crypto_quote_in_percent),
                     "Auto-Quote: {:>23}".format(str('Y' if CONF.auto_quote is True else 'N')),
                     "Tolerance in %: {:>19}".format(CONF.tolerance_in_percent),
                     "Period in minutes: {:>16}".format(CONF.period_in_minutes),
                     "Daily report: {:>21}".format(str('Y' if CONF.daily_report is True else 'N')),
                     "Trade report: {:>21}".format(str('Y' if CONF.trade_report is True else 'N')),
                     "Trade trials: {:>21}".format(CONF.trade_trials),
                     "Order adjust seconds: {:>15}".format(CONF.order_adjust_seconds),
                     "Trade advantage in %: {:>15}".format(CONF.trade_advantage_in_percent)],
            'csv': ["Quote {} in %:;{}".format(CONF.base, CONF.crypto_quote_in_percent),
                    "Auto-Quote:;{}".format(str('Y' if CONF.auto_quote is True else 'N')),
                    "Tolerance in %:;{}".format(CONF.tolerance_in_percent),
                    "Period in minutes:;{}".format(CONF.period_in_minutes),
                    "Daily report:;{}".format(str('Y' if CONF.daily_report is True else 'N')),
                    "Trade report:;{}".format(str('Y' if CONF.trade_report is True else 'N')),
                    "Trade trials:;{}".format(CONF.trade_trials),
                    "Order adjust seconds:;{}".format(CONF.order_adjust_seconds),
                    "Trade advantage in %:;{}".format(CONF.trade_advantage_in_percent)]}


def create_mail_part_general():
    general = ["Generated: {:>28}".format(str(datetime.datetime.utcnow().replace(microsecond=0)) + " UTC"),
               "Bot: {:>30}".format(INSTANCE + '@' + socket.gethostname()),
               "Version: {:>26}".format(CONF.bot_version),
               "Running since: {:>20} UTC".format(str(STARTED))]
    return general


def create_report_part_advice():
    part = {'mail': [], 'csv': []}
    append_mayer(part)
    return part


def create_report_part_performance(daily: bool):
    part = {'mail': [], 'csv': []}
    margin_balance = get_margin_balance()
    margin_balance_of_fiat = get_margin_balance_of_fiat()
    net_deposits = get_net_deposits()
    sleep_for(0, 1)
    append_performance(part, margin_balance['total'], net_deposits)
    wallet_balance = get_wallet_balance()
    sleep_for(0, 1)
    append_balances(part, margin_balance, margin_balance_of_fiat, wallet_balance, daily)
    return part


def create_report_part_trade(last_order: Order):
    part = {'mail': ["Executed: {:>17}".format(str(last_order))],
            'csv': ["Executed:;{}".format(str(last_order))]}
    return part


def send_mail(subject: str, text: str, attachment: str = None):
    recipients = ", ".join(CONF.recipient_addresses)
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = CONF.sender_address
    msg['To'] = recipients

    readable_part = MIMEMultipart('alternative')
    readable_part.attach(MIMEText(text, 'plain', 'utf-8'))
    html = '<html><body><pre style="font:monospace">' + text + '</pre></body></html>'
    readable_part.attach(MIMEText(html, 'html', 'utf-8'))
    msg.attach(readable_part)

    if attachment and os.path.isfile(attachment):
        part = MIMEBase('application', 'octet-stream')
        with open(attachment, "rb") as file:
            part.set_payload(file.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', "attachment; filename={}".format(attachment))
        msg.attach(part)

    server = smtplib.SMTP_SSL(CONF.mail_server, 465)
    # server.starttls()
    server.set_debuglevel(0)
    server.login(CONF.sender_address, CONF.sender_password)
    server.send_message(msg, None, None, mail_options=(), rcpt_options=())
    server.quit()
    LOG.info("Sent email to %s", recipients)


def append_performance(part: dict, margin_balance: float, net_deposits: float):
    """
    Calculates and appends the absolute and relative overall performance
    """
    if net_deposits is None:
        part['mail'].append("Net deposits {}: {:>17}".format(CONF.base, 'n/a'))
        part['mail'].append("Overall performance in {}: {:>7} (% n/a)".format(CONF.base, 'n/a'))
        part['csv'].append("Net deposits {}:;{}".format(CONF.base, 'n/a'))
        part['csv'].append("Overall performance in {}:;{};% n/a".format(CONF.base, 'n/a'))
    else:
        part['mail'].append("Net deposits {}: {:>20.4f}".format(CONF.base, net_deposits))
        part['csv'].append("Net deposits {}:;{:.4f}".format(CONF.base, net_deposits))
        absolute_performance = margin_balance - net_deposits
        if net_deposits > 0 and absolute_performance != 0:
            relative_performance = round(100 / (net_deposits / absolute_performance), 2)
            part['mail'].append("Overall performance in {}: {:>+10.4f} ({:+.2f}%)".format(CONF.base,
                                                                                          absolute_performance,
                                                                                          relative_performance))
            part['csv'].append("Overall performance in {}:;{:.4f};{:+.2f}%".format(CONF.base,
                                                                                   absolute_performance,
                                                                                   relative_performance))
        else:
            part['mail'].append("Overall performance in {}: {:>+10.4f} (% n/a)".format(CONF.base, absolute_performance))
            part['csv'].append("Overall performance in {}:;{:.4f};% n/a".format(CONF.base, absolute_performance))


def append_balances(part: dict, margin_balance: dict, margin_balance_of_fiat: dict, wallet_balance: float, daily: bool):
    """
    Appends liquidation price, wallet balance, margin balance (including stats), used margin and leverage information
    """
    if wallet_balance is None:
        part['mail'].append("Wallet balance {}: {:>15}".format(CONF.base, 'n/a'))
        part['csv'].append("Wallet balance {}:;n/a".format(CONF.base))
    else:
        part['mail'].append("Wallet balance {}: {:>18.4f}".format(CONF.base, wallet_balance))
        part['csv'].append("Wallet balance {}:;{:.4f}".format(CONF.base, wallet_balance))
    price = get_current_price()
    if CONF.exchange == 'bitmex':
        today = calculate_daily_statistics(margin_balance['total'], margin_balance_of_fiat['total'], price, daily)
        append_margin_change(part, today)
    else:
        cb = get_crypto_balance()
        crypto_total = cb['total'] if cb else 0
        fb = get_fiat_balance()
        fiat_total = fb['total'] if fb else 0
        today = calculate_daily_statistics(crypto_total, fiat_total, price, daily)
        append_balance_change(part, today)
    append_net_change(part, today)
    append_price_change(part, today, price)
    used_margin = calculate_used_margin_percentage(margin_balance)
    part['mail'].append("Used margin: {:>23.2f}%".format(used_margin))
    part['csv'].append("Used margin:;{:.2f}%".format(used_margin))
    if CONF.exchange == 'kraken':
        actual_leverage = get_margin_leverage()
        part['mail'].append("Actual leverage: {:>19.2f}%".format(actual_leverage))
        part['csv'].append("Actual leverage:;{:.2f}%".format(used_margin))
    elif CONF.exchange == 'bitmex':
        actual_leverage = get_margin_leverage()
        part['mail'].append("Actual leverage: {:>19.2f}x".format(actual_leverage))
        part['csv'].append("Actual leverage:;{:.2f}x".format(actual_leverage))
    else:
        part['mail'].append("Actual leverage: {:>19}".format('n/a'))
        part['csv'].append("Actual leverage:;{}".format('n/a'))
    used_balance = get_used_balance()
    if used_balance is None:
        used_balance = 'n/a'
    part['mail'].append("Position {}: {:>22.2f}".format(CONF.quote, used_balance))
    part['csv'].append("Position {}:;{:.2}".format(CONF.quote, used_balance))


def append_margin_change(part: dict, today: dict):
    """
    Appends margin changes
    """
    m_bal = "Margin balance {}: {:>18.4f}".format(CONF.base, today['mBal'])
    if 'mBalChan24' in today:
        change = "{:+.2f}%".format(today['mBalChan24'])
        m_bal += " ("
        m_bal += change
        m_bal += ")*"
    else:
        change = "% n/a"
    part['mail'].append(m_bal)
    part['csv'].append("Margin balance {}:;{:.4f};{}".format(CONF.base, today['mBal'], change))

    fm_bal = "Margin balance {}: {:>16.2f}".format(CONF.quote, today['fmBal'])
    if 'fmBalChan24' in today:
        change = "{:+.2f}%".format(today['fmBalChan24'])
        fm_bal += "   ("
        fm_bal += change
        fm_bal += ")*"
    else:
        change = "% n/a"
    part['mail'].append(fm_bal)
    part['csv'].append("Margin balance {}:;{:.2f};{}".format(CONF.quote, today['fmBal'], change))


def append_balance_change(part: dict, today: dict):
    """
    Appends balance changes
    """
    m_bal = "Balance {}: {:>25.4f}".format(CONF.base, today['mBal'])
    if 'mBalChan24' in today:
        change = "{:+.2f}%".format(today['mBalChan24'])
        m_bal += " ("
        m_bal += change
        m_bal += ")*"
    else:
        change = "% n/a"
    part['mail'].append(m_bal)
    part['csv'].append("Balance {}:;{:.4f};{}".format(CONF.base, today['mBal'], change))

    fm_bal = "Balance {}: {:>23.2f}".format(CONF.quote, today['fmBal'])
    if 'fmBalChan24' in today:
        change = "{:+.2f}%".format(today['fmBalChan24'])
        fm_bal += "   ("
        fm_bal += change
        fm_bal += ")*"
    else:
        change = "% n/a"
    part['mail'].append(fm_bal)
    part['csv'].append("Balance {}:;{:.2f};{}".format(CONF.quote, today['fmBal'], change))


def append_net_change(part: dict, today: dict):
    if 'mBalChan24' in today and 'fmBalChan24' in today:
        change = "{:+.2f}".format(today['mBalChan24'] + today['fmBalChan24'])
    else:
        change = "% n/a"
    net_result = "Net result: {:>25}%*".format(change)
    part['mail'].append(net_result)
    part['csv'].append("Net result:;{}%".format(change))


def append_price_change(part: dict, today: dict, price: float):
    """
    Appends price changes
    """
    rate = "{} price {}: {:>21.2f}".format(CONF.base, CONF.quote, price)
    if 'priceChan24' in today:
        change = "{:+.2f}%".format(today['priceChan24'])
        rate += "   ("
        rate += change
        rate += ")*"
    else:
        change = "% n/a"
    part['mail'].append(rate)
    part['csv'].append("{} price {}:;{:.2f};{}".format(CONF.base, CONF.quote, price, change))


def calculate_daily_statistics(m_bal: float, fm_bal: float, price: float, update_stats: bool):
    """
    Calculates, updates and persists the change in the margin balance compared with yesterday
    :param m_bal: todays margin balance
    :param fm_bal: todays fiat margin balance
    :param price: the current rate
    :param update_stats: update and persists the statistic values
    :return: todays statistics including price and margin balance changes compared with 24 hours ago
    """
    stats = load_statistics()

    today = {'mBal': m_bal, 'fmBal': fm_bal, 'price': price}
    if stats is None:
        if update_stats and datetime.datetime.utcnow().time() > datetime.datetime(2012, 1, 17, 12, 1).time():
            stats = Stats(int(datetime.date.today().strftime("%Y%j")), today)
            persist_statistics(stats)
        return today

    if update_stats and datetime.datetime.utcnow().time() > datetime.datetime(2012, 1, 17, 12, 1).time():
        stats.add_day(int(datetime.date.today().strftime("%Y%j")), today)
        persist_statistics(stats)
    before_24h = stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 1)
    if before_24h:
        today['mBalChan24'] = round((today['mBal'] / before_24h['mBal'] - 1) * 100, 2)
        if 'fmBal' in before_24h:
            today['fmBalChan24'] = round((today['fmBal'] / before_24h['fmBal'] - 1) * 100, 2)
        if 'price' in before_24h:
            today['priceChan24'] = round((today['price'] / before_24h['price'] - 1) * 100, 2)
    return today


def load_statistics():
    stats_file = INSTANCE + '.pkl'
    if os.path.isfile(stats_file):
        with open(stats_file, "rb") as file:
            return pickle.load(file)
    return None


def persist_statistics(stats: Stats):
    stats_file = INSTANCE + '.pkl'
    with open(stats_file, "wb") as file:
        pickle.dump(stats, file)


def calculate_used_margin_percentage(bal=None):
    """
    Calculates the used margin percentage
    """
    if bal is None:
        bal = get_margin_balance()
        if bal['total'] <= 0:
            return 0
    return float(100 - (bal['free'] / bal['total']) * 100)


def write_csv(content: str, filename_csv: str):
    if not is_already_written(filename_csv):
        write_mode = 'a' if int(datetime.date.today().strftime("%j")) != 1 else 'w'
        with open(filename_csv, write_mode) as file:
            file.write(content)


def is_already_written(filename_csv: str):
    if os.path.isfile(filename_csv):
        with open(filename_csv, 'r') as file:
            return str(datetime.date.today().isoformat()) in list(file)[-1]
    return False


def get_margin_balance():
    """
    Fetches the margin balance (of crypto) in fiat (free and total)
    return: balance of crypto in fiat
    """
    try:
        if CONF.exchange == 'kraken':
            bal = EXCHANGE.private_post_tradebalance({'asset': CONF.base})['result']
            bal['free'] = float(bal['mf'])
            bal['total'] = float(bal['e'])
            bal['used'] = float(bal['m'])
        else:
            bal = get_crypto_balance()
        return bal

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_margin_balance()


def get_margin_balance_of_fiat():
    """
    Fetches the margin balance (of fiat) in fiat (free and total)
    return: balance of fiat in fiat
    """
    try:
        if CONF.exchange == 'kraken':
            bal = EXCHANGE.private_post_tradebalance({'asset': CONF.quote})['result']
            bal['free'] = float(bal['mf'])
            bal['total'] = float(bal['e'])
            bal['used'] = float(bal['m'])
        elif CONF.exchange == 'bitmex':
            pos = get_position_info()
            bal = {'total': pos['homeNotional'] * pos['lastPrice']}
        else:
            bal = get_fiat_balance()
        return bal

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_margin_balance_of_fiat()


def get_margin_leverage():
    """
    Fetch the leverage
    """
    try:
        if CONF.exchange == 'bitmex':
            return EXCHANGE.fetch_balance()['info'][0]['marginLeverage']
        if CONF.exchange == 'kraken':
            result = EXCHANGE.private_post_tradebalance()['result']
            if hasattr(result, 'ml'):
                return float(result['ml'])
            return 0
        LOG.error("get_margin_leverage() not yet implemented for %s", CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_margin_leverage()


def get_net_deposits():
    """
    Get deposits and withdraws to calculate the net deposits in crypto.
    return: net deposits
    """
    try:
        currency = CONF.base if CONF.base != 'BTC' else 'XBt'
        if CONF.exchange == 'bitmex':
            result = EXCHANGE.private_get_user_wallet({'currency': currency})
            return (result['deposited'] - result['withdrawn']) * CONF.satoshi_factor
        if CONF.exchange == 'kraken':
            net_deposits = 0
            deposits = EXCHANGE.fetch_deposits(CONF.base)
            for deposit in deposits:
                net_deposits += deposit['amount']
            ledgers = EXCHANGE.private_post_ledgers({'asset': currency, 'type': 'withdrawal'})['result']['ledger']
            for withdrawal_id in ledgers:
                net_deposits += float(ledgers[withdrawal_id]['amount'])
            return net_deposits
        LOG.error("get_net_deposit() not yet implemented for %s", CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_net_deposits()


def get_wallet_balance():
    """
    Fetch the wallet balance in crypto
    """
    try:
        if CONF.exchange == 'bitmex':
            return EXCHANGE.fetch_balance()['info'][0]['walletBalance'] * CONF.satoshi_factor
        if CONF.exchange == 'kraken':
            asset = CONF.base if CONF.base != 'BTC' else 'XBt'
            return float(EXCHANGE.private_post_tradebalance({'asset': asset})['result']['tb'])
        if CONF.exchange == 'liquid':
            result = EXCHANGE.private_get_accounts_balance()
            if result:
                for bal in result:
                    if bal['currency'] == CONF.base:
                        return float(bal['balance'])
        else:
            LOG.error("get_wallet_balance() is not implemented for %s", CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_wallet_balance()


def get_open_orders():
    """
    Gets open orders
    :return: [Order]
    """
    try:
        if CONF.exchange == 'paymium':
            orders = EXCHANGE.private_get_user_orders({'active': True})
        elif CONF.exchange == 'binance':
            orders = EXCHANGE.fetch_open_orders(CONF.pair, since=None, limit=20)
        else:
            orders = EXCHANGE.fetch_open_orders(CONF.pair, since=None, limit=20, params={'reverse': True})
        if orders:
            open_orders = []
            for order in orders:
                open_orders.append(Order(order))
            return open_orders
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_open_orders()


def get_closed_order():
    """
    Gets the last closed order
    :return: Order
    """
    try:
        result = EXCHANGE.fetch_closed_orders(CONF.pair, since=None, limit=2, params={'reverse': True})
        if result:
            orders = sorted(result, key=lambda order: order['datetime'])
            last_order = Order(orders[-1])
            LOG.info('Last %s', str(last_order))
            return last_order
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_closed_order()


def get_current_price(attempts: int = 0, limit: int = None):
    """
    Fetches the current BTC/USD exchange rate
    In case of failure, the function calls itself again until success
    :return: int current market price
    """
    try:
        price = EXCHANGE.fetch_ticker(CONF.pair)['bid']
        if not price:
            LOG.warning('Price was None')
            sleep_for(1, 2)
            return get_current_price(attempts, limit)
        return int(price)

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.info('Got an error %s %s, retrying in 5 seconds...', type(error).__name__, str(error.args))
        attempts += 1
        if not limit or attempts < limit:
            sleep_for(4, 6)
            return get_current_price(attempts, limit)
    return 0


def connect_to_exchange():
    exchanges = {}
    for id in ccxt.exchanges:
        exchange = getattr(ccxt, id)
        exchanges[id] = exchange

    exchange = exchanges[CONF.exchange]({
        'enableRateLimit': True,
        'apiKey': CONF.api_key,
        'secret': CONF.api_secret,
        # 'verbose': True,
    })

    if hasattr(CONF, 'test') & CONF.test:
        if 'test' in exchange.urls:
            exchange.urls['api'] = exchange.urls['test']
        else:
            raise SystemExit('Test not supported by {}'.format(CONF.exchange))

    return exchange


def write_control_file():
    with open(INSTANCE + '.pid', 'w') as file:
        file.write(str(os.getpid()) + ' ' + INSTANCE)


def do_buy(quote: float, reference_price: float):
    """
    Buys at market price lowered by configured percentage or at market price if not successful
    within the configured trade attempts
    :return: Order
    """
    i = 1
    while i <= CONF.trade_trials:
        buy_price = calculate_buy_price(get_current_price())
        order_size = calculate_buy_order_size(quote, reference_price, buy_price)
        if order_size is None:
            LOG.info("Buy order size below minimum")
            return None
        order = create_buy_order(buy_price, order_size)
        if order is None:
            LOG.warning("Could not create buy order over %s", order_size)
            return None
        sleep(CONF.order_adjust_seconds)
        order_status = fetch_order_status(order.id)
        if order_status in ['open', 'active']:
            cancel_order(order)
            i += 1
            daily_report()
        else:
            return order
    order_size = calculate_buy_order_size(quote, reference_price, get_current_price())
    if order_size is None:
        return None
    return create_market_buy_order(order_size)


def calculate_buy_price(price: float):
    """
    Calculates the buy price based on the market price lowered by configured percentage
    :param price: market price
    :return: buy price
    """
    return round(price / (1 + CONF.trade_advantage_in_percent / 100), 1)


def calculate_buy_order_size(reference_quote: float, reference_price: float, actual_price: float):
    """
    Calculates the buy order size. Minus 1% for fees.
    :param reference_quote
    :param reference_price
    :param actual_price:
    :return: the calculated buy_order_size in crypto or None
    """
    quote = reference_quote * (reference_price / actual_price)
    size = TOTAL_BALANCE_IN_CRYPTO / (100 / quote) / 1.01
    if size > MIN_ORDER_SIZE:
        return round(size - 0.000000006, 8)
    LOG.info("Order size %f < %f", size, MIN_ORDER_SIZE)
    return None


def do_sell(quote: float, reference_price: float):
    """
    Sells at market price raised by configured percentage or at market price if not successful
    within the configured trade attempts
    :return: Order
    """
    i = 1
    while i <= CONF.trade_trials:
        sell_price = calculate_sell_price(get_current_price())
        order_size = calculate_sell_order_size(quote, reference_price, sell_price)
        if order_size is None:
            LOG.info("Sell order size below minimum")
            return None
        order = create_sell_order(sell_price, order_size)
        if order is None:
            LOG.warning("Could not create sell order over %s", order_size)
            return None
        sleep(CONF.order_adjust_seconds)
        order_status = fetch_order_status(order.id)
        if order_status in ['open', 'active']:
            cancel_order(order)
            i += 1
            daily_report()
        else:
            return order
    order_size = calculate_sell_order_size(quote, reference_price, get_current_price())
    if order_size is None:
        return None
    return create_market_sell_order(order_size)


def calculate_sell_price(price: float):
    """
    Calculates the sell price based on the market price raised by configured percentage
    :param price: market price
    :return: sell price
    """
    return round(price * (1 + CONF.trade_advantage_in_percent / 100), 1)


def calculate_sell_order_size(reference_quote: float, reference_price: float, actual_price: float):
    """
    Calculates the sell order size. Minus 1% for fees.
    :param reference_quote
    :param reference_price
    :param actual_price:
    :return: the calculated sell_order_size or None
    """
    quote = reference_quote / (reference_price / actual_price)
    size = TOTAL_BALANCE_IN_CRYPTO / (100 / quote) / 1.01
    return round(size - 0.000000006, 8) if size > MIN_ORDER_SIZE else None


def fetch_order_status(order_id: str):
    """
    Fetches the status of an order
    input: id of an order
    output: status of the order (open, closed)
    """
    try:
        if CONF.exchange == 'paymium':
            order = EXCHANGE.private_get_user_orders_uuid({'uuid': order_id})
            if order:
                return order['state']
            LOG.warning('Order with id %s not found', order_id)
            return 'unknown'
        if CONF.exchange == 'binance':
            order = EXCHANGE.fetch_order(order_id, symbol=CONF.pair)
            if order:
                return order['status']
            LOG.warning('Order with id %s not found', order_id)
            return 'unknown'
        return EXCHANGE.fetch_order_status(order_id)

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return fetch_order_status(order_id)


def cancel_all_open_orders():
    if not KEEP_ORDERS:
        orders = get_open_orders()
        if orders:
            for order in orders:
                cancel_order(order)


def cancel_order(order: Order):
    """
    Cancels an order
    """
    try:
        if order:
            status = fetch_order_status(order.id)
            if status in ['open', 'active']:
                EXCHANGE.cancel_order(order.id)
                LOG.info('Canceled %s', str(order))
            else:
                LOG.warning('Order to be canceled %s was in state %s', str(order), status)

    except ccxt.OrderNotFound as error:
        LOG.error('Order to be canceled not found %s %s', str(order), str(error.args))
        return
    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        cancel_order(order)


def create_sell_order(price: float, amount_crypto: float):
    """
    Creates a sell order
    :param price: float price in fiat
    :param amount_crypto: float amount in crypto
    :return: Order
    """
    if amount_crypto is None:
        return None
    try:
        if CONF.exchange == 'bitmex':
            price = round(price * 2) / 2
            order_size = round(price * amount_crypto)
            new_order = EXCHANGE.create_limit_sell_order(CONF.pair, order_size, price)
        else:
            new_order = EXCHANGE.create_limit_sell_order(CONF.pair, amount_crypto, price)
        norder = Order(new_order)
        LOG.info('Created %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError, ccxt.InvalidOrder) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            not_selling = 'Order submission not possible - not selling %s'
            if CONF.exchange == 'bitmex':
                LOG.warning(not_selling, order_size)
            else:
                LOG.warning(not_selling, amount_crypto)
            return None
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_sell_order(price, amount_crypto)


def create_buy_order(price: float, amount_crypto: float):
    """
    Creates a buy order
    :param price: float current price of crypto
    :param amount_crypto: float the order volume
    """
    if amount_crypto is None:
        return None
    try:
        if CONF.exchange == 'bitmex':
            price = round(price * 2) / 2
            order_size = round(price * amount_crypto)
            new_order = EXCHANGE.create_limit_buy_order(CONF.pair, order_size, price)
        elif CONF.exchange == 'kraken':
            new_order = EXCHANGE.create_limit_buy_order(CONF.pair, amount_crypto, price, {'oflags': 'fcib'})
        else:
            new_order = EXCHANGE.create_limit_buy_order(CONF.pair, amount_crypto, price)

        norder = Order(new_order)
        LOG.info('Created %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError, ccxt.InvalidOrder) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            not_buying = 'Order submission not possible - not buying %s'
            if CONF.exchange == 'bitmex':
                LOG.warning(not_buying, order_size)
            else:
                LOG.warning(not_buying, amount_crypto)
            return None
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_buy_order(price, amount_crypto)


def create_market_sell_order(amount_crypto: float):
    """
    Creates a market sell order
    input: amount_crypto to be sold
    """
    try:
        if CONF.exchange == 'bitmex':
            amount_fiat = round(amount_crypto * get_current_price())
            new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_fiat)
        else:
            new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_crypto)
        norder = Order(new_order)
        LOG.info('Created market %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError, ccxt.InvalidOrder) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.warning('Order submission not possible - not selling %s', amount_crypto)
            return None
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_market_sell_order(amount_crypto)


def create_market_buy_order(amount_crypto: float):
    """
    Creates a market buy order
    input: amount_crypto to be bought
    """
    try:
        if CONF.exchange == 'bitmex':
            amount_fiat = round(amount_crypto * get_current_price())
            new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_fiat)
        elif CONF.exchange == 'kraken':
            new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_crypto, {'oflags': 'fcib'})
        else:
            new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_crypto)
        norder = Order(new_order)
        LOG.info('Created market %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError, ccxt.InvalidOrder) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.warning('Order submission not possible - not buying %s', amount_crypto)
            return None
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_market_buy_order(amount_crypto)


def get_used_balance():
    """
    Fetch the used balance in fiat.
    output: float
    """
    try:
        if CONF.exchange == 'bitmex':
            position = EXCHANGE.private_get_position()
            if not position:
                return None
            return float(position[0]['currentQty'])
        if CONF.exchange == 'kraken':
            result = EXCHANGE.private_post_tradebalance()['result']
            return float(result['e']) - float(result['mf'])
        return float(get_crypto_balance()['used'] * get_current_price())

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_used_balance()


def get_crypto_balance():
    """
    Fetch the balance in crypto.
    output: balance (used,free,total)
    """
    return get_balance(CONF.base)


def get_fiat_balance():
    """
    Fetch the balance in fiat.
    output: balance (used,free,total)
    """
    return get_balance(CONF.quote)


def get_balance(currency: str):
    try:
        if CONF.exchange != 'liquid':
            bal = EXCHANGE.fetch_balance()[currency]
            if bal['used'] is None:
                bal['used'] = 0
            if bal['free'] is None:
                bal['free'] = 0
            return bal

        # TODO check
        result = EXCHANGE.private_get_trading_accounts()
        if result:
            for acc in result:
                if acc['currency_pair_code'] == CONF.symbol and float(acc['margin']) > 0:
                    return {'used': float(acc['margin']), 'free': float(acc['free_margin']),
                            'total': float(acc['equity'])}

        # no position => return wallet balance
        result = EXCHANGE.private_get_accounts_balance()
        if result:
            for bal in result:
                if bal['currency'] == currency:
                    return {'used': 0, 'free': float(bal['balance']), 'total': float(bal['balance'])}
        LOG.warning('Could not get balance for liquid')
        return None

    except KeyError:
        LOG.warning('No %s balance found', currency)
        return {'used': 0, 'free': 0, 'total': 0}

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_balance(currency)


def get_position_info():
    try:
        if CONF.exchange == 'bitmex':
            position = EXCHANGE.private_get_position()
            if position:
                return position[0]
            return None
        LOG.error("get_postion_info() is not implemented for %s", CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_position_info()


def set_leverage(new_leverage: float):
    try:
        if CONF.exchange == 'bitmex':
            EXCHANGE.private_post_position_leverage({'symbol': CONF.symbol, 'leverage': new_leverage})
            LOG.info('Setting leverage to %s', new_leverage)
        else:
            LOG.error("set_leverage() not yet implemented for %s", CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.warning('Insufficient available balance - not setting leverage to %s', new_leverage)
            return None
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return set_leverage(new_leverage)


def sleep_for(greater: int, less: int = None):
    if less:
        seconds = round(random.uniform(greater, less), 3)
    else:
        seconds = greater
    time.sleep(seconds)


def do_post_trade_action():
    if ORDER:
        LOG.info('Filled %s', str(ORDER))
        trade_report()


def meditate(quote: float, price: float):
    if CONF.auto_quote:
        mm = fetch_mayer()
        if mm is None:
            return None
        target_quote = CONF.crypto_quote_in_percent / mm['current']
        target_quote = 10 if target_quote < 10 else 90 if target_quote > 90 else target_quote
    else:
        target_quote = CONF.crypto_quote_in_percent
    if quote < target_quote - CONF.tolerance_in_percent:
        return do_buy(target_quote - quote, price)
    if quote > target_quote + CONF.tolerance_in_percent:
        return do_sell(quote - target_quote, price)
    return None


def calculate_quote():
    crypto_quote = (CRYPTO_BALANCE / TOTAL_BALANCE_IN_CRYPTO) * 100 if CRYPTO_BALANCE > 0 else 0
    LOG.info('%s total/crypto quote %f/%f %f @ %d', CONF.base, TOTAL_BALANCE_IN_CRYPTO, CRYPTO_BALANCE, crypto_quote, PRICE)
    return crypto_quote


if __name__ == '__main__':
    print('Starting BalanceR Bot')
    print('ccxt version:', ccxt.__version__)

    if len(sys.argv) > 1:
        INSTANCE = os.path.basename(sys.argv[1])
        if len(sys.argv) > 2:
            if sys.argv[2] == '-eo':
                EMAIL_ONLY = True
            elif sys.argv[2] == '-keep':
                KEEP_ORDERS = True
    else:
        INSTANCE = os.path.basename(input('Filename with API Keys (config): ') or 'config')

    LOG_FILENAME = 'log' + os.path.sep + INSTANCE
    if not os.path.exists('log'):
        os.makedirs('log')

    LOG = function_logger(logging.DEBUG, LOG_FILENAME, logging.INFO)
    LOG.info('-----------------------')
    CONF = ExchangeConfig()
    LOG.info('BalanceR version: %s', CONF.bot_version)

    EXCHANGE = connect_to_exchange()

    if EMAIL_ONLY:
        daily_report(True)
        sys.exit(0)

    write_control_file()

    if CONF.exchange == 'kraken':
        MIN_ORDER_SIZE = 0.002
    elif CONF.exchange == 'bitmex':
        MIN_ORDER_SIZE = 0.0001

    if CONF.exchange == 'bitmex':
        set_leverage(0)

    if not KEEP_ORDERS:
        cancel_all_open_orders()

    while 1:

        if CONF.exchange == 'bitmex':
            POS = get_position_info()
            # aka margin balance
            TOTAL_BALANCE_IN_CRYPTO = get_crypto_balance()['total']
            PRICE = POS['lastPrice']
            if POS['avgEntryPrice']:
                CRYPTO_BALANCE = (abs(POS['foreignNotional']) / POS['avgEntryPrice'] * PRICE) / POS['avgEntryPrice']
            else:
                CRYPTO_BALANCE = 0
        else:
            CRYPTO_BALANCE = get_crypto_balance()['total']
            FIAT_BALANCE = get_fiat_balance()['total']
            PRICE = get_current_price()
            TOTAL_BALANCE_IN_CRYPTO = CRYPTO_BALANCE + (FIAT_BALANCE / PRICE)

        ORDER = meditate(calculate_quote(), PRICE)
        do_post_trade_action()
        daily_report()
        sleep_for(CONF.period_in_seconds)
