#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yixn 爬虫 · 正文抓取版
交互式 · 无依赖 · 自动识别 · 导出 TXT
"""

import re
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from html.parser import HTMLParser

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BANNER = """
========================================
      🕷️  Yixn 爬虫 · 正文抓取版  🕷️
   交互式 · 无依赖 · 自动识别 · 导出 TXT
========================================
"""


# ============ 网络请求 ============

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="ignore")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"状态码异常: {e.code}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"请求失败: {e.reason}")
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}")


# ============ 工具 ============

_ENTITY_MAP = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'", "&apos;": "'",
}

def decode_entities(s):
    for k, v in _ENTITY_MAP.items():
        s = s.replace(k, v)
    return s

def clean_url(base, href):
    if not href:
        return ""
    return urllib.parse.urljoin(base, href.strip())


# ============ 收集链接 ============

class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            d = dict(attrs)
            self._href = d.get("href", "")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = "".join(self._text).strip()
            self.links.append((self._href, text))
            self._href = None


# ============ 正文提取 ============

class TextExtractor(HTMLParser):
    """提取正文纯文本，跳过 script/style/nav/footer/header"""

    SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self.chunks = []
        self._in_body = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self._in_body = True
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "li"):
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "li"):
            self.chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0 and self._in_body:
            self.chunks.append(data)


def extract_article_text(html):
    """从文章页提取正文（自动选最长文本块）"""
    p = TextExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    raw = "".join(p.chunks)
    raw = decode_entities(raw)

    # 按行整理，去掉过短的行（导航残留）
    lines = []
    for line in raw.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if len(line) >= 10:   # 正文行一般较长，过滤导航短词
            lines.append(line)

    # 合并成段落，去掉连续重复
    result = []
    prev = None
    for ln in lines:
        if ln != prev:
            result.append(ln)
        prev = ln

    return "\n".join(result)


# ============ 自动识别文章链接 ============

def find_article_links(html, base_url):
    """从列表页/首页找出所有文章链接"""
    p = LinkCollector()
    try:
        p.feed(html)
    except Exception:
        pass

    # 按路径特征聚类
    from collections import Counter
    cand = []
    seen = set()
    for href, text in p.links:
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        text = decode_entities(text).strip()
        if len(text) < 3:
            continue
        u = clean_url(base_url, href)
        if u in seen:
            continue
        # 排除明显非文章的链接
        if re.search(r"\.(css|js|png|jpg|jpeg|gif|svg|ico|xml|zip)$", u, re.I):
            continue
        seen.add(u)
        cand.append((u, text))

    # 过滤导航词
    blacklist = {
        "首页", "主页", "home", "关于", "about", "联系", "contact",
        "登录", "login", "注册", "register", "更多", "more",
        "下一页", "上一页", "next", "prev", "previous",
        "归档", "archive", "标签", "tags", "分类", "categories",
        "rss", "sitemap", "评论", "comment",
    }
    cand = [(u, t) for u, t in cand if t.lower() not in blacklist]

    return cand


# ============ TXT 导出 ============

def save_txt(articles, source_url, filename=""):
    if not filename:
        filename = f"yixn_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    lines = []
    lines.append("=" * 60)
    lines.append("Yixn 爬虫导出结果 · 正文抓取")
    lines.append(f"来源: {source_url}")
    lines.append(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"文章数: {len(articles)}")
    lines.append("=" * 60)

    for i, art in enumerate(articles, 1):
        lines.append("")
        lines.append("=" * 60)
        lines.append(f"【第 {i} 篇】{art['title']}")
        lines.append(f"链接: {art['link']}")
        lines.append(f"抓取: {art['crawled_at']}")
        lines.append("-" * 60)
        lines.append("")
        lines.append(art["content"] if art["content"] else "（未提取到正文）")
        lines.append("")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"✅ 已保存 {len(articles)} 篇文章到 {filename}")


# ============ 交互 ============

def ask(p):
    return input(p).strip()

def ask_default(p, d):
    a = input(f"{p} [默认: {d}]: ").strip()
    return a if a else d


# ============ 主流程 ============

def run_crawl():
    print("\n--- 配置爬取参数（直接回车使用默认值）---")

    url = ask("目标 URL（首页或文章列表页）: ")
    if not url:
        print("❌ URL 不能为空")
        return
    if not url.startswith("http"):
        url = "https://" + url

    max_articles_str = ask_default("最多抓取文章数", "10")
    try:
        max_articles = max(1, int(max_articles_str))
    except ValueError:
        max_articles = 10

    delay_str = ask_default("每篇间隔秒数（避免被封）", "1")
    try:
        delay = max(0, float(delay_str))
    except ValueError:
        delay = 1.0

    filename = ask("保存文件名 (留空自动生成): ")

    # ---- 第一步：抓列表页，找文章链接 ----
    print(f"\n🔍 第一步：分析列表页 {url}")
    try:
        html = fetch(url)
    except RuntimeError as e:
        print(f"❌ 失败: {e}")
        return

    links = find_article_links(html, url)
    print(f"  ✔ 找到 {len(links)} 个候选链接")

    if not links:
        print("😢 没找到文章链接，可能页面是 JS 渲染")
        return

    # 限制数量
    links = links[:max_articles]

    print(f"\n📄 第二步：逐篇抓取正文（共 {len(links)} 篇）")
    articles = []

    for i, (link, title) in enumerate(links, 1):
        print(f"  [{i}/{len(links)}] {title[:40]}")
        try:
            art_html = fetch(link)
            content = extract_article_text(art_html)
        except RuntimeError as e:
            print(f"     ⚠️  失败: {e}")
            content = ""

        # 如果标题太短，尝试从页面 <title> 补全
        if len(title) < 5:
            m = re.search(r"<title[^>]*>(.*?)</title>", art_html, re.S | re.I)
            if m:
                title = decode_entities(m.group(1).strip())

        articles.append({
            "title": title,
            "link": link,
            "content": content,
            "crawled_at": datetime.now().isoformat(),
        })

        if i < len(links) and delay > 0:
            time.sleep(delay)

    if not articles:
        print("😢 没有成功抓取任何文章")
        return

    print(f"\n✅ 抓取完成，共 {len(articles)} 篇")
    save_txt(articles, url, filename)


def main():
    print(BANNER)
    while True:
        print("\n请选择操作：")
        print("  1. 开始爬取")
        print("  2. 退出")
        choice = ask("输入序号: ")

        if choice == "1":
            run_crawl()
        elif choice in ("2", "q", "exit"):
            print("👋 再见！")
            break
        else:
            print("❌ 无效选项")


if __name__ == "__main__":
    main()