import urllib.request
from bs4 import BeautifulSoup

url = "https://google.com/search?q=xiaohongshu"

# log to output files
def log(url, data):
    with open("log.txt", "w", encoding="utf-8") as file:
        file.write(url)
        file.write('\n')

    with open("webpage.html", "w", encoding="utf-8") as file:
        soup = BeautifulSoup(data)
        file.write(soup.prettify())

# html parsing
from html.parser import HTMLParser
class URLParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        print("Encountered a start tag:", tag)

    def handle_data(self, data):
        if data:
            print("Encountered some data  :", data[:100])

response = urllib.request.urlopen(url)
content = response.read()
parser = URLParser()
# parse html content
parser.feed(content[:1000].decode("utf-8", errors="ignore")) # convert bytes into string
# log site visit
log(url, (content[:100].decode("utf-8", errors="ignore")))

#  Robot Exclusion Protocol
# https://yoast.com/ultimate-guide-robots-txt/
