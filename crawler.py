import urllib.request
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin, urlparse, urlunparse
import tldextract
_extractor = tldextract.TLDExtract(suffix_list_urls=()) # predownload suffix list
import base64

from bs4 import BeautifulSoup
from queue import PriorityQueue, Empty

import math
import threading
import time
from datetime import datetime, timedelta

headers = {
    "User-Agent": "Mozilla/5.0 (compatible; ClassCrawler/4.0;)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}

# blacklisted extensions
extensions = (".jpg",".jpeg",".png",".gif",".pdf",".zip",".gz",".mp3",".mp4", ".avi",".css",".js",".ico",".svg",".xml",".rss",".doc",".docx", ".ppt",".pptx",".xls",".xlsx",".tar",".rar",".exe",".dmg")

# logging data
start_time = datetime.now()
num_errors = {}

# limit num of sites visted
num_visited = 0
max_visit = 10000

# site data
site_queue = PriorityQueue()
visited_sites = {}
visited_urls = set()

# threading locks
visited_sites_lock = threading.Lock()
visited_urls_lock = threading.Lock()
robot_cache_lock = threading.Lock()
log_lock = threading.Lock()

def parse_url(url):
    parsed_extract = _extractor(url)
    parsed_url = urlparse(url)
    return {
        # Reference URL:
        # https://shop.example.co.uk:443/products/phones?category=smartphones#reviews

        # "sub": parsed_url.subdomain, # "shop"
        # "domain": parsed_url.domain, # "example"
        # "suffix": parsed_url.suffix, # "co.uk"
        "superdomain": parsed_extract.top_domain_under_public_suffix, # "example.co.uk"
        "fqdn" : parsed_extract.fqdn, # "shop.example.co.uk"
        "scheme" : parsed_url.scheme.lower(), # https
        "netlock": parsed_url.netloc.lower(), # "shop.example.co.uk:443"
        "path": parsed_url.path, # "/products/phones"
        "query": parsed_url.query,
        "params": parsed_url.params
    }

def normalize_url(p):
    path = p['path'] or '/'
    return urlunparse((p['scheme'], p['netlock'], path, p['params'], p['query'], ''))

#  --- ROBOT EXCLUSION PROTOCOL ---
robots_cache = {}  # record robots.txt for each domain
robots_time = {} # next available fetch time based on time accessed
robots_delay = {} # crawl delay per domain

def robot_fetch(url, parsed, user_agent="*"):
    # check if website can be scraped
    robots_url = f"{parsed['scheme']}://{parsed['netlock']}/robots.txt"
    crawl_delay = timedelta(seconds=5.0)

    with robot_cache_lock:
        rp = robots_cache.get(robots_url)

    if rp is None:
        rp = RobotFileParser()
        rp.set_url(robots_url)

        try:
            rp.read()
            rp_crawl_delay = rp.crawl_delay('*')
            crawl_delay = timedelta(seconds=rp_crawl_delay) if rp_crawl_delay is not None else crawl_delay
        except Exception:
            rp.parse([])  # empty rules, allow everything

        with robot_cache_lock:
            robots_cache[robots_url] = rp
            robots_time[robots_url] = datetime.now()
            robots_delay[robots_url] = crawl_delay

    with robot_cache_lock:
        rp = robots_cache[robots_url]

    if not rp.can_fetch("*", url):
        return False

    with robot_cache_lock:
        crawl_delay = robots_delay[robots_url]
        current_time = datetime.now()
        scheduled_time = robots_time[robots_url]
        if scheduled_time <= current_time:
            time_slot = current_time
        else:
            time_slot = scheduled_time

        # reserve slot for the next thread
        robots_time[robots_url] = time_slot + crawl_delay

    wait = (time_slot - datetime.now()).total_seconds()
    if wait > 0:
        time.sleep(wait)
        print(f"SLEEP : {wait} seconds at {url}")

    return True

def site_priority(p, priority_score = -2.0):
    # priority queue uses min-heap --> start at a negative number
    # add penalty as you revisit superdomain and fqdn
    with visited_sites_lock:
        superdomain_count = visited_sites.get(p['superdomain'], 0)
        priority_score += math.log1p(superdomain_count)

        fqdn_count = visited_sites.get(p['fqdn'],0)
        
        priority_score += math.log1p(fqdn_count)
    return priority_score

def log(url, p, soup, status_code, priority, depth, bytes):
    # log.txt --> time | depth | bytes | status code | page priority | url
    with open("log.txt", "a", encoding="utf-8") as file:
        # file.write(f"{datetime.now()} | {depth} | {bytes} bytes | {status_code} | page priority : {priority} | {p['superdomain']} | {p['fqdn']} | {url}\n")
        file.write(f"{datetime.now()} | {depth} | {bytes} bytes | {status_code} | page priority : {priority} | {url}\n")

    # /webpages --> html of webpage
    with open(f"webpages/webpage{num_visited}.html", "w", encoding="utf-8") as file:
        file.write(soup.prettify())

def crawler():
    global num_visited
    while num_visited < max_visit:
        try:
            priority, depth, url, p = site_queue.get(timeout=5.0)
            current_priority = site_priority(p)
            while current_priority != priority:
                # lazy update to first item until the priority scores match
                current_priority = site_priority(p)
                site_queue.put((current_priority, depth, url, p))
                priority, depth, url, p = site_queue.get(timeout=5.0)
        except Empty:
            return
        
        try:                    
            # check if website allows crawlers
            if not robot_fetch(url,p):
                print(f"ROBOT.TXT: prohibited at {url}")
                continue

            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=5) as response:
                url = response.geturl()
                p = parse_url(url)
                normalized_url = normalize_url(p)

                with visited_urls_lock:
                    if normalized_url in visited_urls:
                        continue
                    url = normalized_url
                    visited_urls.add(url)

                status_code = response.status
                content_type = response.headers.get("Content-Type", "")

                if "text/html" not in content_type.lower():
                    print(f"NOT HTML: {content_type!r} at {url}")
                    continue
                
                content = response.read()
                bytes = len(content)
                content = content.decode("utf-8", errors="ignore")  # convert bytes into string
                soup = BeautifulSoup(content, "html.parser")

                # log site visit        
                with visited_sites_lock:
                    visited_sites[p["superdomain"]]  = visited_sites.get(p["superdomain"], 0) + 1
                    if p["fqdn"] != p["superdomain"]: # prevent double counting if they are the same
                        visited_sites[p["fqdn"]] = visited_sites.get(p["fqdn"], 0) + 1

                with log_lock:
                    num_visited += 1
                    log(url, p, soup, status_code, current_priority, depth, bytes)

                # if using base tag, append url to the base
                base_tag = soup.find("base", href=True)
                base_link = urljoin(url, base_tag["href"]) if base_tag else url # double check if this works
                # if (base_tag):
                #     print("BASE TAG : ", url, base_tag, base_tag["href"], base_link)
                
                # find links on site
                for a in soup.find_all("a", href=True):
                    href = a["href"].lower()

                    # skip link with blacklisted file endings
                    if href.endswith(extensions):
                        continue

                    # skip non url redirects
                    if href.startswith(('javascript:', 'mailto:', 'tel:', 'data:', 'ftp:', 'file:')):
                        continue
                    
                    # skip link with cgi scripts
                    if href.find("cgi-bin") != -1:
                        continue

                    link = urljoin(base_link, a['href'])
                    p_link = parse_url(link)
                    link = normalize_url(p_link)

                    if p_link['scheme'] not in ('http', 'https'):
                        continue

                    with visited_urls_lock:
                        if link not in visited_urls:
                            visited_urls.add(link)
                            site_queue.put((site_priority(p_link), depth + 1, link, p_link))


        except Exception as e:
            # errors to address:
            # ERROR: InvalidURL: nonnumeric port: 'void(0)' at https://javascript:void(0)/
            # ERROR: URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1032)> at https://bit.ly/4vVyIxj
            # ERROR: URLError: <urlopen error [SSL: TLSV1_ALERT_INTERNAL_ERROR] tlsv1 alert internal error (_ssl.c:1032)> at https://litterbox.koyu.space/
            # ERROR: URLError: <urlopen error [Errno 11001] getaddrinfo failed> at http://www.insertlink.ccc/
            error = f"{type(e).__name__}: {e}"
            num_errors[error] = num_errors.get(error, 0) + 1
            print(f"ERROR: {error} at {url}")

# --- FETCH SEED PAGES ---

def fetch_page(url):
    request = urllib.request.Request(url, headers=headers)
    response = urllib.request.urlopen(request, timeout=5)

    final_url = response.geturl() # get the final url after redirects

    content = response.read().decode("utf-8", errors="ignore") # convert from bytes to text
    soup = BeautifulSoup(content, "html.parser")

    return final_url, soup

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
        p_seed = parse_url(final_url)
        final_url = normalize_url(p_seed)
        print(final_url)
        
        site_queue.put((-2.0, 0, final_url, p_seed)) # priority, depth, url, parsed url
        visited_urls.add(final_url)

# --- MULTI-THREADING ---
num_threads = 5
threads = [threading.Thread(target=crawler, daemon=True) for i in range(num_threads)] # set background threads that exit at any time
 
for t in threads:
    t.start()

for t in threads:
    t.join(timeout=15.0)

# --- FINAL SUMMARY ---
print("Number of Documents in Queue", site_queue.qsize())
print(f"Time take: {datetime.now() - start_time}")
print(num_errors)