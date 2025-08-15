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
MIN_FIAT_ORDER_SIZE = 100
INIT = False
ORDER = None
LAST_ORDER = None
BAL = {'cryptoBalance': 0, 'totalBalanceInCrypto': 0, 'price': 0}
EMAIL_SENT = False
EMAIL_ONLY = False
KEEP_ORDERS = False
NO_LOG = False
SIMULATE = False
DATA_DIR = ''
STARTED = datetime.datetime.utcnow().replace(microsecond=0)
STOP_ERRORS = ['order_size', 'smaller', 'MIN_NOTIONAL', 'nsufficient', 'too low', 'too small', 'not_enough', 'below',
               'exceeds account', 'price', 'nvalid arg', 'nvalid orderQty']
ACCOUNT_ERRORS = ['account has been disabled', 'key is disabled', 'authentication failed', 'permission denied',
                  'invalid api key', 'access denied']
RETRY_MESSAGE = 'Got an error %s %s, retrying in about 5 seconds...'
NOT_IMPLEMENTED_MESSAGE = '%s is not implemented for %s'
NA = 'n/a'


class ExchangeConfig:
    def __init__(self):
        self.mm_quotes = ['OFF', 'MM', 'MMRange']
        self.report_cadences = ['T', 'D', 'M', 'A']
        self.mayer_file = f'{DATA_DIR}mayer.avg'
        self.api_password = ''
        config = configparser.ConfigParser(interpolation=None)
        config.read(f'{DATA_DIR}{INSTANCE}.txt')

        try:
            props = config['config']
            self.bot_version = '1.5.2'
            self.exchange = str(props['exchange']).strip('"').lower()
            self.api_key = str(props['api_key']).strip('"')
            self.api_secret = str(props['api_secret']).strip('"')
            if config.has_option('config', 'api_password'):
                self.api_password = str(props['api_password']).strip('"')
            self.test = bool(str(props['test']).strip('"').lower() == 'true')
            self.pair = str(props['pair']).strip('"')
            self.symbol = str(props['symbol']).strip('"')
            self.net_deposits_in_base_currency = abs(float(props['net_deposits_in_base_currency']))
            self.start_crypto_price = abs(int(props['start_crypto_price']))
            self.start_margin_balance = abs(float(props['start_margin_balance']))
            self.start_mayer_multiple = abs(float(props['start_mayer_multiple']))
            self.start_date = str(props['start_date']).strip('"').strip()
            self.reference_net_deposits = abs(float(props['reference_net_deposits']))
            self.crypto_quote_in_percent = abs(float(props['crypto_quote_in_percent']))
            self.auto_quote = str(props['auto_quote']).strip('"')
            self.mm_quote_0 = abs(float(props['mm_quote_0']))
            self.mm_quote_100 = abs(float(props['mm_quote_100']))
            self.tolerance_in_percent = abs(float(props['tolerance_in_percent']))
            self.period_in_minutes = abs(float(props['period_in_minutes']))
            self.trade_trials = abs(int(props['trade_trials']))
            self.order_adjust_seconds = abs(int(props['order_adjust_seconds']))
            self.trade_advantage_in_percent = float(props['trade_advantage_in_percent'])
            self.stop_buy = bool(str(props['stop_buy']).strip('"').lower() == 'true')
            self.stop_sell = bool(str(props['stop_sell']).strip('"').lower() == 'true')
            self.max_crypto_quote_in_percent = abs(float(props['max_crypto_quote_in_percent']))
            self.max_leverage_in_percent = abs(float(props['max_leverage_in_percent']))
            self.backtrade_only_on_profit = bool(str(props['backtrade_only_on_profit']).strip('"').lower() == 'true')
            self.report = str(props['report']).strip('"')
            self.base, self.quote = self.pair.split("/")
            if self.auto_quote not in self.mm_quotes:
                raise SystemExit(f"Invalid value for auto_quote: '{self.auto_quote}' possible values are: {self.mm_quotes}")
            if self.report not in self.report_cadences:
                raise SystemExit(f"Invalid value for report: '{self.report}' possible values are: {self.report_cadences}")
            self.period_in_seconds = round(self.period_in_minutes * 60)
            self.satoshi_factor = 0.00000001
            if config.has_option('config', 'mayer_file'):
                self.mayer_file = str(props['mayer_file']).strip('"')
            self.recipient_addresses = str(props['recipient_addresses']).strip('"').replace(' ', '').split(",")
            self.sender_address = str(props['sender_address']).strip('"')
            self.sender_password = str(props['sender_password']).strip('"')
            self.mail_server = str(props['mail_server']).strip('"')
            self.info = str(props['info']).strip('"')
            self.url = 'https://bitcoin-schweiz.ch/bot/'
        except (configparser.NoSectionError, KeyError):
            raise SystemExit(f'Invalid configuration for {INSTANCE}')


class Order:
    """
    Holds the relevant data of an order
    """
    __slots__ = 'id', 'price', 'amount', 'side', 'datetime'

    def __init__(self, ccxt_order, amount_fiat: float = None, amount_crypto: float = None, price: float = None):
        if 'id' in ccxt_order:
            self.id = ccxt_order['id']
        elif 'uuid' in ccxt_order:
            self.id = ccxt_order['uuid']

        if 'price' in ccxt_order:
            self.price = set_price(ccxt_order['price'], price)
        elif 'info' in ccxt_order:
            self.price = set_price(ccxt_order['info']['price'], price)

        if 'amount' in ccxt_order:
            self.amount = compute_amount(ccxt_order['amount'], ccxt_order['price'] if 'price' in ccxt_order else None, amount_fiat, amount_crypto)
        elif 'info' in ccxt_order:
            self.amount = compute_amount(ccxt_order['info']['amount'], ccxt_order['info']['price'], amount_fiat, amount_crypto)

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
        return f"{self.side}, price: {self.price}, amount: {self.amount}, order id: {self.id}, created: {self.datetime}"


class Stats:
    """
    Holds the daily statistics in a ring memory (today plus the previous two)
    """

    def __init__(self, day_of_year: int = None, data: dict = None):
        self.days = []
        if day_of_year and data:
            self.add_day(day_of_year, data)

    def add_day(self, day_of_year: int, data: dict):
        if self.get_day(day_of_year) is None:
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


def function_logger(console_level: int, log_file: str = None, file_level: int = None):
    function_name = inspect.stack()[1][3]
    logger = logging.getLogger(function_name)
    # By default log all messages
    logger.setLevel(logging.DEBUG)

    # StreamHandler logs to console
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter('%(asctime)s: %(message)s', '%Y-%m-%d %H:%M:%S'))
    logger.addHandler(ch)

    if log_file and file_level:
        fh = RotatingFileHandler(f"{log_file}.log", mode='a', maxBytes=5 * 1024 * 1024, backupCount=4, encoding=None,
                                 delay=False)
        fh.setLevel(file_level)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(lineno)4d - %(levelname)-8s - %(message)s'))
        logger.addHandler(fh)
    return logger


def compute_amount(ccxt_amount: float = None, price: float = None, amount_fiat: float = None, amount_crypto: float = None):
    if CONF.exchange == 'bitmex':
        return amount_fiat if amount_fiat is not None else ccxt_amount if \
            (not ccxt_amount or ccxt_amount >= MIN_FIAT_ORDER_SIZE or not price) else round(price * ccxt_amount)
    return ccxt_amount if ccxt_amount is not None else amount_crypto


def set_price(ccxt_price: float = None, price: float = None):
    return round(ccxt_price) if ccxt_price is not None else round(price) if price is not None else None


def fetch_mayer(tries: int = 0):
    try:
        req = requests.get('https://bitcoinition.com/current.json', timeout=10)
        if req.text:
            mayer = req.json()['data']
            return {'current': float(mayer['current_mayer_multiple']),
                    'average': float(mayer['average_mayer_multiple'])}
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
    if mayer:
        mayer['current'] = mayer['current'] if mayer['current'] > 0 else get_mayer()['current']
    advice = evaluate_mayer(mayer)
    part['labels'].append("MM")
    if mayer is None:
        part['mail'].append("Mayer multiple: {:>19} (n/a)".format(advice))
        part['csv'].append(NA)
        return
    if advice == 'HOLD':
        part['mail'].append("Mayer multiple: {:>19.2f} (< {:.2f} = {})".format(mayer['current'], 2.4, advice))
    elif advice == 'BUY':
        part['mail'].append(
            "Mayer multiple: {:>19.2f} (< {:.2f} = {})".format(mayer['current'], mayer['average'], advice))
    else:
        part['mail'].append("Mayer multiple: {:>19.2f} (> {:.2f} = {})".format(mayer['current'], 2.4, advice))
    part['csv'].append("{:.2f}".format(mayer['current']))


def get_mayer():
    btc_usd = get_btc_usd_pair()
    mayer = calculate_mayer(get_current_price(btc_usd, 0, 3))
    if mayer is None:
        mayer = fetch_mayer()
    return mayer


def calculate_mayer(price: float):
    average = read_daily_average()
    if average:
        return {'current': price / average}
    return None


def read_daily_average():
    if CONF.mayer_file and os.path.isfile(CONF.mayer_file):
        with open(CONF.mayer_file, "rt") as file:
            return float(file.read())
    return None


def daily_report(immediately: bool = False):
    """
    Creates a daily report email around 12:02 UTC or immediately if told to do so
    """
    global EMAIL_SENT

    now = datetime.datetime.utcnow()
    if immediately or datetime.datetime(2012, 1, 17, 12, 25).time() > now.time() \
            > datetime.datetime(2012, 1, 17, 12, 1).time() and EMAIL_SENT != now.day:
        content = create_mail_content(True)
        filename_csv = f'{DATA_DIR}{INSTANCE}.csv'
        update_csv(content, filename_csv)
        if immediately or is_due_date(datetime.date.today()):
            cadence = "Daily" if CONF.report in ['T', 'D'] else "Monthly" if CONF.report == 'M' else 'Annual'
            subject = f"{cadence} BalanceR report {INSTANCE}"
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
        subject = f"RB Trade report {INSTANCE}"
        content = create_mail_content()
        send_mail(subject, content['text'])


def create_mail_content(daily: bool = False):
    """
    Fetches and formats the data required for the daily report email
    :return: dict: text: str
    """
    if not daily:
        order = ORDER if ORDER else get_closed_order()
        trade = ["Trade", "-----", '\n'.join(create_report_part_trade(order)), '\n\n']
        text = '\n'.join(trade)
    else:
        text = ''
    performance_part = create_report_part_performance(daily)
    base_values_part = create_report_part_base_values()
    advice_part = create_report_part_advice()
    settings_part = create_report_part_settings()
    general_part = create_mail_part_general()

    performance = ["Performance", "-----------", '\n'.join(performance_part['mail']) +
                   '\n* (change since yesterday noon)', '\n\n']
    if CONF.exchange == 'bitmex':
        start = ["Base information", "----------------", '\n'.join(base_values_part['mail']), '\n\n']
    else:
        start = []
    advice = ["Assessment / advice", "-------------------", '\n'.join(advice_part['mail']), '\n\n']
    settings = ["Your settings", "-------------", '\n'.join(settings_part['mail']), '\n\n']
    general = ["General", "-------", '\n'.join(general_part), '\n\n']

    if not CONF.info:
        text += '\n'.join(performance) + '\n'.join(start) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(
            general) + CONF.url + '\n'
    else:
        text += '\n'.join(performance) + '\n'.join(start) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(
            general) + CONF.info + '\n\n' + CONF.url + '\n'

    csv = None if not daily else "{};{} UTC;{};{};{};{};{}\n".format(INSTANCE,
                                                                     datetime.datetime.utcnow().replace(microsecond=0),
                                                                     ';'.join(performance_part['csv']),
                                                                     ';'.join(base_values_part['csv']),
                                                                     ';'.join(advice_part['csv']),
                                                                     ';'.join(settings_part['csv']),
                                                                     CONF.info)

    labels = None if not daily else "Bot;Datetime;{};{};{};{};\n".format(';'.join(performance_part['labels']),
                                                                         ';'.join(base_values_part['labels']),
                                                                         ';'.join(advice_part['labels']),
                                                                         ';'.join(settings_part['labels']))

    return {'text': text, 'csv': csv, 'labels': labels}


def create_report_part_base_values():
    part = {'mail': [], 'csv': [], 'labels': []}
    part['labels'].append("Price")
    part['labels'].append("Margin")
    part['labels'].append("MM")
    part['labels'].append("Start Date")
    if CONF.exchange == 'bitmex':
        part['mail'].append("Price {}: {:>24}".format(CONF.quote, CONF.start_crypto_price))
        part['mail'].append("Margin balance {}: {:>15}".format(CONF.base, round(CONF.start_margin_balance, 4)))
        part['mail'].append("MM: {:>31}".format(round(CONF.start_mayer_multiple, 4)))
        part['mail'].append("Start date: {:>27}".format(CONF.start_date))
        part['csv'].append("{}".format(CONF.start_crypto_price))
        part['csv'].append("{}".format(CONF.start_margin_balance))
        part['csv'].append("{}".format(round(CONF.start_mayer_multiple, 1)))
        part['csv'].append("{}".format(CONF.start_date))
    else:
        part['csv'].append(NA)
        part['csv'].append(NA)
        part['csv'].append(NA)
        part['csv'].append(NA)
    return part


def create_report_part_settings():
    part = {'mail': [], 'csv': [], 'labels': []}
    part['labels'].append("Quote {}".format(CONF.base))
    base_len = len(CONF.base)
    if CONF.auto_quote == 'MMRange':
        part['csv'].append(NA)
    else:
        part['mail'].append("Quote {} in %: {:>{}}".format(CONF.base, CONF.crypto_quote_in_percent, 22-base_len))
        part['csv'].append("{}".format(CONF.crypto_quote_in_percent))
    part['labels'].append("Auto-Quote")
    part['mail'].append("Auto-quote: {:>23}".format(CONF.auto_quote))
    part['csv'].append("{}".format(CONF.auto_quote))
    part['labels'].append("MM Q0")
    part['mail'].append("MM quote 0: {:>23}".format(CONF.mm_quote_0))
    part['csv'].append("{}".format(CONF.mm_quote_0))
    part['labels'].append("MM Q100")
    part['mail'].append("MM quote 100: {:>21}".format(CONF.mm_quote_100))
    part['csv'].append("{}".format(CONF.mm_quote_100))
    part['labels'].append("Max Quote")
    part['mail'].append("Max quote {} in %: {:>{}}".format(CONF.base, CONF.max_crypto_quote_in_percent, 18-base_len))
    part['csv'].append("{}".format(CONF.max_crypto_quote_in_percent))
    part['labels'].append("Max Leverage")
    part['mail'].append("Max leverage in %: {:>16}".format(CONF.max_leverage_in_percent))
    part['csv'].append("{}".format(CONF.max_leverage_in_percent))
    part['labels'].append("Tol. %")
    part['mail'].append("Tolerance in %: {:>19}".format(CONF.tolerance_in_percent))
    part['csv'].append("{}".format(CONF.tolerance_in_percent))
    part['labels'].append("Period Min.")
    part['mail'].append("Period in minutes: {:>16}".format(CONF.period_in_minutes))
    part['csv'].append("{}".format(CONF.period_in_minutes))
    part['labels'].append("Trade Trials")
    part['mail'].append("Trade trials: {:>21}".format(CONF.trade_trials))
    part['csv'].append("{}".format(CONF.trade_trials))
    part['labels'].append("Order Adj. Sec.")
    part['mail'].append("Order adjust seconds: {:>13}".format(CONF.order_adjust_seconds))
    part['csv'].append("{}".format(CONF.order_adjust_seconds))
    part['labels'].append("Trade Adv. %")
    part['mail'].append("Trade advantage in %: {:>13}".format(CONF.trade_advantage_in_percent))
    part['csv'].append("{}".format(CONF.trade_advantage_in_percent))
    part['labels'].append("Stop Buy")
    part['mail'].append("Stop buy: {:>25}".format(str('Y' if CONF.stop_buy is True else 'N')))
    part['csv'].append("{}".format(str('Y' if CONF.stop_buy is True else 'N')))
    part['labels'].append("Stop Sell")
    part['mail'].append("Stop sell: {:>24}".format(str('Y' if CONF.stop_sell is True else 'N')))
    part['csv'].append("{}".format(str('Y' if CONF.stop_sell is True else 'N')))
    part['labels'].append("Backtrade Only Profit")
    part['mail'].append("Backtrade only on profit: {:>9}".format(str('Y' if CONF.backtrade_only_on_profit is True else 'N')))
    part['csv'].append("{}".format(str('Y' if CONF.backtrade_only_on_profit is True else 'N')))
    part['labels'].append("Report")
    part['mail'].append("Report: {:>27}".format(CONF.report))
    part['csv'].append("{}".format(CONF.report))
    part['labels'].append("Info")
    return part


def create_mail_part_general():
    return ["Generated: {:>28}".format(str(datetime.datetime.utcnow().replace(microsecond=0)) + " UTC"),
            "Bot: {:>30}".format(INSTANCE + '@' + socket.gethostname()),
            "Version: {:>26}".format(CONF.bot_version),
            "Running since: {:>20} UTC".format(str(STARTED))]


def create_report_part_advice():
    part = {'mail': [], 'csv': [], 'labels': []}
    append_mayer(part)
    return part


def create_report_part_performance(daily: bool):
    part = {'mail': [], 'csv': [], 'labels': []}
    margin_balance = get_margin_balance()
    net_deposits = get_net_deposits()
    sleep_for(0, 1)
    append_performance(part, margin_balance, net_deposits)
    sleep_for(0, 1)
    append_balances(part, margin_balance, daily)
    return part


def create_report_part_trade(last_order: Order):
    return ["{:>17}".format(str(last_order))]


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
    part['labels'].append("Deposit {}".format(CONF.base))
    part['labels'].append("Overall Perf. {}".format(CONF.base))
    part['labels'].append("Performance %")
    base_len = len(CONF.base)
    if net_deposits is None:
        part['mail'].append("Net deposits {}: {:>{}}".format(CONF.base, NA, 20-base_len))
        part['mail'].append("Overall performance in {}: {:>{}} (% n/a)".format(CONF.base, NA, 10-base_len))
        part['csv'].append(NA)
        part['csv'].append(NA)
        part['csv'].append(NA)
    else:
        part['mail'].append("Net deposits {}: {:>{}.4f}".format(CONF.base, net_deposits, 20-base_len))
        part['csv'].append("{:.4f}".format(net_deposits))
        absolute_performance = margin_balance - net_deposits
        if net_deposits > 0 and absolute_performance != 0:
            relative_performance = round(100 / (net_deposits / absolute_performance), 2)
            part['mail'].append("Overall performance in {}: {:>+{}.4f} ({:+.2f}%)".format(CONF.base,
                                                                                         absolute_performance,
                                                                                         10-base_len,
                                                                                         relative_performance))
            part['csv'].append("{:.4f};{:+.2f}".format(absolute_performance, relative_performance))
        else:
            part['mail'].append("Overall performance in {}: {:>+{}.4f} (% n/a)".format(CONF.base,
                                                                                      absolute_performance,
                                                                                      10-base_len))
            part['csv'].append("{:.4f};n/a".format(absolute_performance))


def append_balances(part: dict, margin_balance: float, daily: bool):
    """
    Appends wallet balance, margin balance (including stats), used margin and leverage information, liquidation price
    """
    price = get_current_price()
    append_wallet_balance(part, price)
    stats = load_statistics()
    if CONF.exchange == 'bitmex':
        margin_balance_of_fiat = get_margin_balance_of_fiat()
        today = calculate_daily_statistics(margin_balance, margin_balance_of_fiat['total'], price, stats, daily)
        append_margin_change(part, today)
        append_position_change(part, today)
    else:
        c_bal = get_crypto_balance()
        crypto_total = c_bal['total'] if c_bal else 0
        f_bal = get_fiat_balance()
        fiat_total = f_bal['total'] if f_bal else 0
        today = calculate_daily_statistics(crypto_total, fiat_total, price, stats, daily)
        append_balance_change(part, today)
    yesterday = None if stats is None else stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 1)
    append_value_change(part, today, yesterday, price)
    append_trading_result(part, today, yesterday, price)
    append_price_change(part, today, price)
    append_actual_quote(part, price)
    append_margin_leverage(part)
    part['labels'].append("Target Position {}".format(CONF.quote))
    target_position = NA
    if CONF.exchange == 'bitmex':
        target_position = round(calculate_target_position(calculate_target_quote(), price))
        part['mail'].append("Target position {}: {:>{}}".format(CONF.quote, target_position, 17-len(CONF.quote)))
    part['csv'].append("{}".format(target_position))
    append_liquidation_price(part)


def append_wallet_balance(part: dict, price: float):
    wallet_balance = get_wallet_balance(price)
    part['labels'].append("Wallet {}".format(CONF.base))
    base_len = len(CONF.base)
    if wallet_balance is None:
        part['mail'].append("Wallet balance {}: {:>{}}".format(CONF.base, NA, 15-base_len))
        part['csv'].append(NA)
    else:
        part['mail'].append("Wallet balance {}: {:>{}.4f}".format(CONF.base, wallet_balance, 18-base_len))
        part['csv'].append("{:.4f}".format(wallet_balance))


def append_liquidation_price(part: dict):
    poi = None
    part['labels'].append("Liq. Price {}".format(CONF.quote))
    if CONF.exchange == 'bitmex':
        sleep_for(1, 2)
        poi = get_position_info()
    padding = 15-len(CONF.quote)
    if poi is not None and 'liquidationPrice' in poi and poi['liquidationPrice'] is not None:
        part['mail'].append("Liquidation price {}: {:>{}}".format(CONF.quote, round(float(poi['liquidationPrice'])), padding))
        part['csv'].append("{}".format(round(float(poi['liquidationPrice']))))
    else:
        part['mail'].append("Liquidation price {}: {:>{}}".format(CONF.quote, 'n/a', padding))
        part['csv'].append(NA)


def append_margin_change(part: dict, today: dict):
    """
    Appends crypto margin and its change (bitmex only)
    """
    part['labels'].append("Margin {}".format(CONF.base))
    part['labels'].append("Change %")
    part['labels'].append("Position {}".format(CONF.quote))
    part['labels'].append("Change %")
    m_bal = "Margin balance {}: {:>{}.4f}".format(CONF.base, today['mBal'], 18-len(CONF.base))
    change = NA
    if 'mBalChan24' in today:
        change = "{:+.2f}%".format(today['mBalChan24'])
        m_bal += " (" + change + ")*"
        change = "{:+.2f}".format(today['mBalChan24'])
    part['mail'].append(m_bal)
    part['csv'].append("{:.4f};{}".format(today['mBal'], change))

def append_position_change(part: dict, today: dict):
    """
    Appends fiat position and its change (bitmex only)
    """
    fm_bal = "Position {}: {:>{}}".format(CONF.quote, round(today['fmBal']), 24-len(CONF.quote))
    change = NA
    if 'fmBalChan24' in today:
        change = "{:+.2f}%".format(today['fmBalChan24'])
        fm_bal += " (" + change + ")*"
        change = "{:+.2f}".format(today['fmBalChan24'])
    part['mail'].append(fm_bal)
    part['csv'].append("{};{}".format(round(today['fmBal']), change))


def append_balance_change(part: dict, today: dict):
    """
    Appends balance changes
    """
    part['labels'].append("Balance {}".format(CONF.base))
    part['labels'].append("Change %")
    part['labels'].append("Balance {}".format(CONF.quote))
    part['labels'].append("Change %")
    m_bal = "Balance {}: {:>{}.4f}".format(CONF.base, today['mBal'], 25-len(CONF.base))
    change = NA
    if 'mBalChan24' in today:
        change = "{:+.2f}%".format(today['mBalChan24'])
        m_bal += " (" + change + ")*"
        change = "{:+.2f}".format(today['mBalChan24'])
    part['mail'].append(m_bal)
    part['csv'].append("{:.4f};{}".format(today['mBal'], change))
    fm_bal = "Balance {}: {:>{}}".format(CONF.quote, round(today['fmBal']), 25-len(CONF.quote))
    change = NA
    if 'fmBalChan24' in today:
        change = "{:+.2f}%".format(today['fmBalChan24'])
        fm_bal += " (" + change + ")*"
        change = "{:+.2f}".format(today['fmBalChan24'])
    part['mail'].append(fm_bal)
    part['csv'].append("{};{}".format(round(today['fmBal']), change))


def append_value_change(part: dict, today: dict, yesterday: dict, price: float):
    part['labels'].append("Value Change %")
    change = NA
    if CONF.exchange == 'bitmex':
        if 'mBalChan24' in today and 'priceChan24' in today:
            margin_change = today['mBalChan24']
            price_change = today['priceChan24']
            margin_leverage = get_margin_leverage()
            if margin_leverage:
                margin_leverage = round(margin_leverage * 100)
                change = "{:+.4f}".format(margin_change - price_change * margin_leverage / 100)
    elif yesterday and 'mBal' in today and 'fmBal' in today:
        yesterday_total_in_fiat = yesterday['mBal'] * yesterday['price'] + yesterday['fmBal']
        today_total_in_fiat = today['mBal'] * price + today['fmBal']
        change = "{:+.2f}".format(
            (today_total_in_fiat / yesterday_total_in_fiat - 1) * 100) if yesterday_total_in_fiat > 0 else NA
    if change != NA:
        part['mail'].append("Value change: {:>21}%*".format(change))
    else:
        part['mail'].append("Value change: {:>21}*".format(change))
    part['csv'].append("{}".format(change))


def append_trading_result(part: dict, today: dict, yesterday: dict, price: float):
    part['labels'].append("Trading Result {}".format(CONF.quote))
    trading_result = NA
    if yesterday and 'mBal' in today and 'fmBal' in today:
        trading_result = (today['mBal'] - yesterday['mBal']) * price + today['fmBal'] - yesterday['fmBal']
        trading_result = "{:+}".format(round(trading_result))
    part['mail'].append("Trading result in {}: {:>{}}*".format(CONF.quote, trading_result, 15-len(CONF.quote)))
    part['csv'].append("{}".format(trading_result))


def append_price_change(part: dict, today: dict, price: float):
    """
    Appends price changes
    """
    part['labels'].append("{} Price {}".format(CONF.base, CONF.quote))
    part['labels'].append("Change %")
    padding = 26-len(CONF.base)-len(CONF.quote)
    rate = "{} price {}: {:>{}}".format(CONF.base, CONF.quote, round(price), padding)
    change = NA
    if 'priceChan24' in today:
        change = "{:+.2f}%".format(today['priceChan24'])
        rate += " (" + change + ")*"
        change = "{:+.2f}".format(today['priceChan24'])
    part['mail'].append(rate)
    part['csv'].append("{};{}".format(round(price), change))


def append_actual_quote(part: dict, price: float = None):
    """
    :param part: dict { 'labels': [], 'mail': [], 'csv': [] }
    :param price: optional, but required for bitmex
    """
    part['labels'].append("Actual Quote %")
    actual_quote = calculate_actual_quote(price)
    if actual_quote >= CONF.max_crypto_quote_in_percent * 0.98:
        part['mail'].append("Actual quote: {:>21n}%  (Max.)".format(round(actual_quote)))
    else:
        part['mail'].append("Actual quote: {:>21n}%".format(round(actual_quote)))
    part['csv'].append("{:n}".format(round(actual_quote)))


def append_margin_leverage(part: dict):
    part['labels'].append("Leverage %")
    margin_leverage = get_margin_leverage()
    if margin_leverage:
        margin_leverage = round(margin_leverage * 100)
        if margin_leverage >= CONF.max_leverage_in_percent * 0.98:
            part['mail'].append("Margin leverage: {:>18n}% (Max.)".format(margin_leverage))
        else:
            part['mail'].append("Margin leverage: {:>18n}%".format(margin_leverage))
        part['csv'].append("{:n}".format(margin_leverage))
    else:
        part['mail'].append("Margin leverage: {:>18}".format("% n/a"))
        part['csv'].append(NA)


def calculate_daily_statistics(m_bal: float, fm_bal: float, price: float, stats: Stats, update_stats: bool):
    """
    Calculates, updates and persists the change in the margin balance compared with yesterday
    :param m_bal: today's margin balance
    :param fm_bal: today's fiat margin balance
    :param price: the current rate
    :param stats: the loaded stats
    :param update_stats: update and persists the statistic values
    :return: today's statistics including price and margin balance changes compared with 24 hours ago
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
    stats_file = f'{DATA_DIR}{INSTANCE}.pkl'
    if os.path.isfile(stats_file):
        with open(stats_file, "rb") as file:
            return pickle.load(file)
    return None


def persist_statistics(stats: Stats):
    stats_file = f'{DATA_DIR}{INSTANCE}.pkl'
    with open(stats_file, "wb") as file:
        pickle.dump(stats, file)


def update_csv(content: dict, filename_csv: str):
    if not os.path.isfile(filename_csv) or (
            int(datetime.date.today().strftime("%j")) == 1 and not is_already_written(filename_csv)):
        write_csv_header(content['labels'], filename_csv)
    write_csv(content['csv'], filename_csv)


def write_csv_header(content: str, filename_csv: str):
    with open(filename_csv, 'w') as file:
        file.write(content)


def write_csv(content: str, filename_csv: str):
    if not is_already_written(filename_csv):
        with open(filename_csv, 'a') as file:
            file.write(content)


def is_already_written(filename_csv: str):
    if os.path.isfile(filename_csv):
        with open(filename_csv, 'r') as file:
            return str(datetime.date.today().isoformat()) in list(file)[-1]
    return False


def set_start_values(values: dict):
    config = configparser.ConfigParser(interpolation=None, allow_no_value=True, comment_prefixes="£", strict=False)
    config.read(f'{DATA_DIR}{INSTANCE}.txt')
    config.set('config', 'start_crypto_price', str(values['crypto_price']))
    config.set('config', 'start_margin_balance', str(values['margin_balance']))
    config.set('config', 'start_mayer_multiple', str(values['mayer_multiple']))
    config.set('config', 'reference_net_deposits', str(values['net_deposits']))
    sv_type = 'Initial'
    if 'date' in values and values['date']:
        config.set('config', 'start_date', str(values['date']))
        sv_type = 'Final'
    LOG.info('%s start position: price: %s, margin: %s, mayer: %s, deposits: %s', sv_type, values['crypto_price'],
             values['margin_balance'], values['mayer_multiple'], values['net_deposits'])
    with open(f'{DATA_DIR}{INSTANCE}.txt', 'w') as config_file:
        config.write(config_file)


def update_deposits(reference_deposits: float, diff: float = 0):
    new_margin_balance = CONF.start_margin_balance + diff
    config = configparser.ConfigParser(interpolation=None, allow_no_value=True, comment_prefixes="£", strict=False)
    config.read(f'{DATA_DIR}{INSTANCE}.txt')
    if diff and CONF.net_deposits_in_base_currency:
        new_net_deposits_in_base_currency = CONF.net_deposits_in_base_currency + diff
        config.set('config', 'net_deposits_in_base_currency', str(new_net_deposits_in_base_currency))
    config.set('config', 'start_margin_balance', str(new_margin_balance))
    config.set('config', 'reference_net_deposits', str(reference_deposits))
    with open(f'{DATA_DIR}{INSTANCE}.txt', 'w') as config_file:
        config.write(config_file)
    if diff:
        if CONF.net_deposits_in_base_currency:
            LOG.info('Updated start margin, reference and net deposits: %s %s %s (%s)', str(new_margin_balance),
                     str(reference_deposits), str(new_net_deposits_in_base_currency), str(diff))
        else:
            LOG.info('Updated start margin and reference deposits: %s %s (%s)', str(new_margin_balance),
                     str(reference_deposits), str(diff))
    else:
        LOG.info('Initialized reference deposits: %s', str(reference_deposits))


def get_margin_balance():
    """
    Fetches the margin balance (of crypto) in fiat
    return: balance of crypto in fiat
    """
    try:
        if CONF.exchange == 'kraken':
            bal = EXCHANGE.private_post_tradebalance({'asset': CONF.base})['result']
            # bal['free'] = float(bal['mf'])
            return float(bal['e'])
            # bal['used'] = float(bal['m'])
        if CONF.exchange in ['bitpanda', 'coinbase', 'coinbasepro']:
            return get_crypto_balance()['total'] + get_fiat_balance()['total'] / get_current_price()
        return get_crypto_balance()['total']

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_margin_balance()


def get_margin_balance_of_fiat():
    """
    Fetches the margin balance (of fiat) in fiat
    return: balance of fiat in fiat
    """
    try:
        if CONF.exchange == 'bitmex':
            pos = get_position_info()
            if not pos or 'markPrice' not in pos or not pos['markPrice']:
                return {'total': 0}
            return {'total': float(pos['homeNotional']) * float(pos['markPrice'])}
        LOG.warning(NOT_IMPLEMENTED_MESSAGE, 'get_margin_balance_of_fiat()', CONF.exchange)
        return None

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
            asset = CONF.base if CONF.base != 'BTC' else 'XBt'
            balances = EXCHANGE.fetch_balance()['info']
            for bal in balances:
                if bal['currency'] == asset:
                    return float(bal['marginLeverage'])
        if CONF.exchange == 'kraken':
            result = EXCHANGE.private_post_tradebalance()['result']
            if hasattr(result, 'ml'):
                return float(result['ml'])
            return 0
        if CONF.exchange in ['bitpanda', 'coinbase']:
            return 0  # Margin trading unavailable
        LOG.warning(NOT_IMPLEMENTED_MESSAGE, 'get_margin_leverage()', CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_margin_leverage()


def get_net_deposits(from_exchange: bool = False):
    """
    Get deposits and withdraws to calculate the net deposits in crypto.
    return: net deposits
    """
    if not from_exchange and CONF.net_deposits_in_base_currency:
        return CONF.net_deposits_in_base_currency
    try:
        currency = CONF.base if CONF.base != 'BTC' else 'XBt'
        if CONF.exchange == 'bitmex':
            result = EXCHANGE.private_get_user_wallet({'currency': currency})
            return (int(result['deposited']) + int(result['transferIn']) - int(result['withdrawn']) - int(result['transferOut'])) * CONF.satoshi_factor
        if CONF.exchange == 'kraken':
            net_deposits = 0
            deposits = EXCHANGE.fetch_deposits(CONF.base)
            for deposit in deposits:
                net_deposits += deposit['amount']
            ledgers = EXCHANGE.private_post_ledgers({'asset': currency, 'type': 'withdrawal'})['result']['ledger']
            for withdrawal_id in ledgers:
                net_deposits += float(ledgers[withdrawal_id]['amount'])
            return net_deposits
        if CONF.exchange in ['bitpanda', 'coinbase', 'coinbasepro']:
            net_deposits = 0
            net_withdrawals = 0
            deposits = EXCHANGE.fetch_deposits(CONF.base)
            for deposit in deposits:
                net_deposits += deposit['amount']
            withdrawals = EXCHANGE.fetch_withdrawals(CONF.base)
            for withdrawal in withdrawals:
                net_withdrawals += withdrawal['amount']
            if net_deposits > net_withdrawals:
                return net_deposits - net_withdrawals
            return 0
        LOG.warning(NOT_IMPLEMENTED_MESSAGE, 'get_net_deposit()', CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_net_deposits(from_exchange)


def get_wallet_balance(price: float):
    """
    Fetch the wallet balance in crypto
    """
    try:
        if CONF.exchange == 'bitmex':
            asset = CONF.base if CONF.base != 'BTC' else 'XBt'
            balances = EXCHANGE.fetch_balance()['info']
            for bal in balances:
                if bal['currency'] == asset:
                    return float(bal['walletBalance']) * CONF.satoshi_factor
        if CONF.exchange == 'kraken':
            return float(EXCHANGE.private_post_tradebalance({'asset': CONF.base})['result']['tb'])
        if CONF.exchange in ['bitpanda', 'coinbase']:
            balance = 0
            balances = EXCHANGE.fetch_balance()
            if balances:
                if CONF.base in balances and 'total' in balances[CONF.base]:
                    balance += balances[CONF.base]['total']
                if CONF.quote in balances and 'total' in balances[CONF.quote]:
                    fiat = balances[CONF.quote]['total']
                    if fiat and fiat > 0:
                        balance += fiat / price
                return balance
            LOG.warning('get_net_deposit() could not retrieve bitpanda/coinbase wallet balance')
            return 0
        LOG.warning(NOT_IMPLEMENTED_MESSAGE, 'get_wallet_balance()', CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_wallet_balance(price)


def get_balances():
    """
    Fetch the margin and wallet balance in satoshi
    """
    try:
        if CONF.exchange == 'bitmex':
            asset = CONF.base if CONF.base != 'BTC' else 'XBt'
            balances = EXCHANGE.fetch_balance()['info']
            for bal in balances:
                if bal['currency'] == asset:
                    return bal
        LOG.warning(NOT_IMPLEMENTED_MESSAGE, 'get_balances()', CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_balances()


def get_open_orders():
    """
    Gets open orders
    :return: [Order]
    """
    try:
        if CONF.exchange == 'paymium':
            orders = EXCHANGE.private_get_user_orders({'active': True})
        elif CONF.exchange == 'binance':
            orders = EXCHANGE.fetch_open_orders(CONF.pair, limit=20)
        elif CONF.exchange == 'bitmex':
            orders = EXCHANGE.fetch_open_orders(CONF.symbol, limit=20, params={'reverse': True})
        else:
            orders = EXCHANGE.fetch_open_orders(CONF.pair, limit=20, params={'reverse': True})
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
        if CONF.exchange in ['kraken', 'coinbase']:
            result = EXCHANGE.fetch_closed_orders(CONF.pair, limit=10)
        elif CONF.exchange == 'bitmex':
            result = EXCHANGE.fetch_closed_orders(CONF.symbol, limit=10, params={'reverse': True})
        else:
            result = EXCHANGE.fetch_closed_orders(CONF.pair, limit=10, params={'reverse': True})
        if result:
            closed = [r for r in result if r['status'] != 'canceled']
            orders = sorted(closed, key=lambda order: order['datetime'])
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
    pair = CONF.symbol if CONF.exchange == 'bitmex' else CONF.pair if not pair else pair
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
        'password': CONF.api_password
        # 'verbose': True,
    })

    if hasattr(CONF, 'test') & CONF.test:
        if 'test' in exchange.urls:
            exchange.urls['api'] = exchange.urls['test']
        else:
            raise SystemExit(f'Test not supported by {CONF.exchange}')

    return exchange


def write_control_file():
    with open(f'{DATA_DIR}{INSTANCE}.pid', 'w') as file:
        file.write(str(os.getpid()) + ' ' + INSTANCE)


def do_buy(quote: float, amount: float, reference_price: float, attempt: int):
    """
    Buys at market price lowered by configured percentage or at market price if not successful
    within the configured trade attempts
    Default case is using quote, if quote is None, amount in fiat must be provided (bitmex MMRange)
    :return: Order
    """
    order_size_crypto = None
    order_size_fiat = None
    if attempt <= CONF.trade_trials:
        buy_price = calculate_buy_price(get_current_price())
        max_price = last_price('BUY')
        if max_price and max_price < buy_price:
            LOG.info('Not buying @ %s', buy_price)
            sleep_for(CONF.period_in_seconds)
            return None
        if quote:
            order_size_crypto = calculate_buy_order_size(quote, reference_price, buy_price)
        elif amount:
            order_size_fiat = to_bitmex_order_size(amount)
        if order_size_crypto is None and order_size_fiat is None:
            LOG.info('Buy order size below minimum')
            sleep_for(CONF.period_in_seconds)
            return None
        order = create_buy_order(buy_price, order_size_crypto, order_size_fiat)
        if order is None:
            order_failed = 'Could not create buy order over %s'
            if order_size_crypto:
                LOG.warning(order_failed, order_size_crypto)
            elif order_size_fiat:
                LOG.warning(order_failed, order_size_fiat)
            sleep_for(CONF.period_in_seconds)
            return None
        sleep(CONF.order_adjust_seconds)
        order_status = fetch_order_status(order.id)
        if order_status in ['open', 'active']:
            return cancel_order(order)
        return order

    if quote:
        order_size_crypto = calculate_buy_order_size(quote, reference_price, get_current_price())
    elif amount:
        order_size_fiat = to_bitmex_order_size(amount)
    if order_size_crypto is None and order_size_fiat is None:
        return None
    return create_market_buy_order(order_size_crypto, order_size_fiat)


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


def to_bitmex_order_size(amount_fiat: float):
    if CONF.exchange != 'bitmex':
        LOG.warning('to_bitmex_order_size is intended for bitmex only')
        return None
    size = int(round(amount_fiat, -2))
    if size >= MIN_FIAT_ORDER_SIZE:
        return size
    LOG.info('Order size (%s) %s < %s', amount_fiat, size, MIN_FIAT_ORDER_SIZE)
    sleep_for(30, 50)
    return None


def do_sell(quote: float, amount: float, reference_price: float, attempt: int):
    """
    Sells at market price raised by configured percentage or at market price if not successful
    within the configured trade attempts
    Default case is using quote, if quote is None, amount in fiat must be provided (bitmex MMRange)
    :return: Order
    """
    order_size_crypto = None
    order_size_fiat = None
    if attempt <= CONF.trade_trials:
        sell_price = calculate_sell_price(get_current_price())
        min_price = last_price('SELL')
        if min_price and min_price > sell_price:
            LOG.info('Not selling @ %s', sell_price)
            sleep_for(CONF.period_in_seconds)
            return None
        if quote:
            order_size_crypto = calculate_sell_order_size(quote, reference_price, sell_price)
        elif amount:
            order_size_fiat = to_bitmex_order_size(amount)
        if order_size_crypto is None and order_size_fiat is None:
            LOG.info('Sell order size below minimum')
            sleep_for(CONF.period_in_seconds)
            return None
        order = create_sell_order(sell_price, order_size_crypto, order_size_fiat)
        if order is None:
            order_failed = 'Could not create sell order over %s'
            if order_size_crypto:
                LOG.warning(order_failed, order_size_crypto)
            elif order_size_fiat:
                LOG.warning(order_failed, order_size_fiat)
            sleep_for(CONF.period_in_seconds)
            return None
        sleep(CONF.order_adjust_seconds)
        order_status = fetch_order_status(order.id)
        if order_status in ['open', 'active']:
            return cancel_order(order)
        return order

    if quote:
        order_size_crypto = calculate_sell_order_size(quote, reference_price, get_current_price())
    elif amount:
        order_size_fiat = to_bitmex_order_size(amount)
    if order_size_crypto is None and order_size_fiat is None:
        return None
    return create_market_sell_order(order_size_crypto, order_size_fiat)


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
            if status and str(status).lower() in ['filled', 'closed']:
                return order
            LOG.warning('Order to be canceled %s was in state %s', str(order), status)
        return None

    except ccxt.OrderNotFound as error:
        if any(e in str(error.args).lower() for e in ['filled', 'cancelorder']):
            return order
        LOG.error('Order to be canceled not found %s %s', str(order), str(error.args))
        return None
    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        cancel_order(order)


def create_sell_order(price: float, amount_crypto: float, amount_fiat: float):
    """
    Creates a sell order
    :param price: float price in fiat
    :param amount_crypto: float amount in crypto
    :param amount_fiat: float amount in fiat
    :return: Order
    """
    if amount_crypto is None and amount_fiat is None:
        return None
    try:
        if CONF.exchange == 'bitmex':
            price = round(price * 2) / 2
            if not amount_fiat:
                amount_fiat = amount_crypto * price
            amount_fiat = to_bitmex_order_size(amount_fiat)
            if not amount_fiat:
                return None
            new_order = EXCHANGE.create_limit_sell_order(CONF.symbol, amount_fiat, price)
        else:
            new_order = EXCHANGE.create_limit_sell_order(CONF.pair, amount_crypto, price)
        norder = Order(new_order, amount_fiat, amount_crypto, price)
        LOG.info('Created %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError, ccxt.InvalidOrder) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            not_selling = 'Order submission not possible - not selling %s'
            if CONF.exchange == 'bitmex':
                LOG.warning(not_selling, amount_fiat)
            else:
                LOG.warning(not_selling, amount_crypto)
            LOG.error(error)
            sleep_for(CONF.period_in_seconds * 10)
            return None
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_sell_order(price, amount_crypto, amount_fiat)


def create_buy_order(price: float, amount_crypto: float, amount_fiat: float):
    """
    Creates a buy order
    :param price: float current price of crypto
    :param amount_crypto: float the order volume
    :param amount_fiat: float the order volume
    """
    if amount_crypto is None and amount_fiat is None:
        return None
    try:
        if CONF.exchange == 'bitmex':
            price = round(price * 2) / 2
            if not amount_fiat:
                amount_fiat = amount_crypto * price
            amount_fiat = to_bitmex_order_size(amount_fiat)
            if not amount_fiat:
                return None
            new_order = EXCHANGE.create_limit_buy_order(CONF.symbol, amount_fiat, price)
        elif CONF.exchange == 'kraken':
            new_order = EXCHANGE.create_limit_buy_order(CONF.pair, amount_crypto, price, {'oflags': 'fcib'})
        else:
            new_order = EXCHANGE.create_limit_buy_order(CONF.pair, amount_crypto, price)

        norder = Order(new_order, amount_fiat, amount_crypto, price)
        LOG.info('Created %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError, ccxt.InvalidOrder) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            not_buying = 'Order submission not possible - not buying %s'
            if CONF.exchange == 'bitmex':
                LOG.warning(not_buying, amount_fiat)
            else:
                LOG.warning(not_buying, amount_crypto)
            LOG.error(error)
            sleep_for(CONF.period_in_seconds * 10)
            return None
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_buy_order(price, amount_crypto, amount_fiat)


def create_market_sell_order(amount_crypto: float, amount_fiat: float):
    """
    Creates a market sell order
    input: amount_crypto to be sold
    input: amount_fiat to be sold
    """
    try:
        if CONF.exchange == 'bitmex':
            if not amount_fiat:
                amount_fiat = amount_crypto * get_current_price()
            amount_fiat = to_bitmex_order_size(amount_fiat)
            if not amount_fiat:
                return None
            new_order = EXCHANGE.create_market_sell_order(CONF.symbol, amount_fiat)
        else:
            new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_crypto)
        norder = Order(new_order, amount_fiat, amount_crypto)
        LOG.info('Created market %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError, ccxt.InvalidOrder) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            not_selling = 'Order submission not possible - not selling %s'
            if amount_crypto:
                LOG.warning(not_selling, amount_crypto)
            elif amount_fiat:
                LOG.warning(not_selling, amount_fiat)
            LOG.error(error)
            sleep_for(CONF.period_in_seconds * 10)
            return None
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_market_sell_order(amount_crypto, amount_fiat)


def create_market_buy_order(amount_crypto: float, amount_fiat: float = None):
    """
    Creates a market buy order
    input: amount_crypto to be bought
    input: amount_fiat to be bought
    """
    try:
        if CONF.exchange == 'bitmex':
            if not amount_fiat:
                amount_fiat = amount_crypto * get_current_price()
            amount_fiat = to_bitmex_order_size(amount_fiat)
            if not amount_fiat:
                return None
            new_order = EXCHANGE.create_market_buy_order(CONF.symbol, amount_fiat)
        elif CONF.exchange == 'kraken':
            new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_crypto, {'oflags': 'fcib'})
        else:
            new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_crypto)
        norder = Order(new_order, amount_fiat, amount_crypto)
        LOG.info('Created market %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError, ccxt.InvalidOrder) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            not_buying = 'Order submission not possible - not buying %s'
            if amount_crypto:
                LOG.warning(not_buying, amount_crypto)
            elif amount_fiat:
                LOG.warning(not_buying, amount_fiat)
            LOG.error(error)
            sleep_for(CONF.period_in_seconds * 10)
            return None
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_market_buy_order(amount_crypto, amount_fiat)


def get_used_balance():
    """
    Fetch the used balance in fiat.
    output: float
    """
    try:
        if CONF.exchange == 'bitmex':
            position = EXCHANGE.private_get_position()
            if position:
                for po in position:
                    if po['symbol'] == CONF.symbol:
                        return float(po['currentQty'])
            return None
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
        alt_currency = ''
        if CONF.exchange == 'kraken':
            if currency == 'BTC':
                alt_currency = 'XBT.F'
            else:
                alt_currency = currency + '.F'
        balance_result = {'free': 0, 'used': 0, 'total': 0}
        bal = EXCHANGE.fetch_balance()
        if currency in bal or alt_currency in bal:
            if alt_currency in bal and bal[alt_currency]['total'] > 0:
                currency = alt_currency
            if 'free' in bal[currency]:
                balance_result['free'] = bal[currency]['free'] or 0
            if 'used' in bal[currency]:
                balance_result['used'] = bal[currency]['used'] or 0
            if 'total' in bal[currency]:
                balance_result['total'] = bal[currency]['total'] or 0
        else:
            LOG.warning('No %s balance found', currency)
        return balance_result

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
                for po in position:
                    if po['symbol'] == CONF.symbol:
                        return po
            return None
        LOG.warning(NOT_IMPLEMENTED_MESSAGE, 'get_postion_info()', CONF.exchange)
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
        if 'Account has zero' in str(error.args):
            LOG.warning('Account not funded yet, retrying in 20 minutes')
            sleep_for(1200)
        if any(e in str(error.args) for e in ['Forbidden']):
            LOG.warning('Access denied, retrying in 40 minutes')
            sleep_for(2400)
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.warning('Insufficient available balance - not setting leverage to %s', new_leverage)
            return None
        handle_account_errors(str(error.args))
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return set_leverage(new_leverage)


def sleep_for(minimal: int, maximal: int = None):
    if maximal:
        time.sleep(round(random.uniform(minimal, maximal), 3))
    else:
        time.sleep(minimal)


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
    target_quote = calculate_target_quote()
    if not CONF.stop_buy and quote < target_quote - CONF.tolerance_in_percent and (
            quote < CONF.max_crypto_quote_in_percent or CONF.auto_quote == 'OFF'):
        action['direction'] = 'BUY'
        action['amount'] = None
        action['percentage'] = target_quote - quote
        action['price'] = price
        return action
    if not CONF.stop_sell and quote > target_quote + CONF.tolerance_in_percent:
        action['direction'] = 'SELL'
        action['amount'] = None
        action['percentage'] = quote - target_quote
        action['price'] = price
        return action
    return None


def meditate_bitmex(price: float):
    action = {}
    target_quote = calculate_target_quote()
    target_position = calculate_target_position(target_quote, price)
    actual_position = int(get_position_info()['currentQty'])
    if not CONF.stop_buy and target_position > actual_position * (1 + CONF.tolerance_in_percent / 100):
        leverage = get_margin_leverage() * 100
        LOG.info('Leverage is %.2f', leverage)
        if leverage >= CONF.max_leverage_in_percent:
            LOG.info('Leverage limited by configuration to %.2f', CONF.max_leverage_in_percent)
            return None
        action['direction'] = 'BUY'
        action['amount'] = round(target_position - actual_position)
        action['percentage'] = None
        action['price'] = price
        return action
    if not CONF.stop_sell and target_position < actual_position * (1 - CONF.tolerance_in_percent / 100):
        action['direction'] = 'SELL'
        action['amount'] = round(actual_position - target_position)
        action['percentage'] = None
        action['price'] = price
        return action
    return None


def calculate_target_quote():
    if CONF.auto_quote == 'OFF':
        return CONF.crypto_quote_in_percent
    mayer = get_mayer()
    if CONF.auto_quote == 'MM':
        if CONF.exchange == 'bitmex':
            target_quote = 100 * (CONF.start_mayer_multiple / mayer['current']) * \
                           (CONF.crypto_quote_in_percent / 100 / CONF.start_mayer_multiple)
        else:
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


def calculate_target_position(target_quote_in_percent: float, price: float):
    return CONF.start_margin_balance * CONF.start_crypto_price * target_quote_in_percent / 100 / price * CONF.start_crypto_price


def calculate_actual_quote(price: float = None):
    """
    :param price: optional, but required for bitmex
    :return: actual_qoute in %
    """
    if CONF.exchange == 'bitmex':
        actual_position = int(get_position_info()['currentQty'])
        crypto_quote = 100 * actual_position / CONF.start_crypto_price / CONF.start_margin_balance * price / CONF.start_crypto_price
        return crypto_quote
    crypto_quote = (BAL['cryptoBalance'] / BAL['totalBalanceInCrypto']) * 100 if BAL['cryptoBalance'] > 0 else 0
    LOG.info('%s total/crypto quote %.2f/%.2f %.2f @ %d', CONF.base, BAL['totalBalanceInCrypto'], BAL['cryptoBalance'],
             crypto_quote, BAL['price'])
    return crypto_quote


def calculate_balances():
    balance = {'cryptoBalance': 0, 'totalBalanceInCrypto': 0, 'price': 0}
    if CONF.exchange == 'bitmex':
        pos = get_position_info()
        if pos and pos['homeNotional'] and float(pos['homeNotional']) < 0:
            LOG.warning('Position short by %f', abs(float(pos['homeNotional'])))
            create_market_buy_order(abs(float(pos['homeNotional'])))
            sleep_for(2, 4)
            pos = get_position_info()
        # aka margin balance
        balance['totalBalanceInCrypto'] = get_crypto_balance()['total']
        if 'markPrice' in pos:
            balance['price'] = float(pos['markPrice'])
        if not balance['price']:
            balance['price'] = get_current_price()
        if pos['avgEntryPrice'] and float(pos['avgEntryPrice']) > 0:
            balance['cryptoBalance'] = (abs(int(pos['foreignNotional'])) / float(pos['avgEntryPrice']) * balance['price']) / float(pos['avgEntryPrice'])
        return balance
    balance['cryptoBalance'] = get_crypto_balance()['total']
    sleep_for(3, 5)
    fiat_balance = get_fiat_balance()['total']
    balance['price'] = get_current_price()
    balance['totalBalanceInCrypto'] = balance['cryptoBalance'] + (fiat_balance / balance['price'])
    return balance


def calculate_used_margin_percentage():
    """
    Calculates the used margin percentage
    """
    bal = get_margin_balance()
    if bal['total'] <= 0:
        return 0
    return float(100 - (bal['free'] / bal['total']) * 100)


def is_nonprofit_trade(last_order: Order, action: dict):
    if not CONF.backtrade_only_on_profit:
        return False
    if not hasattr(last_order, 'price') or not last_order.price:
        return False
    if action['direction'] == 'BUY':
        return last_order and last_order.side.upper() != action['direction'] and last_order.price < action['price']
    return last_order and last_order.side.upper() != action['direction'] and last_order.price > action['price']


def is_price_difference_smaller_than_tolerance(last_order: Order, action: dict):
    if action['direction'] == 'BUY':
        return last_order and last_order.price * (1 - CONF.tolerance_in_percent / 100) < action['price']
    return last_order and last_order.price * (1 + CONF.tolerance_in_percent / 100) > action['price']


def last_price(direction: str):
    if not CONF.backtrade_only_on_profit:
        return None
    if not hasattr(LAST_ORDER, 'price') or not LAST_ORDER.price:
        return None
    return LAST_ORDER.price if LAST_ORDER and LAST_ORDER.side.upper() != direction else None


def handle_account_errors(error_message: str):
    if any(e in error_message.lower() for e in ACCOUNT_ERRORS):
        LOG.error(error_message)
        deactivate_bot(error_message)


def deactivate_bot(message: str):
    os.remove(f'{DATA_DIR}{INSTANCE}.pid')
    text = f"Deactivated RB {INSTANCE}"
    LOG.error(text)
    send_mail(text, message)
    sys.exit(0)


def init_bitmex():
    start_values = {}
    balances = get_balances()
    mayer = get_mayer()
    price = get_current_price()
    net_deposits = get_net_deposits()
    start_values['crypto_price'] = round(price)
    start_values['margin_balance'] = float(balances['marginBalance']) * CONF.satoshi_factor
    start_values['mayer_multiple'] = mayer['current']
    start_values['net_deposits'] = net_deposits
    return start_values


def finit_bitmex():
    start_values = {}
    balances = get_balances()
    mayer = get_mayer()
    net_deposits = get_net_deposits()
    pos = get_position_info()
    if pos['avgEntryPrice']:
        start_values['crypto_price'] = round(float(pos['avgEntryPrice']))
        start_values['margin_balance'] = float(balances['marginBalance']) * CONF.satoshi_factor
        start_values['mayer_multiple'] = mayer['current']
        start_values['date'] = str(datetime.datetime.utcnow().replace(microsecond=0)) + " UTC"
        start_values['net_deposits'] = net_deposits
        return start_values
    return None


def check_deposits():
    net_deposits = get_net_deposits(True)
    if CONF.reference_net_deposits:
        diff = net_deposits - CONF.reference_net_deposits
        if diff != 0:
            update_deposits(net_deposits, diff)
            return ExchangeConfig()
    else:
        update_deposits(net_deposits)
        return ExchangeConfig()
    return CONF


if __name__ == '__main__':
    print('Starting BalanceR Bot')
    print('ccxt version:', ccxt.__version__)

    if len(sys.argv) > 1:
        if os.path.sep in sys.argv[1]:
            parts = sys.argv[1].split(os.path.sep)
            INSTANCE = os.path.basename(parts.pop())
            DATA_DIR = os.path.sep.join(parts) + os.path.sep
        else:
            INSTANCE = os.path.basename(sys.argv[1])
        if len(sys.argv) > 2:
            if '-eo' in sys.argv:
                EMAIL_ONLY = True
            if '-keep' in sys.argv:
                KEEP_ORDERS = True
            if '-nolog' in sys.argv:
                NO_LOG = True
            if '-simulate' in sys.argv:
                SIMULATE = True
    else:
        INSTANCE = os.path.basename(input('Filename with API Keys (config): ') or 'config')

    if NO_LOG:
        LOG = function_logger(logging.DEBUG)
    else:
        LOG_FILENAME = os.path.join(DATA_DIR, 'log', INSTANCE)
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

    if not SIMULATE:
        write_control_file()

    if CONF.exchange == 'coinbasepro':
        MIN_ORDER_SIZE = 0.000016

    if CONF.exchange == 'bitmex':
        MIN_ORDER_SIZE = 0.0001
        set_leverage(0)
        if not CONF.start_date:
            if not CONF.start_margin_balance:
                initial_position = init_bitmex()
                set_start_values(initial_position)
                CONF = ExchangeConfig()
            INIT = True

    if not KEEP_ORDERS:
        cancel_all_open_orders()

    if not INIT and CONF.backtrade_only_on_profit:
        LAST_ORDER = get_closed_order()

    while 1:
        if CONF.exchange == 'bitmex':
            CONF = check_deposits()
            ACTION = meditate_bitmex(get_current_price())
        else:
            BAL = calculate_balances()
            ACTION = meditate(calculate_actual_quote(), BAL['price'])
        if SIMULATE:
            print(ACTION)
            break
        ATTEMPT: int = 1 if not INIT else CONF.trade_trials + 1
        while ACTION:
            if is_nonprofit_trade(LAST_ORDER, ACTION):
                LOG.info('Not %sing @ %s (nonprofit)', ACTION['direction'].lower(), ACTION['price'])
                break
            if is_price_difference_smaller_than_tolerance(LAST_ORDER, ACTION):
                LOG.info('Not %sing @ %s (tolerance)', ACTION['direction'].lower(), ACTION['price'])
                break
            if ACTION['direction'] == 'BUY':
                ORDER = do_buy(ACTION['percentage'], ACTION['amount'], ACTION['price'], ATTEMPT)
            else:
                ORDER = do_sell(ACTION['percentage'], ACTION['amount'], ACTION['price'], ATTEMPT)
            if ORDER:
                if INIT:
                    start_position = finit_bitmex()
                    if start_position:
                        set_start_values(start_position)
                        CONF = ExchangeConfig()
                        INIT = False
                        ATTEMPT = 1
                if CONF.backtrade_only_on_profit:
                    LAST_ORDER = ORDER
                # we need the values after the trade
                BAL = calculate_balances()
                do_post_trade_action()
                ACTION = None
            else:
                daily_report()
                if INIT:
                    sleep_for(CONF.period_in_seconds)
                ATTEMPT += 1
                if CONF.exchange == 'bitmex':
                    CONF = check_deposits()
                    ACTION = meditate_bitmex(get_current_price())
                else:
                    BAL = calculate_balances()
                    ACTION = meditate(calculate_actual_quote(), BAL['price'])
        daily_report()
        sleep_for(CONF.period_in_seconds)
