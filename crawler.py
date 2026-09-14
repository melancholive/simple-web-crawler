import urllib.request

response = urllib.request.urlopen("https://google.com/search?q=xiaohongshu")
print(response.status)
print(response.read()[:200])

#  Robot Exclusion Protocol
# https://yoast.com/ultimate-guide-robots-txt/
