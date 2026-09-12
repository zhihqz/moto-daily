import os
import re
import html
import hashlib
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

PUSHPLUS_TOKEN = os.environ["PUSHPLUS_TOKEN"]
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]

KEYWORDS = "摩托车 OR 机车 OR 摩托"
MAX_ITEMS = 35
KEEP_HOURS = 30

def clean_text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def parse_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None

def fetch_google_news():
    q = quote(KEYWORDS)
    url = f"https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    return feedparser.parse(url)

def fetch_bing_news():
    q = quote("摩托车")
    url = f"https://www.bing.com/news/search?q={q}&format=rss&setlang=zh-CN"
    return feedparser.parse(url)

def collect_items():
    items = []
    seen = set()
    feeds = []

    for name, fetcher in (("google", fetch_google_news), ("bing", fetch_bing_news)):
        try:
            feeds.append((name, fetcher()))
        except Exception as e:
            print(f"{name} fetch failed: {e}")

    for name, feed in feeds:
        for e in feed.entries[:60]:
            title = clean_text(e.get("title", ""))
            if not title:
                continue

            link = e.get("link", "")
            summary = clean_text(e.get("summary", ""))[:300]
            dt = parse_time(e)

            if dt and dt < datetime.now(timezone.utc) - timedelta(hours=KEEP_HOURS):
                continue

            key = hashlib.md5((title + link).encode("utf-8")).hexdigest()
            if key in seen:
                continue
            seen.add(key)

            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "dt": dt,
                "time": dt.strftime("%m-%d %H:%M") if dt else "",
                "source": name,
            })

    items.sort(
        key=lambda x: x["dt"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )
    return items[:MAX_ITEMS]

def summarize(items):
    if not items:
        return "今天没抓到新的摩托车消息。可能是新闻源断了，或者关键词太窄。"

    lines = []
    for i, it in enumerate(items, 1):
        lines.append(
            f"{i}. 标题：{it['title']}\n"
            f"时间：{it['time']}\n"
            f"来源：{it['source']}\n"
            f"摘要：{it['summary']}\n"
            f"链接：{it['link']}"
        )

    raw = "\n\n".join(lines)

    prompt = f"""你是摩托车行业编辑。下面是我抓到的最近摩托车相关新闻。请用中文做一份适合微信阅读的每日汇总。
要求：
1. 先给3到5条重点，每条一两句话。
2. 按新品、政策、赛事、行业、骑行安全分类，没有的分组可以不写。
3. 只根据输入内容总结，不要编造。
4. 给一句趋势判断。
5. 全文控制在800字以内，纯文本，不要表格。
新闻如下：
{raw}
"""

    r = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "你是严谨的摩托车行业编辑，只根据输入总结，不编造。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()

def push_wechat(title, content):
    r = requests.post(
        "https://www.pushplus.plus/send",
        json={
            "token": PUSHPLUS_TOKEN,
            "title": title,
            "content": content,
            "template": "txt",
        },
        timeout=30,
    )
    r.raise_for_status()
    print(r.text)

def main():
    items = collect_items()
    bj_now = datetime.now(timezone(timedelta(hours=8)))
    title = f"摩托车日报 {bj_now.strftime('%Y-%m-%d')}"
    summary = summarize(items)

    links = "\n".join(
        f"{i}. {it['title']}\n{it['link']}"
        for i, it in enumerate(items[:15], 1)
    )

    full = f"{summary}\n\n原始链接：\n{links}"
    push_wechat(title, full)

if __name__ == "__main__":
    main()

