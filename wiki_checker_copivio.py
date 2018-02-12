#!/usr/bin/env python
# coding: utf-8
import requests
from urllib.parse import urlencode, quote
# from vladi_commons import vladi_commons
# from vladi_commons.vladi_commons import csv_save_dict_fromListWithHeaders, json_store_to_file, json_data_from_file
from vladi_commons.vladi_commons import csv_save_dict
import sqlite3
import json
from lxml.html import fromstring
from datetime import datetime, timedelta
import time
from lxml import cssselect
import re
# import html5lib
from urllib.parse import urlparse, parse_qs, parse_qsl, unquote, quote


def get_newpages(limit=1000, hours_offset=5):
	"""Берем со страницы Special:NewPages. Альтернативы:
	- PWB, но он не позволяет фильтровать период времени, правки ботов, и перенаправления.
	- wiki API, но оно слишком запутано, не ясно где брать эту инфу.
	- wiki база данных имеет сложности с подключением доступа; а сервисы-прокладки от third-party ненадежны.
	Параметры:
	offset_days - отступ списка новых страниц от этой даты. не нужно
				(datetime.today() - timedelta(days=offset_days)).strftime('%Y%m%d')
	limit - число ссылок на странице
	"""
	# import locale
	# locale.setlocale(locale.LC_ALL, '')
	# datetime.strptime("20:58, 11 февраля 2018", "%H:%M, %d %m %Y")
	r = requests.get(url='https://ru.wikipedia.org/w/index.php',
					 params={'title': 'Special:NewPages', 'limit': limit, 'hidebots': 1})
	tree = fromstring(r.text)
	newpages = parse_newpages(tree, hours_offset)
	return newpages


def parse_newpages(tree, hours_offset):
	newpages = []
	for p in tree.cssselect('div#mw-content-text > ul li'):
		time_create = p.cssselect('span.mw-newpages-time')[0].text_content()
		for o, n in [('января', '1'), ('февраля', '2'), ('марта', '3'), ('апреля', '4'), ('мая', '5'),
					 ('июня', '6'), ('июля', '7'), ('августа', '8'), ('сентября', '9'), ('октября', '10'),
					 ('ноября', '11'), ('декабря', '12')]:
			time_create = time_create.replace(o, n)
		time_create = datetime.strptime(time_create, "%H:%M, %d %m %Y")
		time_offset = datetime.today() - timedelta(hours=hours_offset)
		if time_create > time_offset:
			pagename = p.cssselect('a.mw-newpages-pagename')[0].text_content()
			user = p.cssselect('a.mw-userlink')[0].text_content()
			time_create_f = datetime.strftime(time_create, "%Y-%m-%d %H:%M")
			newpages.append({'time_create': time_create_f, 'pagename': pagename, 'user': user})
	return newpages


def filter_pages_by_category(pages, filter_category):
	params = {'action': 'query', 'prop': 'categories', 'format': 'json', 'utf8': 1,
			  'titles': '|'.join([t['pagename'] for t in pages])}
	r = requests.get('https://ru.wikipedia.org/w/api.php', params=params, headers={'User-Agent': 'user:textworkerBot'})
	pc = r.json()['query']['pages']
	pagesout = set()
	for p in pc.values():
		if p.get('categories'):
			for c in p['categories']:
				if filter_category in c.values():
					pagesout.add(p['title'])
	pages = [p for p in newpages if p['pagename'] not in pagesout]
	return pages


def req_copyvios(newpages, use_engine=True):
	results = []
	s = requests.Session()
	s.headers.update({'User-Agent': 'user:textworkerBot'})
	s.params.update({'action': 'search', 'lang': 'ru', 'project': 'wikipedia',
					 'use_engine': use_engine, 'use_links': True, 'nocache': False, 'noredirect': False,
					 'noskip': False})
	for p in newpages:
		title = p['pagename']
		print(f'{title}', end=' ')
		r = s.get('https://tools.wmflabs.org/copyvios/api.json', params={'title': title})
		# r = req_copyvios(title, use_engine=True)
		page_result = r.json()
		if page_result['status'] == 'ok':
			results.append({'result': page_result, 'url_service': r.url.replace('copyvios/api.json?', 'copyvios/?')})
			print(' ...checked')
	return results


if __name__ == '__main__':
	# Взять список новых страниц
	limit_newpages = 10
	newpages = get_newpages(limit=limit_newpages)

	# отфильтровка страниц
	filterout_category = 'Категория:Страницы значений по алфавиту'
	newpages = filter_pages_by_category(newpages, filterout_category)

	# Проверка страниц на КОПИВИО
	results = []
	for p in newpages:
		title = p['pagename']
		print(f'{title}', end=' ')
		r = req_copyvios(title, use_engine=True)
		page_result = r.json()
		if page_result['status'] == 'ok':
			results.append({'result': page_result, 'url_service': r.url.replace('copyvios/api.json?', 'copyvios/?')})
			print(' ...checked')

	# Запись результатов проверки в файл, и сортировка по проценту
	if len(results):
		dataset, rate0, rate1 = [], [], []
		for p in results:
			pp, pb = p['result']['page'], p['result']['best']
			d = {'title': pp['title'], 'url_page': pp['url'], 'url_service': p['url_service'],
				 'confidence': pb['confidence'], 'url': pb['url']}
			dataset.append(d)
			if p['best']['confidence'] >= 0.80:
				rate0.append(d)
			elif p['best']['confidence'] >= 0.60:
				rate1.append(d)
		# запись полного списка. filename_all = 'dataset.csv'
		csv_save_dict('dataset.csv', dataset)

	pass
