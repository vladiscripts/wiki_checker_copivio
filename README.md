# The bot that checking the new pages of Russian Wikipedia for copivio   

Description: https://ru.wikipedia.org/wiki/User:CheckerCopyvioBot

#### Work
Uses the tool https://tools.wmflabs.org/copyvios.
Works for every 10 minutes by schedule via crontab. In CSV files stored last checked pages, this is a little database.

#### Requirements
requests, lxml, cssselect, [pywikibot](https://www.mediawiki.org/wiki/Manual:Pywikibot)
