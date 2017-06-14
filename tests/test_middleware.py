# -*- coding: utf-8 -*-

import unittest
from datetime import datetime

from scrapy.exceptions import NotConfigured
from scrapy.utils.test import get_crawler

from history.middleware import HistoryMiddleware

MANDATORY_SETTINGS = ['HISTORY_S3_BUCKET',
                      'AWS_ACCESS_KEY_ID',
                      'AWS_SECRET_ACCESS_KEY']


class TestHistoryMiddleware(unittest.TestCase):

    def setUp(self):
        settings_dict = {k: 'mock setting' for k in MANDATORY_SETTINGS}
        crawler = get_crawler(settings_dict=settings_dict)
        self.middleware = HistoryMiddleware(crawler)

    def test_unconfigured_init(self):
        with self.assertRaises(NotConfigured):
            self.middleware = HistoryMiddleware(get_crawler())

    def test_parse_epoch(self):
        self.assertIsInstance(
            self.middleware.parse_epoch('yesterday'),
            datetime)
