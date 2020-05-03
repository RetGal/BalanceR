import datetime
import unittest
from unittest import mock
from unittest.mock import patch

import ccxt

import balancer


class BalancerTest(unittest.TestCase):

    def test_calculate_buy_order_size_no_change(self):
        balancer.TOTAL_BALANCE_IN_CRYPTO = 1
        order_size = balancer.calculate_buy_order_size(10, 10000, 10000)

        self.assertAlmostEqual(0.099, order_size, 3)

    def test_calculate_buy_order_size_positive_price_change(self):
        balancer.TOTAL_BALANCE_IN_CRYPTO = 1
        order_size = balancer.calculate_buy_order_size(10, 10000, 10100)

        self.assertAlmostEqual(0.098, order_size, 3)

    def test_calculate_buy_order_size_negative_price_change(self):
        balancer.TOTAL_BALANCE_IN_CRYPTO = 1
        order_size = balancer.calculate_buy_order_size(10, 10000, 9900)

        self.assertAlmostEqual(0.100, order_size, 3)

    def test_calculate_sell_order_size_no_change(self):
        balancer.TOTAL_BALANCE_IN_CRYPTO = 1
        order_size = balancer.calculate_sell_order_size(10, 10000, 10000)

        self.assertAlmostEqual(0.099, order_size, 3)

    def test_calculate_sell_order_size_positive_price_change(self):
        balancer.TOTAL_BALANCE_IN_CRYPTO = 1
        order_size = balancer.calculate_sell_order_size(10, 10000, 10100)

        self.assertAlmostEqual(0.100, order_size, 3)

    def test_calculate_sell_order_size_negative_price_change(self):
        balancer.TOTAL_BALANCE_IN_CRYPTO = 1
        order_size = balancer.calculate_sell_order_size(10, 10000, 9900)

        self.assertAlmostEqual(0.098, order_size, 3)

    def test_calculate_buy_price(self):
        balancer.CONF = self.create_default_conf()

        price = balancer.calculate_buy_price(10000)

        self.assertEqual(9998, price)

    def test_calculate_sell_price(self):
        balancer.CONF = self.create_default_conf()

        price = balancer.calculate_sell_price(10000)

        self.assertEqual(10002, price)

    def test_calculate_sell_price_decimals(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.trade_advantage_in_percent = 0.0333

        price = balancer.calculate_sell_price(10000)

        self.assertEqual(10003.3, price)

    @patch('balancer.get_open_orders')
    def test_cancel_all_open_orders(self, mock_get_open_orders):
        balancer.cancel_all_open_orders()

        mock_get_open_orders.assert_called()


    @patch('balancer.get_open_orders')
    def test_cancel_all_open_orders_with_keep_orders_enabled(self, mock_get_open_orders):
        balancer.KEEP_ORDERS = True

        balancer.cancel_all_open_orders()

        mock_get_open_orders.assert_not_called()

    @patch('balancer.do_buy')
    def test_meditate_quote_too_low(self, mock_do_buy):
        balancer.CONF = self.create_default_conf()

        balancer.meditate(35, 10000)

        mock_do_buy.assert_called_with(15, 10000)

    @patch('balancer.do_sell')
    def test_meditate_quote_too_high(self, mock_do_sell):
        balancer.CONF = self.create_default_conf()

        balancer.meditate(56.5, 10000)

        mock_do_sell.assert_called_with(6.5, 10000)

    @patch('balancer.do_sell')
    @patch('balancer.do_buy')
    def test_meditate_quote_too_high(self, mock_do_buy, mock_do_sell):
        balancer.CONF = self.create_default_conf()

        balancer.meditate(51, 10000)

        mock_do_buy.assert_not_called()
        mock_do_sell.assert_not_called()

    @patch('balancer.logging')
    def test_calculate_quote_very_low(self, mock_logger):
        balancer.LOG = mock_logger
        balancer.CRYPTO_BALANCE = 0.02
        balancer.TOTAL_BALANCE_IN_CRYPTO = 1.00
        balancer.PRICE = 0

        quote = balancer.calculate_quote()

        self.assertAlmostEqual(2, quote, 2)

    @patch('balancer.logging')
    def test_calculate_quote_low(self, mock_logger):
        balancer.LOG = mock_logger
        balancer.CRYPTO_BALANCE = 1.002
        balancer.TOTAL_BALANCE_IN_CRYPTO = 2.002
        balancer.PRICE = 0

        quote = balancer.calculate_quote()

        self.assertAlmostEqual(50.05, quote, 2)

    @patch('balancer.logging')
    def test_calculate_quote_lowest(self, mock_logger):
        balancer.LOG = mock_logger
        balancer.CRYPTO_BALANCE = 1294.79168016 / 6477
        balancer.TOTAL_BALANCE_IN_CRYPTO = 2584.87168016 / 6477
        balancer.PRICE = 0

        quote = balancer.calculate_quote()

        self.assertAlmostEqual(50.0911, quote, 3)

    @patch('balancer.logging')
    def test_calculate_quote_high(self, mock_logger):
        balancer.LOG = mock_logger
        balancer.CRYPTO_BALANCE = 0.99
        balancer.TOTAL_BALANCE_IN_CRYPTO = 1.00
        balancer.PRICE = 0

        quote = balancer.calculate_quote()

        self.assertAlmostEqual(99, quote, 2)

    def test_calculate_used_margin_percentage(self):
        percentage = balancer.calculate_used_margin_percentage({'total': 100, 'free': 49})

        self.assertEqual(51, percentage)

    @patch('balancer.get_margin_balance', return_value={'total': 0})
    def test_calculate_used_margin_percentage_without_provided_balance(self, mock_get_margin_balance):
        percentage = balancer.calculate_used_margin_percentage()

        mock_get_margin_balance.assert_called()
        self.assertEqual(0, percentage)

    def test_stats_add_same_again_day(self):
        today = {'mBal': 0.999, 'price': 10000}
        stats = balancer.Stats(int(datetime.date.today().strftime("%Y%j")), today)
        same_day = {'mBal': 0.666, 'price': 9000}

        stats.add_day(int(datetime.date.today().strftime("%Y%j")), same_day)

        day = stats.get_day(int(datetime.date.today().strftime("%Y%j")))
        self.assertTrue(day['mBal'] == 0.999)
        self.assertTrue(day['price'] == 10000)

    def test_stats_add_day_removes_oldest(self):
        h72 = {'mBal': 0.720, 'price': 10072}
        h48 = {'mBal': 0.480, 'price': 10048}
        h24 = {'mBal': 0.240, 'price': 10024}
        today = {'mBal': 0.000, 'price': 10000}
        stats = balancer.Stats(int(datetime.date.today().strftime("%Y%j")) - 3, h72)
        stats.add_day(int(datetime.date.today().strftime("%Y%j")) - 2, h48)
        stats.add_day(int(datetime.date.today().strftime("%Y%j")) - 1, h24)
        self.assertTrue(len(stats.days) == 3)

        stats.add_day(int(datetime.date.today().strftime("%Y%j")), today)

        self.assertEqual(3, len(stats.days))
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 3) is None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 2) is not None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 1) is not None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j"))) is not None)

    @patch('balancer.load_statistics', return_value=None)
    @patch('balancer.persist_statistics')
    def test_calculate_statistics_first_day_without_persist(self, mock_persist_statistics, mock_load_statistics):
        today = balancer.calculate_daily_statistics(90, 110, 8000.0, False)

        self.assertTrue(today['mBal'] == 90)
        self.assertTrue(today['fmBal'] == 110)
        self.assertTrue(today['price'] == 8000.0)
        mock_persist_statistics.assert_not_called()

    @patch('balancer.load_statistics', return_value=balancer.Stats(int(datetime.date.today().strftime("%Y%j")) - 1,
                                                                   {'mBal': 50.1, 'fmBal': 100, 'price': 8000.0}))
    def test_calculate_statistics_positive_change(self, mock_load_statistics):
        today = balancer.calculate_daily_statistics(100.2, 105, 8800.0, False)

        self.assertEqual(100.2, today['mBal'])
        self.assertEqual(105, today['fmBal'])
        self.assertEqual(8800.0, today['price'])
        self.assertEqual(100.0, today['mBalChan24'])
        self.assertEqual(5, today['fmBalChan24'])
        self.assertEqual(10.0, today['priceChan24'])

    @patch('balancer.load_statistics', return_value=balancer.Stats(int(datetime.date.today().strftime("%Y%j")) - 1,
                                                                   {'mBal': 150.3, 'fmBal': 100, 'price': 8000.0}))
    @patch('balancer.persist_statistics')
    def test_calculate_statistics_negative_change(self, mock_persist_statistics, mock_load_statistics):
        today = balancer.calculate_daily_statistics(100.2, 90, 7600.0, True)

        self.assertEqual(100.2, today['mBal'])
        self.assertEqual(7600.0, today['price'])
        self.assertEqual(-33.33, today['mBalChan24'])
        self.assertEqual(-10, today['fmBalChan24'])
        self.assertEqual(-5.0, today['priceChan24'])

    @patch('balancer.create_report_part_trade')
    @patch('balancer.create_report_part_performance')
    @patch('balancer.create_report_part_advice')
    @patch('balancer.create_report_part_settings')
    @patch('balancer.create_mail_part_general')
    def test_create_daily_report(self, mock_create_mail_part_general, mock_create_report_part_settings,
                                 mock_create_report_part_performance, mock_create_report_part_advice,
                                 mock_create_report_part_trade):
        balancer.INSTANCE = 'test'
        balancer.CONF = self.create_default_conf()

        balancer.create_mail_content(True)

        mock_create_report_part_trade.assert_not_called()
        mock_create_report_part_performance.assert_called()
        mock_create_report_part_advice.assert_called()
        mock_create_report_part_settings.assert_called()
        mock_create_mail_part_general.assert_called()

    @patch('balancer.create_report_part_trade')
    @patch('balancer.create_report_part_performance')
    @patch('balancer.create_report_part_advice')
    @patch('balancer.create_report_part_settings')
    @patch('balancer.create_mail_part_general')
    def test_create_trade_report(self, mock_create_mail_part_general,
                                 mock_create_report_part_settings, mock_create_report_part_performance,
                                 mock_create_report_part_advice, mock_create_report_part_trade):
        balancer.CONF = self.create_default_conf()
        balancer.ORDER = {'id': '1'}

        balancer.create_mail_content()

        mock_create_report_part_trade.assert_called()
        mock_create_report_part_performance.assert_called()
        mock_create_report_part_advice.assert_called()
        mock_create_report_part_settings.assert_called()
        mock_create_mail_part_general.assert_called()

    def test_exchange_configuration(self):
        balancer.INSTANCE = 'test'
        balancer.CONF = balancer.ExchangeConfig()

        self.assertEqual('bitmex', balancer.CONF.exchange)
        self.assertEqual('BTC/USD', balancer.CONF.pair)
        self.assertEqual('BTC', balancer.CONF.base)
        self.assertEqual('USD', balancer.CONF.quote)
        self.assertTrue(balancer.CONF.trade_report)
        self.assertEqual(50, balancer.CONF.crypto_quote_in_percent)
        self.assertEqual('Test', balancer.CONF.info)

    @patch('balancer.logging')
    @mock.patch.object(ccxt.kraken, 'fetch_balance')
    def test_get_balance(self, mock_fetch_balance, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.test = False
        balancer.LOG = mock_logging
        balancer.EXCHANGE = balancer.connect_to_exchange()
        mock_fetch_balance.return_value = {'BTC': {'used': None, 'free': None, 'total': 0.9}}

        balance = balancer.get_crypto_balance()

        self.assertEqual(0, balance['used'])
        self.assertEqual(0, balance['free'])
        self.assertEqual(0.9, balance['total'])

    @patch('balancer.logging')
    @patch('ccxt.kraken')
    def test_get_margin_balance_kraken(self, mock_kraken, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.base = 'BTC'
        balancer.EXCHANGE = mock_kraken
        balancer.LOG = mock_logging
        mock_kraken.private_post_tradebalance.return_value = {'result': {'mf': 100, 'e': 150, 'm': 50}}

        balance = balancer.get_margin_balance()

        mock_kraken.private_post_tradebalance.assert_called()
        self.assertEqual(50, balance['used'])
        self.assertEqual(100, balance['free'])
        self.assertEqual(150, balance['total'])

    @patch('balancer.logging')
    @patch('ccxt.bitmex')
    def test_get_margin_balance_bitmex(self, mock_bitmex, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.EXCHANGE = mock_bitmex
        balancer.LOG = mock_logging

        mock_bitmex.fetch_balance.return_value = {balancer.CONF.base: {'free': 100, 'total': 150, 'used': None}}
        balancer.get_margin_balance()

        mock_bitmex.fetch_balance.assert_called()

    @patch('balancer.logging')
    @mock.patch.object(ccxt.kraken, 'cancel_order')
    @mock.patch.object(ccxt.kraken, 'fetch_order_status')
    def test_cancel_order(self, mock_fetch_order_status, mock_cancel_order, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.test = False
        balancer.LOG = mock_logging
        balancer.EXCHANGE = balancer.connect_to_exchange()

        order1 = balancer.Order({'side': 'sell', 'id': 's1o', 'price': 10000, 'amount': 100,
                                 'datetime': datetime.datetime.today().isoformat()})
        order2 = balancer.Order({'side': 'buy', 'id': 'b2c', 'price': 9000, 'amount': 90,
                                 'datetime': datetime.datetime.today().isoformat()})

        return_values = {'s1o': 'open', 'b2c': 'canceled'}
        mock_fetch_order_status.side_effect = return_values.get
        balancer.cancel_order(order1)
        mock_cancel_order.assert_called()

        balancer.cancel_order(order2)
        mock_logging.warning.assert_called_with('Order to be canceled %s was in state %s', str(order2), 'canceled')

    @patch('balancer.logging')
    @patch('ccxt.kraken')
    def test_create_sell_order_should_call_create_limit_sell_order_with_expected_values(self, mock_kraken, mock_logging):
        sell_price = 14000
        amount_crypto = 0.025
        balancer.LOG = mock_logging
        balancer.CONF = self.create_default_conf()
        balancer.EXCHANGE = mock_kraken
        mock_kraken.create_limit_sell_order.return_value = {'id': 1, 'price': sell_price, 'amount': amount_crypto,
                                                            'side': 'sell', 'datetime': str(datetime.datetime.utcnow())}

        balancer.create_sell_order(sell_price, amount_crypto)

        mock_kraken.create_limit_sell_order.assert_called_with(balancer.CONF.pair, amount_crypto, sell_price)

    @patch('balancer.logging')
    @patch('ccxt.bitmex')
    def test_create_sell_order_should_call_create_limit_sell_order_with_expected_fiat_values(self, mock_bitmex, mock_logging):
        sell_price = 10000
        amount_crypto = 0.025
        balancer.LOG = mock_logging
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.EXCHANGE = mock_bitmex
        mock_bitmex.create_limit_sell_order.return_value = {'id': 1, 'price': sell_price, 'amount': amount_crypto,
                                                            'side': 'sell', 'datetime': str(datetime.datetime.utcnow())}

        balancer.create_sell_order(sell_price, amount_crypto)

        mock_bitmex.create_limit_sell_order.assert_called_with(balancer.CONF.pair, round(amount_crypto * sell_price), sell_price)

    @patch('balancer.logging')
    @patch('ccxt.kraken')
    def test_create_buy_order_should_call_create_limit_buy_order_with_expected_values(self, mock_kraken, mock_logging):
        buy_price = 9900
        amount_crypto = 0.03
        balancer.LOG = mock_logging
        balancer.CONF = self.create_default_conf()
        balancer.EXCHANGE = mock_kraken
        mock_kraken.create_limit_buy_order.return_value = {'id': 1, 'price': buy_price, 'amount': amount_crypto,
                                                           'side': 'sell', 'datetime': str(datetime.datetime.utcnow())}

        balancer.create_buy_order(buy_price, amount_crypto)

        mock_kraken.create_limit_buy_order.assert_called_with(balancer.CONF.pair, amount_crypto, buy_price, {'oflags': 'fcib'})

    @patch('balancer.fetch_mayer', return_value={'current': 1, 'average': 1.5})
    def test_print_mayer_buy(self, mock_fetch_mayer):
        advice = balancer.print_mayer()

        self.assertTrue(advice.endswith('BUY)'))

    @patch('balancer.fetch_mayer', return_value={'current': 2.5, 'average': 1.5})
    def test_print_mayer_sell(self, mock_fetch_mayer):
        advice = balancer.print_mayer()

        self.assertTrue(advice.endswith('SELL)'))

    def test_append_performance(self):
        balancer.CONF = self.create_default_conf()
        part = {'mail': [], 'csv': []}
        balancer.append_performance(part, 100.2, 50.1)
        mail_part = ''.join(part['mail'])
        csv_part = ''.join(part['csv'])

        self.assertTrue(mail_part.rfind('100.00%)') > 0)
        self.assertTrue(csv_part.rfind('50.1') > 0)

    def test_append_performance_no_deposits(self):
        balancer.CONF = self.create_default_conf()
        part = {'mail': [], 'csv': []}
        balancer.append_performance(part, 100.2, None)
        mail_part = ''.join(part['mail'])
        csv_part = ''.join(part['csv'])

        self.assertTrue(mail_part.rfind('n/a') > 0)
        self.assertTrue(csv_part.rfind('n/a') > 0)

    @staticmethod
    def create_default_conf():
        conf = balancer.ExchangeConfig
        conf.exchange = 'kraken'
        conf.api_key = '1234'
        conf.api_secret = 'secret'
        conf.test = True
        conf.pair = 'BTC/EUR'
        conf.symbol = 'XBTEUR'
        conf.base = 'BTC'
        conf.quote = 'EUR'
        conf.satoshi_factor = 0.00000001
        conf.bot_version = '0.0.1'
        conf.trade_trials = 5
        conf.trade_advantage_in_percent = 0.02
        conf.crypto_quote_in_percent = 50
        conf.tolerance_in_percent = 2
        conf.period_in_minutes = 10
        conf.daily_report = False
        conf.trade_report = False
        conf.info = ''
        conf.mail_server = 'smtp.example.org'
        conf.sender_address = 'test@example.org'
        conf.recipient_addresses = ''
        return conf


if __name__ == '__main__':
    unittest.main()