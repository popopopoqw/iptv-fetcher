import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from iptv_fetcher.fetchers import parse_m3u, parse_txt
from iptv_fetcher.models import Entry
from iptv_fetcher.normalize import classify, normalize_name
from iptv_fetcher.selector import min_pixels, select_best
