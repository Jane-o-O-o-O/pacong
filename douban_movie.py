#!/usr/bin/env python3
"""
豆瓣电影爬虫 — 爬取电影信息、Top250、搜索功能
支持导出 JSON / CSV

Usage:
    python douban_movie.py top250              # 爬取 Top 250
    python douban_movie.py detail <movie_id>   # 爬取单部电影详情
    python douban_movie.py search <keyword>    # 搜索电影
    python douban_movie.py --help
"""

import json
import csv
import re
import sys
import time
import random
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# ─── 配置 ───────────────────────────────────────────────

BASE_URL = "https://movie.douban.com"
TOP250_URL = f"{BASE_URL}/top250"
SUBJECT_URL = f"{BASE_URL}/subject/{{movie_id}}/"
SEARCH_URL = f"{BASE_URL}/subject_search?search_text={{keyword}}&cat=1002"

# User-Agent 池（真实浏览器 UA）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

# 请求间隔（秒）
DELAY_MIN = 2.0
DELAY_MAX = 5.0

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("douban")


# ─── 数据模型 ──────────────────────────────────────────

@dataclass
class Movie:
    """电影数据"""
    id: str = ""
    title: str = ""                     # 中文名
    original_title: str = ""            # 原名
    year: str = ""
    rating: float = 0.0
    rating_count: int = 0
    director: str = ""
    screenwriter: str = ""
    actors: str = ""
    genre: str = ""
    region: str = ""
    language: str = ""
    duration: str = ""
    release_date: str = ""
    aka: str = ""                       # 又名
    imdb: str = ""
    synopsis: str = ""                  # 剧情简介
    poster_url: str = ""
    ranking: int = 0                    # Top250 排名
    tags: str = ""
    url: str = ""


# ─── 爬虫核心 ──────────────────────────────────────────

class DoubanScraper:
    """豆瓣电影爬虫"""

    def __init__(self, output_dir: str = "output"):
        self.session = requests.Session()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._request_count = 0
        # 初始化 session — 先访问首页拿 cookie
        self._init_session()

    def _init_session(self):
        """初始化 session：访问首页获取 cookie"""
        try:
            log.info("🍪 初始化 session 获取 cookie ...")
            self.session.get(
                "https://www.douban.com/",
                headers=self._get_headers(),
                timeout=15,
            )
            time.sleep(random.uniform(1, 2))
            self.session.get(
                BASE_URL,
                headers=self._get_headers(),
                timeout=15,
            )
            time.sleep(random.uniform(1, 2))
        except Exception as e:
            log.warning(f"Session 初始化失败（继续尝试）: {e}")

    def _get_headers(self) -> dict:
        """生成随机请求头"""
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer": BASE_URL,
            "Connection": "keep-alive",
            "Cache-Control": "max-age=0",
        }

    def _delay(self):
        """随机延迟，避免被封"""
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        log.debug(f"等待 {delay:.1f}s ...")
        time.sleep(delay)

    def _fetch(self, url: str, retry: int = 3) -> Optional[BeautifulSoup]:
        """获取页面，带重试和反爬"""
        for attempt in range(retry):
            try:
                self._request_count += 1
                if self._request_count > 1:
                    self._delay()

                resp = self.session.get(url, headers=self._get_headers(), timeout=15)

                if resp.status_code == 403:
                    log.warning(f"403 被限流，等待30s后重试 ({attempt+1}/{retry})")
                    time.sleep(30 + random.uniform(0, 10))
                    continue

                if resp.status_code == 404:
                    log.error(f"404 页面不存在: {url}")
                    return None

                resp.raise_for_status()
                resp.encoding = "utf-8"

                soup = BeautifulSoup(resp.text, "html.parser")

                # 检查是否触发验证码
                if "sec.douban.com" in resp.url or soup.find("div", id="captcha"):
                    log.warning(f"触发验证码，等待60s后重试 ({attempt+1}/{retry})")
                    time.sleep(60 + random.uniform(0, 30))
                    continue

                return soup

            except requests.RequestException as e:
                log.error(f"请求失败 ({attempt+1}/{retry}): {e}")
                if attempt < retry - 1:
                    time.sleep(10 * (attempt + 1))

        log.error(f"所有重试失败: {url}")
        return None

    # ─── Top 250 ────────────────────────────────────────

    def scrape_top250(self) -> list[Movie]:
        """爬取豆瓣电影 Top 250"""
        log.info("🎬 开始爬取豆瓣电影 Top 250 ...")
        movies = []

        for page in range(10):  # 10页，每页25部
            start = page * 25
            url = f"{TOP250_URL}?start={start}&filter="
            log.info(f"📄 第 {page+1}/10 页 (start={start})")

            soup = self._fetch(url)
            if not soup:
                log.error(f"第 {page+1} 页获取失败，跳过")
                continue

            items = soup.select("ol.grid_view li")
            if not items:
                log.warning(f"第 {page+1} 页无数据，可能被反爬")
                continue

            for item in items:
                movie = self._parse_top250_item(item)
                if movie:
                    movies.append(movie)
                    log.info(f"  #{movie.ranking:3d} {movie.title} ({movie.year}) ⭐{movie.rating}")

        log.info(f"✅ Top 250 爬取完成，共 {len(movies)} 部电影")
        return movies

    def _parse_top250_item(self, item) -> Optional[Movie]:
        """解析 Top 250 列表项"""
        try:
            movie = Movie()

            # 排名
            rank_em = item.select_one("em")
            if rank_em:
                movie.ranking = int(rank_em.text)

            # 链接和ID
            link = item.select_one(".hd a")
            if link:
                href = link.get("href", "")
                match = re.search(r"/subject/(\d+)/", href)
                if match:
                    movie.id = match.group(1)
                movie.url = href

            # 标题
            title_spans = item.select(".hd a span.title")
            if len(title_spans) >= 1:
                movie.title = title_spans[0].text.strip()
            if len(title_spans) >= 2:
                movie.original_title = title_spans[1].text.strip().lstrip("/ ")

            # 海报
            poster = item.select_one(".pic a img")
            if poster:
                movie.poster_url = poster.get("src", "")

            # 评分 — 结构是 .bd div span.rating_num
            rating = item.select_one("span.rating_num")
            if rating:
                try:
                    movie.rating = float(rating.text.strip())
                except ValueError:
                    pass

            # 评价人数
            rating_count = item.select_one("span.rating_num ~ span:last-child")
            if not rating_count:
                # 回退：bd 内 div 里最后一个 span
                bd_div = item.select_one(".bd > div")
                if bd_div:
                    spans = bd_div.select("span")
                    if spans:
                        rating_count = spans[-1]
            if rating_count:
                count_text = rating_count.text.strip()
                match = re.search(r"(\d+)", count_text)
                if match:
                    movie.rating_count = int(match.group(1))

            # 导演/演员/年份等信息（第一段 p）
            info_p = item.select_one(".bd p:first-child")
            if info_p:
                info_text = info_p.get_text(separator=" ", strip=True)
                # 导演 — 到"主演:"或行尾为止
                dir_match = re.search(r"导演:\s*(.+?)(?:\s+主演:|$)", info_text)
                if dir_match:
                    movie.director = dir_match.group(1).strip().rstrip(".")

                # 年份/地区/类型 — 在第二个文本行（<br>之后）
                raw = info_p.get_text(separator="\n")
                lines = [l.strip() for l in raw.split("\n") if l.strip()]
                if len(lines) >= 2:
                    year_line = lines[-1]
                elif len(lines) == 1 and "/" in lines[0]:
                    year_line = lines[0]
                else:
                    year_line = ""
                if year_line:
                    parts = [p.strip().replace("\xa0", " ") for p in year_line.split("/")]
                    if parts:
                        movie.year = parts[0].strip()
                    if len(parts) >= 2:
                        movie.region = parts[1].strip()
                    if len(parts) >= 3:
                        movie.genre = parts[2].strip()

            # 一句话评价
            quote = item.select_one(".bd p.quote span")
            if quote:
                movie.synopsis = quote.text.strip()

            return movie

        except Exception as e:
            log.error(f"解析列表项失败: {e}")
            return None

    # ─── 电影详情 ──────────────────────────────────────

    def scrape_detail(self, movie_id: str) -> Optional[Movie]:
        """爬取单部电影详情页（HTML 方式，失败时回退 API）"""
        url = SUBJECT_URL.format(movie_id=movie_id)
        log.info(f"🎬 爬取电影详情: {url}")

        soup = self._fetch(url)
        if not soup:
            # 回退到 API
            log.info("HTML 方式失败，尝试 API 方式 ...")
            return self._fetch_api_detail(movie_id)

        movie = self._parse_detail_page(soup, movie_id)
        if movie:
            log.info(f"✅ {movie.title} ({movie.year}) ⭐{movie.rating}")
        return movie

    def _fetch_api_detail(self, movie_id: str) -> Optional[Movie]:
        """通过 API 获取电影详情（备用方案）"""
        api_url = f"https://frodo.douban.com/api/v2/movie/{movie_id}"
        api_key = "0ac44ae016490db2204ce0a042db2916"  # 豆瓣小程序公开 key
        params = {
            "apikey": api_key,
        }
        headers = {
            "User-Agent": "api-client/1 com.douban.frodo/7.22.0.beta9(231) Android/23 product/Mi 10 vendor/Xiaomi model/Mi 10  rom/miui6  network/wifi  platform/AndroidPad",
            "Accept": "application/json",
        }
        try:
            self._delay()
            resp = self.session.get(api_url, params=params, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                movie = self._parse_api_data(data, movie_id)
                if movie:
                    log.info(f"✅ (API) {movie.title} ({movie.year}) ⭐{movie.rating}")
                return movie
            else:
                log.warning(f"API 返回 {resp.status_code}")
        except Exception as e:
            log.error(f"API 请求失败: {e}")
        return None

    def _parse_api_data(self, data: dict, movie_id: str) -> Optional[Movie]:
        """解析 API 返回的电影数据"""
        try:
            movie = Movie(
                id=movie_id,
                url=SUBJECT_URL.format(movie_id=movie_id),
                title=data.get("title", ""),
                original_title=data.get("original_title", ""),
                year=str(data.get("year", "")),
                poster_url=data.get("pic", {}).get("normal", "") or data.get("pic", {}).get("large", ""),
                synopsis=data.get("intro", "") or data.get("short_comment", {}).get("text", ""),
            )

            # 评分
            rating_data = data.get("rating", {})
            if rating_data:
                movie.rating = rating_data.get("value", 0) or 0
                movie.rating_count = rating_data.get("count", 0) or 0

            # 类型
            genres = data.get("genres", [])
            if genres:
                movie.genre = " / ".join(genres)

            # 国家
            countries = data.get("countries", [])
            if countries:
                movie.region = " / ".join(countries)

            # 语言
            languages = data.get("languages", [])
            if languages:
                movie.language = " / ".join(languages)

            # 片长
            durations = data.get("durations", [])
            if durations:
                movie.duration = " / ".join(durations)

            # 上映日期
            pubdate = data.get("pubdate", [])
            if pubdate:
                movie.release_date = " / ".join(pubdate)

            # 又名
            aka = data.get("aka", [])
            if aka:
                movie.aka = " / ".join(aka)

            # 导演
            directors = data.get("directors", [])
            if directors:
                movie.director = " / ".join(d.get("name", "") for d in directors if d.get("name"))

            # 编剧
            writers = data.get("writers", [])
            if writers:
                movie.screenwriter = " / ".join(w.get("name", "") for w in writers if w.get("name"))

            # 演员
            actors = data.get("actors", [])
            if actors:
                movie.actors = " / ".join(a.get("name", "") for a in actors[:10] if a.get("name"))

            # IMDb
            imdb_id = data.get("imdb_id", "")
            if imdb_id:
                movie.imdb = imdb_id

            # 标签
            tags = data.get("tags", [])
            if tags:
                movie.tags = " / ".join(t.get("name", "") for t in tags[:10] if t.get("name"))

            return movie

        except Exception as e:
            log.error(f"解析 API 数据失败: {e}")
            return None

    def _parse_detail_page(self, soup: BeautifulSoup, movie_id: str) -> Optional[Movie]:
        """解析电影详情页"""
        try:
            movie = Movie(id=movie_id, url=SUBJECT_URL.format(movie_id=movie_id))

            # 标题
            title_span = soup.select_one("h1 span[property='v:itemreviewed']")
            if title_span:
                full_title = title_span.text.strip()
                # 有些标题包含 "中文名 English Name"
                parts = full_title.split(" ", 1)
                movie.title = parts[0]
                if len(parts) > 1:
                    movie.original_title = parts[1]

            # 年份
            year_span = soup.select_one("h1 span.year")
            if year_span:
                movie.year = year_span.text.strip("()")

            # 海报
            poster = soup.select_one("#mainpic img")
            if poster:
                movie.poster_url = poster.get("src", "")

            # 评分
            rating_strong = soup.select_one("strong[property='v:average']")
            if rating_strong:
                try:
                    movie.rating = float(rating_strong.text.strip())
                except ValueError:
                    pass

            # 评价人数
            votes_span = soup.select_one("span[property='v:votes']")
            if votes_span:
                try:
                    movie.rating_count = int(votes_span.text.strip())
                except ValueError:
                    pass

            # #info 区块解析
            info_div = soup.select_one("#info")
            if info_div:
                self._parse_info_block(info_div, movie)

            # 剧情简介
            summary = soup.select_one("#link-report span[property='v:summary']")
            if not summary:
                summary = soup.select_one("#link-report span.short span[property='v:summary']")
            if not summary:
                summary = soup.select_one("div.indent span[property='v:summary']")
            if summary:
                movie.synopsis = summary.get_text(separator="\n", strip=True)

            # 标签
            tags = soup.select(".tags-body a")
            if tags:
                movie.tags = " / ".join(t.text.strip() for t in tags)

            return movie

        except Exception as e:
            log.error(f"解析详情页失败: {e}")
            return None

    def _parse_info_block(self, info_div: BeautifulSoup, movie: Movie):
        """解析 #info 信息区块"""
        html_str = str(info_div)

        # 按 <br> 分割各个字段
        # 移除 HTML 标签后按行解析
        info_text = info_div.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in info_text.split("\n") if l.strip()]

        current_key = None
        current_val = []

        for line in lines:
            # 检查是否是新的 key: value 行
            if ":" in line or "：" in line:
                # 保存上一个字段
                if current_key:
                    self._save_info_field(movie, current_key, " ".join(current_val))

                # 分割 key 和 value
                sep = "：" if "：" in line else ":"
                parts = line.split(sep, 1)
                current_key = parts[0].strip()
                current_val = [parts[1].strip()] if len(parts) > 1 and parts[1].strip() else []
            else:
                # 继续上一个字段的值
                current_val.append(line.strip())

        # 保存最后一个字段
        if current_key:
            self._save_info_field(movie, current_key, " ".join(current_val))

    def _save_info_field(self, movie: Movie, key: str, value: str):
        """将 info 字段映射到 Movie 对象"""
        value = value.strip().rstrip("/")
        key_map = {
            "导演": "director",
            "编剧": "screenwriter",
            "主演": "actors",
            "类型": "genre",
            "制片国家/地区": "region",
            "语言": "language",
            "片长": "duration",
            "上映日期": "release_date",
            "又名": "aka",
            "IMDb": "imdb",
        }
        for cn_key, field_name in key_map.items():
            if cn_key in key:
                setattr(movie, field_name, value)
                break

    # ─── 搜索 ──────────────────────────────────────────

    def search(self, keyword: str, max_pages: int = 3) -> list[Movie]:
        """搜索电影"""
        log.info(f"🔍 搜索: {keyword}")
        movies = []

        for page in range(max_pages):
            start = page * 15
            url = f"{BASE_URL}/subject_search?search_text={quote(keyword)}&cat=1002&start={start}"
            log.info(f"📄 搜索结果第 {page+1} 页")

            soup = self._fetch(url)
            if not soup:
                break

            # 搜索结果的结构
            items = soup.select(".result")
            if not items:
                # 尝试其他选择器
                items = soup.select("div.item")

            if not items:
                log.info("没有更多结果")
                break

            for item in items:
                movie = self._parse_search_item(item)
                if movie:
                    movies.append(movie)
                    log.info(f"  📽️ {movie.title} ({movie.year}) ⭐{movie.rating}")

        log.info(f"✅ 搜索完成，共 {len(movies)} 部电影")
        return movies

    def _parse_search_item(self, item) -> Optional[Movie]:
        """解析搜索结果项"""
        try:
            movie = Movie()

            # 标题
            title = item.select_one("div.title a")
            if not title:
                title = item.select_one("a.nbg")
            if title:
                movie.title = title.text.strip()
                href = title.get("href", "")
                match = re.search(r"/subject/(\d+)/", href)
                if match:
                    movie.id = match.group(1)
                    movie.url = f"{BASE_URL}/subject/{movie.id}/"

            # 评分
            rating = item.select_one(".rating_nums")
            if rating:
                try:
                    movie.rating = float(rating.text.strip())
                except ValueError:
                    pass

            # 信息
            info = item.select_one("div.info p")
            if info:
                info_text = info.text.strip()
                # 提取年份
                year_match = re.search(r"(\d{4})", info_text)
                if year_match:
                    movie.year = year_match.group(1)

            return movie if movie.title else None

        except Exception as e:
            log.error(f"解析搜索结果失败: {e}")
            return None

    # ─── 批量爬取详情 ─────────────────────────────────

    def scrape_details_batch(self, movie_ids: list[str]) -> list[Movie]:
        """批量爬取电影详情"""
        log.info(f"📦 批量爬取 {len(movie_ids)} 部电影详情 ...")
        movies = []

        for i, mid in enumerate(movie_ids):
            log.info(f"[{i+1}/{len(movie_ids)}] 爬取 {mid}")
            movie = self.scrape_detail(mid)
            if movie:
                movies.append(movie)

        log.info(f"✅ 批量爬取完成，成功 {len(movies)}/{len(movie_ids)}")
        return movies

    # ─── 导出 ──────────────────────────────────────────

    def export_json(self, movies: list[Movie], filename: str = "movies.json"):
        """导出为 JSON"""
        path = self.output_dir / filename
        data = [asdict(m) for m in movies]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info(f"📁 JSON 已保存: {path} ({len(movies)} 条记录)")
        return str(path)

    def export_csv(self, movies: list[Movie], filename: str = "movies.csv"):
        """导出为 CSV"""
        path = self.output_dir / filename
        if not movies:
            log.warning("无数据可导出")
            return ""

        fieldnames = list(asdict(movies[0]).keys())
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for m in movies:
                writer.writerow(asdict(m))
        log.info(f"📁 CSV 已保存: {path} ({len(movies)} 条记录)")
        return str(path)


# ─── CLI 入口 ──────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="🎬 豆瓣电影爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python douban_movie.py top250                    # 爬取 Top 250
  python douban_movie.py top250 --format csv       # 导出为 CSV
  python douban_movie.py detail 1292052            # 爬取肖申克的救赎详情
  python douban_movie.py detail 1292052 1291546    # 批量爬取详情
  python douban_movie.py search "诺兰"              # 搜索电影
  python douban_movie.py top250 --detail            # Top250 + 逐部爬取详情
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # top250
    p_top = subparsers.add_parser("top250", help="爬取豆瓣电影 Top 250")
    p_top.add_argument("--detail", action="store_true", help="同时爬取每部电影的详情页")
    p_top.add_argument("--format", choices=["json", "csv", "both"], default="json", help="导出格式")

    # detail
    p_detail = subparsers.add_parser("detail", help="爬取电影详情")
    p_detail.add_argument("movie_ids", nargs="+", help="电影ID（可以多个）")
    p_detail.add_argument("--format", choices=["json", "csv", "both"], default="json")

    # search
    p_search = subparsers.add_parser("search", help="搜索电影")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--pages", type=int, default=3, help="最大搜索页数")
    p_search.add_argument("--format", choices=["json", "csv", "both"], default="json")

    # 通用参数
    parser.add_argument("-o", "--output", default="output", help="输出目录")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    scraper = DoubanScraper(output_dir=args.output)
    movies = []

    if args.command == "top250":
        movies = scraper.scrape_top250()
        if args.detail and movies:
            log.info("🔄 开始爬取每部电影详情（这将耗时较久）...")
            ids = [m.id for m in movies if m.id]
            detail_movies = scraper.scrape_details_batch(ids)
            # 合并详情数据
            detail_map = {m.id: m for m in detail_movies}
            for i, m in enumerate(movies):
                if m.id in detail_map:
                    detail = detail_map[m.id]
                    detail.ranking = m.ranking  # 保留排名
                    movies[i] = detail

    elif args.command == "detail":
        movies = scraper.scrape_details_batch(args.movie_ids)

    elif args.command == "search":
        movies = scraper.search(args.keyword, max_pages=args.pages)

    # 导出
    if movies:
        if args.format in ("json", "both"):
            scraper.export_json(movies)
        if args.format in ("csv", "both"):
            scraper.export_csv(movies)

    print(f"\n🎬 完成！共获取 {len(movies)} 部电影数据")


if __name__ == "__main__":
    main()
