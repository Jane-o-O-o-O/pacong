# 🎬 豆瓣电影爬虫

一个功能完善的豆瓣电影信息爬虫，支持 Top 250 爬取、电影详情获取、搜索功能，导出 JSON / CSV。

## 安装依赖

```bash
pip install requests beautifulsoup4
```

## 使用方法

### 1. 爬取豆瓣电影 Top 250

```bash
python douban_movie.py top250
```

同时导出 JSON + CSV：
```bash
python douban_movie.py top250 --format both
```

爬取 Top 250 并逐部获取详情（耗时较久）：
```bash
python douban_movie.py top250 --detail --format both
```

### 2. 爬取单部电影详情

```bash
# 单部
python douban_movie.py detail 1292052

# 批量（多部电影）
python douban_movie.py detail 1292052 1291546 1295644
```

电影 ID 从豆瓣 URL 获取，例如：
`https://movie.douban.com/subject/1292052/` → ID 是 `1292052`

### 3. 搜索电影

```bash
python douban_movie.py search "诺兰"
python douban_movie.py search "周星驰" --pages 5
```

### 4. 指定输出目录

```bash
python douban_movie.py top250 -o ./my_data --format both
```

## 输出格式

### JSON 示例

```json
{
  "id": "1292052",
  "title": "肖申克的救赎",
  "original_title": "The Shawshank Redemption",
  "year": "1994",
  "rating": 9.7,
  "rating_count": 3285317,
  "director": "弗兰克·德拉邦特",
  "actors": "蒂姆·罗宾斯 / 摩根·弗里曼",
  "genre": "犯罪 剧情",
  "region": "美国",
  "duration": "142分钟",
  "synopsis": "希望让人自由。",
  "poster_url": "https://img3.doubanio.com/...",
  "ranking": 1
}
```

### CSV

支持 Excel 直接打开（UTF-8 BOM 编码），包含所有字段。

## 爬取的数据字段

| 字段 | 说明 |
|------|------|
| id | 豆瓣电影ID |
| title | 中文名 |
| original_title | 原名 |
| year | 年份 |
| rating | 评分（0-10） |
| rating_count | 评价人数 |
| director | 导演 |
| screenwriter | 编剧 |
| actors | 主演 |
| genre | 类型 |
| region | 制片国家/地区 |
| language | 语言 |
| duration | 片长 |
| release_date | 上映日期 |
| aka | 又名 |
| imdb | IMDb编号 |
| synopsis | 剧情简介 |
| poster_url | 海报图片URL |
| ranking | Top250排名 |
| tags | 用户标签 |
| url | 豆瓣页面链接 |

## 反爬策略

- User-Agent 随机轮换（5个真实浏览器UA）
- 请求间隔 2-5 秒随机延迟
- Session cookie 自动维护
- 403 限流自动等待 30s 重试（最多3次）
- 触发验证码自动等待 60s
- HTML 爬取失败自动回退 API 方式

## 注意事项

1. **请勿高频爬取**，豆瓣限制约 200 请求/小时/IP
2. 爬取 Top 250 约需 5-10 分钟（含延迟）
3. 建议在非高峰时段运行
4. 仅供学习研究使用，请遵守豆瓣使用条款

## 文件结构

```
douban-scraper/
├── douban_movie.py      # 爬虫主程序
├── requirements.txt     # Python依赖
├── README.md            # 本说明文件
└── output/              # 爬取结果
    ├── movies.json      # JSON格式
    └── movies.csv       # CSV格式
```
