#!/usr/bin/env python3
"""
豆瓣电影爬虫 Web 服务器
提供 API 接口和实时进度推送（SSE）

Usage:
    python app.py                # 启动服务器 (默认 localhost:5000)
    python app.py --port 8080    # 指定端口
"""

import json
import queue
import logging
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from douban_movie import DoubanScraper

# ─── Flask App ──────────────────────────────────────────

app = Flask(__name__, static_folder=".", static_url_path="")

# ─── 全局状态 ──────────────────────────────────────────

scrape_state = {
    "status": "idle",       # idle / running / done / error
    "task": "",             # top250 / search / detail
    "message": "",
    "result_count": 0,
}

log_queues: list[queue.Queue] = []
state_lock = threading.Lock()


# ─── SSE 日志 Handler ──────────────────────────────────

class SSELogHandler(logging.Handler):
    """将日志消息推送到所有连接的 SSE 客户端"""

    def emit(self, record):
        msg = self.format(record)
        with state_lock:
            dead = []
            for i, q in enumerate(log_queues):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(i)
            for i in reversed(dead):
                log_queues.pop(i)


def setup_sse_logging():
    """配置日志系统，添加 SSE handler"""
    handler = SSELogHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))

    # 给 douban 模块的 logger 添加 SSE handler
    douban_logger = logging.getLogger("douban")
    douban_logger.addHandler(handler)
    douban_logger.setLevel(logging.INFO)

    # flask 的 werkzeug 日志级别调高，减少噪音
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


setup_sse_logging()
log = logging.getLogger("douban")


# ─── 辅助函数 ──────────────────────────────────────────

def update_state(**kwargs):
    with state_lock:
        scrape_state.update(kwargs)


def run_scraping_task(task_func, task_name):
    """在后台线程中运行爬虫任务"""
    with state_lock:
        if scrape_state["status"] == "running":
            return False

    update_state(status="running", task=task_name, message="开始爬取...", result_count=0)

    def _run():
        try:
            scraper, movies = task_func()
            count = len(movies) if movies else 0

            if movies:
                scraper.export_json(movies)
                scraper.export_csv(movies)

            update_state(
                status="done",
                message=f"完成！共获取 {count} 部电影",
                result_count=count,
            )
            log.info(f"✅ 任务完成，共 {count} 部电影")
        except Exception as e:
            update_state(status="error", message=f"错误: {e}")
            log.error(f"❌ 任务失败: {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return True


# ─── 路由：静态文件 ─────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/output/<path:filename>")
def serve_output(filename):
    return send_from_directory("output", filename)


# ─── 路由：API ──────────────────────────────────────────

@app.route("/api/status")
def api_status():
    with state_lock:
        return jsonify(scrape_state)


@app.route("/api/top250", methods=["POST"])
def api_top250():
    detail = request.json.get("detail", False) if request.is_json else False

    def task():
        scraper = DoubanScraper(output_dir="output")
        movies = scraper.scrape_top250()
        if detail and movies:
            log.info("🔄 开始爬取每部电影详情...")
            ids = [m.id for m in movies if m.id]
            detail_movies = scraper.scrape_details_batch(ids)
            detail_map = {m.id: m for m in detail_movies}
            for i, m in enumerate(movies):
                if m.id in detail_map:
                    d = detail_map[m.id]
                    d.ranking = m.ranking
                    movies[i] = d
        return scraper, movies

    if run_scraping_task(task, "top250"):
        return jsonify({"success": True, "message": "Top 250 爬取任务已启动"})
    return jsonify({"success": False, "message": "已有任务在运行中"}), 409


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json(force=True)
    keyword = data.get("keyword", "").strip()
    pages = data.get("pages", 3)

    if not keyword:
        return jsonify({"success": False, "message": "请输入搜索关键词"}), 400

    def task():
        scraper = DoubanScraper(output_dir="output")
        movies = scraper.search(keyword, max_pages=pages)
        return scraper, movies

    if run_scraping_task(task, "search"):
        return jsonify({"success": True, "message": f"搜索 \"{keyword}\" 已启动"})
    return jsonify({"success": False, "message": "已有任务在运行中"}), 409


@app.route("/api/detail", methods=["POST"])
def api_detail():
    data = request.get_json(force=True)
    movie_ids = data.get("movie_ids", [])

    if not movie_ids:
        # 如果没指定 ID，使用当前 movies.json 中的所有 ID
        json_path = Path("output/movies.json")
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                existing = json.load(f)
            movie_ids = [m["id"] for m in existing if m.get("id")]

    if not movie_ids:
        return jsonify({"success": False, "message": "没有可爬取的电影 ID"}), 400

    def task():
        scraper = DoubanScraper(output_dir="output")
        movies = scraper.scrape_details_batch(movie_ids)
        return scraper, movies

    if run_scraping_task(task, "detail"):
        return jsonify({"success": True, "message": f"批量详情爬取已启动（{len(movie_ids)} 部）"})
    return jsonify({"success": False, "message": "已有任务在运行中"}), 409


@app.route("/api/progress")
def api_progress():
    """SSE 端点 — 实时推送日志"""

    def stream():
        q = queue.Queue(maxsize=500)
        with state_lock:
            log_queues.append(q)

        try:
            # 发送初始状态
            with state_lock:
                yield f"data: {json.dumps({'type': 'status', **scrape_state}, ensure_ascii=False)}\n\n"

            while True:
                try:
                    msg = q.get(timeout=30)
                    yield f"data: {json.dumps({'type': 'log', 'message': msg}, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    # 心跳，保持连接
                    with state_lock:
                        yield f"data: {json.dumps({'type': 'heartbeat', **scrape_state}, ensure_ascii=False)}\n\n"
        except GeneratorExit:
            pass
        finally:
            with state_lock:
                if q in log_queues:
                    log_queues.remove(q)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/export/<fmt>")
def api_export(fmt):
    if fmt not in ("json", "csv"):
        return jsonify({"success": False, "message": "不支持的格式"}), 400

    filename = f"movies.{fmt}"
    filepath = Path("output") / filename
    if not filepath.exists():
        return jsonify({"success": False, "message": f"文件不存在: {filename}"}), 404

    return send_from_directory("output", filename, as_attachment=True)


# ─── 入口 ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="豆瓣电影爬虫 Web 服务器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=5000, help="监听端口")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    print(f"\n🎬 豆瓣电影爬虫 Web 服务器")
    print(f"   地址: http://{args.host}:{args.port}")
    print(f"   按 Ctrl+C 停止\n")

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
