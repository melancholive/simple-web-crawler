import urllib.request
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin, urlparse, parse_qs
import tldextract
import base64

from bs4 import BeautifulSoup
from queue import PriorityQueue

import random
import math
import threading
import time
from datetime import datetime

# header to spoof user-agent value
headers = {
    "User-Agent": f"testing-a-web-crawler-aowiebfvoawieka",
    "Accept-Language": "en-US,en;q=0.9",
}

# logging data
start_time = datetime.now()
num_errors = {}

# limit num of sites visted
num_visited = 0
max_download = 100

# site data
site_queue = PriorityQueue()
visited_sites = {}
visited_urls = set()

# threading locks
site_queue_lock = threading.Lock()
visited_sites_lock = threading.Lock()
visited_urls_lock = threading.Lock()

def parse_url(url):
    parsed_url = tldextract.extract(url)
    return {
        # Reference URL:
        # https://shop.example.co.uk:443/products/phones?category=smartphones#reviews

        # "sub": parsed_url.subdomain, # "shop"
        # "domain": parsed_url.domain, # "example"
        # "suffix": parsed_url.suffix, # "co.uk"
        "superdomain": parsed_url.top_domain_under_public_suffix, # "example.co.uk"
        "fqdn" : parsed_url.fqdn, # "shop.example.co.uk"
        "scheme" : urlparse(url).scheme, # https
        "netlock": urlparse(url).netloc, # "shop.example.co.uk:443"
        "path": urlparse(url).path, # "/products/phones"
        "query": urlparse(url).query #"?category=smartphones"
    }

#  --- ROBOT EXCLUSION PROTOCOL ---
robots_cache = {}  # record robots.txt for each domain
robots_time = {} # last time each domain was accessed
crawl_delay = 5.0

def robot_fetch(url, parsed, user_agent="*"):
    # check if website can be scraped
    robots_url = f"{parsed['scheme']}://{parsed['netlock']}/robots.txt"

    if robots_url not in robots_cache:
        rp = RobotFileParser()
        rp.set_url(robots_url)

        try:
            rp.read()
        except Exception:
            rp.parse([])  # empty rules, allow everything

        robots_cache[robots_url] = rp
        robots_time[robots_url] = datetime.now()
    else:
        elapsed_time = (datetime.now() - robots_time[robots_url]).total_seconds()
        if elapsed_time < crawl_delay:
            print(f'sleeping for {crawl_delay} at {url}')
            time.sleep(crawl_delay-elapsed_time)
    return robots_cache[robots_url].can_fetch("*", url)

def site_priority(p, priority_score = -2):
    # priority queue uses min-heap --> start at a negative number
    # add penalty as you revisit superdomain and fqdn
    with visited_sites_lock:
        superdomain_count = visited_sites.get(p['superdomain'], 0)
        priority_score += math.log1p(superdomain_count)

        fqdn_count = visited_sites.get(p['fqdn'],0)
        
        priority_score += math.log1p(fqdn_count)
    return priority_score

def log(url, p, soup, data, status_code, priority, depth):
    # log.txt --> time | depth | bytes | status code | page priority | domain priority | url
    with open("log.txt", "a", encoding="utf-8") as file:
        file.write(f"{datetime.now()} | {depth} | {len(data)} bytes | {status_code} | page priority : {priority} | {p['superdomain']} | {p['fqdn']} | {url}\n")

    # /webpages --> html of webpage
    with open(f"webpages/webpage{num_visited}.html", "w", encoding="utf-8") as file:
        file.write(soup.prettify())

def crawler():
    global num_visited
    while not site_queue.empty() and num_visited < max_download:
        with site_queue_lock:
            priority, depth, url, p = site_queue.get()
            while site_priority(p) != priority:
                site_queue.put((site_priority(p), depth, url, p))
                priority, depth, url, p = site_queue.get()

        try:
            # blacklist certain file endings
            extensions = (".jpg",".jpeg",".png",".gif",".pdf",".zip",".gz",".mp3",".mp4", ".avi",".css",".js",".ico",".svg",".xml",".rss",".doc",".docx", ".ppt",".pptx",".xls",".xlsx",".tar",".rar",".exe",".dmg")
            if p['path'].lower().endswith(extensions):
                continue

            # check if website allows crawlers
            if not robot_fetch(url,p):
                print(f"ROBOT.TXT: prohibited at {url}")
                continue

            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=5) as response:
                url = response.geturl() # account for url forwarding
                # NEED TO ADD REDIRECTED URL TO VISITED SITE
                status_code = response.status
                content_type = response.headers.get("Content-Type", "")

                if "text/html" not in content_type.lower():
                    print(f"NOT HTML: {content_type!r} at {url}")
                    continue
                
                content = response.read().decode("utf-8", errors="ignore")  # convert bytes into string
                soup = BeautifulSoup(content, "html.parser")

                # log site visit        
                num_visited += 1

                with visited_sites_lock:
                    visited_sites[p["superdomain"]]  = visited_sites.get(p["superdomain"], 0) + 1
                    if p["fqdn"] != p["superdomain"]: # prevent double counting if they are the same
                        visited_sites[p["fqdn"]] = visited_sites.get(p["fqdn"], 0) + 1

                log(url, p, soup, content, status_code, site_priority(p), depth)

                # if using base tag, append url to the base
                # double check if this works as expected
                base_tag = soup.find("base", href=True)
                base_link = urljoin(url, base_tag["href"]) if base_tag else url # double check if this works
                if (base_tag):
                    print("BAsE TAG : ", url, base_tag, base_tag["href"], base_link)
                
                # find links on site
                for a in soup.find_all("a", href=True):
                    link = urljoin(base_link, a["href"])
                    with visited_urls_lock:
                        if link not in visited_urls and link.find("cgi") == -1:
                            p_link = parse_url(link) 
                            if p_link['scheme'] not in ('http', 'https'):
                                # skip link if javascript, telephone num, mailto, or data
                                continue
                            # ACCOUNT FOR EXTRA INFO IN LINK LATER
                            visited_urls.add(link) # add before putting into queue, to prevent duplicates later
                            with site_queue_lock:
                                site_queue.put((site_priority(p_link), depth + 1, link, p_link))


        except Exception as e:
            # address:
            # <url oppen error [ssl: certificate_verify_failed] certificate verify failed
            
            num_errors[e] = num_errors.get(e, 0) + 1
            print(f"ERROR: {e} at {url}")

# --------------------------

def fetch_page(url):
    request = urllib.request.Request(url, headers=headers)
    response = urllib.request.urlopen(request, timeout=5)

    final_url = response.geturl() # get the final url after redirects

    content = response.read().decode("utf-8", errors="ignore") # convert from bytes to text
    soup = BeautifulSoup(content, "html.parser")

    return final_url, soup

# FETCH SEED URLS FROM USER INPUT
search_term = input("Enter your search term: ")
search_term = search_term.replace(" ", "+") # accounts for terms with spaces
seed_url, initial_soup = fetch_page(f"https://bing.com/?q={search_term}")

seed_urls = []
search_results = initial_soup.select("h2 a") # search results are nested here

for result in search_results: 
    result = result.get('href') # get the link portion
    marker = "&u=a1" # start of the hashed url

    i = result.find(marker)
    if i != -1: # make sure that the marker exists
        # splice the hashed portion of the redirect url
        u = result[i + len(marker):].split("&", 1)[0]

        # add buffer to make sure right size for hash
        u += "=" * (-len(u) % 4) 

        # convert hash to usable url
        final_url = base64.urlsafe_b64decode(u).decode("utf-8", "ignore")
        print(final_url)
        
        site_queue.put((-2, 0, final_url, parse_url(final_url))) # priority, depth, url, parsed url
        visited_urls.add(final_url)

# multi-threading
NUM_THREADS = 5
# set background threads that exit at any time
threads = [threading.Thread(target=crawler, daemon=True) for i in range(NUM_THREADS)] 
queue_lock = threading.Lock()

for t in threads:
    t.start()

for t in threads:
    t.join()

print("Number of Documents in Queue", site_queue.qsize())
print(f"Time take: {datetime.now() - start_time}")
print(num_errors)