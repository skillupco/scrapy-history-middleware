# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals
import base64
from datetime import datetime
import json
import logging
import os

import boto
from six.moves.urllib import parse
from scrapy.exceptions import NotConfigured
from scrapy.http import TextResponse, Headers
from scrapy.responsetypes import responsetypes
from scrapy.utils.request import request_fingerprint

MANDATORY_SETTINGS = [
    'HISTORY_S3_BUCKET',
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY'
]

# This source template allows to store jobs response by spider name.
# It also makes it possible to find sources by job id and execution time
# in order to replay history.
DEFAULT_S3_SOURCE_TEMPLATE = '{name}/{time}_{jobid}'

logger = logging.getLogger('{}:'.format(__name__))


def _reformat_response(response):
    binary = response_body = None
    if isinstance(response, TextResponse):
        # Textual response (HTMl, XML, csv, etc.),
        # decoded to unicode using encoding (from Content-Type)
        binary = False
        response_body = response.body.decode(response.encoding)
        logger.debug('encoded to unicode from text response format: {}'.format(response.encoding))
    else:
        # Binary response (excel, pdf, etc.)
        binary = True
        # encode it to be able to store it on S3 as a string
        response_body = base64.b64encode(response.body)
        logger.debug('encoded binary response to base64')

    return response_body, binary


def _truncate_metadata_fields(metadata, max_length=400):
    truncated_fields = {}
    # s3_key.update_metadata(metadata) #=> can't use this as need to cast to unicode
    for k, v in metadata.items():
        v = u'' + str(v)
        v = v[:max_length] + '...' if len(v) > max_length else v
        truncated_fields[k] = v

    return truncated_fields


def _truncate_url(url, max_length=200):
    return (url[:max_length] + '...' if len(url) > max_length else url)


class S3CacheStorage(object):

    def __init__(self, stats, general_settings):
        # Mandatory settings
        self.S3_ACCESS_KEY = general_settings.get('AWS_ACCESS_KEY_ID')
        self.S3_SECRET_KEY = general_settings.get('AWS_SECRET_ACCESS_KEY')
        self.S3_CACHE_BUCKET = general_settings.get('HISTORY_S3_BUCKET', None)
        configured = all([general_settings.get(k, False) for k in MANDATORY_SETTINGS])
        if not configured:
            raise NotConfigured('{} are mandatoy settings, set them either from the settings file '
                                'or from the Scrapinghub spider settings '
                                'section.'.format(','.join(MANDATORY_SETTINGS)))

        # Optional settings
        # boto s3_connection does not work through proxy.
        # comment this line from the original file
        # self.use_proxy = settings.get('HISTORY_USE_PROXY', False)
        self.save_source_template = general_settings.get('HISTORY_SAVE_SOURCE',
                                                         DEFAULT_S3_SOURCE_TEMPLATE)
        self.stats = stats

    def open_spider(self, spider):
        self.s3_connection = boto.connect_s3(self.S3_ACCESS_KEY,
                                             self.S3_SECRET_KEY,
                                             # Fails with understandable Traceback
                                             # if is_secure is set to True.
                                             # Else it will fail on S3Connection.get_bucket()
                                             # with a super vague message Trace:
                                             # TypeError: int() argument must be a string
                                             #   or a number, not 'NoneType'
                                             is_secure=True)
        # S3Connection does not work when using proxy. S3Connection.use_proxy must be set to False.
        self.s3_connection.use_proxy = False
        # Use spider fields to replace var in key name.
        self.save_source = self.save_source_template.format(**self._get_uri_params(spider))
        # The bucket keeps the name given
        self.s3_bucket = self.s3_connection.get_bucket(self.S3_CACHE_BUCKET)
        # self.versioning = self.s3_bucket.get_versioning_status()
        # => {} or {'Versioning': 'Enabled'}

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

    def _get_request_storage_key(self, spider, request):
        key = request_fingerprint(request)
        return '{name}/cache/{key}'.format(name=spider.name, key=key)

    def retrieve_response(self, spider, request):
        """
        Return response if present in cache, or None otherwise.
        """
        key = self._get_request_storage_key(spider, request)

        epoch = request.meta.get('epoch')  # guaranteed to be True or datetime
        s3_key = self._get_s3_key(key, epoch)
        logger.debug('Retrieving response for key {}.'.format(s3_key))

        if not s3_key:
            return

        try:
            data_string = s3_key.get_contents_as_string()
        except boto.exception.S3ResponseError as e:
            # See store_response for error descriptions
            raise e
        finally:
            s3_key.close()

        data = json.loads(data_string)

        metadata = data['metadata']
        response_headers = Headers(data['response_headers'])
        response_body = data['response_body']

        if data.get('binary', False):
            logger.debug('retrieved binary body')
            response_body = base64.b64decode(response_body.decode('utf8'))
            encoding = {}
        else:
            encoding = {'encoding': 'utf8'}
        url = str(metadata['response_url'])
        status = metadata.get('status')
        Response = responsetypes.from_args(headers=response_headers, url=url)

        return Response(url=url,
                        headers=response_headers,
                        status=status,
                        body=response_body,
                        **encoding)

    def store_response(self, spider, request, response):
        """Store the given response in the cache.

        """
        logger.debug('storing response for {}.'.format(request.url))
        key = self._get_request_storage_key(spider, request)
        response_body, binary = _reformat_response(response)

        metadata = {
            'url': request.url,
            'method': request.method,
            'status': response.status,
            'response_url': response.url,
        }

        data = {
            'binary': binary,
            'metadata': metadata,
            'request_headers': request.headers,
            'request_body': request.body,
            'response_headers': response.headers,
            'response_body': response_body
        }

        data_string = json.dumps(data, ensure_ascii=False, encoding='utf-8')
        # sometimes can cause memory error in SH if too big
        logger.debug('request/response object size: {} kB'.format(len(data_string) / 1024))
        # With versioning enabled creating a new s3_key is not
        # necessary. We could just write over an old s3_key. However,
        # the cost to GET the old s3_key is higher than the cost to
        # simply regenerate it using self._get_request_storage_key().
        s3_key = self.s3_bucket.new_key(key)

        try:
            metadata = _truncate_metadata_fields(metadata)
            for k, v in metadata.items():
                s3_key.set_metadata(k, v)
            s3_key.set_contents_from_string(data_string)
            # save source file
            job_folder = self.save_source
            # if the S3 key is too long, the AWS interface does not allow to download the file !
            source_url = _truncate_url(request.url)
            source_name = "{}/source/{}__{}".format(job_folder, request_fingerprint(request),
                                                    parse.quote_plus(source_url))
            source_key = self.s3_bucket.new_key(source_name)
            source_key.set_contents_from_string(response.body)
            # sometimes can cause memory error in SH if too big
            logger.debug('body size {} kB'.format(len(response.body) / 1024))

        except boto.exception.S3ResponseError as e:
            # http://docs.pythonboto.org/en/latest/ref/boto.html#module-boto.exception
            #   S3CopyError        : Error copying a key on S3.
            #   S3CreateError      : Error creating a bucket or key on S3.
            #   S3DataError        : Error receiving data from S3.
            #   S3PermissionsError : Permissions error when accessing a bucket or key on S3.
            #   S3ResponseError    : Error in response from S3.
            #  e.status == 404 Not Found, probably the wrong bucket name
            #  e.status == 403 Forbidden, probably incorrect credentials
            raise e

        finally:
            source_key.close()
            s3_key.close()

    # from https://github.com/scrapy/scrapy/blob/342cb622f1ea93268477da557099010bbd72529a/scrapy/extensions/feedexport.py  # noqa
    def _get_uri_params(self, spider):
        params = {}
        for k in dir(spider):
            params[k] = getattr(spider, k)
        ts = self.stats.get_value('start_time').replace(microsecond=0).isoformat().replace(':', '-')
        params['time'] = ts
        if not params.get('jobid', None):
            jobid = os.getenv('SHUB_JOBKEY') or ''
            params['jobid'] = jobid.replace('/', '_')
        return params
