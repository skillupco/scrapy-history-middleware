Scrapy History Middleware
=========================

[![CircleCI](https://circleci.com/gh/Kpler/scrapy-history-middleware.svg?style=svg)](https://circleci.com/gh/Kpler/scrapy-history-middleware)

The history middleware is designed to create a permanent record of the
raw requests and responses generated as scrapy crawls the web.

It also functions as a drop-in replacement for the builtin scrapy
httpcache middleware
(`scrapy.contrib.downloadermiddleware.httpcache.HttpCacheMiddleware`). For
example:

```python

    DOWNLOADER_MIDDLEWARES = {
        'history.middleware.HistoryMiddleware': 901 # Right after HttpCacheMiddleware
    }
    AWS_ACCESS_KEY_ID = 'YOUR_AWS_ACCESS_KEY_ID'
    AWS_SECRET_ACCESS_KEY = 'YOUR_AWS_SECRET_ACCESS_KEY'
    HISTORY_EPOCH = True
    HISTORY_STORE_IF = 'history.logic.StoreAlways'
    HISTORY_RETRIEVE_IF = 'history.logic.RetrieveAlways'
    HISTORY_BACKEND = 'history.storage.S3CacheStorage'
    HISTORY_SAVE_SOURCE = '{name}/{time}__{jobid}'
    HISTORY_S3_BUCKET = 'YOUR_S3_CACHE_BUCKET_NAME'
    HISTORY_USE_PROXY = True
    HTTPCACHE_IGNORE_MISSING = False
```

will store and retrieve responses exactly as you expect. However, even
if multiple developers are working on the same spider, the spidered
website will only ever see one request (so long as they all use the
same S3 bucket).

Scrapy introduced the `DbmCacheStorage` backend in version 0.13. In
principle this is capable of interfacing with S3, but the history
middleware is still necessary as it provides versioning capability.


## Config

The history middleware is designed to play well with the httpcache
middleware. As such, the default logic modules use
`HTTPCACHE_IGNORE_MISSING`, `HTTPCACHE_IGNORE_SCHEMES`, and
`HTTPCACHE_IGNORE_HTTP_CODES`, and responses will not be stored if
they are flagged as having returned from the cache storage.


## Settings

* `HISTORY_USE_PROXY`: can either be defined in `settings.py`,
  `local_settings.py`, or on the command line:

  ```bash
  $ scrapy crawl {{ spider }} --set="HISTORY_EPOCH=yesterday"
  ```
  
  Note that scrapy will choose the value in local_settings.py over the
  command line.

  Possible values:

    * `True`: The middleware will always try to retrieve the most
      recently stored version of a url, subject to the logic in
      `RETRIEVE_IF`.

    * `False` (default): The middleware won't ever try to retrieve
      stored responses.

    * `{{ string }}`: The middleware will attempt to generate a datetime
      using the heuristics of the
      [parsedatetime](http://code.google.com/p/parsedatetime/)
      module. The retrieved response will either be newer than `EPOCH`,
      or the most recently stored response.

* `HISTORY_STORE_IF`: (default `history.logic.StoreAlways`) Path to a
  callable that accepts the current spider, request, and response as
  arguments and returns `True` if the response should be stored, or
  `False` otherwise.

* `HISTORY_RETRIEVE_IF`: (default `history.logic.RetrieveNever`) Path to a
  callable that accepts the current spider and request as arguments
  and returns `True` if the response should be retrieved from the
  storage backend, or `False` otherwise.

* `HISTORY_BACKEND`: (default `history.storage.S3CacheStorage`) The storage
  backend.

* `S3_ACCESS_KEY`: Required if using `S3CacheStorage`.

* `S3_BUCKET_KEY`: Required if using `S3CacheStorage`.

* `HISTORY_S3_BUCKET`: Required if using `S3CacheStorage`.

* `HISTORY_USE_PROXY`: Mention if boto should be using a proxy to connect to the S3 bucket


## Using it with Scrapinghub

In order to activate this middleware on Scrapinghub, you need to add it on your pypi and mention it in the requirements.txt file of your scrapy project.

You also have to add the settings in the `spider settings` section of the webpage if you want to activate it for all spiders. Else, add these settings to the settings section of the specific spider for which you want to use the middleware.

```python

    DOWNLOADER_MIDDLEWARES = {
        'history.middleware.HistoryMiddleware': 901 # Right after HttpCacheMiddleware
    }

    HISTORY_EPOCH = True
    HISTORY_STORE_IF= 'history.logic.StoreAlways'
    HISTORY_RETRIEVE_IF = 'history.logic.RetrieveAlways'
    HISTORY_BACKEND = 'history.storage.S3CacheStorage'
    HISTORY_SAVE_SOURCE = '{name}/{time}__{jobid}'
    HISTORY_S3_ACCESS_KEY = 'YOUR_AWS_ACCESS_KEY_ID'
    HISTORY_S3_SECRET_KEY = 'YOUR_AWS_SECRET_ACCESS_KEY'
    HISTORY_S3_BUCKET = 'YOUR_S3_CACHE_BUCKET_NAME'
    HISTORY_USE_PROXY = True
    HTTPCACHE_IGNORE_MISSING = False
```
