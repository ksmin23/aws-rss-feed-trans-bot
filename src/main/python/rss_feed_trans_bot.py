#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
# vim: tabstop=2 shiftwidth=2 softtabstop=2 expandtab

import sys
from datetime import datetime
import time
import collections
import logging
import io
import os
import pprint
import random

import feedparser
from bs4 import BeautifulSoup
from googletrans import Translator
import boto3

random.seed(47)

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
LOGGER = logging.getLogger()

DRY_RUN = True if 'true' == os.getenv('DRY_RUN', 'true') else False

AWS_REGION = os.getenv('REGION_NAME', 'us-east-1')

S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'your-bucket-name')
S3_OBJ_KEY_PREFIX = os.getenv('S3_OBJ_KEY_PREFIX', 'whats-new')

PRESIGNED_URL_EXPIRES_IN = int(os.getenv('PRESIGNED_URL_EXPIRES_IN', 86400*7))

EMAIL_FROM_ADDRESS = os.getenv('EMAIL_FROM_ADDRESS', 'your-sender-email-addr')
EMAIL_TO_ADDRESSES = os.getenv('EMAIL_TO_ADDRESSES', 'your-receiver-email-addr-list')
EMAIL_TO_ADDRESSES = [e.strip() for e in EMAIL_TO_ADDRESSES.split(',')]

TRANS_DEST_LANG = os.getenv('TRANS_DEST_LANG', 'ko')
TRANS_REQ_INTERVALS = [0.1, 0.3, 0.5, 0.7, 1.0]

WHATS_NEW_URL = 'https://aws.amazon.com/about-aws/whats-new/recent/feed/'


def strip_html_tags(html):
  soup = BeautifulSoup(html, features='html.parser')
  text = soup.get_text()
  a_hrefs = soup.find_all('a')
  return {'text': text, 'a_hrefs': a_hrefs}


def parse_feed(feed_url):
  parsed_rss_feed = feedparser.parse(feed_url)

  status = parsed_rss_feed['status']
  if 200 != status:
    return

  ENTRY_KEYS = '''link,id,title,summary,published_parsed'''.split(',')
  entry_list = []
  for entry in parsed_rss_feed['entries']:
    doc = {k: entry[k] for k in ENTRY_KEYS}
    doc['tags'] = [e['term'] for e in entry['tags']]
    doc['summary_parsed'] = strip_html_tags(doc['summary'])
    entry_list.append(doc)
  return {'entries': entry_list, 'updated_parsed': parsed_rss_feed['updated_parsed'], 'count': len(entry_list)}


def translate(translator, texts, dest='ko', interval=1):
  trans_texts = collections.OrderedDict()

  for key, elem in texts:
    trans_res = translator.translate(elem, dest=dest)
    trans_texts[key] = trans_res.text
    time.sleep(interval)
  return trans_texts


def gen_html(res):
  HTML_FORMAT = '''<!DOCTYPE html>
<html>
<head>
<style>
table {{
  font-family: arial, sans-serif;
  border-collapse: collapse;
  width: 100%;
}}

td, th {{
  border: 1px solid #dddddd;
  text-align: left;
  padding: 8px;
}}

tr:nth-child(even) {{
  background-color: #dddddd;
}}
</style>
</head>
<body>

<h2>Recent Anouncements ({last_updated})</h2>

<table>
  <tr>
    <th>doc_id</th>
    <th>link</th>
    <th>pub_date</th>
    <th>title</th>
    <th>summary</th>
    <th>title_{lang}</th>
    <th>summary_{lang}</th>
    <th>tags</th>
  </tr>
  {table_rows}
</table>

</body>
</html>'''

  HTML_TABLE_ROW_FORMAT = '''
  <tr>
    <td>{doc_id}</td>
    <td>{link}</td>
    <td>{pub_date}</td>
    <td>{title}</td>
    <td>{summary}</td>
    <td>{title_trans}</td>
    <td>{summary_trans}</td>
    <td>{tags}</td>
  </tr>'''

  html_table_rows = []
  for elem in res['entries']:
    html_tr_elem = HTML_TABLE_ROW_FORMAT.format(doc_id=elem['id'],
      link=elem['link'], pub_date=time.strftime('%Y-%m-%dT%H:%M:%S', elem['published_parsed']),
      title=elem['title'], summary=elem['summary_parsed']['text'],
      title_trans=elem['title_trans']['text'], summary_trans=elem['summary_trans']['text'],
      lang=elem['title_trans']['lang'], tags=','.join(elem['tags']))
    html_table_rows.append(html_tr_elem)

  html_doc = HTML_FORMAT.format(last_updated=time.strftime('%Y-%m-%dT%H:%M:%S', res['updated_parsed']),
    lang='ko', table_rows='\n'.join(html_table_rows))

  return html_doc


def fwrite_s3(s3_client, doc, s3_bucket, s3_obj_key):
  output = io.StringIO()
  output.write(doc)

  ret = s3_client.put_object(Body=output.getvalue(),
    Bucket=s3_bucket,
    Key=s3_obj_key)

  output.close()
  try:
    status_code = ret['ResponseMetadata']['HTTPStatusCode']
    return (200 == status_code)
  except Exception as ex:
    return False


def fread_s3(s3_client, s3_bucket_name, s3_obj_key):
  ret = s3_client.get_object(Bucket=s3_bucket_name, Key=s3_obj_key)

  try:
    content_length = ret['ContentLength']
    status_code = ret['ResponseMetadata']['HTTPStatusCode']
    if content_length > 0 and status_code == 200:
      body = ret['Body']
      return [elem.decode('utf-8') for elem in body.iter_lines()]
    else:
      return []
  except Exception as ex:
    return []


def create_presigned_url(bucket_name, object_name, expiration=3600):
  s3_client = boto3.client('s3', region_name=AWS_REGION)
  try:
    res = s3_client.generate_presigned_url('get_object',
      Params={'Bucket': bucket_name, 'Key': object_name},
      ExpiresIn=expiration)
  except botocore.exceptions.ClientError as ex:
    LOGGER.error(repr(ex))
    return None
  return res


def send_email(from_addr, to_addrs, subject, html_body):
  ses_client = boto3.client('ses', region_name=AWS_REGION)
  ret = ses_client.send_email(Destination={'ToAddresses': to_addrs},
    Message={'Body': {
        'Html': {
          'Charset': 'UTF-8',
          'Data': html_body
        }
      },
      'Subject': {
        'Charset': 'UTF-8',
        'Data': subject
      }
    },
    Source=from_addr
  )
  retrn ret


def lambda_handler(event, context):
  LOGGER.info('start to get rss feed')

  res = parse_feed(WHATS_NEW_URL)

  LOGGER.info('rss_feed: count={count}, last_updated="{last_updated}"'.format(count=res['count'],
    last_updated=time.strftime('%Y-%m-%dT%H:%M:%S', res['updated_parsed'])))

  LOGGER.info('translate rss feed')
  translator = Translator()
  title_texts = [(e['id'], e['title']) for e in res['entries']]
  title_texts_trans = translate(translator, title_texts,
    dest=TRANS_DEST_LANG, interval=random.choice(TRANS_REQ_INTERVALS))

  summary_texts = [(e['id'], e['summary_parsed']['text']) for e in res['entries']]
  summary_texts_trans = translate(translator, summary_texts,
    dest=TRANS_DEST_LANG, interval=random.choice(TRANS_REQ_INTERVALS))

  LOGGER.info('add translated rss feed')

  entry_ids_by_idx = {e['id']: idx for idx, e in enumerate(res['entries'])}
  for k, idx in entry_ids_by_idx.items():
    title_trans = title_texts_trans.get(k, '')
    summary_trans = summary_texts_trans.get(k, '')
    res['entries'][idx]['title_trans'] = {'text': title_trans, 'lang': TRANS_DEST_LANG}
    res['entries'][idx]['summary_trans'] = {'text': summary_trans, 'lang': TRANS_DEST_LANG}

  html_doc = gen_html(res)

  LOGGER.info('save translated rss feed in S3')

  s3_file_name = 'anncmt-{}.html'.format(time.strftime('%Y%m%d%H', res['updated_parsed']))
  s3_obj_key = '{prefix}-html/{file_name}'.format(prefix=S3_OBJ_KEY_PREFIX, file_name=s3_file_name)
  s3_client = boto3.client('s3', region_name=AWS_REGION)
  fwrite_s3(s3_client, html_doc, s3_bucket=S3_BUCKET_NAME, s3_obj_key=s3_obj_key)

  LOGGER.info('send translated rss feed by email')

  s3_obj_url = create_presigned_url(S3_BUCKET_NAME, s3_obj_key, expiration=PRESIGNED_URL_EXPIRES_IN)

  from_addr = EMAIL_FROM_ADDRESS
  to_addrs = EMAIL_TO_ADDRESSES
  subject = '''[translated] AWS Recent Announcements'''
  html_body = '''You can download AWS Recent Announcements translated in Korean:</br>
<a class="ulink" href="{}" target="_blank">here</a>'''.format(s3_obj_url)

  if DRY_RUN:
    LOGGER.info('download-url: {}'.format(s3_obj_url))
  elif s3_obj_url is not None:
    send_email(from_addr, to_addrs, subject, html_body)

  LOGGER.info('end')


if __name__ == '__main__':
  event = {
    "id": "cdc73f9d-aea9-11e3-9d5a-835b769c0d9c",
    "detail-type": "Scheduled Event",
    "source": "aws.events",
    "account": "",
    "time": "1970-01-01T00:00:00Z",
    "region": "us-east-1",
    "resources": [
      "arn:aws:events:us-east-1:123456789012:rule/ExampleRule"
    ],
    "detail": {}
  }
  event['time'] = datetime.utcnow().strftime('%Y-%m-%dT%H:00:00')

  start_t = time.time()

  lambda_handler(event, {})

  end_t = time.time()
  LOGGER.info('run_time: {:.2f}'.format(end_t - start_t))

