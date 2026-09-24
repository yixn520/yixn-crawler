#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yixn 全能蜘蛛爬虫 v3.1（修复版）
====================================
修复：
  🔧 RLock 死锁（原 Lock 嵌套调用导致线程卡死）
  🔧 控制字符清洗，避免 lxml 崩溃
  🔧 BeautifulSoup lxml → html.parser 降级
  🔧 parse 异常打印完整堆栈
  🔧 翻页链接后缀过滤

功能：
  ✅ 并发爬取 / 自动翻页 / 断点续爬 / 失败重试
  ✅ 自研进度条 / 多格式导出 / 图片归档
  ✅ 自研正文提取 / 增量更新 / Cookie / 配置 / 日志

依赖：requests / beautifulsoup4 / lxml（自动安装）
"""

import os
import re
import sys
import csv
import json
import time
import hashlib
import logging
import argparse
import threading
import subprocess
import importlib
import urllib.parse
import traceback
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue, Empty
from typing import Set, Dict, List, Optional, Tuple, Any
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 依赖自动安装
# ============================================================

REQUIRED = {
    'requests': 'requests',
    'bs4': 'beautifulsoup4',
    'lxml': 'lxml',
}


def _install_pkg(pkg: str) -> bool:
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg, "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except Exception:
        return False


def ensure_dependencies():
    missing = []
    for mod, pkg in REQUIRED.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"📦 需要安装依赖: {', '.join(missing)}")
        for pkg in missing:
            ok = _install_pkg(pkg)
            print(f"  {'✅' if ok else '❌'} {pkg}")
        print()


ensure_dependencies()

import requests
from bs4 import BeautifulSoup


# ============================================================
# 日志系统
# ============================================================

def setup_logger(output_dir: str, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("yixn")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    log_dir = os.path.join(output_dir, "logs")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        os.path.join(log_dir, "yixn.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8'
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ============================================================
# 进度条
# ============================================================

class ProgressBar:
    def __init__(self, total: int, prefix: str = "", width: int = 30,
                 enabled: bool = True):
        self.total = max(total, 1)
        self.prefix = prefix
        self.width = width
        self.enabled = enabled
        self.n = 0
        self.start = time.time()
        self._last_render = 0.0
        self._lock = threading.Lock()

    def update(self, n: int = 1):
        with self._lock:
            self.n += n
        self._render()

    def set(self, n: int):
        with self._lock:
            self.n = n
        self._render()

    def _render(self, force: bool = False):
        if not self.enabled:
            return
        now = time.time()
        if not force and now - self._last_render < 0.15:
            return
        self._last_render = now

        with self._lock:
            n = min(self.n, self.total)
        frac = n / self.total
        filled = int(self.width * frac)
        bar = "█" * filled + "░" * (self.width - filled)
        elapsed = max(now - self.start, 0.001)
        speed = n / elapsed

        if n > 0 and speed > 0:
            remain = (self.total - n) / speed
            eta = str(timedelta(seconds=int(remain)))
        else:
            eta = "--:--:--"

        line = (f"\r{self.prefix} |{bar}| {n}/{self.total} "
                f"[{frac*100:5.1f}%] {speed:5.1f}页/s ETA {eta}")
        sys.stdout.write(line)
        sys.stdout.flush()

    def close(self):
        if self.enabled:
            self._render(force=True)
            sys.stdout.write("\n")
            sys.stdout.flush()


# ============================================================
# 常量
# ============================================================

NEXT_PAGE_KEYWORDS = [
    'next', '下一页', '下页', 'older', 'more', '›', '»',
    '下一章', '下一篇', '→',
]

SKIP_EXT = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.rar', '.7z', '.tar', '.gz', '.exe', '.msi',
    '.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv',
    '.mp3', '.wav', '.flac', '.aac', '.css', '.js',
}

IMG_EXT_MAP = {
    'jpg': 'jpg', 'jpeg': 'jpg', 'png': 'png', 'gif': 'gif',
    'bmp': 'bmp', 'svg': 'svg', 'webp': 'webp', 'ico': 'ico',
    'tiff': 'tiff', 'tif': 'tiff',
}

NON_CONTENT_KEYWORDS = [
    'nav', 'menu', 'footer', 'header', 'sidebar', 'side-bar',
    'comment', 'advert', 'banner', 'share', 'related', 'recommend',
    'breadcrumb', 'pagination', 'copyright', 'friendlink',
    'toolbar', 'meta', 'tag-list', 'subscribe',
]

# 控制字符（保留 \t \n \r）
_CTRL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


# ============================================================
# 主爬虫类
# ============================================================

class YixnCrawlerV3:

    def __init__(
        self,
        start_url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        allow_cross_domain: bool = False,
        output_dir: str = "yixn-output",
        download_images: bool = True,
        concurrency: int = 8,
        img_concurrency: int = 5,
        formats: Optional[List[str]] = None,
        follow_pagination: bool = True,
        cookie_file: Optional[str] = None,
        resume: bool = False,
        incremental: bool = False,
        verbose: bool = False,
        debug: bool = False,
    ):
        self.start_url = start_url
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.allow_cross_domain = allow_cross_domain
        self.output_dir = output_dir
        self.download_images = download_images
        self.concurrency = max(1, concurrency)
        self.img_concurrency = max(1, img_concurrency)
        self.formats = formats or ['txt', 'json']
        self.follow_pagination = follow_pagination
        self.cookie_file = cookie_file
        self.resume = resume
        self.incremental = incremental
        self.debug = debug

        self._create_dirs()
        self.logger = setup_logger(output_dir, verbose=verbose or debug)

        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

        # ✅ 关键修复 1：使用 RLock，允许同线程重入
        self.lock = threading.RLock()

        # Session
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        if cookie_file and os.path.exists(cookie_file):
            self._load_cookies(cookie_file)

        # 容器
        self.visited_urls: Set[str] = set()
        self.queued_urls: Set[str] = set()
        self.image_queue: Queue = Queue()
        self.downloaded_image_urls: Set[str] = set()

        self.results: Dict[str, Any] = {
            'pages': [],
            'links': set(),
            'images': set(),
        }

        self.stats = {
            'total_pages': 0,
            'total_links': 0,
            'total_images': 0,
            'downloaded_images': 0,
            'total_content': 0,
            'errors': 0,
            'skipped_non_html': 0,
            'retries': 0,
            'parse_errors': 0,        # 新增：解析错误计数
        }

        self.base_domain = urlparse(start_url).netloc
        self.domains: Set[str] = {self.base_domain}

        self.cache: Dict[str, str] = {}
        if incremental:
            self._load_cache()

        self.state_file = os.path.join(self.output_dir, ".yixn_state.json")
        self.cache_file = os.path.join(self.output_dir, ".yixn_cache.json")
        self.crawl_done = False

        self.logger.info("=" * 60)
        self.logger.info("🕷️  Yixn 全能蜘蛛爬虫 v3.1")
        self.logger.info(f"📌 起始URL : {start_url}")
        self.logger.info(f"📊 深度/页数: {max_depth} / {max_pages}")
        self.logger.info(f"⚡ 并发    : {self.concurrency} (图片 {self.img_concurrency})")
        self.logger.info(f"🌐 跨域    : {'是' if allow_cross_domain else '否'}")
        self.logger.info(f"🖼️  图片    : {'启用' if download_images else '禁用'}")
        self.logger.info(f"📦 导出格式: {','.join(self.formats)}")
        self.logger.info(f"📁 输出目录: {os.path.abspath(output_dir)}")
        if resume:
            self.logger.info("💾 断点续爬: 启用")
        if incremental:
            self.logger.info("🔄 增量更新: 启用")
        self.logger.info("=" * 60)

    # ============ 目录 ============

    def _create_dirs(self):
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        for sub in ['pages', 'contents', 'images', 'links', 'data']:
            Path(os.path.join(self.output_dir, sub)).mkdir(exist_ok=True)
        if self.download_images:
            Path(os.path.join(self.output_dir, 'downloaded_images')).mkdir(exist_ok=True)

    # ============ Cookie ============

    def _load_cookies(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    self.session.cookies.set(k, v)
            elif isinstance(data, list):
                for item in data:
                    self.session.cookies.set(item['name'], item['value'],
                                             domain=item.get('domain'))
            self.logger.info(f"🍪 已加载 Cookie: {path}")
        except Exception as e:
            self.logger.warning(f"Cookie 加载失败: {e}")

    # ============ 缓存 / 状态 ============

    def _load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
                self.logger.info(f"🔄 已加载增量缓存: {len(self.cache)} 条")
            except Exception:
                self.cache = {}

    def _save_cache(self):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False)
        except Exception as e:
            self.logger.warning(f"缓存保存失败: {e}")

    def _save_state(self):
        with self.lock:
            state = {
                'start_url': self.start_url,
                'visited_urls': list(self.visited_urls),
                'queued_urls': list(self.queued_urls),
                'stats': dict(self.stats),
                'domains': list(self.domains),
                'saved_at': datetime.now().isoformat(),
            }
        tmp = self.state_file + ".tmp"
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False)
            os.replace(tmp, self.state_file)
        except Exception as e:
            self.logger.warning(f"状态保存失败: {e}")

    def _load_state(self):
        if not os.path.exists(self.state_file):
            return False
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            self.visited_urls = set(state.get('visited_urls', []))
            self.queued_urls = set(state.get('queued_urls', []))
            self.stats.update(state.get('stats', {}))
            self.domains.update(state.get('domains', []))
            self.logger.info(f"💾 已恢复进度: 已访问 {len(self.visited_urls)} 页")
            return True
        except Exception as e:
            self.logger.warning(f"状态恢复失败: {e}")
            return False

    # ============ URL 工具 ============

    def _hash(self, s: str, n: int = 16) -> str:
        return hashlib.md5(s.encode()).hexdigest()[:n]

    def _normalize_url(self, url: str, base: str) -> Optional[str]:
        try:
            if not url:
                return None
            url = url.strip()
            if url.startswith('//'):
                url = 'https:' + url
            elif url.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'data:')):
                return None
            elif not url.startswith(('http://', 'https://')):
                url = urljoin(base, url)
            p = urlparse(url)
            if p.scheme not in ('http', 'https'):
                return None
            # ✅ 修复：过滤明显非 HTML 后缀
            path_lower = p.path.lower()
            if any(path_lower.endswith(e) for e in SKIP_EXT):
                return None
            q = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
            q.sort()
            query = urllib.parse.urlencode(q)
            return urllib.parse.urlunparse(
                (p.scheme, p.netloc, p.path, p.params, query, '')
            )
        except Exception:
            return None

    def _is_same_domain(self, url: str) -> bool:
        try:
            d = urlparse(url).netloc
            if not d:
                return False
            if self.allow_cross_domain:
                with self.lock:
                    if d not in self.domains:
                        self.domains.add(d)
                return True
            return d in self.domains
        except Exception:
            return False

    def _should_crawl(self, url: str) -> bool:
        with self.lock:
            if url in self.visited_urls:
                return False
            if len(self.visited_urls) >= self.max_pages:
                return False
        if not self._is_same_domain(url):
            return False
        path = urlparse(url).path.lower()
        return not any(path.endswith(e) for e in SKIP_EXT)

    # ============ 请求（含重试）============

    def fetch(self, url: str, max_retry: int = 3, timeout: int = 15) -> Tuple[Optional[str], Dict]:
        meta: Dict[str, Any] = {}
        for attempt in range(max_retry):
            try:
                r = self.session.get(url, timeout=timeout, allow_redirects=True)
                meta = {
                    'status_code': r.status_code,
                    'content_type': r.headers.get('content-type', '').lower(),
                    'size': len(r.content),
                    'final_url': r.url,
                }
                if r.status_code == 200:
                    if r.encoding is None or r.encoding == 'ISO-8859-1':
                        r.encoding = r.apparent_encoding or 'utf-8'
                    ct = meta['content_type']
                    if 'html' in ct or 'text' in ct or 'xml' in ct:
                        # ✅ 关键修复 2：清洗控制字符，避免 lxml 崩溃
                        html = _CTRL_RE.sub('', r.text)
                        return html, meta
                    return None, meta
                if 500 <= r.status_code < 600 and attempt < max_retry - 1:
                    with self.lock:
                        self.stats['retries'] += 1
                    time.sleep(2 ** attempt)
                    continue
                return None, meta
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt < max_retry - 1:
                    with self.lock:
                        self.stats['retries'] += 1
                    time.sleep(2 ** attempt)
                    continue
                meta['error'] = str(e)
                return None, meta
            except Exception as e:
                meta['error'] = str(e)
                return None, meta
        return None, meta

    # ============ 解析 ============

    def parse(self, html: str, url: str) -> Dict:
        out = {
            'links': [], 'images': [], 'image_elements': [],
            'content': '', 'title': '', 'word_count': 0,
            'next_page': None, 'markdown': '',
        }
        # ✅ 关键修复 3：BS 降级 + 完整堆栈
        try:
            soup = self._make_soup(html)
        except Exception as e:
            with self.lock:
                self.stats['parse_errors'] += 1
            if self.debug:
                self.logger.error(
                    f"❌ BeautifulSoup 初始化失败 {url}: {e}\n"
                    f"{traceback.format_exc()}"
                )
            else:
                self.logger.error(f"❌ BS 初始化失败 {url}: {e}")
            return out

        try:
            title_tag = soup.find('title')
            out['title'] = title_tag.get_text().strip() if title_tag else ''

            # 链接
            for tag in soup.find_all(['a', 'link']):
                href = tag.get('href')
                if href:
                    n = self._normalize_url(href, url)
                    if n:
                        out['links'].append(n)

            # 自动翻页 - rel=next
            for a in soup.find_all('a', rel=lambda v: v and 'next' in v):
                href = a.get('href')
                if href:
                    n = self._normalize_url(href, url)
                    if n:
                        out['next_page'] = n
                        break

            # 关键词匹配
            if self.follow_pagination and not out['next_page']:
                for a in soup.find_all('a'):
                    text = (a.get_text() or '').strip().lower()
                    aria = (a.get('aria-label') or '').lower()
                    cls = ' '.join(a.get('class', [])).lower()
                    rel = ' '.join(a.get('rel', [])).lower()
                    blob = f"{text} {aria} {cls} {rel}"
                    if any(k in blob for k in NEXT_PAGE_KEYWORDS):
                        href = a.get('href')
                        if href:
                            n = self._normalize_url(href, url)
                            if n and n != url:
                                out['next_page'] = n
                                break

            # 图片
            for img in soup.find_all('img'):
                src = (img.get('src') or img.get('data-src')
                       or img.get('data-original') or img.get('data-lazy-src'))
                if src:
                    n = self._normalize_url(src, url)
                    if n:
                        out['images'].append(n)
                        out['image_elements'].append({
                            'url': n,
                            'alt': img.get('alt', ''),
                            'title': img.get('title', ''),
                        })

            # 正文
            content, md = self._extract_content(html, url)
            out['content'] = content
            out['markdown'] = md
            out['word_count'] = len(content.split())

        except Exception as e:
            with self.lock:
                self.stats['parse_errors'] += 1
            if self.debug:
                self.logger.error(
                    f"❌ 解析失败 {url}: {e}\n{traceback.format_exc()}"
                )
            else:
                self.logger.error(f"❌ 解析失败 {url}: {e}")

        return out

    def _make_soup(self, html: str) -> BeautifulSoup:
        """构造 BeautifulSoup，lxml 失败时降级 html.parser"""
        try:
            return BeautifulSoup(html, 'lxml')
        except Exception:
            return BeautifulSoup(html, 'html.parser')

    # ---- 正文提取 ----

    def _extract_content(self, raw_html: str, url: str) -> Tuple[str, str]:
        """自研正文提取（文本密度算法）"""
        work = self._make_soup(raw_html)

        for tag in work(['script', 'style', 'noscript', 'iframe',
                         'nav', 'footer', 'header', 'aside',
                         'form', 'button', 'svg', 'canvas']):
            try:
                tag.decompose()
            except Exception:
                pass

        for tag in work.find_all(True):
            try:
                ident = ' '.join(filter(None, [
                    tag.get('id', '') or '',
                    ' '.join(tag.get('class', [])) if tag.get('class') else '',
                ])).lower()
                if ident and any(k in ident for k in NON_CONTENT_KEYWORDS):
                    tag.decompose()
            except Exception:
                pass

        candidates: List[Any] = []
        candidates.extend(work.find_all('article'))
        candidates.extend(work.find_all(attrs={'role': 'main'}))
        for tag in work.find_all(['div', 'section', 'main']):
            try:
                ident = ' '.join(filter(None, [
                    tag.get('id', '') or '',
                    ' '.join(tag.get('class', [])) if tag.get('class') else '',
                ])).lower()
                if any(k in ident for k in ['article', 'content', 'post',
                                             'entry', 'main', 'detail', 'body']):
                    candidates.append(tag)
            except Exception:
                pass
        if not candidates and work.body:
            candidates.append(work.body)

        def text_density(tag) -> float:
            try:
                text = tag.get_text(separator=' ', strip=True)
                tlen = len(text)
                if tlen == 0:
                    return 0.0
                tag_count = len(tag.find_all(True)) or 1
                p_count = len(tag.find_all('p'))
                link_len = sum(len(a.get_text(strip=True))
                               for a in tag.find_all('a'))
                link_ratio = link_len / tlen
                score = (tlen / tag_count) * (1 - min(link_ratio, 1.0))
                score += p_count * 5
                if p_count:
                    score += (tlen / p_count) * 0.5
                return score
            except Exception:
                return 0.0

        best = max(candidates, key=text_density) if candidates else work

        try:
            text = best.get_text(separator='\n', strip=True)
        except Exception:
            text = ''
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        text = '\n'.join(lines)

        # 从原始 soup 取 title
        title = ''
        try:
            orig = self._make_soup(raw_html)
            tt = orig.find('title')
            title = tt.get_text().strip() if tt else ''
        except Exception:
            pass

        md = self._to_markdown(best, title, url)

        return text[:20000], md

    def _to_markdown(self, soup: BeautifulSoup, title: str, url: str) -> str:
        lines = [f"# {title}\n", f"> 来源: {url}\n"]
        try:
            elements = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                                      'p', 'li', 'pre', 'blockquote'])
        except Exception:
            return '\n'.join(lines)

        for el in elements:
            try:
                t = el.get_text(strip=True)
            except Exception:
                continue
            if not t:
                continue
            name = el.name
            if name.startswith('h'):
                try:
                    lvl = int(name[1])
                except Exception:
                    lvl = 2
                lines.append(f"\n{'#' * lvl} {t}\n")
            elif name == 'li':
                lines.append(f"- {t}")
            elif name == 'pre':
                lines.append(f"\n```\n{t}\n```\n")
            elif name == 'blockquote':
                lines.append(f"> {t}\n")
            else:
                lines.append(f"\n{t}\n")
        return '\n'.join(lines)

    # ============ 图片下载 ============

    def _img_filename(self, url: str, content_type: str = '') -> Tuple[str, str]:
        p = urlparse(url)
        path = p.path.lower()
        ext = None
        for k, v in IMG_EXT_MAP.items():
            if path.endswith(f'.{k}'):
                ext = v
                break
        if not ext and content_type:
            ct = content_type.lower()
            if 'jpeg' in ct or 'jpg' in ct: ext = 'jpg'
            elif 'png' in ct: ext = 'png'
            elif 'gif' in ct: ext = 'gif'
            elif 'webp' in ct: ext = 'webp'
            elif 'svg' in ct: ext = 'svg'
        return ext or 'jpg', self._hash(url)

    def download_image(self, img_url: str, article_dir: str,
                       referer: str = '') -> Optional[str]:
        with self.lock:
            if img_url in self.downloaded_image_urls:
                return None
        try:
            headers = {'Referer': referer} if referer else {}
            r = self.session.get(img_url, headers=headers, timeout=15, stream=True)
            if r.status_code != 200:
                return None
            ext, h = self._img_filename(img_url, r.headers.get('content-type', ''))
            filename = f"{h}.{ext}"
            fp = os.path.join(article_dir, filename)
            if os.path.exists(fp):
                with self.lock:
                    self.downloaded_image_urls.add(img_url)
                return fp
            with open(fp, 'wb') as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
            with self.lock:
                self.downloaded_image_urls.add(img_url)
                self.stats['downloaded_images'] += 1
            return fp
        except Exception as e:
            self.logger.debug(f"图片下载失败 {img_url}: {e}")
            return None

    def _safe_dirname(self, title: str, url: str) -> str:
        if not title:
            title = self._hash(url, 8)
        s = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', title).strip()
        s = s[:80] if len(s) > 80 else s
        if not s:
            s = self._hash(url, 8)
        return f"{self._hash(url, 8)}-{s}"

    # ============ 保存数据 ============

    def save_page(self, url: str, depth: int, parsed: Dict, meta: Dict):
        h = self._hash(url)
        domain = urlparse(url).netloc
        title = parsed.get('title', '') or 'untitled'
        content = parsed.get('content', '')

        try:
            if content:
                with open(os.path.join(self.output_dir, 'contents', f"{h}.txt"),
                          'w', encoding='utf-8') as f:
                    f.write(f"标题: {title}\nURL: {url}\n域名: {domain}\n深度: {depth}\n")
                    f.write(f"时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                    f.write("=" * 60 + "\n\n")
                    f.write(content)
                with self.lock:
                    self.stats['total_content'] += 1

            with open(os.path.join(self.output_dir, 'links', f"{h}.txt"),
                      'w', encoding='utf-8') as f:
                f.write(f"页面: {url}\n标题: {title}\n" + "=" * 60 + "\n")
                for i, l in enumerate(parsed.get('links', []), 1):
                    f.write(f"{i}. {l}\n")

            if parsed.get('images'):
                with open(os.path.join(self.output_dir, 'images', f"{h}.txt"),
                          'w', encoding='utf-8') as f:
                    f.write(f"页面: {url}\n标题: {title}\n" + "=" * 60 + "\n")
                    for i, im in enumerate(parsed.get('images', []), 1):
                        f.write(f"{i}. {im}\n")

            page_meta = {
                'url': url, 'title': title, 'depth': depth,
                'word_count': parsed.get('word_count', 0),
                'link_count': len(parsed.get('links', [])),
                'image_count': len(parsed.get('images', [])),
                'meta': meta,
                'crawled_at': datetime.now().isoformat(),
            }
            with open(os.path.join(self.output_dir, 'pages', f"{h}.json"),
                      'w', encoding='utf-8') as f:
                json.dump(page_meta, f, ensure_ascii=False, indent=2)

            with self.lock:
                self.results['pages'].append(page_meta)
                self.results['links'].update(parsed.get('links', []))
                self.results['images'].update(parsed.get('images', []))
                self.stats['total_links'] = len(self.results['links'])
                self.stats['total_images'] = len(self.results['images'])
        except Exception as e:
            self.logger.error(f"保存失败 {url}: {e}")
            if self.debug:
                self.logger.error(traceback.format_exc())

        # 图片入队（按文章归档）
        if self.download_images and parsed.get('image_elements'):
            try:
                article_dir_name = self._safe_dirname(title, url)
                article_dir = os.path.join(
                    self.output_dir, 'downloaded_images', article_dir_name
                )
                Path(article_dir).mkdir(parents=True, exist_ok=True)
                for el in parsed['image_elements']:
                    self.image_queue.put((el['url'], article_dir, url))
            except Exception as e:
                self.logger.debug(f"图片入队失败 {url}: {e}")

        # 增量缓存
        if self.incremental:
            ch = hashlib.md5(content.encode('utf-8', 'ignore')).hexdigest()
            with self.lock:
                self.cache[url] = ch

    # ============ 图片下载线程 ============

    def _img_worker(self):
        while True:
            try:
                item = self.image_queue.get(timeout=2)
            except Empty:
                if self.crawl_done and self.image_queue.empty():
                    break
                continue
            if item is None:
                break
            img_url, article_dir, referer = item
            try:
                self.download_image(img_url, article_dir, referer)
            except Exception as e:
                self.logger.debug(f"图片 worker 异常: {e}")

    # ============ 单页处理 ============

    def process_one(self, url: str, depth: int) -> Optional[Dict]:
        if not self._should_crawl(url):
            return None

        with self.lock:
            if url in self.visited_urls:
                return None
            self.visited_urls.add(url)

        html, meta = self.fetch(url)

        if html is None:
            ct = meta.get('content_type', '')
            if ct and 'html' not in ct and 'text' not in ct:
                with self.lock:
                    self.stats['skipped_non_html'] += 1
            else:
                with self.lock:
                    self.stats['errors'] += 1
            return None

        # 增量：跳过未变更
        if self.incremental and url in self.cache:
            h_now = hashlib.md5(html.encode('utf-8', 'ignore')).hexdigest()
            if h_now == self.cache.get(url):
                self.logger.debug(f"⏭️  未变更跳过: {url}")
                return None

        parsed = self.parse(html, url)
        self.save_page(url, depth, parsed, meta)

        with self.lock:
            self.stats['total_pages'] += 1

        new_tasks = []
        if depth < self.max_depth:
            for link in parsed.get('links', []):
                if link in self.visited_urls:
                    continue
                if not self._is_same_domain(link):
                    continue
                if not self._should_crawl(link):
                    continue
                with self.lock:
                    if link in self.queued_urls:
                        continue
                    self.queued_urls.add(link)
                new_tasks.append((link, depth + 1))

        if self.follow_pagination and parsed.get('next_page') and depth < self.max_depth:
            np = parsed['next_page']
            with self.lock:
                if np not in self.visited_urls and np not in self.queued_urls:
                    self.queued_urls.add(np)
                    new_tasks.append((np, depth))

        return {'new_tasks': new_tasks, 'url': url}

    # ============ 主流程 ============

    def crawl(self):
        start = self._normalize_url(self.start_url, self.start_url)
        if not start:
            self.logger.error("❌ 起始URL无效")
            return

        if self.resume and self._load_state():
            initial = [(u, 0) for u in self.queued_urls
                       if u not in self.visited_urls]
            if not initial:
                initial = [(start, 0)]
        else:
            self.queued_urls.add(start)
            initial = [(start, 0)]

        # 图片下载线程
        img_threads = []
        if self.download_images:
            for _ in range(self.img_concurrency):
                t = threading.Thread(target=self._img_worker, daemon=True)
                t.start()
                img_threads.append(t)

        start_time = time.time()
        self.logger.info("🚀 开始爬取...")

        progress = ProgressBar(self.max_pages, prefix="📄 爬取进度")

        task_queue: Queue = Queue()
        for t in initial:
            task_queue.put(t)

        # 哨兵计数：用 sentinel 结束
        active_workers = [self.concurrency]

        def worker():
            while True:
                try:
                    item = task_queue.get(timeout=2)
                except Empty:
                    with self.lock:
                        if self.crawl_done:
                            break
                    continue

                if item is None:
                    task_queue.task_done()
                    break

                url, depth = item

                try:
                    result = self.process_one(url, depth)
                except Exception as e:
                    self.logger.error(f"任务异常 {url}: {e}")
                    if self.debug:
                        self.logger.error(traceback.format_exc())
                    result = None

                progress.set(len(self.visited_urls))

                if result and result.get('new_tasks'):
                    with self.lock:
                        can_add = (self.max_pages
                                   - len(self.visited_urls)
                                   - task_queue.qsize())
                    for nt in result['new_tasks']:
                        if can_add <= 0:
                            break
                        task_queue.put(nt)
                        can_add -= 1

                task_queue.task_done()

                # 定期保存
                with self.lock:
                    done = len(self.visited_urls)
                if done > 0 and done % 20 == 0:
                    self._save_state()
                    if self.incremental:
                        self._save_cache()

        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            futures = [ex.submit(worker) for _ in range(self.concurrency)]

            # 监控
            while True:
                with self.lock:
                    done = len(self.visited_urls)
                if done >= self.max_pages:
                    break
                if task_queue.empty() and all(f.done() for f in futures):
                    break
                time.sleep(0.3)

            # 收尾
            self.crawl_done = True
            for _ in range(self.concurrency):
                task_queue.put(None)
            for f in as_completed(futures):
                try:
                    f.result(timeout=5)
                except Exception:
                    pass

        progress.close()

        # 等待图片下载
        self.crawl_done = True
        for _ in range(self.img_concurrency):
            self.image_queue.put(None)
        for t in img_threads:
            t.join(timeout=60)

        self._save_state()
        if self.incremental:
            self._save_cache()

        elapsed = time.time() - start_time
        self._export_all()
        self._generate_report(elapsed)
        self._print_summary()
        self._save_summary()

    # ============ 导出 ============

    def _export_all(self):
        fmt = set(self.formats)
        if 'json' in fmt:
            self._export_json()
        if 'csv' in fmt:
            self._export_csv()
        if 'md' in fmt:
            self._export_markdown()
        if 'txt' in fmt:
            self._export_txt()

    def _export_json(self):
        data = {
            'start_url': self.start_url,
            'exported_at': datetime.now().isoformat(),
            'pages': self.results['pages'],
            'links': sorted(self.results['links']),
            'images': sorted(self.results['images']),
        }
        fp = os.path.join(self.output_dir, 'data', 'result.json')
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.logger.info(f"📦 JSON 已导出: {fp}")

    def _export_csv(self):
        fp = os.path.join(self.output_dir, 'data', 'pages.csv')
        with open(fp, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['URL', '标题', '深度', '字数', '链接数',
                        '图片数', '状态码', '时间'])
            for p in self.results['pages']:
                w.writerow([
                    p['url'], p['title'], p['depth'],
                    p['word_count'], p['link_count'], p['image_count'],
                    p.get('meta', {}).get('status_code', ''),
                    p.get('crawled_at', ''),
                ])
        self.logger.info(f"📦 CSV 已导出: {fp}")

    def _export_markdown(self):
        fp = os.path.join(self.output_dir, 'data', 'result.md')
        with open(fp, 'w', encoding='utf-8') as f:
            f.write("# 爬取结果\n\n")
            f.write(f"- 起始URL: {self.start_url}\n")
            f.write(f"- 页面数: {len(self.results['pages'])}\n")
            f.write(f"- 链接数: {len(self.results['links'])}\n")
            f.write(f"- 图片数: {len(self.results['images'])}\n")
            f.write(f"- 导出时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
            f.write("---\n\n")
            for p in self.results['pages']:
                f.write(f"## [{p['title']}]({p['url']})\n\n")
                f.write(f"- 深度: {p['depth']}, 字数: {p['word_count']}, "
                        f"链接: {p['link_count']}, 图片: {p['image_count']}\n\n")
        self.logger.info(f"📦 Markdown 已导出: {fp}")

    def _export_txt(self):
        fp = os.path.join(self.output_dir, 'data', 'result.txt')
        with open(fp, 'w', encoding='utf-8') as f:
            f.write("Yixn 爬虫 v3.1 导出结果\n" + "=" * 60 + "\n")
            f.write(f"起始URL: {self.start_url}\n")
            f.write(f"页面数: {len(self.results['pages'])}\n")
            f.write(f"链接数: {len(self.results['links'])}\n")
            f.write(f"图片数: {len(self.results['images'])}\n")
            f.write(f"导出时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
            for p in self.results['pages']:
                f.write(f"[{p['depth']}] {p['title']}\n    {p['url']}\n")
        self.logger.info(f"📦 TXT 已导出: {fp}")

    # ============ 报告 ============

    def _generate_report(self, elapsed: float):
        report = {
            'crawler': 'Yixn 全能蜘蛛爬虫 v3.1',
            'start_url': self.start_url,
            'base_domain': self.base_domain,
            'config': {
                'max_depth': self.max_depth,
                'max_pages': self.max_pages,
                'allow_cross_domain': self.allow_cross_domain,
                'download_images': self.download_images,
                'concurrency': self.concurrency,
                'img_concurrency': self.img_concurrency,
                'formats': self.formats,
                'follow_pagination': self.follow_pagination,
                'resume': self.resume,
                'incremental': self.incremental,
            },
            'end_time': datetime.now().isoformat(),
            'elapsed_seconds': round(elapsed, 2),
            'statistics': self.stats,
            'domains': list(self.domains),
        }
        fp = os.path.join(self.output_dir, 'crawl_report.json')
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    def _print_summary(self):
        log = self.logger.info
        log("=" * 60)
        log("  📊 爬取完成摘要")
        log("=" * 60)
        log(f"✅ 成功爬取页面 : {len(self.visited_urls)}")
        log(f"🔗 发现唯一链接 : {len(self.results['links'])}")
        log(f"🖼️  发现唯一图片 : {len(self.results['images'])}")
        if self.download_images:
            log(f"💾 已下载图片   : {self.stats['downloaded_images']}")
        log(f"📄 保存内容文件 : {self.stats['total_content']}")
        log(f"⏭️  跳过非HTML   : {self.stats['skipped_non_html']}")
        log(f"🔁 重试次数     : {self.stats['retries']}")
        log(f"⚠️  解析错误     : {self.stats.get('parse_errors', 0)}")
        log(f"❌ 错误数量     : {self.stats['errors']}")
        log(f"📁 输出目录     : {os.path.abspath(self.output_dir)}")
        log("=" * 60)

    def _save_summary(self):
        fp = os.path.join(self.output_dir, 'summary.txt')
        with open(fp, 'w', encoding='utf-8') as f:
            f.write("Yixn 全能蜘蛛爬虫 v3.1 — 摘要\n" + "=" * 40 + "\n")
            f.write(f"起始URL: {self.start_url}\n")
            f.write(f"页面数: {len(self.visited_urls)}\n")
            f.write(f"链接数: {len(self.results['links'])}\n")
            f.write(f"图片数: {len(self.results['images'])}\n")
            if self.download_images:
                f.write(f"下载图片: {self.stats['downloaded_images']}\n")
            f.write(f"内容文件: {self.stats['total_content']}\n")
            f.write(f"解析错误: {self.stats.get('parse_errors', 0)}\n")
            f.write(f"错误: {self.stats['errors']}\n")
            f.write(f"目录: {os.path.abspath(self.output_dir)}\n")


# ============================================================
# 配置文件
# ============================================================

def load_config(path: str) -> Dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ 配置加载失败: {e}")
        return {}


def merge_config(args, cfg: Dict) -> Dict:
    site = args.site
    base = cfg.get('sites', {}).get(site, {}) if site else cfg.get('default', {})
    if not isinstance(base, dict):
        base = {}
    merged = dict(base)
    for k, v in vars(args).items():
        if v is None or v is False:
            continue
        if k in ('site', 'config'):
            continue
        merged[k] = v
    return merged


# ============================================================
# 命令行入口
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='yixn',
        description='Yixn 全能蜘蛛爬虫 v3.1',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python yixn.py -u https://example.com
  python yixn.py -u https://example.com -d 3 -p 200 --concurrency 10
  python yixn.py -u https://example.com --format txt,json,md,csv
  python yixn.py -u https://example.com --resume
  python yixn.py -u https://example.com --incremental
  python yixn.py --config config.json --site my-blog
        """
    )
    p.add_argument('-u', '--url', help='起始URL')
    p.add_argument('-d', '--depth', type=int, help='最大深度 (默认3)')
    p.add_argument('-p', '--pages', type=int, help='最大页数 (默认100)')
    p.add_argument('-o', '--output', help='输出目录')
    p.add_argument('--cross-domain', action='store_true',
                   help='允许跨域名 (默认不允许)')
    p.add_argument('--no-images', action='store_true', help='不下载图片')
    p.add_argument('--no-pagination', action='store_true', help='不自动翻页')
    p.add_argument('--concurrency', type=int, help='并发线程数 (默认8)')
    p.add_argument('--img-concurrency', type=int, help='图片下载线程数 (默认5)')
    p.add_argument('--format', dest='formats',
                   help='导出格式: txt,json,md,csv (逗号分隔)')
    p.add_argument('--cookie', help='Cookie JSON 文件')
    p.add_argument('--resume', action='store_true', help='断点续爬')
    p.add_argument('--incremental', action='store_true', help='增量更新')
    p.add_argument('--config', help='配置文件路径')
    p.add_argument('--site', help='配置中的站点名')
    p.add_argument('-v', '--verbose', action='store_true', help='详细日志')
    p.add_argument('--debug', action='store_true',
                   help='调试模式（打印完整异常堆栈）')
    p.add_argument('--interactive', action='store_true',
                   help='交互式输入参数')
    return p


def interactive_input() -> Dict:
    print("=" * 60)
    print("  🕷️  Yixn 全能蜘蛛爬虫 v3.1 (交互模式)")
    print("=" * 60)
    url = input("请输入要爬取的URL: ").strip()
    if not url:
        print("❌ URL不能为空!")
        sys.exit(1)
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    d = input("最大爬取深度 [默认3]: ").strip()
    p = input("最大爬取页数 [默认100]: ").strip()
    c = input("允许跨域名? (y/n) [默认n]: ").strip().lower()
    di = input("下载图片? (y/n) [默认y]: ").strip().lower()
    co = input("并发线程数 [默认8]: ").strip()
    fmt = input("导出格式 [默认txt,json]: ").strip() or "txt,json"
    od = input("输出目录 [默认yixn-output]: ").strip() or "yixn-output"
    rs = input("启用断点续爬? (y/n) [默认n]: ").strip().lower()

    return {
        'url': url,
        'depth': int(d) if d else 3,
        'pages': int(p) if p else 100,
        'cross_domain': c == 'y',
        'no_images': di == 'n',
        'concurrency': int(co) if co else 8,
        'formats': fmt,
        'output': od,
        'resume': rs == 'y',
    }


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.interactive or not args.url:
        it = interactive_input()
        for k, v in it.items():
            setattr(args, k, v)

    cfg = load_config(args.config)
    merged = merge_config(args, cfg)

    url = merged.get('url') or args.url
    if not url:
        parser.error("必须提供 --url 或使用 --interactive")

    formats = merged.get('formats') or 'txt,json'
    if isinstance(formats, str):
        formats = [f.strip() for f in formats.split(',') if f.strip()]

    crawler = YixnCrawlerV3(
        start_url=url,
        max_depth=int(merged.get('depth', 3)),
        max_pages=int(merged.get('pages', 100)),
        allow_cross_domain=bool(merged.get('cross_domain', False)),
        output_dir=merged.get('output', 'yixn-output'),
        download_images=not bool(merged.get('no_images', False)),
        concurrency=int(merged.get('concurrency', 8)),
        img_concurrency=int(merged.get('img_concurrency', 5)),
        formats=formats,
        follow_pagination=not bool(merged.get('no_pagination', False)),
        cookie_file=merged.get('cookie'),
        resume=bool(merged.get('resume', False)),
        incremental=bool(merged.get('incremental', False)),
        verbose=bool(merged.get('verbose', False)),
        debug=bool(merged.get('debug', False)),
    )

    try:
        crawler.crawl()
        print(f"\n✅ 爬取完成! 输出: {os.path.abspath(crawler.output_dir)}")
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断，正在保存...")
        crawler.crawl_done = True
        for _ in range(crawler.img_concurrency):
            crawler.image_queue.put(None)
        try:
            crawler._save_state()
            if crawler.incremental:
                crawler._save_cache()
            crawler._generate_report(0)
            crawler._save_summary()
        except Exception:
            pass
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()