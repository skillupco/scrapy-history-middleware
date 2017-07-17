# -*- coding: utf-8 -*-

from datetime import datetime

from parsedatetime import parsedatetime, Constants
from scrapy import signals
from scrapy.exceptions import NotConfigured, IgnoreRequest
from scrapy.utils.misc import load_object

MANDATORY_SETTINGS = ['HISTORY_S3_BUCKET',
                      'AWS_ACCESS_KEY_ID',
                      'AWS_SECRET_ACCESS_KEY']
EPOCH_DATE_FORMAT = '%Y%m%d'


def ignore_on_fail(func):
    def _inner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            raise IgnoreRequest('middleware crashed: {err}'.format(err=e))
    return _inner


class HistoryMiddleware(object):

    def __init__(self, crawler):
        self.stats = crawler.stats
        settings = crawler.settings

        configured = all([settings.get(k, False) for k in MANDATORY_SETTINGS])
        if not configured:
            # deactivate the login if we can't talk to S3 anyway
            raise NotConfigured('__init__')

        # EPOCH:
        #   == False: don't retrieve historical data
        #   == True : retrieve most recent version
        #   == datetime(): retrieve next version after datetime()
        self.epoch = self.parse_epoch(settings.get('HISTORY_EPOCH', False))
        self.retrieve_if = load_object(
            settings.get('HISTORY_RETRIEVE_IF', 'history.logic.RetrieveNever'))(settings)
        self.store_if = load_object(
            settings.get('HISTORY_STORE_IF', 'history.logic.StoreAlways'))(settings)
        self.storage = load_object(
            settings.get('HISTORY_BACKEND',
                         'history.storage.S3CacheStorage'))(self.stats, settings)
        self.ignore_missing = settings.getbool('HTTPCACHE_IGNORE_MISSING')

    @classmethod
    def from_crawler(cls, crawler):
        # instantiate the extension object
        ext = cls()

        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)

        return cls(crawler)

    def spider_opened(self, spider):
        self.storage.open_spider(spider)
        self.store_if.spider_opened(spider)
        self.retrieve_if.spider_opened(spider)

    def spider_closed(self, spider):
        self.storage.close_spider(spider)
        self.store_if.spider_closed(spider)
        self.retrieve_if.spider_closed(spider)

    @ignore_on_fail
    def process_request(self, request, spider):
        """A request is approaching the Downloader.

        Decide if we would like to intercept the request and supply a
        response ourselves.
        """
        if self.epoch and self.retrieve_if(spider, request):
            request.meta['epoch'] = self.epoch
            response = self.storage.retrieve_response(spider, request)
            if response:
                response.flags.append('historic')
                return response
            elif self.ignore_missing:
                raise IgnoreRequest("Ignored; request not in history: %s" % request)

    @ignore_on_fail
    def process_response(self, request, response, spider):
        """A response is leaving the Downloader. It was either retreived
        from the web or from another middleware.

        Decide if we would like to store it in the history.
        """
        if self.store_if(spider, request, response):
            self.storage.store_response(spider, request, response)
            self.stats.set_value('history/cached', True, spider=spider)

        return response

    @staticmethod
    def parse_epoch(epoch):
        if isinstance(epoch, bool) or isinstance(epoch, datetime):
            return epoch
        elif epoch == 'True':
            return True
        elif epoch == 'False':
            return False

        try:
            return datetime.strptime(epoch, EPOCH_DATE_FORMAT)
        except ValueError:
            pass

        parser = parsedatetime.Calendar(Constants())
        time_tupple = parser.parse(epoch)  # 'yesterday' => (time.struct_time, int)
        if not time_tupple[1]:
            raise NotConfigured('Could not parse epoch: %s' % epoch)

        time_struct = time_tupple[0]

        return datetime(*time_struct[:6])
