import unittest
from datetime import datetime
from unittest.mock import patch

import mayer


class MayerTest(unittest.TestCase):

    def test_calculate_average_first(self):
        avg = mayer.calculate_daily_average({0: 1, 1: 15000}, 18000)

        self.assertEqual(16500, avg)

    def test_calculate_average(self):
        avg = mayer.calculate_daily_average({0: 2, 1: 15000}, 18000)

        self.assertEqual(16000, avg)

    @patch('mayer.logging')
    @patch('mayer.sleep_for')
    @patch('mayer.get_average', return_value={0: 20000})
    @patch('mayer.write_average_file')
    def test_update_average(self, mock_write_average_file, mock_get_average, mock_sleep, mock_logger):
        mayer.LOG = mock_logger
        mayer.update_average()

        mock_write_average_file.assert_called_with(20000)

    @patch('mayer.sleep_for')
    @patch('mayer.get_current_price', return_value=20000)
    @patch('mayer.persist_rate')
    def test_update_rates(self, mock_persis_rate, mock_current_price, mock_sleep):
        mayer.update_rates()

        mock_persis_rate.assert_called_with(20000)

    @patch('mayer.sleep_for')
    @patch('mayer.get_current_price', return_value=None)
    @patch('mayer.get_last_rate', return_value={0: 20000})
    @patch('mayer.persist_rate')
    def test_update_rates_failed_current_price(self, mock_persis_rate, mock_last_rate, mock_current_price, mock_sleep):
        mayer.update_rates()

        mock_last_rate.assert_called()
        mock_persis_rate.assert_called_with(20000)

    @patch('mayer.get_last_date', return_value=datetime.strptime('2021-01-01', '%Y-%m-%d').date())
    @patch('mayer.complete_data')
    def test_check_data(self, mock_complete_data, mock_get_last_date):
        mayer.check_data()

        mock_complete_data.assert_called_with(datetime.strptime('2021-01-01', '%Y-%m-%d').date())

    @patch('mayer.add_entry')
    @patch('mayer.fetch_rates',
           return_value=[{'Date': '2020-12-31', 'Price': 30030.3030}, {'Date': '2021-01-01', 'Price': 31031.3131},
                         {'Date': '2021-01-02', 'Price': 32032.3232}])
    def test_complete_data(self, mock_fetch_rates, mock_add_entry):
        mayer.complete_data(datetime.strptime('2021-01-01', '%Y-%m-%d').date())

        mock_add_entry.assert_called_with('2021-01-02', 32032.3232)


if __name__ == '__main__':
    unittest.main()
