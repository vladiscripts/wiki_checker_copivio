#!/usr/bin/env python
# coding: utf-8
import requests
from lxml.html import fromstring
import re
import pywikibot
from datetime import datetime, timedelta


class CheckerBot:
	# мин. процентный уровень для учёта
	min_level_copivio_warning = 60
	newpages = []
	results = []
	pages_checked, pages_highrates = [], []
	last_pages_checked_filename, last_pages_highrates_filename = 'pages_checked.csv', 'pages_highrate.csv'
	dataset_last_newpages = 'last_newpages.csv'
	newpages_no_doubles = []
	row_template = """\
|-
|style="background-color:{color_cell};" | {confidence}
|{time_create}
|[[{title}]]
|{{{{u|{user}}}}}
|[{url} сервис проверки]
|{{{{ccvit|{{{{Обсуждение:{title}}}}}}}}} [[Обсуждение:{title}|Обс.]]
"""  # дублировать двойные фигурные скобки

	def __init__(self):
		self.site = pywikibot.Site('ru', 'wikipedia', user='CheckerCopyvioBot')

	def get_newpages(self, length_listpages=300, hours_offset=2):
		"""Взятие новых страниц со Special:NewPages. Альтернативы:
		- PWB, но он не позволяет фильтровать период времени, правки ботов, и перенаправления.
		- wiki API, но оно слишком запутано, не ясно где брать эту инфу.
		- wiki база данных имеет сложности с подключением доступа; а сервисы-прокладки от third-party ненадежны.

		Параметры:
		hours_offset - брать новые страницы за это число часов. 0 - без лимита по времени
		length_listpages - число статей на странице, max 5000
		"""
		print('%s Получение списка новых страниц' % (self.get_timeutc()), end=' ')
		r = requests.get(url='https://ru.wikipedia.org/w/index.php',
						 params={'title': 'Special:NewPages', 'limit': length_listpages, 'hidebots': 1})
		tree = fromstring(r.text)
		for p in tree.cssselect('div#mw-content-text > ul li'):
			# парсинг времени создания
			time_create = p.cssselect('span.mw-newpages-time')[0].text_content()
			for o, n in [('января', '1'), ('февраля', '2'), ('марта', '3'), ('апреля', '4'), ('мая', '5'),
						 ('июня', '6'), ('июля', '7'), ('августа', '8'), ('сентября', '9'), ('октября', '10'),
						 ('ноября', '11'), ('декабря', '12')]:
				time_create = time_create.replace(o, n)
			time_create = datetime.strptime(time_create, "%H:%M, %d %m %Y")
			time_offset = datetime.utcnow() - timedelta(hours=hours_offset)
			if time_create > time_offset:
				pagename = p.cssselect('a.mw-newpages-pagename')[0].text_content()
				user = p.cssselect('a.mw-userlink')[0].text_content()
				time_create_f = datetime.strftime(time_create, "%Y-%m-%d %H:%M")
				self.newpages.append({'time_create': time_create_f, 'pagename': pagename, 'user': user})
		print('...done')

	def filter_pages_by_category(self, filterout_category):
		"""отфильтровка ненужных страниц по категории"""
		params = {'action': 'query', 'prop': 'categories', 'format': 'json', 'utf8': 1,
				  'titles': '|'.join([p['pagename'] for p in self.newpages])}
		r = requests.get('https://ru.wikipedia.org/w/api.php', params=params,
						 headers={'User-Agent': 'user:textworkerBot'})
		pc = r.json()['query']['pages']
		pagesout = set()
		for p in pc.values():
			if p.get('categories'):
				for c in p['categories']:
					if filterout_category in c.values():
						pagesout.add(p['title'])
		self.newpages = [p for p in self.newpages if p['pagename'] not in pagesout]

	def filter_already_checked_pages(self):
		"""Отфильтровка уже проверенных страниц, в сравнении со списком предыдущих из файла"""
		last_newpages = self.csv_read_dict(self.dataset_last_newpages)
		for p in self.newpages:
			if p['pagename'] not in [old['pagename'] for old in last_newpages]:
				self.newpages_no_doubles.append(p)

	def req_copyvios(self, use_search_engine=True):
		"""Проверка страниц на КОПИВИО"""
		s = requests.Session()
		s.headers.update({'User-Agent': 'user:textworkerBot'})
		s.params.update({'action': 'search', 'lang': 'ru', 'project': 'wikipedia',
						 'use_engine': use_search_engine, 'use_links': True, 'nocache': False, 'noredirect': False,
						 'noskip': False})
		if self.newpages_no_doubles:
			print('%s Отправка на проверку КОПИВИО' % (self.get_timeutc()))
		for p in self.newpages_no_doubles:
			title = p['pagename']
			print('%s %s' % (self.get_timeutc(), title), end=' ')
			r = s.get('https://tools.wmflabs.org/copyvios/api.json', params={'title': title})
			page_result = r.json()
			if page_result['status'] == 'ok':
				p.update({'result': page_result, 'url_service': r.url.replace('copyvios/api.json?', 'copyvios/?')})
				self.results.append(p)
				print(' ...checked (%s%%)' % self.confidence_normalize(p['result']['best']['confidence']))
		if self.newpages_no_doubles and not self.results:
			print('%s Не найдено страниц с нарушением' % (self.get_timeutc()))
		s.close()

	def sort_by_persent(self):
		for p in self.results:
			pp, pb = p['result']['page'], p['result']['best']
			d = {'title': pp['title'], 'url_page': pp['url'], 'url_service': p['url_service'],
				 'confidence': self.confidence_normalize(pb['confidence']), 'url': pb['url'],
				 'time_create': p['time_create'], 'user': p['user']}
			self.pages_checked.append(d)
			if self.confidence_normalize(pb['confidence']) >= self.min_level_copivio_warning:
				self.pages_highrates.append(d)

	@staticmethod
	def confidence_normalize(confidence):
		"""Нормализация процента копивио"""
		return round(float(confidence) * 100)

	def save_results_to_files(self):
		# запись полного списка
		if self.pages_checked:
			self.csv_save_dict(self.last_pages_checked_filename, self.pages_checked)

	def select_postproperties_by_rate(self, confidence_rate):
		"""Значения свойств для постинга в зависимости от процента копивио"""
		d = {}
		confidence_rate = int(confidence_rate)
		if confidence_rate >= 80:
			d['table_color'] = '#FF0000'
			d['TalkPage_template'] = '{{Check copivio|80}}'
		elif confidence_rate >= 60:
			d['table_color'] = '#FFFF00'
			d['TalkPage_template'] = '{{Check copivio|60}}'
		else:
			d['table_color'] = 'white'
			# d['TalkPage_template'] = '{{Check copivio|80}}'  # for test
			d['TalkPage_template'] = ''
		return d

	def posting_to_wikitable(self):
		page = pywikibot.Page(self.site, 'Участник:CheckerCopyvioBot/Список')
		text_to_post = []
		# for p in self.pages_checked:  # for tests
		for p in self.pages_highrates:
			text_to_post.append(self.row_template.format(
				confidence=p['confidence'],
				time_create=p['time_create'],
				title=p['title'],
				user=p['user'],
				url=p['url_service'],
				color_cell=self.select_postproperties_by_rate(p['confidence'])['table_color']))
		t = re.sub('(\n<!--\s*%tohere%.*?-->\n)', r'\1' + ''.join(text_to_post), page.get())
		self.wiki_posting_page(page, t, '+')

	def posting_to_Talk_pages(self):
		# for p in self.pages_checked[:1]:  # for tests
		# title = 'Обсуждение участника:CheckerCopyvioBot/Список'  # for tests
		# title = 'Обсуждение Википедии:Песочница'  # for tests
		for p in self.pages_highrates:
			title = 'Обсуждение:' + p['title']
			post_template = '\n{template} {status} --~~~~\n'.format(
				template=self.select_postproperties_by_rate(p['confidence'])['TalkPage_template'],
				status='<onlyinclude>{{Участник:CheckerCopyvioBot/Список/Проверяется}}</onlyinclude>',
			)
			page = pywikibot.Page(self.site, title)
			if page.exists():
				t = page.get() + '\n' + post_template
			else:
				t = post_template
			self.wiki_posting_page(page, t, '+')

	def post_log(self):
		page_log_out = pywikibot.Page(self.site, 'Участник:CheckerCopyvioBot/Log_output')
		page_log_errors = pywikibot.Page(self.site, 'Участник:CheckerCopyvioBot/Log_errors')
		self.wiki_posting_page(page_log_out, self.file_readtext('~/log.out'), '+')
		self.wiki_posting_page(page_log_errors, self.file_readtext('~/log.err'), '+')

	@staticmethod
	def wiki_posting_page(page_obj, text_new, summary):
		if page_obj.text != text_new:
			page_obj.text = text_new
			page_obj.save(summary=summary)

	@staticmethod
	def csv_read_dict(filename, delimiter=','):
		import csv
		with open(filename) as f_obj:
			reader = csv.DictReader(f_obj, delimiter=delimiter)
			return tuple(row for row in reader)

	@staticmethod
	def csv_save_dict(path, dic, fieldnames=None, delimiter=',', headers=True):
		"""Writes a CSV file using DictWriter"""
		import csv
		if not fieldnames:
			fieldnames = dic[0].keys()
		with open(path, "w", newline='') as out_file:
			writer = csv.DictWriter(out_file, delimiter=delimiter, fieldnames=fieldnames)
			if headers:
				writer.writeheader()
			for row in dic:
				writer.writerow(row)

	@staticmethod
	def file_readtext(filename):
		with open(filename, 'r', encoding='utf-8') as f:
			text = f.read()
		return text

	@staticmethod
	def get_timeutc():
		return datetime.strftime(datetime.utcnow(), "%Y-%m-%d %H:%M:%S")


if __name__ == '__main__':
	bot = CheckerBot()

	# Взять список новых страниц
	bot.get_newpages(length_listpages=100, hours_offset=1)
	# bot.newpages = [
	# 	{'time_create': '2018-02-14 16:00', 'pagename': 'Название статьи', 'user': 'Автор'},
	# ]  # for test

	# Отфильтровка страниц
	print('%s Отфильтровка ноднозначностей и уже проверенных страниц' % (bot.get_timeutc()), end=' ')
	# По категории
	filterout_category = 'Категория:Страницы значений по алфавиту'
	bot.filter_pages_by_category(filterout_category)
	# Чистка от уже проверенных, сохраняемых в файле с пред. запуска
	bot.filter_already_checked_pages()
	bot.csv_save_dict(bot.dataset_last_newpages, bot.newpages)
	print('...done')

	# Проверка страниц на КОПИВИО
	bot.req_copyvios(use_search_engine=True)

	# Запись результатов проверки в файлы, с отсортировкой по проценту
	bot.sort_by_persent()
	bot.save_results_to_files()

	# Постинг в таблицу
	bot.posting_to_wikitable()

	# Постинг на СО
	bot.posting_to_Talk_pages()

	# Постинг лога
	# bot.post_log()
	pass
