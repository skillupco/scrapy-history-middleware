from __future__ import unicode_literals

from datetime import datetime
import logging
import boto
import base64
import json
import urllib

from scrapy import log
from scrapy.conf import settings
from scrapy.utils.request import request_fingerprint
from scrapy.responsetypes import responsetypes
from scrapy.http import TextResponse, Headers


logger = logging.getLogger(__name__)

class S3CacheStorage(object):

    def __init__(self, stats, settings=settings):
        # Required settings
        self.S3_ACCESS_KEY   = settings.get('AWS_ACCESS_KEY_ID')
        self.S3_SECRET_KEY   = settings.get('AWS_SECRET_ACCESS_KEY')
        self.S3_CACHE_BUCKET = settings.get('HISTORY_S3_BUCKET')

        # Optional settings
        self.use_proxy = settings.getbool('HISTORY_USE_PROXY', True)
        self.SAVE_SOURCE = settings.get('HISTORY_SAVE_SOURCE')
        self.stats = stats


    def _get_key(self, spider, request):
        key = request_fingerprint(request)
        return '%s/cache/%s' % (spider.name, key)

    def open_spider(self, spider):
        self.s3_connection = boto.connect_s3(self.S3_ACCESS_KEY, self.S3_SECRET_KEY, is_secure=False)
        self.s3_connection.use_proxy = self.use_proxy
        #use spider fields to replace var in bucket string
        if self.S3_CACHE_BUCKET:
            self.S3_CACHE_BUCKET = self.S3_CACHE_BUCKET % self._get_uri_params(spider)

        self.s3_bucket = self.s3_connection.get_bucket(self.S3_CACHE_BUCKET, validate=False)
        #self.versioning = self.s3_bucket.get_versioning_status() #=> {} or {'Versioning': 'Enabled'}

    def close_spider(self, spider):
        self.s3_connection.close()

    def _get_s3_key(self, key, epoch):
        """
        Return key with timestamp >= epoch.

        If epoch is not a datetime then just return the first key.

        The versions of a key in s3 are stored according to the time
        they were added. Thus the first result of element in
        s3_bucket.list_versions() is the most recent.

        s3_key.name: 0805...
               version_id  last_modified
               X72xb...    2012-04-17T02:25:37.000Z
               EFTqO...    2012-04-17T02:05:38.000Z
               zQtzi...    2012-04-16T23:01:53.000Z
               null        2012-04-14T11:47:16.000Z *

               * versioning was not enabled at this point
        """
        # list_versions returns an iterator interface; build an actual
        # iterator
        s3_keys = iter(self.s3_bucket.list_versions(prefix=key))

        # Since we assume the keys are returned in order of
        # modification the first key is the most recent result
        first_key = next(s3_keys, None)

        # We can only do version checks if we have a datetime to
        # compare with
        if not isinstance(epoch, datetime):
            return first_key

        # Try to find the first key that occurred after epoch but
        # iterating backward through time
        last_key = first_key
        for s3_key in s3_keys:
            if boto.utils.parse_ts(s3_key.last_modified) < epoch:
                return last_key
            else:
                last_key = s3_key

        # Nothing occured before epoch, therefore last_key is closest
        # to epoch
        return last_key

    def retrieve_response(self, spider, request):
        """
        Return response if present in cache, or None otherwise.
        """
        key = self._get_key(spider, request)

        epoch = request.meta.get('epoch') # guaranteed to be True or datetime
        s3_key = self._get_s3_key(key, epoch)
        logger.debug('S3Storage retrieving response for key %s.' % (s3_key))

        if not s3_key:
            return

        logger.info('S3Storage (epoch => %s): retrieving response for %s.' % (epoch, request.url))
        try:
            data_string = s3_key.get_contents_as_string()
        except boto.exception.S3ResponseError as e:
            # See store_response for error descriptions
            raise e
        finally:
            s3_key.close()

        data = json.loads(data_string)

        metadata         = data['metadata']
        request_headers  = Headers(data['request_headers'])
        request_body     = data['request_body']
        response_headers = Headers(data['response_headers'])
        response_body    = data['response_body']

        if 'binary' in data and data['binary'] == True:
            response_body = base64.decode(response_body)

        url      = metadata['response_url']
        status   = metadata.get('status')

        # bug in scrapy 1.0
        Response = responsetypes.from_args(headers=response_headers, url=url, body=response_body)
        return Response(url=url, headers=response_headers, status=status, body=response_body)

    def store_response(self, spider, request, response):
        """
        Store the given response in the cache.
        """
        logger.info('S3Storage: storing response for %s.' % request.url)
        key = self._get_key(spider, request)

        logger.info('S3Storage: path %s' % key)
        logger.debug('S3Storage: response type {} '.format(type(response)))
        if isinstance(response, TextResponse):
            # Textual response (HTMl, XML, csv, etc.), decoded to unicode using encoding (from Content-Type)
            binary = False
            response_body = response.body.decode(response.encoding)
            logger.debug('S3Storage: encoding {} '.format(response.encoding))
        else:
            # Binary response (excel, pdf, etc.)
            binary = True
            response_body = base64.b64encode(response.body)
            logger.debug('S3Storage: body type {} '.format(type(response._body)))
            logger.debug('S3Storage: responsetypes {}'.format(responsetypes.from_args(headers=response.headers, url=response.url, body=response.body)))
        logger.debug('S3Storage: request header {}'.format(request.headers))
        logger.debug('S3Storage: response header {}'.format(response.headers))

        metadata = {
            'url': request.url,
            'method': request.method,
            'status': response.status,
            'response_url': response.url,
            #'timestamp': time(), # This will become the epoch
        }

        data = {
            'binary': binary,
            'metadata'        : metadata,
            'request_headers' : request.headers,
            'request_body'    : request.body,
            'response_headers': response.headers,
            'response_body'   : response_body
        }

        data_string = json.dumps(data, ensure_ascii=False, encoding='utf-8')


        # sometimes can cause memory error in SH if too big
        logger.debug('S3Storage: request/response json object size  {} kB'.format(len(data_string) / 1024))

        # With versioning enabled creating a new s3_key is not
        # necessary. We could just write over an old s3_key. However,
        # the cost to GET the old s3_key is higher than the cost to
        # simply regenerate it using self._get_key().
        s3_key = self.s3_bucket.new_key(key)

        try:
            #s3_key.update_metadata(metadata) #=> can't use this as need to cast to unicode
            for k, v in metadata.items():
                if isinstance(v, str):
                    v = v[:400] + '...' if len(v) > 400 else v
                s3_key.set_metadata(k, unicode(v))
            s3_key.set_contents_from_string(data_string)

            #save source file
            if self.SAVE_SOURCE:
                job_folder = self.SAVE_SOURCE % self._get_uri_params(spider)
                # if the S3 key is too long, the AWS interface does not allow to download the file !
                source_url = request.url[:200] + '...' if len(request.url) > 200 else request.url

                source_name = "{}/source/{}__{}".format(job_folder, request_fingerprint(request), urllib.quote_plus(source_url))
                source_key = self.s3_bucket.new_key(source_name)
                source_key.set_contents_from_string(response.body)
                # sometimes can cause memory error in SH if too big
                logger.debug('S3Storage: body size  {} kB'.format(len(response.body) / 1024))
        except boto.exception.S3ResponseError as e:
            # http://docs.pythonboto.org/en/latest/ref/boto.html#module-boto.exception
            #   S3CopyError        : Error copying a key on S3.
            #   S3CreateError      : Error creating a bucket or key on S3.
            #   S3DataError        : Error receiving data from S3.
            #   S3PermissionsError : Permissions error when accessing a bucket or key on S3.
            #   S3ResponseError    : Error in response from S3.
            #if e.status == 404:   # Not found; probably the wrong bucket name
            #    log.msg('S3Storage: %s %s - %s' % (e.status, e.reason, e.body), log.ERROR)
            #elif e.status == 403: # Forbidden; probably incorrect credentials
            #    log.msg('S3Storage: %s %s - %s' % (e.status, e.reason, e.body), log.ERROR)
            raise e
        finally:
            source_key.close()
            s3_key.close()

    #from https://github.com/scrapy/scrapy/blob/342cb622f1ea93268477da557099010bbd72529a/scrapy/extensions/feedexport.py
    def _get_uri_params(self, spider):
        params = {}
        for k in dir(spider):
            params[k] = getattr(spider, k)
        ts = self.stats.get_value('start_time').replace(microsecond=0).isoformat().replace(':', '-')
        params['time'] = ts
        return params