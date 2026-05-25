# 豆瓣电影爬虫与知识库问答

一个面向豆瓣电影数据采集、可视化浏览和本地知识库问答的轻量工具。项目支持 Top 250、搜索、详情批量抓取，导出 JSON / CSV，并提供基于 SQLite / JSON 数据的前端问答面板。

## 功能

- 爬取豆瓣电影 Top 250、搜索结果和电影详情
- 导出 `movies.json`、`movies.csv`
- 可将 CSV 导入为 `output/movies.sqlite` 作为本地知识库
- Web UI 浏览电影卡片、筛选、排序、查看详情和图表统计
- 右下角电影知识库问答，使用硅基流动 `Qwen/Qwen3-32B`
- 问答支持流式输出和 Markdown 渲染

## 安装

```bash
pip install -r requirements.txt
```

## 配置问答模型

问答接口通过环境变量读取硅基流动 API Key，不建议把密钥写入代码。

PowerShell:

```powershell
$env:SILICONFLOW_API_KEY="你的硅基流动 API Key"
```

模型默认使用：

```text
Qwen/Qwen3-32B
```

## 启动 Web UI

```bash
python app.py
```

默认地址：

```text
http://127.0.0.1:5000/
```

指定端口：

```bash
python app.py --port 8080
```

## Web API

```text
POST /api/top250        爬取 Top 250
POST /api/search        按关键词搜索
POST /api/detail        批量爬取详情
GET  /api/progress      SSE 实时进度
GET  /api/export/json   下载 JSON
GET  /api/export/csv    下载 CSV
GET  /api/chat/meta     问答知识库状态
POST /api/chat          流式电影知识库问答
```

## 命令行用法

爬取 Top 250：

```bash
python douban_movie.py top250 --format both
```

爬取 Top 250 并补全详情：

```bash
python douban_movie.py top250 --detail --format both
```

搜索电影：

```bash
python douban_movie.py search "诺兰" --pages 5
```

爬取单部或多部电影详情：

```bash
python douban_movie.py detail 1292052
python douban_movie.py detail 1292052 1291546 1295644
```

指定输出目录：

```bash
python douban_movie.py top250 -o ./my_data --format both
```

## SQLite 查询

如果已经生成 `output/movies.sqlite`，可以直接查询：

```powershell
sqlite3 output\movies.sqlite "SELECT COUNT(*) FROM movies;"
sqlite3 output\movies.sqlite "SELECT title, year, rating FROM movies ORDER BY CAST(rating AS REAL) DESC LIMIT 10;"
```

进入交互模式：

```powershell
sqlite3 output\movies.sqlite
```

```sql
.headers on
.mode column
SELECT id, title, year, rating FROM movies LIMIT 10;
```

## 输出字段

| 字段 | 说明 |
| --- | --- |
| `id` | 豆瓣电影 ID |
| `title` | 中文名 |
| `original_title` | 原名 |
| `year` | 年份 |
| `rating` | 评分 |
| `rating_count` | 评价人数 |
| `director` | 导演 |
| `screenwriter` | 编剧 |
| `actors` | 主演 |
| `genre` | 类型 |
| `region` | 制片国家/地区 |
| `language` | 语言 |
| `duration` | 片长 |
| `release_date` | 上映日期 |
| `aka` | 又名 |
| `imdb` | IMDb 编号 |
| `synopsis` | 剧情简介 |
| `poster_url` | 海报 URL |
| `ranking` | Top 250 排名 |
| `tags` | 用户标签 |
| `url` | 豆瓣页面链接 |

## 项目结构

```text
douban-scraper/
├── app.py              # Flask Web 服务、进度推送、问答接口
├── douban_movie.py     # 爬虫主程序
├── index.html          # 前端 UI
├── requirements.txt    # Python 依赖
├── README.md
└── output/             # 本地输出目录，默认不提交
    ├── movies.json
    ├── movies.csv
    └── movies.sqlite
```

## 注意

- 请控制请求频率，避免对目标站点造成压力。
- `output/` 目录已被 `.gitignore` 忽略，生成数据默认不提交。
- 本项目仅用于学习和研究，请遵守目标网站的使用条款。
