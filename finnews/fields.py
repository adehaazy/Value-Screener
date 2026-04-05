"""
finnews/fields.py
Feed ID mappings used by CNBC and MarketWatch clients.
Derived from news_enum.py topic categories.
"""

# CNBC RSS feed IDs — maps topic key -> numeric feed ID
cnbc_rss_feeds_id = {
    "top_news":      100003114,
    "world_news":    100727362,
    "us_news":       15837362,
    "asia_news":     19832390,
    "europe_news":   19794221,
    "business":      10001147,
    "earnings":      15839135,
    "commentary":    100370673,
    "economy":       20910258,
    "finance":       10000664,
    "technology":    19854910,
    "politics":      10000113,
    "health_care":   10000108,
    "real_estate":   10000115,
    "wealth":        10001054,
    "autos":         10000101,
    "energy":        19836768,
    "media":         10000110,
    "retail":        10000116,
    "travel":        10000739,
    "small_business":44877279,
    # Investing
    "investing":     15839069,
    "financial_advisors": 100646281,
    "personal_finance":   21324812,
    # Blogs
    "charting_asia":    23103686,
    "funny_business":   17646093,
    "market_insider":   20409666,
    "netnet":           38818154,
    "trader_talk":      20398120,
    "buffett_watch":    19206666,
    # Video / TV
    "top_video":        15839263,
    "latest_video":     100004038,
    "squawk_box":       15838368,
    "mad_money":        15838459,
    "fast_money":       15838499,
    "closing_bell":     15838421,
    "options_action":   28282083,
    # Europe TV
    "capital_connection":  17501773,
    "squawk_box_europe":   15838652,
    "worldwide_exchange":  15838355,
    # Asia TV
    "squawk_box_asia":  15838831,
}

# MarketWatch RSS feed IDs — maps topic key -> URL slug
market_watch_rss_feeds_id = {
    "top_stories":          "topstories",
    "real_time_headlines":  "realtimeheadlines",
    "market_pulse":         "marketpulse",
    "bulletins":            "bulletins",
    "personal_finance":     "pf",
    "stocks_to_watch":      "StockstoWatch",
    "commentary":           "commentary",
    "newsletter_research":  "newslettersandresearch",
    "mutual_funds":         "mutualfunds",
    "banking":              "financial",
    "software":             "software",
    "internet":             "Internet",
    "auto_reviews":         "autoreviews",
}
