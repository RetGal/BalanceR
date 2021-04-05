#!/usr/bin/python3
import calendar
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
BAL = {'cryptoBalance': 0, 'totalBalanceInCrypto': 0, 'price': 0}
EMAIL_SENT = False
EMAIL_ONLY = False
KEEP_ORDERS = False
STARTED = datetime.datetime.utcnow().replace(microsecond=0)
STOP_ERRORS = ['order_size', 'smaller', 'MIN_NOTIONAL', 'nsufficient', 'too low', 'not_enough', 'below', 'price', 'nvalid arg']
ACCOUNT_ERRORS = ['account has been disabled', 'key is disabled', 'authentication failed', 'permission denied']
RETRY_MESSAGE = 'Got an error %s %s, retrying in about 5 seconds...'


class ExchangeConfig:
    def __init__(self):
        self.mm_quotes = ['OFF', 'MM', 'MMRange']
        self.report_cadences = ['T', 'D', 'M', 'A']
        config = configparser.ConfigParser(interpolation=None)
        config.read(INSTANCE + ".txt")

        try:
            props = config['config']
            self.bot_version = '0.7.4'
            self.exchange = str(props['exchange']).strip('"').lower()
            self.api_key = str(props['api_key']).strip('"')
            self.api_secret = str(props['api_secret']).strip('"')
            self.test = bool(str(props['test']).strip('"').lower() == 'true')
            self.pair = str(props['pair']).strip('"')
            self.symbol = str(props['symbol']).strip('"')
            self.net_deposits_in_base_currency = abs(float(props['net_deposits_in_base_currency']))
            self.crypto_quote_in_percent = abs(float(props['crypto_quote_in_percent']))
            self.auto_quote = str(props['auto_quote']).strip('"')
            self.mm_quote_0 = abs(float(props['mm_quote_0']))
            self.mm_quote_100 = abs(float(props['mm_quote_100']))
            self.tolerance_in_percent = abs(float(props['tolerance_in_percent']))
            self.period_in_minutes = abs(float(props['period_in_minutes']))
            self.report = str(props['report']).strip('"')
            self.trade_trials = abs(int(props['trade_trials']))
            self.order_adjust_seconds = abs(int(props['order_adjust_seconds']))
            self.trade_advantage_in_percent = float(props['trade_advantage_in_percent'])
            self.stop_buy = bool(str(props['stop_buy']).strip('"').lower() == 'true')
            self.max_crypto_quote_in_percent = abs(float(props['max_crypto_quote_in_percent']))
            currency = self.pair.split("/")
            self.base = currency[0]
            self.quote = currency[1]
            if self.auto_quote not in self.mm_quotes:
                raise SystemExit("Invalid value for auto_quote: '{}' possible values are: {}"
                                 .format(self.auto_quote, self.mm_quotes))
            if self.report not in self.report_cadences:
                raise SystemExit("Invalid value for report: '{}' possible values are: {}"
                                 .format(self.report, self.report_cadences))
            self.period_in_seconds = round(self.period_in_minutes * 60)
            self.satoshi_factor = 0.00000001
            self.recipient_addresses = str(props['recipient_addresses']).strip('"').replace(' ', '').split(",")
            self.sender_address = str(props['sender_address']).strip('"')
            self.sender_password = str(props['sender_password']).strip('"')
            self.mail_server = str(props['mail_server']).strip('"')
            self.info = str(props['info']).strip('"')
            self.url = 'https://bitcoin-schweiz.ch/bot/'
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('Invalid configuration for ' + INSTANCE) from KeyError


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
        return "{} order id: {}, price: {}, amount: {}, created: {}".format(self.side, self.id, round(self.price),
                                                                            self.amount, self.datetime)


class Stats:
    """
    Holds the daily statistics in a ring memory (today plus the previous two)
    """
    def __init__(self, day_of_year: int = None, data: dict = None):
        self.days = []
        if day_of_year and data:
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
                                 encoding=None, delay=False)
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


def evaluate_mayer(mayer: dict = None):
    if mayer is None:
        return 'n/a'
    if mayer['current'] < mayer['average']:
        return 'BUY'
    if mayer['current'] > 2.4:
        return 'SELL'
    return 'HOLD'


def append_mayer(part: dict):
    mayer = fetch_mayer()
    advice = evaluate_mayer(mayer)
    if mayer is None:
        part['mail'].append("Mayer multiple: {:>19} (n/a)".format(advice))
        part['csv'].append("Mayer multiple:;n/a")
        return
    if advice == 'HOLD':
        part['mail'].append("Mayer multiple: {:>19.2f} (< {:.2f} = {})".format(mayer['current'], 2.4, advice))
    elif advice == 'BUY':
        part['mail'].append("Mayer multiple: {:>19.2f} (< {:.2f} = {})".format(mayer['current'], mayer['average'], advice))
    else:
        part['mail'].append("Mayer multiple: {:>19.2f} (> {:.2f} = {})".format(mayer['current'], 2.4, advice))
    part['csv'].append("Mayer multiple:;{:.2f}".format(mayer['current']))


def get_mayer():
    btc_usd = get_btc_usd_pair()
    mayer = calculate_mayer(get_current_price(btc_usd, 0, 3))
    if mayer is None:
        mayer = fetch_mayer()
    return mayer


def calculate_mayer(price: float):
    average = read_daily_average()
    if average:
        return {'current': price/average}
    return None


def read_daily_average():
    mayer_file = "mayer.avg"
    if mayer_file and os.path.isfile(mayer_file):
        with open("mayer.avg", "rt") as file:
            return float(file.read())
    return None


def daily_report(immediately: bool = False):
    """
    Creates a daily report email around 12:02 UTC or immediately if told to do so
    """
    global EMAIL_SENT

    now = datetime.datetime.utcnow()
    if immediately or datetime.datetime(2012, 1, 17, 12, 22).time() > now.time() \
            > datetime.datetime(2012, 1, 17, 12, 1).time() and EMAIL_SENT != now.day:
        content = create_mail_content(True)
        filename_csv = INSTANCE + '.csv'
        write_csv(content['csv'], filename_csv)
        if immediately or is_due_date(datetime.date.today()):
            cadence = "Daily" if CONF.report in ['T', 'D'] else "Monthly" if CONF.report == 'M' else 'Annual'
            subject = "{} BalanceR report {}".format(cadence, INSTANCE)
            send_mail(subject, content['text'], filename_csv)
        EMAIL_SENT = now.day


def is_due_date(today: datetime.date):
    if CONF.report in ['T', 'D']:
        return True
    if today.day == calendar.monthrange(today.year, today.month)[1]:
        if CONF.report == 'M':
            return True
        if today.month == 12:
            return True
    return False


def trade_report():
    """
    Creates a trade report email
    """
    if CONF.report == 'T':
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
                   '\n'.join(performance_part['mail']) + '\n* (change since yesterday noon)', '\n\n']
    advice = ["Assessment / advice", "-------------------", '\n'.join(advice_part['mail']), '\n\n']
    settings = ["Your settings", "-------------", '\n'.join(settings_part['mail']), '\n\n']
    general = ["General", "-------", '\n'.join(general_part), '\n\n']

    text = '' if daily else '\n'.join(trade)

    if not CONF.info:
        text += '\n'.join(performance) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(general) + CONF.url + '\n'
    else:
        text += '\n'.join(performance) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(general) + CONF.info \
                + '\n\n' + CONF.url + '\n'

    csv = None if not daily else "{};{} UTC;{};{};{};{}\n".format(INSTANCE,
                                                                  datetime.datetime.utcnow().replace(microsecond=0),
                                                                  ';'.join(performance_part['csv']),
                                                                  ';'.join(advice_part['csv']),
                                                                  ';'.join(settings_part['csv']),
                                                                  CONF.info)

    return {'text': text, 'csv': csv}


def create_report_part_settings():
    part = {'mail': [], 'csv': []}
    if CONF.auto_quote == 'MMRange':
        part['csv'].append("Quote {} in %:;n/a".format(CONF.base))
    else:
        part['mail'].append("Quote {} in %: {:>19}".format(CONF.base, CONF.crypto_quote_in_percent))
        part['csv'].append("Quote {} in %:;{}".format(CONF.base, CONF.crypto_quote_in_percent))
    part['mail'].append("Auto-Quote: {:>23}".format(CONF.auto_quote))
    part['csv'].append("Auto-Quote:;{}".format(CONF.auto_quote))
    part['mail'].append("MM Quote 0: {:>23}".format(CONF.mm_quote_0))
    part['csv'].append("MM Quote 0:;{}".format(CONF.mm_quote_0))
    part['mail'].append("MM Quote 100: {:>21}".format(CONF.mm_quote_100))
    part['csv'].append("MM Quote 100:;{}".format(CONF.mm_quote_100))
    part['mail'].append("Max quote {} in %: {:>15}".format(CONF.base, CONF.max_crypto_quote_in_percent))
    part['csv'].append("Max quote {} in %:;{}".format(CONF.base, CONF.max_crypto_quote_in_percent))
    part['mail'].append("Tolerance in %: {:>19}".format(CONF.tolerance_in_percent))
    part['csv'].append("Tolerance in %:;{}".format(CONF.tolerance_in_percent))
    part['mail'].append("Period in minutes: {:>16}".format(CONF.period_in_minutes))
    part['csv'].append("Period in minutes:;{}".format(CONF.period_in_minutes))
    part['mail'].append("Report: {:>27}".format(CONF.report))
    part['csv'].append("Report:;{}".format(CONF.report))
    part['mail'].append("Trade trials: {:>21}".format(CONF.trade_trials))
    part['csv'].append("Trade trials:;{}".format(CONF.trade_trials))
    part['mail'].append("Order adjust seconds: {:>13}".format(CONF.order_adjust_seconds))
    part['csv'].append("Order adjust seconds:;{}".format(CONF.order_adjust_seconds))
    part['mail'].append("Trade advantage in %: {:>13}".format(CONF.trade_advantage_in_percent))
    part['csv'].append("Trade advantage in %:;{}".format(CONF.trade_advantage_in_percent))
    part['mail'].append("Stop buy: {:>25}".format(str('Y' if CONF.stop_buy is True else 'N')))
    part['csv'].append("Stop buy:;{}".format(str('Y' if CONF.stop_buy is True else 'N')))
    return part


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
    sleep_for(0, 1)
    append_balances(part, margin_balance, margin_balance_of_fiat, daily)
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
    LOG.info('Sent email to %s', recipients)


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


def append_balances(part: dict, margin_balance: dict, margin_balance_of_fiat: dict, daily: bool):
    """
    Appends wallet balance, margin balance (including stats), used margin and leverage information, liquidation price
    """
    price = get_current_price()
    append_wallet_balance(part, price)
    stats = load_statistics()
    if CONF.exchange == 'bitmex':
        today = calculate_daily_statistics(margin_balance['total'], margin_balance_of_fiat['total'], price, stats, daily)
        append_margin_change(part, today)
    else:
        c_bal = get_crypto_balance()
        crypto_total = c_bal['total'] if c_bal else 0
        f_bal = get_fiat_balance()
        fiat_total = f_bal['total'] if f_bal else 0
        today = calculate_daily_statistics(crypto_total, fiat_total, price, stats, daily)
        append_balance_change(part, today)
    if not stats:
        yesterday = None
    else:
        yesterday = stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 1)
    append_value_change(part, today, yesterday, price)
    append_trading_result(part, today, yesterday, price)
    append_price_change(part, today, price)
    actual_quote = calculate_quote()
    part['mail'].append("Actual quote: {:>22.2f}%".format(actual_quote))
    part['csv'].append("Actual quote:;{:.2f}%".format(actual_quote))
    used_balance = get_used_balance()
    if used_balance is None:
        used_balance = 'n/a'
    else:
        used_balance = round(used_balance)
    part['mail'].append("Position {}: {:>22}".format(CONF.quote, used_balance))
    part['csv'].append("Position {}:;{}".format(CONF.quote, used_balance))
    append_liquidation_price(part)


def append_wallet_balance(part: dict, price: float):
    wallet_balance = get_wallet_balance(price)
    if wallet_balance is None:
        part['mail'].append("Wallet balance {}: {:>15}".format(CONF.base, 'n/a'))
        part['csv'].append("Wallet balance {}:;n/a".format(CONF.base))
    else:
        part['mail'].append("Wallet balance {}: {:>18.4f}".format(CONF.base, wallet_balance))
        part['csv'].append("Wallet balance {}:;{:.4f}".format(CONF.base, wallet_balance))


def append_liquidation_price(part: dict):
    poi = None
    if CONF.exchange == 'bitmex':
        sleep_for(1, 2)
        poi = get_position_info()
    if poi is not None and 'liquidationPrice' in poi and poi['liquidationPrice'] is not None:
        part['mail'].append("Liquidation price {}: {:>13}".format(CONF.quote, round(poi['liquidationPrice'])))
        part['csv'].append("Liquidation price {}:;{}".format(CONF.quote, round(poi['liquidationPrice'])))
    else:
        part['mail'].append("Liquidation price {}: {:>13}".format(CONF.quote, 'n/a'))
        part['csv'].append("Liquidation price {}:;{}".format(CONF.quote, 'n/a'))


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

    fm_bal = "Margin balance {}: {:>16}".format(CONF.quote, round(today['fmBal']))
    if 'fmBalChan24' in today:
        change = "{:+.2f}%".format(today['fmBalChan24'])
        fm_bal += "   ("
        fm_bal += change
        fm_bal += ")*"
    else:
        change = "% n/a"
    part['mail'].append(fm_bal)
    part['csv'].append("Margin balance {}:;{};{}".format(CONF.quote, round(today['fmBal']), change))


def append_balance_change(part: dict, today: dict):
    """
    Appends balance changes
    """
    nan = "% n/a"
    m_bal = "Balance {}: {:>25.4f}".format(CONF.base, today['mBal'])
    if 'mBalChan24' in today:
        change = "{:+.2f}%".format(today['mBalChan24'])
        m_bal += " ("
        m_bal += change
        m_bal += ")*"
    else:
        change = nan
    part['mail'].append(m_bal)
    part['csv'].append("Balance {}:;{:.4f};{}".format(CONF.base, today['mBal'], change))

    fm_bal = "Balance {}: {:>23}".format(CONF.quote, round(today['fmBal']))
    if 'fmBalChan24' in today:
        change = "{:+.2f}%".format(today['fmBalChan24'])
        fm_bal += "   ("
        fm_bal += change
        fm_bal += ")*"
    else:
        change = nan
    part['mail'].append(fm_bal)
    part['csv'].append("Balance {}:;{};{}".format(CONF.quote, round(today['fmBal']), change))


def append_value_change(part: dict, today: dict, yesterday: dict, price: float):
    nan = "n/a"
    if yesterday and 'mBal' in today and 'fmBal' in today:
        yesterday_total_in_fiat = yesterday['mBal'] * yesterday['price'] + yesterday['fmBal']
        today_total_in_fiat = today['mBal'] * price + today['fmBal']
        change = "{:+.2f}".format((today_total_in_fiat / yesterday_total_in_fiat - 1) * 100) if yesterday_total_in_fiat > 0 else nan
    else:
        change = nan
    if change != nan:
        part['mail'].append("Value change: {:>22}%*".format(change))
        part['csv'].append("Value change:;{}%".format(change))
    else:
        part['mail'].append("Value change: {:>22}*".format(change))
        part['csv'].append("Value change:;{}".format(change))


def append_trading_result(part: dict, today: dict, yesterday: dict, price: float):
    if yesterday and 'mBal' in today and 'fmBal' in today:
        trading_result = (today['mBal'] - yesterday['mBal']) * price + today['fmBal'] - yesterday['fmBal']
        trading_result = "{:+}".format(round(trading_result))
    else:
        trading_result = "n/a"
    part['mail'].append("Trading result in {}: {:>13}*".format(CONF.quote, trading_result))
    part['csv'].append("Trading result in {}:;{}".format(CONF.quote, trading_result))


def append_price_change(part: dict, today: dict, price: float):
    """
    Appends price changes
    """
    rate = "{} price {}: {:>21}".format(CONF.base, CONF.quote, round(price))
    if 'priceChan24' in today:
        change = "{:+.2f}%".format(today['priceChan24'])
        rate += "   ("
        rate += change
        rate += ")*"
    else:
        change = "% n/a"
    part['mail'].append(rate)
    part['csv'].append("{} price {}:;{};{}".format(CONF.base, CONF.quote, round(price), change))


def calculate_daily_statistics(m_bal: float, fm_bal: float, price: float, stats: Stats, update_stats: bool):
    """
    Calculates, updates and persists the change in the margin balance compared with yesterday
    :param m_bal: todays margin balance
    :param fm_bal: todays fiat margin balance
    :param price: the current rate
    :param stats: the loaded stats
    :param update_stats: update and persists the statistic values
    :return: todays statistics including price and margin balance changes compared with 24 hours ago
    """
    today = {'mBal': m_bal, 'fmBal': fm_bal, 'price': price}
    if stats is None:
        stats = Stats()
    if update_stats and datetime.datetime.utcnow().time() > datetime.datetime(2012, 1, 17, 12, 1).time() and not \
            stats.get_day(int(datetime.date.today().strftime("%Y%j"))):
        stats.add_day(int(datetime.date.today().strftime("%Y%j")), today)
        persist_statistics(stats)

    before_24h = stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 1)
    if before_24h:
        if 'mBal' in before_24h and before_24h['mBal'] and before_24h['mBal'] > 0:
            today['mBalChan24'] = round((today['mBal'] / before_24h['mBal'] - 1) * 100, 2)
        if 'fmBal' in before_24h and before_24h['fmBal'] and before_24h['fmBal'] > 0:
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
        handle_account_errors(str(error.args))
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
            if not pos['lastPrice']:
                return {'total': 0}
            return {'total': pos['homeNotional'] * pos['lastPrice']}
        else:
            bal = get_fiat_balance()
        return bal

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
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
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_margin_leverage()


def get_net_deposits():
    """
    Get deposits and withdraws to calculate the net deposits in crypto.
    return: net deposits
    """
    if CONF.net_deposits_in_base_currency:
        return CONF.net_deposits_in_base_currency
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
        LOG.warning('get_net_deposit() not yet implemented for %s', CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_net_deposits()


def get_wallet_balance(price: float):
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
                        crypto = float(bal['balance'])
                    elif bal['currency'] == CONF.quote:
                        fiat = float(bal['balance'])
                if fiat > 0:
                    return crypto + (fiat/price)
                return crypto
        else:
            LOG.warning('get_wallet_balance() is not implemented for %s', CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_wallet_balance(price)


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
        handle_account_errors(str(error.args))
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
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_closed_order()


def get_current_price(pair: str = None, attempts: int = 0, limit: int = None):
    """
    Fetches the current BTC/USD exchange rate
    In case of failure, the function calls itself again until success
    :return: int current market price
    """
    pair = CONF.pair if not pair else pair
    try:
        price = EXCHANGE.fetch_ticker(pair)['bid']
        if not price:
            LOG.warning('Price was None')
            sleep_for(1, 2)
            return get_current_price(pair, attempts, limit)
        return float(price)

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.info('Got an error %s %s, retrying in 5 seconds...', type(error).__name__, str(error.args))
        attempts += 1
        if not limit or attempts < limit:
            sleep_for(4, 6)
            return get_current_price(pair, attempts, limit)
    return 0


def connect_to_exchange():
    exchanges = {}
    for ex in ccxt.exchanges:
        exchange = getattr(ccxt, ex)
        exchanges[ex] = exchange

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


def do_buy(quote: float, reference_price: float, attempt: int):
    """
    Buys at market price lowered by configured percentage or at market price if not successful
    within the configured trade attempts
    :return: Order
    """
    if attempt <= CONF.trade_trials:
        buy_price = calculate_buy_price(get_current_price())
        order_size = calculate_buy_order_size(quote, reference_price, buy_price)
        if order_size is None:
            LOG.info('Buy order size below minimum')
            sleep_for(30, 50)
            return None
        order = create_buy_order(buy_price, order_size)
        if order is None:
            LOG.warning('Could not create buy order over %s', order_size)
            sleep_for(30, 50)
            return None
        sleep(CONF.order_adjust_seconds)
        order_status = fetch_order_status(order.id)
        if order_status in ['open', 'active']:
            return cancel_order(order)
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
    size = BAL['totalBalanceInCrypto'] / (100 / quote) / 1.01
    if size > MIN_ORDER_SIZE:
        return round(size - 0.000000006, 8)
    LOG.info('Order size %f < %f', size, MIN_ORDER_SIZE)
    return None


def do_sell(quote: float, reference_price: float, attempt: int):
    """
    Sells at market price raised by configured percentage or at market price if not successful
    within the configured trade attempts
    :return: Order
    """
    if attempt <= CONF.trade_trials:
        sell_price = calculate_sell_price(get_current_price())
        order_size = calculate_sell_order_size(quote, reference_price, sell_price)
        if order_size is None:
            LOG.info('Sell order size below minimum')
            sleep_for(30, 50)
            return None
        order = create_sell_order(sell_price, order_size)
        if order is None:
            LOG.warning('Could not create sell order over %s', order_size)
            sleep_for(30, 50)
            return None
        sleep(CONF.order_adjust_seconds)
        order_status = fetch_order_status(order.id)
        if order_status in ['open', 'active']:
            return cancel_order(order)
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
    size = BAL['totalBalanceInCrypto'] / (100 / quote) / 1.01
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
        handle_account_errors(str(error.args))
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
    :return the order if it has been filled since, else None
    """
    try:
        if order:
            status = fetch_order_status(order.id)
            if status in ['open', 'active']:
                EXCHANGE.cancel_order(order.id)
                LOG.info('Canceled %s', str(order))
                return None
            else:
                if status and 'filled' in str(status).lower():
                    return order
                LOG.warning('Order to be canceled %s was in state %s', str(order), status)
        return None

    except ccxt.OrderNotFound as error:
        if 'filled' in str(error.args).lower():
            return order
        LOG.error('Order to be canceled not found %s %s', str(order), str(error.args))
        return
    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
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
        handle_account_errors(str(error.args))
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
        handle_account_errors(str(error.args))
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
        handle_account_errors(str(error.args))
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
        handle_account_errors(str(error.args))
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
        handle_account_errors(str(error.args))
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
        handle_account_errors(str(error.args))
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
        LOG.warning('get_postion_info() is not implemented for %s', CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_position_info()


def set_leverage(new_leverage: float):
    try:
        if CONF.exchange == 'bitmex':
            EXCHANGE.private_post_position_leverage({'symbol': CONF.symbol, 'leverage': new_leverage})
            LOG.info('Setting leverage to %s', new_leverage)
        else:
            LOG.error('set_leverage() not yet implemented for %s', CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        if 'zero margin balance' in str(error.args):
            LOG.warning('Account not funded yet, retrying in 20 minutes')
            sleep_for(1200)
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.warning('Insufficient available balance - not setting leverage to %s', new_leverage)
            return None
        handle_account_errors(str(error.args))
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


def get_btc_usd_pair():
    if CONF.exchange == 'binance':
        return 'BTC/USDT'
    return 'BTC/USD'


def meditate(quote: float, price: float):
    action = {}
    if CONF.auto_quote == 'OFF':
        target_quote = CONF.crypto_quote_in_percent
    else:
        target_quote = calculate_target_quote()
    if not CONF.stop_buy and quote < target_quote - CONF.tolerance_in_percent and quote < CONF.max_crypto_quote_in_percent:
        action['direction'] = 'BUY'
        action['percentage'] = target_quote - quote
        action['price'] = price
        return action
    if quote > target_quote + CONF.tolerance_in_percent:
        action['direction'] = 'SELL'
        action['percentage'] = quote - target_quote
        action['price'] = price
        return action
    return None


def calculate_target_quote():
    mayer = get_mayer()
    if CONF.auto_quote == 'MM':
        target_quote = CONF.crypto_quote_in_percent / mayer['current']
    elif CONF.auto_quote == 'MMRange':
        target_quote = 100 * (mayer['current'] - CONF.mm_quote_0) / (CONF.mm_quote_100 - CONF.mm_quote_0)
    if target_quote < 0:
        target_quote = 0
    elif target_quote > 100:
        target_quote = 100
    LOG.info('Auto quote %.2f @ %.2f', target_quote, mayer['current'])
    if target_quote > CONF.max_crypto_quote_in_percent:
        LOG.info('Auto quote limited by configuration to %.2f', CONF.max_crypto_quote_in_percent)
        return CONF.max_crypto_quote_in_percent
    return target_quote


def calculate_quote():
    crypto_quote = (BAL['cryptoBalance'] / BAL['totalBalanceInCrypto']) * 100 if BAL['cryptoBalance'] > 0 else 0
    LOG.info('%s total/crypto quote %.2f/%.2f %.2f @ %d', CONF.base, BAL['totalBalanceInCrypto'], BAL['cryptoBalance'], crypto_quote, BAL['price'])
    return crypto_quote


def calculate_balances():
    balance = {'cryptoBalance': 0, 'totalBalanceInCrypto': 0, 'price': 0}
    if CONF.exchange == 'bitmex':
        pos = get_position_info()
        if pos['homeNotional'] and pos['homeNotional'] < 0:
            LOG.warning('Position short by %f', abs(pos['homeNotional']))
            create_market_buy_order(abs(pos['homeNotional']))
            sleep_for(2, 4)
            pos = get_position_info()
        # aka margin balance
        balance['totalBalanceInCrypto'] = get_crypto_balance()['total']
        balance['price'] = pos['lastPrice']
        if not balance['price']:
            balance['price'] = get_current_price()
        if pos['avgEntryPrice']:
            balance['cryptoBalance'] = (abs(pos['foreignNotional']) / pos['avgEntryPrice'] * balance['price']) / pos['avgEntryPrice']
        return balance
    balance['cryptoBalance'] = get_crypto_balance()['total']
    sleep_for(3, 5)
    fiat_balance = get_fiat_balance()['total']
    balance['price'] = get_current_price()
    balance['totalBalanceInCrypto'] = balance['cryptoBalance'] + (fiat_balance / balance['price'])
    return balance


def handle_account_errors(error_message: str):
    if any(e in error_message.lower() for e in ACCOUNT_ERRORS):
        LOG.error(error_message)
        deactivate_bot(error_message)


def deactivate_bot(message: str):
    os.remove(INSTANCE + '.pid')
    text = "Deactivated RB {}".format(INSTANCE)
    LOG.error(text)
    send_mail(text, message)
    sys.exit(0)


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

    LOG_FILENAME = 'log{}{}'.format(os.path.sep, INSTANCE)
    if not os.path.exists('log'):
        os.makedirs('log')

    LOG = function_logger(logging.DEBUG, LOG_FILENAME, logging.INFO)
    LOG.info('-----------------------')
    CONF = ExchangeConfig()
    LOG.info('BalanceR version: %s', CONF.bot_version)

    EXCHANGE = connect_to_exchange()

    if EMAIL_ONLY:
        BAL = calculate_balances()
        daily_report(True)
        sys.exit(0)

    write_control_file()

    if CONF.exchange == 'bitmex':
        MIN_ORDER_SIZE = 0.0001

    if CONF.exchange == 'bitmex':
        set_leverage(0)

    if not KEEP_ORDERS:
        cancel_all_open_orders()

    while 1:
        BAL = calculate_balances()
        ACTION = meditate(calculate_quote(), BAL['price'])
        ATTEMPT: int = 1
        while ACTION:
            if ACTION['direction'] == 'BUY':
                ORDER = do_buy(ACTION['percentage'], ACTION['price'], ATTEMPT)
            else:
                ORDER = do_sell(ACTION['percentage'], ACTION['price'], ATTEMPT)
            if ORDER:
                # we need the values after the trade
                BAL = calculate_balances()
                do_post_trade_action()
                ACTION = None
            else:
                daily_report()
                ATTEMPT += 1
                BAL = calculate_balances()
                ACTION = meditate(calculate_quote(), BAL['price'])
        daily_report()
        sleep_for(CONF.period_in_seconds)
