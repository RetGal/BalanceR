import datetime
import time
import unittest
from math import isclose
from unittest import mock
from unittest.mock import patch

import ccxt

import balancer


class BalancerTest(unittest.TestCase):

    def test_calculate_buy_order_size_no_change(self):
        balancer.BAL['totalBalanceInCrypto'] = 1
        order_size = balancer.calculate_buy_order_size(10, 10000, 10000)

        self.assertAlmostEqual(0.099, order_size, 3)

    def test_calculate_buy_order_size_positive_price_change(self):
        balancer.BAL['totalBalanceInCrypto'] = 1
        order_size = balancer.calculate_buy_order_size(10, 10000, 10100)

        self.assertAlmostEqual(0.098, order_size, 3)

    def test_calculate_buy_order_size_negative_price_change(self):
        balancer.BAL['totalBalanceInCrypto'] = 1
        order_size = balancer.calculate_buy_order_size(10, 10000, 9900)

        self.assertAlmostEqual(0.100, order_size, 3)

    def test_calculate_sell_order_size_no_change(self):
        balancer.BAL['totalBalanceInCrypto'] = 1
        order_size = balancer.calculate_sell_order_size(10, 10000, 10000)

        self.assertAlmostEqual(0.099, order_size, 3)

    def test_calculate_sell_order_size_positive_price_change(self):
        balancer.BAL['totalBalanceInCrypto'] = 1
        order_size = balancer.calculate_sell_order_size(10, 10000, 10100)

        self.assertAlmostEqual(0.100, order_size, 3)

    def test_calculate_sell_order_size_negative_price_change(self):
        balancer.BAL['totalBalanceInCrypto'] = 1
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

    def test_is_negative_sell_after_none(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.backtrade_only_on_profit = True
        action = {'direction': 'SELL', 'price': 50000}

        self.assertFalse(balancer.is_nonprofit_trade(None, action))

    def test_is_negative_sell_after_sell(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.backtrade_only_on_profit = True
        last_order = balancer.Order({'side': 'sell', 'id': '1', 'price': 40000, 'amount': 100,
                                     'datetime': datetime.datetime.today().isoformat()})
        action = {'direction': 'SELL', 'price': 50000}

        self.assertFalse(balancer.is_nonprofit_trade(last_order, action))

    def test_is_negative_sell_after_buy(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.backtrade_only_on_profit = True
        last_order = balancer.Order({'side': 'buy', 'id': '1', 'price': 40000, 'amount': 100,
                                     'datetime': datetime.datetime.today().isoformat()})
        action = {'direction': 'SELL', 'price': 50000}

        self.assertFalse(balancer.is_nonprofit_trade(last_order, action))

    def test_is_negative_sell_after_more_expensive_buy(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.backtrade_only_on_profit = True
        last_order = balancer.Order({'side': 'buy', 'id': '1', 'price': 50001, 'amount': 100,
                                     'datetime': datetime.datetime.today().isoformat()})
        action = {'direction': 'SELL', 'price': 50000}

        self.assertTrue(balancer.is_nonprofit_trade(last_order, action))

    def test_is_negative_sell_after_more_expensive_buy_with_backtrade_only_on_profit_off(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.backtrade_only_on_profit = False
        last_order = balancer.Order({'side': 'buy', 'id': '1', 'price': 50001, 'amount': 100,
                                     'datetime': datetime.datetime.today().isoformat()})
        action = {'direction': 'SELL', 'price': 50000}

        self.assertFalse(balancer.is_nonprofit_trade(last_order, action))

    def test_is_negative_buy_after_cheaper_sell(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.backtrade_only_on_profit = True
        last_order = balancer.Order({'side': 'sell', 'id': '1', 'price': 49999, 'amount': 100,
                                     'datetime': datetime.datetime.today().isoformat()})
        action = {'direction': 'BUY', 'price': 50000}

        self.assertTrue(balancer.is_nonprofit_trade(last_order, action))

    def test_is_negative_buy_after_market_sell(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.backtrade_only_on_profit = True
        last_order = balancer.Order({'side': 'sell', 'id': '1', 'price': None, 'amount': 100,
                                     'datetime': datetime.datetime.today().isoformat()})
        action = {'direction': 'BUY', 'price': 50000}

        self.assertFalse(balancer.is_nonprofit_trade(last_order, action))

    def test_is_negative_buy_after_cheaper_sell_with_backtrade_only_on_profit_off(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.backtrade_only_on_profit = False
        last_order = balancer.Order({'side': 'sell', 'id': '1', 'price': 49999, 'amount': 100,
                                     'datetime': datetime.datetime.today().isoformat()})
        action = {'direction': 'BUY', 'price': 50000}

        self.assertFalse(balancer.is_nonprofit_trade(last_order, action))

    @patch('balancer.get_open_orders')
    def test_cancel_all_open_orders(self, mock_get_open_orders):
        balancer.cancel_all_open_orders()

        mock_get_open_orders.assert_called()

    @patch('balancer.get_open_orders')
    def test_cancel_all_open_orders_with_keep_orders_enabled(self, mock_get_open_orders):
        balancer.KEEP_ORDERS = True

        balancer.cancel_all_open_orders()

        mock_get_open_orders.assert_not_called()

    def test_meditate_quote_too_low(self):
        balancer.CONF = self.create_default_conf()

        action = balancer.meditate(35, 10000)

        self.assertEqual('BUY', action['direction'])
        self.assertEqual(15, action['percentage'])
        self.assertEqual(10000, action['price'])

    @patch('balancer.get_margin_leverage', return_value=1.2)
    @patch('balancer.get_position_info', return_value={'currentQty': 4000})
    def test_meditate_quote_too_low_bitmex(self, mock_get_position_info, mock_get_margin_leverage):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.start_crypto_price = 30000

        action = balancer.meditate_bitmex(30000)

        self.assertEqual('BUY', action['direction'])
        self.assertEqual(2000, action['amount'])
        self.assertEqual(30000, action['price'])

    @patch('balancer.get_margin_leverage', return_value=1.2)
    @patch('balancer.get_position_info', return_value={'currentQty': 4000})
    def test_meditate_tolerance_not_matched_bitmex(self, mock_get_position_info, mock_get_margin_leverage):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.start_crypto_price = 30000
        balancer.CONF.tolerance_in_percent = 2.0

        # target_position ≃ 4045 which is below tolerance (4000 + 2% = 4080)
        action = balancer.meditate_bitmex(44500)

        self.assertIsNone(action)

    @patch('balancer.logging')
    @patch('balancer.get_margin_leverage', return_value=1.2)
    @patch('balancer.get_position_info', return_value={'currentQty': 4000})
    def test_meditate_tolerance_matched_bitmex(self, mock_get_position_info, mock_get_margin_leverage, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.start_crypto_price = 30000
        balancer.CONF.tolerance_in_percent = 0.5

        # target_position ≃ 4045 which is above tolerance (4000 + 1% = 4040)
        action = balancer.meditate_bitmex(44500)

        self.assertEqual('BUY', action['direction'])
        self.assertEqual(45, action['amount'])
        self.assertEqual(44500, action['price'])

    @patch('balancer.logging')
    @patch('balancer.get_margin_leverage', return_value=1.6)
    @patch('balancer.get_position_info', return_value={'currentQty': 5000})
    def test_meditate_quote_too_low_but_limited_by_max_leverage_bitmex(self, mock_get_position_info, mock_get_margin_leverage, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.start_crypto_price = 30000

        self.assertIsNone(balancer.meditate_bitmex(30000))
        mock_logger.info.assert_called_with('Leverage limited by configuration to %.2f', balancer.CONF.max_leverage_in_percent)

    @patch('balancer.get_position_info', return_value={'currentQty': 6000})
    def test_meditate_quote_too_high_bitmex(self, mock_get_position_info):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.start_crypto_price = 30000

        action = balancer.meditate_bitmex(32000)

        self.assertEqual('SELL', action['direction'])
        self.assertEqual(375, action['amount'])
        self.assertEqual(32000, action['price'])

    def test_meditate_quote_too_low_stop_buy_enabled(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.stop_buy = True

        action = balancer.meditate(35, 10000)

        self.assertIsNone(action)

    def test_meditate_quote_too_high_stop_sell_enabled(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.stop_sell = True

        action = balancer.meditate(95, 10000)

        self.assertIsNone(action)

    @patch('balancer.read_daily_average', return_value=10000)
    @patch('balancer.get_current_price', return_value=10000)
    def test_meditate_quote_too_low_auto_quote_enabled(self, mock_current_price, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MM'

        action = balancer.meditate(35, 10000)

        self.assertEqual('BUY', action['direction'])
        self.assertEqual(15, action['percentage'])
        self.assertEqual(10000, action['price'])

    @patch('balancer.read_daily_average', return_value=None)
    @patch('balancer.fetch_mayer', return_value={'current': 0.5})
    def test_meditate_quote_too_low_auto_quote_enabled_low_mayer_from_remote_high_max_crypto_quote(self, mock_mayer, read_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.max_crypto_quote_in_percent = 100
        balancer.CONF.auto_quote = 'MM'

        action = balancer.meditate(40, 10000)

        self.assertEqual('BUY', action['direction'])
        self.assertEqual(60, action['percentage'])
        self.assertEqual(10000, action['price'])

    @patch('balancer.logging')
    @patch('balancer.read_daily_average', return_value=None)
    @patch('balancer.fetch_mayer', return_value={'current': 0.5})
    def test_meditate_quote_too_low_auto_quote_enabled_low_mayer_from_remote_limited_by_default_max_crypto_quote(self, mock_mayer, read_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MM'

        action = balancer.meditate(50, 10000)

        mock_logger.info.assert_called_with('Auto quote limited by configuration to %.2f', balancer.CONF.max_crypto_quote_in_percent)
        self.assertEqual('BUY', action['direction'])
        self.assertEqual(30, action['percentage'])
        self.assertEqual(10000, action['price'])

    @patch('balancer.logging')
    @patch('balancer.read_daily_average', return_value=None)
    @patch('balancer.fetch_mayer', return_value={'current': 0.5})
    def test_meditate_quote_too_low_auto_quote_enabled_low_mayer_from_remote_low_max_crypto_quote(self, mock_mayer, read_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.max_crypto_quote_in_percent = 60
        balancer.CONF.auto_quote = 'MM'

        action = balancer.meditate(50, 10000)

        mock_logger.info.assert_called_with('Auto quote limited by configuration to %.2f', balancer.CONF.max_crypto_quote_in_percent)
        self.assertEqual('BUY', action['direction'])
        self.assertEqual(10, action['percentage'])
        self.assertEqual(10000, action['price'])

    def test_meditate_quote_too_high(self):
        balancer.CONF = self.create_default_conf()

        action = balancer.meditate(56.5, 10000)

        self.assertEqual('SELL', action['direction'])
        self.assertEqual(6.5, action['percentage'])
        self.assertEqual(10000, action['price'])

    def test_meditate_quote_within_tolerance(self):
        balancer.CONF = self.create_default_conf()

        action = balancer.meditate(51, 10000)

        self.assertIsNone(action)

    @patch('balancer.read_daily_average', return_value=6250)
    @patch('balancer.get_current_price', return_value=10000)
    def test_meditate_quote_too_high_auto_quote_enabled_high_mayer(self, mock_current_price, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MM'

        action = balancer.meditate(35, 10000)

        self.assertEqual('SELL', action['direction'])
        self.assertEqual(3.75, action['percentage'])
        self.assertEqual(10000, action['price'])

    @patch('balancer.read_daily_average', return_value=1800)
    @patch('balancer.get_current_price', return_value=10000)
    def test_meditate_quote_high_auto_quote_enabled_very_high_mayer(self, mock_current_price, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MM'

        action = balancer.meditate(35, 10000)

        self.assertEqual('SELL', action['direction'])
        self.assertEqual(26, action['percentage'])
        self.assertEqual(10000, action['price'])

    def test_meditate_quote_too_low_with_auto_quote_off_should_ignore_max_crypto_quote(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'OFF'
        balancer.CONF.crypto_quote_in_percent = 70
        balancer.CONF.max_crypto_quote_in_percent = 60

        action = balancer.meditate(65, 10000)

        self.assertEqual('BUY', action['direction'])

    @patch('balancer.calculate_target_quote', return_value=65)
    def test_meditate_quote_too_low_but_above_max_crypto_quote(self, mock_calculate_target_quote):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.max_crypto_quote_in_percent = 65

        action = balancer.meditate(66, 10000)

        self.assertIsNone(action)

    @patch('balancer.calculate_target_quote', return_value=68)
    def test_meditate_quote_too_low_and_below_max_crypto_quote(self, mock_calculate_target_quote):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.max_crypto_quote_in_percent = 70

        action = balancer.meditate(65, 10000)

        self.assertEqual('BUY', action['direction'])
        self.assertEqual(3, action['percentage'])
        self.assertEqual(10000, action['price'])

    @patch('balancer.calculate_target_quote', return_value=66.875)
    @patch('balancer.get_position_info', return_value={'currentQty': 8000})
    def test_meditate_actual_position_too_high(self, mock_get_position_info, mock_calculate_target_quote):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MMRange'

        action = balancer.meditate_bitmex(20000)

        self.assertEqual('SELL', action['direction'])
        self.assertEqual(2650, action['amount'])
        self.assertEqual(20000, action['price'])

    @patch('balancer.calculate_target_quote', return_value=66.875)
    @patch('balancer.get_position_info', return_value={'currentQty': 8000})
    def test_meditate_position_too_high_stop_sell_enabled(self, mock_get_position_info, mock_calculate_target_quote):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.stop_sell = True

        action = balancer.meditate_bitmex(20000)

        self.assertIsNone(action)

    @patch('balancer.get_margin_leverage', return_value=1.2)
    @patch('balancer.calculate_target_quote', return_value=89.375)
    @patch('balancer.get_position_info', return_value={'currentQty': 5350})
    def test_meditate_actual_position_too_low(self, mock_get_position_info, mock_calculate_target_quote, mock_get_margin_leverage):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MMRange'

        action = balancer.meditate_bitmex(14580)

        self.assertEqual('BUY', action['direction'])
        self.assertEqual(4458, action['amount'])
        self.assertEqual(14580, action['price'])

    @patch('balancer.get_margin_leverage', return_value=1.2)
    @patch('balancer.calculate_target_quote', return_value=89.375)
    @patch('balancer.get_position_info', return_value={'currentQty': '5350'})
    def test_meditate_actual_position_too_low_stop_buy_enabled(self, mock_get_position_info, mock_calculate_target_quote, mock_get_margin_leverage):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.stop_buy = True

        action = balancer.meditate_bitmex(14580)

        self.assertIsNone(action)

    @patch('balancer.calculate_target_quote', return_value=61)
    @patch('balancer.get_position_info', return_value={'currentQty': '3200'})
    def test_meditate_actual_position_too_low_but_within_tolerance(self, mock_get_position_info, mock_calculate_target_quote):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MMRange'

        action = balancer.meditate_bitmex(30000)

        self.assertIsNone(action)

    @patch('balancer.read_daily_average', return_value=1000)
    @patch('balancer.get_current_price', return_value=10000)
    def test_calculate_mayer_high(self, mock_current_price, mock_read_daily_average):
        balancer.CONF = self.create_default_conf()

        mm = balancer.get_mayer()

        self.assertEqual(10, mm['current'])

    @patch('balancer.read_daily_average', return_value=6666)
    @patch('balancer.get_current_price', return_value=9999)
    def test_calculate_mayer_average(self, mock_current_price, mock_read_daily_average):
        balancer.CONF = self.create_default_conf()

        mm = balancer.get_mayer()

        self.assertEqual(1.5, mm['current'])

    @patch('balancer.get_mayer', return_value={'current': 10})
    def test_calculate_target_quote_mm_very_high_mayer(self, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MM'

        target_quote = balancer.calculate_target_quote()

        self.assertEqual(5, target_quote)

    @patch('balancer.get_mayer', return_value={'current': 1.5})
    def test_calculate_target_quote_mm_average_mayer(self, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MM'

        target_quote = balancer.calculate_target_quote()

        self.assertAlmostEqual(33.333, target_quote, 3)

    @patch('balancer.logging')
    @patch('balancer.get_mayer', return_value={'current': 0.5})
    def test_calculate_target_quote_mm_very_low_mayer_low_max_quote(self, mock_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.max_crypto_quote_in_percent = 66
        balancer.CONF.auto_quote = 'MM'

        target_quote = balancer.calculate_target_quote()

        mock_logger.info.assert_called_with('Auto quote limited by configuration to %.2f', balancer.CONF.max_crypto_quote_in_percent)
        self.assertEqual(66, target_quote)

    @patch('balancer.logging')
    @patch('balancer.get_mayer', return_value={'current': 0.5})
    def test_calculate_target_quote_mm_very_low_mayer_default_max_quote(self, mock_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MM'

        target_quote = balancer.calculate_target_quote()

        mock_logger.info.assert_called_with('Auto quote limited by configuration to %.2f', balancer.CONF.max_crypto_quote_in_percent)
        self.assertEqual(80, target_quote)

    @patch('balancer.logging')
    @patch('balancer.get_mayer', return_value={'current': 0.5})
    def test_calculate_target_quote_mm_very_low_mayer_high_max_quote(self, mock_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.max_crypto_quote_in_percent = 100
        balancer.CONF.auto_quote = 'MM'

        target_quote = balancer.calculate_target_quote()

        mock_logger.info.assert_called_with('Auto quote %.2f @ %.2f', target_quote, 0.5)
        self.assertEqual(100, target_quote)

    @patch('balancer.logging')
    @patch('balancer.get_mayer', return_value={'current': 1.33})
    def test_calculate_target_quote_mm_bitmex_1(self, mock_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MM'
        balancer.CONF.start_mayer_multiple = 0.87

        target_quote = balancer.calculate_target_quote()

        mock_logger.info.assert_called_with('Auto quote %.2f @ %.2f', target_quote, 1.33)
        self.assertAlmostEqual(37.593984962406, target_quote, 12)

    @patch('balancer.logging')
    @patch('balancer.get_mayer', return_value={'current': 0.97})
    def test_calculate_target_quote_mm_bitmex_2(self, mock_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MM'
        balancer.CONF.start_mayer_multiple = 0.87

        target_quote = balancer.calculate_target_quote()

        mock_logger.info.assert_called_with('Auto quote %.2f @ %.2f', target_quote, 0.97)
        self.assertAlmostEqual(51.5463917525773, target_quote, 12)

    @patch('balancer.logging')
    @patch('balancer.get_mayer', return_value={'current': 2.35})
    def test_calculate_target_quote_mm_bitmex_3(self, mock_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MM'
        balancer.CONF.start_mayer_multiple = 0.87

        target_quote = balancer.calculate_target_quote()

        mock_logger.info.assert_called_with('Auto quote %.2f @ %.2f', target_quote, 2.35)
        self.assertAlmostEqual(21.2765957446808, target_quote, 12)

    @patch('balancer.logging')
    @patch('balancer.get_mayer', return_value={'current': 1.33})
    def test_calculate_target_quote_mmrange_bitmex_1(self, mock_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.mm_quote_0 = 2.4
        balancer.CONF.mm_quote_100 = 0.8

        target_quote = balancer.calculate_target_quote()

        mock_logger.info.assert_called_with('Auto quote %.2f @ %.2f', target_quote, 1.33)
        self.assertAlmostEqual(66.8750, target_quote, 12)

    @patch('balancer.logging')
    @patch('balancer.get_mayer', return_value={'current': 0.97})
    def test_calculate_target_quote_mmrange_bitmex_2(self, mock_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.mm_quote_0 = 2.4
        balancer.CONF.mm_quote_100 = 0.8
        balancer.CONF.max_crypto_quote_in_percent = 90

        target_quote = balancer.calculate_target_quote()

        mock_logger.info.assert_called_with('Auto quote %.2f @ %.2f', target_quote, 0.97)
        self.assertAlmostEqual(89.3750, target_quote, 12)

    @patch('balancer.logging')
    @patch('balancer.get_mayer', return_value={'current': 2.35})
    def test_calculate_target_quote_mmrange_bitmex_3(self, mock_mayer, mock_logger):
        balancer.LOG = mock_logger
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.mm_quote_0 = 2.4
        balancer.CONF.mm_quote_100 = 0.8

        target_quote = balancer.calculate_target_quote()

        mock_logger.info.assert_called_with('Auto quote %.2f @ %.2f', target_quote, 2.35)
        self.assertAlmostEqual(3.1250, target_quote, 12)

    @patch('balancer.get_mayer', return_value={'current': 3})
    def test_calculate_target_quote_mmrange_high_mayer(self, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.mm_quote_0 = 2
        balancer.CONF.mm_quote_100 = 1.2

        target_quote = balancer.calculate_target_quote()

        self.assertEqual(0, target_quote)

    @patch('balancer.get_mayer', return_value={'current': 1.5})
    def test_calculate_target_quote_mmrange_average_mayer(self, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.mm_quote_0 = 2
        balancer.CONF.mm_quote_100 = 1.2

        target_quote = balancer.calculate_target_quote()

        self.assertEqual(62.5, target_quote)

    @patch('balancer.get_mayer', return_value={'current': 1.5})
    def test_calculate_target_quote_mmrange_average_mayer_alternative_conf1(self, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.mm_quote_0 = 2.6
        balancer.CONF.mm_quote_100 = 1.6
        balancer.CONF.max_crypto_quote_in_percent = 100

        target_quote = balancer.calculate_target_quote()

        self.assertEqual(100, target_quote)

    @patch('balancer.get_mayer', return_value={'current': 1.5})
    def test_calculate_target_quote_mmrange_average_mayer_alternative_conf2(self, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.mm_quote_0 = 1.6
        balancer.CONF.mm_quote_100 = 0.8

        target_quote = balancer.calculate_target_quote()

        self.assertAlmostEqual(13, target_quote, 0)

    @patch('balancer.get_mayer', return_value={'current': 0.9})
    def test_calculate_target_quote_mmrange_low_mayer_limited_by_default_max_crypto_quote(self, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.mm_quote_0 = 2
        balancer.CONF.mm_quote_100 = 1.2

        target_quote = balancer.calculate_target_quote()

        self.assertEqual(80, target_quote)

    @patch('balancer.get_mayer', return_value={'current': 0.9})
    def test_calculate_target_quote_mmrange_low_mayer_alternative_conf1(self, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.mm_quote_0 = 2.6
        balancer.CONF.mm_quote_100 = 1.6
        balancer.CONF.max_crypto_quote_in_percent = 100

        target_quote = balancer.calculate_target_quote()

        self.assertEqual(100, target_quote)

    @patch('balancer.get_mayer', return_value={'current': 0.9})
    def test_calculate_target_quote_mmrange_low_mayer_alternative_conf3(self, mock_mayer):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.auto_quote = 'MMRange'
        balancer.CONF.mm_quote_0 = 1.2
        balancer.CONF.mm_quote_100 = 0.4

        target_quote = balancer.calculate_target_quote()

        self.assertAlmostEqual(37.5, target_quote, 1)

    @patch('balancer.logging')
    def test_calculate_actual_quote_very_low(self, mock_logger):
        balancer.CONF = self.create_default_conf()
        balancer.LOG = mock_logger
        balancer.BAL['cryptoBalance'] = 0.02
        balancer.BAL['totalBalanceInCrypto'] = 1.00
        balancer.BAL['price'] = 0

        quote = balancer.calculate_actual_quote()

        self.assertAlmostEqual(2, quote, 2)

    @patch('balancer.logging')
    def test_calculate_actual_quote_low(self, mock_logger):
        balancer.CONF = self.create_default_conf()
        balancer.LOG = mock_logger
        balancer.BAL['cryptoBalance'] = 1.002
        balancer.BAL['totalBalanceInCrypto'] = 2.002
        balancer.BAL['price'] = 0

        quote = balancer.calculate_actual_quote()

        self.assertAlmostEqual(50.05, quote, 2)

    @patch('balancer.logging')
    def test_calculate_actual_quote_lowest(self, mock_logger):
        balancer.CONF = self.create_default_conf()
        balancer.LOG = mock_logger
        balancer.BAL['cryptoBalance'] = 1294.79168016 / 6477
        balancer.BAL['totalBalanceInCrypto'] = 2584.87168016 / 6477
        balancer.BAL['price'] = 0

        quote = balancer.calculate_actual_quote()

        self.assertAlmostEqual(50.0911, quote, 3)

    @patch('balancer.logging')
    def test_calculate_actual_quote_high(self, mock_logger):
        balancer.CONF = self.create_default_conf()
        balancer.LOG = mock_logger
        balancer.BAL['cryptoBalance'] = 0.99
        balancer.BAL['totalBalanceInCrypto'] = 1.00
        balancer.BAL['price'] = 0

        quote = balancer.calculate_actual_quote()

        self.assertAlmostEqual(99, quote, 2)

    @patch('balancer.get_position_info', return_value={'currentQty': '20000'})
    def test_calculate_actual_quote_bitmex_max(self, mock_get_position_info):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.start_crypto_price = 40000
        balancer.CONF.start_margin_balance = 0.5

        quote = balancer.calculate_actual_quote(40000)

        self.assertEqual(100, quote)

    @patch('balancer.get_position_info', return_value={'currentQty': '10000'})
    def test_calculate_actual_quote_bitmex(self, mock_get_position_info):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.start_crypto_price = 40000
        balancer.CONF.start_margin_balance = 0.5

        quote = balancer.calculate_actual_quote(60000)

        self.assertEqual(75, quote)

    @patch('balancer.calculate_actual_quote', return_value=48.99)
    def test_append_actual_quote(self, mock_calculate_actual_quote):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.max_crypto_quote_in_percent = 50
        part = {'mail': [], 'csv': [], 'labels': []}

        balancer.append_actual_quote(part)

        self.assertEqual("49", part['csv'][0])
        self.assertEqual("Actual Quote %", part['labels'][0])

    @patch('balancer.calculate_actual_quote', return_value=49)
    def test_append_actual_quote_near_max(self, mock_calculate_actual_quote):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.max_crypto_quote_in_percent = 50
        part = {'mail': [], 'csv': [], 'labels': []}

        balancer.append_actual_quote(part)

        self.assertEqual("49", part['csv'][0])
        self.assertEqual("Actual quote:                    49%  (Max.)", part['mail'][0])
        self.assertEqual("Actual Quote %", part['labels'][0])

    def test_stats_add_same_again_day(self):
        today = {'mBal': 0.999, 'price': 10000}
        stats = balancer.Stats(int(datetime.date.today().strftime("%Y%j")), today)
        same_day = {'mBal': 0.666, 'price': 9000}

        stats.add_day(int(datetime.date.today().strftime("%Y%j")), same_day)

        day = stats.get_day(int(datetime.date.today().strftime("%Y%j")))
        self.assertTrue(isclose(day['mBal'], 0.999, rel_tol=1e-09, abs_tol=1e-09))
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

    @patch('balancer.persist_statistics')
    def test_calculate_statistics_first_day_without_persist(self, mock_persist_statistics):
        today = balancer.calculate_daily_statistics(90, 110, 8000.0, None, False)

        self.assertTrue(today['mBal'] == 90)
        self.assertTrue(today['fmBal'] == 110)
        self.assertTrue(isclose(today['price'], 8000.0, rel_tol=1e-09, abs_tol=1e-09))
        mock_persist_statistics.assert_not_called()

    def test_calculate_statistics_positive_change(self):
        stats = balancer.Stats(int(datetime.date.today().strftime("%Y%j")) - 1, {'mBal': 50.1, 'fmBal': 100, 'price': 8000.0})
        today = balancer.calculate_daily_statistics(100.2, 105, 8800.0, stats, False)

        self.assertEqual(100.2, today['mBal'])
        self.assertEqual(105, today['fmBal'])
        self.assertEqual(8800.0, today['price'])
        self.assertEqual(100.0, today['mBalChan24'])
        self.assertEqual(5, today['fmBalChan24'])
        self.assertEqual(10.0, today['priceChan24'])

    @patch('balancer.persist_statistics')
    def test_calculate_statistics_negative_change(self, mock_persist_statistics):
        stats = balancer.Stats(int(datetime.date.today().strftime("%Y%j")) - 1, {'mBal': 150.3, 'fmBal': 100, 'price': 8000.0})
        today = balancer.calculate_daily_statistics(100.2, 90, 7600.0, stats, True)

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
        self.assertEqual('T', balancer.CONF.report)
        self.assertEqual(50, balancer.CONF.crypto_quote_in_percent)
        self.assertEqual('Test', balancer.CONF.info)
        self.assertEqual('', balancer.CONF.start_date)

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
        mock_kraken.private_post_tradebalance.return_value = {'result': {'e': 150}}

        balance = balancer.get_margin_balance()

        mock_kraken.private_post_tradebalance.assert_called()
        self.assertEqual(150, balance)

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
    def test_cancel_order_success(self, mock_fetch_order_status, mock_cancel_order, mock_logging):
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

        return1 = balancer.cancel_order(order1)
        mock_cancel_order.assert_called()
        self.assertIsNone(return1)

        return2 = balancer.cancel_order(order2)
        mock_logging.warning.assert_called_with('Order to be canceled %s was in state %s', str(order2), 'canceled')
        self.assertIsNone(return2)

    @patch('balancer.logging')
    @mock.patch.object(ccxt.kraken, 'cancel_order')
    @mock.patch.object(ccxt.kraken, 'fetch_order_status')
    def test_cancel_order_already_filled(self, mock_fetch_order_status, mock_cancel_order, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.test = False
        balancer.LOG = mock_logging
        balancer.EXCHANGE = balancer.connect_to_exchange()

        order1 = balancer.Order({'side': 'sell', 'id': 's1o', 'price': 10000, 'amount': 100,
                                 'datetime': datetime.datetime.today().isoformat()})

        return_values = {'s1o': 'filled'}
        mock_fetch_order_status.side_effect = return_values.get

        return1 = balancer.cancel_order(order1)
        mock_cancel_order.assert_not_called()
        self.assertEqual(order1, return1)

    @patch('balancer.logging')
    @mock.patch.object(ccxt.kraken, 'cancel_order')
    @mock.patch.object(ccxt.kraken, 'fetch_order_status')
    def test_cancel_order_not_found_already_filled(self, mock_fetch_order_status, mock_cancel_order, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.test = False
        balancer.LOG = mock_logging
        balancer.EXCHANGE = balancer.connect_to_exchange()

        order1 = balancer.Order({'side': 'sell', 'id': 's1o', 'price': 10000, 'amount': 100,
                                 'datetime': datetime.datetime.today().isoformat()})

        return_values = {'s1o': 'open'}
        mock_fetch_order_status.side_effect = return_values.get
        mock_cancel_order.side_effect = ccxt.OrderNotFound('kraken cancelOrder() error {"error":["EOrder:Unknown order"]}')

        return1 = balancer.cancel_order(order1)
        self.assertEqual(order1, return1)

    @patch('balancer.logging')
    @mock.patch.object(ccxt.bitmex, 'cancel_order')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    def test_cancel_order_not_found_already_filled_bitmex(self, mock_fetch_order_status, mock_cancel_order, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.LOG = mock_logging
        balancer.EXCHANGE = balancer.connect_to_exchange()

        order1 = balancer.Order({'side': 'sell', 'id': 's1o', 'price': 10000, 'amount': 100,
                                 'datetime': datetime.datetime.today().isoformat()})

        return_values = {'s1o': 'open'}
        mock_fetch_order_status.side_effect = return_values.get
        mock_cancel_order.side_effect = ccxt.OrderNotFound('bitmex cancelOrder() failed: Unable to cancel order due to existing state: Filled')

        return1 = balancer.cancel_order(order1)
        self.assertEqual(order1, return1)

    @patch('balancer.logging')
    @patch('ccxt.kraken')
    def test_get_closed_orders_should_return_most_recent_order(self, mock_kraken, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.EXCHANGE = mock_kraken
        balancer.LOG = mock_logging

        mock_kraken.fetch_closed_orders.return_value = [{'id': 1, 'side': 'buy', 'price': 40400.3, 'amount': 0.00161055, 'status': 'closed', 'datetime': '2021-08-16T16:02:13.214Z'}, {'id': 2, 'side': 'sell', 'price': 42450.1, 'amount': 0.00151015, 'status': 'closed', 'datetime': '2021-08-06T16:02:13.214Z'}]

        last_order = balancer.get_closed_order()

        self.assertEqual(1, last_order.id)

    @patch('balancer.logging')
    @patch('ccxt.kraken')
    def test_get_closed_orders_should_filter_canceled(self, mock_kraken, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.EXCHANGE = mock_kraken
        balancer.LOG = mock_logging

        mock_kraken.fetch_closed_orders.return_value = [{'id': 1, 'side': 'buy', 'price': 40400.3, 'amount': 0.00161055, 'status': 'canceled', 'datetime': '2021-08-16T16:02:13.214Z'}, {'id': 2, 'side': 'sell', 'price': 42450.1, 'amount': 0.00151015, 'status': 'closed', 'datetime': '2021-08-06T16:02:13.214Z'}]

        last_order = balancer.get_closed_order()

        self.assertEqual(2, last_order.id)

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

        balancer.create_sell_order(sell_price, amount_crypto, None)

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

        balancer.create_sell_order(sell_price, amount_crypto, None)

        mock_bitmex.create_limit_sell_order.assert_called_with(balancer.CONF.symbol, round(amount_crypto * sell_price, -2), sell_price)

    @patch('balancer.logging')
    @patch('ccxt.bitmex')
    def test_create_sell_order_should_call_create_limit_sell_order_with_provided_fiat_amount(self, mock_bitmex, mock_logging):
        sell_price = 10000
        amount_fiat = 180
        balancer.LOG = mock_logging
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.EXCHANGE = mock_bitmex
        mock_bitmex.create_limit_sell_order.return_value = {'id': 1, 'price': sell_price, 'amount': amount_fiat,
                                                            'side': 'sell', 'datetime': str(datetime.datetime.utcnow())}

        balancer.create_sell_order(sell_price, None, amount_fiat)

        mock_bitmex.create_limit_sell_order.assert_called_with(balancer.CONF.symbol, round(amount_fiat, -2), sell_price)

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

        balancer.create_buy_order(buy_price, amount_crypto, None)

        mock_kraken.create_limit_buy_order.assert_called_with(balancer.CONF.pair, amount_crypto, buy_price, {'oflags': 'fcib'})

    def test_evaluate_mayer_buy(self):
        advice = balancer.evaluate_mayer({'current': 1, 'average': 1.5})

        self.assertEqual('BUY', advice)

    def test_evaluate_mayer_sell(self):
        advice = balancer.evaluate_mayer({'current': 2.5, 'average': 1.5})

        self.assertEqual('SELL', advice)

    def test_evaluate_mayer_hold(self):
        advice = balancer.evaluate_mayer({'current': 2.2, 'average': 1.5})

        self.assertEqual('HOLD', advice)

    def test_evaluate_mayer_na(self):
        advice = balancer.evaluate_mayer()

        self.assertEqual('n/a', advice)

    def test_append_performance(self):
        balancer.CONF = self.create_default_conf()
        part = {'mail': [], 'csv': [], 'labels': []}
        balancer.append_performance(part, 100.2, 50.1)
        mail_part = ''.join(part['mail'])
        csv_part = ''.join(part['csv'])

        self.assertTrue(mail_part.rfind('100.00%)') > 0)
        self.assertTrue(csv_part.rfind('50.1') > 0)

    def test_append_performance_no_deposits(self):
        balancer.CONF = self.create_default_conf()
        part = {'mail': [], 'csv': [], 'labels': []}
        balancer.append_performance(part, 100.2, None)
        mail_part = ''.join(part['mail'])
        csv_part = ''.join(part['csv'])

        self.assertTrue(mail_part.rfind('n/a') > 0)
        self.assertTrue(csv_part.rfind('n/a') > 0)

    def test_append_net_change_positive_fiat(self):
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'mBal': 1, 'fmBal': 10100}
        yesterday = {'mBal': 1, 'fmBal': 10000, 'price': 10000}

        balancer.append_value_change(part, today, yesterday, 10000)

        self.assertEqual('+0.50', part['csv'][0])
        self.assertEqual('Value Change %', part['labels'][0])

    def test_append_net_change_positive_crypto(self):
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'mBal': 1.01, 'fmBal': 10000}
        yesterday = {'mBal': 1, 'fmBal': 10000, 'price': 10000}

        balancer.append_value_change(part, today, yesterday, 10000)

        self.assertEqual('+0.50', part['csv'][0])
        self.assertEqual('Value Change %', part['labels'][0])

    def test_append_net_change_positive_crypto_by_price(self):
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'mBal': 1, 'fmBal': 4000}
        yesterday = {'mBal': 1, 'fmBal': 4000, 'price': 10000}

        balancer.append_value_change(part, today, yesterday, 10070)

        self.assertEqual('+0.50', part['csv'][0])
        self.assertEqual('Value Change %', part['labels'][0])

    def test_append_net_change_negative_fiat(self):
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'mBal': 1, 'fmBal': 10000}
        yesterday = {'mBal': 1, 'fmBal': 10100, 'price': 10000}

        balancer.append_value_change(part, today, yesterday, 10000)

        self.assertEqual('-0.50', part['csv'][0])
        self.assertEqual('Value Change %', part['labels'][0])

    def test_append_net_change_negative_crypto(self):
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'mBal': 1, 'fmBal': 10000}
        yesterday = {'mBal': 1.01, 'fmBal': 10000, 'price': 10000}

        balancer.append_value_change(part, today, yesterday, 10000)

        self.assertEqual('-0.50', part['csv'][0])
        self.assertEqual('Value Change %', part['labels'][0])

    def test_append_net_change_negative_crypto_by_price(self):
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'mBal': 1, 'fmBal': 10000}
        yesterday = {'mBal': 1, 'fmBal': 10000, 'price': 10100}

        balancer.append_value_change(part, today, yesterday, 10000)

        self.assertEqual('-0.50', part['csv'][0])
        self.assertEqual('Value Change %', part['labels'][0])

    def test_append_trading_result_positive(self):
        balancer.CONF.quote = 'EUR'
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'mBal': 0.1, 'fmBal': 10002.50}
        yesterday = {'mBal': 0.09, 'fmBal': 10100.00}

        balancer.append_trading_result(part, today, yesterday, 10000)

        self.assertEqual('+2', part['csv'][0])
        self.assertEqual('Trading Result EUR', part['labels'][0])

    def test_append_trading_result_negative(self):
        balancer.CONF.quote = 'EUR'
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'mBal': 0.1, 'fmBal': 9999}
        yesterday = {'mBal': 0.09, 'fmBal': 10100}

        balancer.append_trading_result(part, today, yesterday, 10000)

        self.assertEqual('-1', part['csv'][0])
        self.assertEqual('Trading Result EUR', part['labels'][0])

    def test_append_trading_result_real_life_positive(self):
        balancer.CONF.quote = 'USD'
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'mBal': 0.2775, 'fmBal': 3132.82}
        yesterday = {'mBal': 0.2746, 'fmBal': 3164.98}

        balancer.append_trading_result(part, today, yesterday, 11222)

        self.assertEqual('+0', part['csv'][0])
        self.assertEqual('Trading Result USD', part['labels'][0])

    def test_append_trading_result_real_life_negative(self):
        balancer.CONF.quote = 'EUR'
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'mBal': 0.29208266, 'fmBal': 3716.1498}
        yesterday = {'mBal': 0.24747199, 'fmBal': 4124.5834}

        balancer.append_trading_result(part, today, yesterday, 9061)

        self.assertEqual('-4', part['csv'][0])
        self.assertEqual('Trading Result EUR', part['labels'][0])

    def test_append_price_change(self):
        balancer.CONF = self.create_default_conf()
        part = {'mail': [], 'csv': [], 'labels': []}
        today = {'priceChan24': +0.21}

        balancer.append_price_change(part, today, 100)

        self.assertEqual('100;+0.21', part['csv'][0])
        self.assertEqual('BTC Price EUR', part['labels'][0])

    def test_append_liquidation_price_kraken(self):
        balancer.CONF = self.create_default_conf()
        part = {'mail': [], 'csv': [], 'labels': []}

        balancer.append_liquidation_price(part)

        self.assertEqual('n/a', part['csv'][0])
        self.assertEqual('Liq. Price EUR', part['labels'][0])

    @patch('balancer.get_position_info', return_value={'liquidationPrice': '10000'})
    def test_append_liquidation_price_bitmex(self, mock_position_info):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.quote = 'USD'
        part = {'mail': [], 'csv': [], 'labels': []}

        balancer.append_liquidation_price(part)

        self.assertEqual('10000', part['csv'][0])
        self.assertEqual('Liq. Price USD', part['labels'][0])

    @patch('ccxt.kraken')
    def test_get_net_deposits(self, mock_kraken):
        balancer.CONF = self.create_default_conf()
        balancer.EXCHANGE = mock_kraken

        balancer.get_net_deposits()

        mock_kraken.fetch_deposits.assert_called_with('BTC')

    @patch('ccxt.bitmex')
    def test_get_net_deposits_bitmex(self, mock_bitmex):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.EXCHANGE = mock_bitmex

        balancer.get_net_deposits()

        mock_bitmex.private_get_user_wallet.assert_called_with({'currency': 'XBt'})

    @patch('ccxt.kraken')
    def test_get_net_deposits_from_config(self, mock_kraken):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.net_deposits_in_base_currency = 0.1
        balancer.EXCHANGE = mock_kraken

        net_deposit = balancer.get_net_deposits()

        mock_kraken.fetch_deposits.assert_not_called()
        self.assertEqual(balancer.CONF.net_deposits_in_base_currency, net_deposit)

    @mock.patch.object(balancer, 'ExchangeConfig')
    @patch('balancer.update_deposits')
    @patch('balancer.get_net_deposits', return_value=1.5)
    def test_check_net_deposits_without_reference_net_deposit(self, mock_get_net_deposits, mock_update_deposits, mock_exchange_config):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.reference_net_deposits = 0.0

        balancer.check_deposits()

        mock_update_deposits.assert_called_with(1.5)

    @mock.patch.object(balancer, 'ExchangeConfig')
    @patch('balancer.update_deposits')
    @patch('balancer.get_net_deposits', return_value=1.5)
    def test_check_net_deposits_deposit(self, mock_get_net_deposits, mock_update_deposits, mock_exchange_config):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.reference_net_deposits = 1.0

        balancer.check_deposits()

        mock_update_deposits.assert_called_with(1.5, 0.5)

    @mock.patch.object(balancer, 'ExchangeConfig')
    @patch('balancer.update_deposits')
    @patch('balancer.get_net_deposits', return_value=1)
    def test_check_net_deposits_withdraw(self, mock_get_net_deposits, mock_update_deposits, mock_exchange_config):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.reference_net_deposits = 1.5

        balancer.check_deposits()

        mock_update_deposits.assert_called_with(1, -0.5)

    @patch('balancer.logging')
    @patch('configparser.ConfigParser')
    def test_update_deposits(self, mock_configparser, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.start_margin_balance = 2
        balancer.CONF.net_deposits_in_base_currency = 0
        balancer.INSTANCE = ''
        balancer.DATA_DIR = ''
        balancer.LOG = mock_logging
        diff = -0.05
        reference_deposits = 1.05

        balancer.update_deposits(reference_deposits, diff)

        mock_logging.info.assert_called_with('Updated start margin and reference deposits: %s %s (%s)', str(1.95), str(reference_deposits), str(diff))

    @patch('balancer.logging')
    @patch('configparser.ConfigParser')
    def test_update_reference_deposits_and_net_deposits(self, mock_configparser, mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.start_margin_balance = 2
        balancer.CONF.net_deposits_in_base_currency = 1
        balancer.INSTANCE = ''
        balancer.DATA_DIR = ''
        balancer.LOG = mock_logging
        diff = -0.05
        reference_deposits = 1.05

        balancer.update_deposits(reference_deposits, diff)

        mock_logging.info.assert_called_with('Updated start margin, reference and net deposits: %s %s %s (%s)', str(1.95), str(reference_deposits), str(0.95), str(diff))

    @patch('balancer.logging')
    @patch('configparser.ConfigParser')
    def test_update_deposits_with_zero_difference(self, mock_conf_read,  mock_logging):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'
        balancer.CONF.start_margin_balance = 2
        balancer.INSTANCE = ''
        balancer.DATA_DIR = ''
        balancer.LOG = mock_logging
        net_deposits = 1.05

        balancer.update_deposits(net_deposits)

        mock_logging.info.assert_called_with('Initialized reference deposits: %s', str(net_deposits))

    @patch('balancer.logging')
    @patch('balancer.deactivate_bot')
    def test_handle_account_errors_miss(self, mock_deactivate_bot, mock_logging):
        balancer.LOG = mock_logging

        balancer.handle_account_errors('error')

        mock_logging.error.assert_not_called()
        mock_deactivate_bot.assert_not_called()

    @patch('balancer.logging')
    @patch('balancer.deactivate_bot')
    def test_handle_account_errors_match(self, mock_deactivate_bot, mock_logging):
        balancer.LOG = mock_logging

        balancer.handle_account_errors('account has been disabled')

        mock_logging.error.assert_called()
        mock_deactivate_bot.assert_called()

    @patch('balancer.logging')
    @patch('balancer.send_mail')
    @patch('os.remove')
    def test_deactivate_bot(self, mock_os_remove, mock_send_mail, mock_logging):
        balancer.LOG = mock_logging
        balancer.INSTANCE = 'test'
        message = 'bang!'

        with self.assertRaises(SystemExit):
            balancer.deactivate_bot(message)

        mock_logging.error.assert_called()
        mock_send_mail.assert_called_with('Deactivated RB ' + balancer.INSTANCE, message)

    def test_is_due_date(self):
        balancer.CONF = self.create_default_conf()
        day = datetime.date.replace(datetime.date.today(), 2020, 2, 28)
        balancer.CONF.report = 'A'
        self.assertFalse(balancer.is_due_date(day))
        balancer.CONF.report = 'M'
        self.assertFalse(balancer.is_due_date(day))
        balancer.CONF.report = 'D'
        self.assertTrue(balancer.is_due_date(day))
        balancer.CONF.report = 'T'
        self.assertTrue(balancer.is_due_date(day))

        day = datetime.date.replace(datetime.date.today(), 2020, 2, 29)
        balancer.CONF.report = 'A'
        self.assertFalse(balancer.is_due_date(day))
        balancer.CONF.report = 'M'
        self.assertTrue(balancer.is_due_date(day))
        balancer.CONF.report = 'D'
        self.assertTrue(balancer.is_due_date(day))
        balancer.CONF.report = 'T'
        self.assertTrue(balancer.is_due_date(day))

        day = datetime.date.replace(datetime.date.today(), 2020, 12, 31)
        balancer.CONF.report = 'A'
        self.assertTrue(balancer.is_due_date(day))
        balancer.CONF.report = 'M'
        self.assertTrue(balancer.is_due_date(day))
        balancer.CONF.report = 'D'
        self.assertTrue(balancer.is_due_date(day))
        balancer.CONF.report = 'T'
        self.assertTrue(balancer.is_due_date(day))

    def test_sleep_for(self):
        before = time.time()

        balancer.sleep_for(1, 2)

        after = time.time()
        diff = after - before
        self.assertGreater(diff, 1, 'Should have slept for more than 1 second, but did not')
        self.assertLessEqual(diff, 2, 'Should have slept for less than 2 seconds, but did not')

    def test_compute_amount_from_fiat_amount_has_priority(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'

        self.assertEqual(balancer.compute_amount(0.001, 30000, 400), 400)

    def test_compute_amount_from_amount_and_price(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'

        self.assertEqual(balancer.compute_amount(0.01, 30000), 300)

    def test_compute_amount_from_amount_if_amount_already_fiat(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'bitmex'

        self.assertEqual(balancer.compute_amount(100, 30000), 100)

    def test_compute_amount_from_amount_if_not_bitmex(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'kraken'

        self.assertEqual(balancer.compute_amount(10, 30000), 10)

    def test_compute_amount_from_cctx_amount_has_priority_if_not_bitmex(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'coinbase'

        self.assertEqual(balancer.compute_amount(0.1, None, None, 0.01), 0.1)

    def test_compute_amount_use_from_amount_crypto_has_as_fallback_if_not_bitmex(self):
        balancer.CONF = self.create_default_conf()
        balancer.CONF.exchange = 'coinbase'

        self.assertEqual(balancer.compute_amount(None, None, None, 0.01), 0.01)

    def test_set_price_from_cctx_price_has_priority(self):

        self.assertEqual(balancer.set_price(38000.1, 39000), 38000)

    def test_set_price_from_price_as_fallback(self):

        self.assertEqual(balancer.set_price(None, 39000.1), 39000)

    @staticmethod
    def create_default_conf():
        conf = balancer.ExchangeConfig
        conf.exchange = 'kraken'
        conf.api_key = '1234'
        conf.api_secret = 'secret'
        conf.api_password = ''
        conf.test = True
        conf.pair = 'BTC/EUR'
        conf.symbol = 'XBTEUR'
        conf.start_crypto_price = 20000
        conf.start_margin_balance = 0.4
        conf.start_mayer_multiple = 1.3
        conf.start_date = ''
        conf.reference_net_deposits = 0.0
        conf.net_deposits_in_base_currency = 0
        conf.base = 'BTC'
        conf.quote = 'EUR'
        conf.satoshi_factor = 0.00000001
        conf.bot_version = '0.0.1'
        conf.trade_trials = 5
        conf.order_adjust_seconds = 90
        conf.trade_advantage_in_percent = 0.02
        conf.crypto_quote_in_percent = 50
        conf.auto_quote = 'OFF'
        conf.mm_quote_0 = 2
        conf.mm_quote_100 = 1.2
        conf.max_crypto_quote_in_percent = 80
        conf.max_leverage_in_percent = 160
        conf.tolerance_in_percent = 2
        conf.period_in_minutes = 10
        conf.stop_buy = False
        conf.stop_sell = False
        conf.backtrade_only_on_profit = False
        conf.report = 'T'
        conf.info = ''
        conf.url = 'http://example.org'
        conf.mail_server = 'smtp.example.org'
        conf.sender_address = 'test@example.org'
        conf.recipient_addresses = ''
        return conf


if __name__ == '__main__':
    unittest.main()
