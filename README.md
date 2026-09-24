```markdown
# Yixn 全能蜘蛛爬虫 v3.1 使用说明

> 并发爬取 · 断点续爬 · 多格式导出 · 速度提升 10 倍

---

## 📖 目录

- [简介](#-简介)
- [下载地址](#-下载地址)
- [环境要求](#-环境要求)
- [快速开始](#-快速开始)
- [命令行参数](#-命令行参数)
- [输出结构](#-输出结构)
- [核心功能详解](#-核心功能详解)
- [常见问题](#-常见问题)
- [免责声明](#-免责声明)

---

## 🕷️ 简介

**Yixn 全能蜘蛛爬虫 v3.1** 是一个基于 Python 标准库 + requests 的**全能网站爬虫工具**。

在 v2.0 基础上，v3.1 加入了 **并发爬取、断点续爬、多格式导出、图片按文章归档、自研正文提取** 等核心能力，速度提升 **5~10 倍**。

### 核心特性

| 特性 | 说明 |
|------|------|
| ⚡ **并发爬取** | 多线程并发请求，速度提升 5~10 倍 |
| 💾 **断点续爬** | 中断后从上次位置继续，不重复抓取 |
| 🔁 **自动翻页** | 自动识别「下一页」链接 |
| 📦 **多格式导出** | TXT / JSON / Markdown / CSV |
| 🖼️ **图片归档** | 每篇文章一个子目录 |
| 🎯 **正文提取** | 自研文本密度算法，自动去导航/广告 |
| 🔄 **失败重试** | 指数退避，最多重试 3 次 |
| 📊 **实时进度条** | 终端显示速度 / ETA |
| 🍪 **Cookie 支持** | 导入 JSON 登录态 |
| 🔥 **增量更新** | 只抓新增 / 变更页面 |

---

## 📦 下载地址

**主下载链接：**

```

https://pan.131206.xyz/pan/python/yixn-crawler/v3.1/main.py

```

**文件说明：**

| 项 | 内容 |
|----|------|
| 文件名 | `main.py` |
| 大小 | 约 40KB |
| 类型 | 单文件 Python 脚本 |
| 版本 | v3.1 |
| 校验 | 下载后建议对比文件大小 |

**备用下载渠道：**

- 官方博客：https://blog.3v4.top/
- 资源站：https://pan.131206.xyz/
- 发布页：https://pan.131206.xyz/

---

## 💻 环境要求

| 项 | 要求 |
|----|------|
| Python | 3.7 及以上 |
| 操作系统 | Windows / macOS / Linux / Android (Termux / Pydroid 3) |
| 依赖 | requests / beautifulsoup4 / lxml（脚本自动安装） |
| 网络 | 可访问外网 |

---

## 🚀 快速开始

### 1. 下载脚本

从上面的下载链接获取 `main.py`。

### 2. 运行脚本

```bash
python main.py
```

首次运行会自动安装依赖（requests / bs4 / lxml）。

3. 交互模式

无参数运行会进入交互模式：

```
============================================================
  🕷️  Yixn 全能蜘蛛爬虫 v3.1 (交互模式)
============================================================
请输入要爬取的URL: https://example.com
最大爬取深度 [默认3]:
最大爬取页数 [默认100]:
允许跨域名? (y/n) [默认n]:
下载图片? (y/n) [默认y]:
并发线程数 [默认8]:
导出格式 [默认txt,json]:
输出目录 [默认yixn-output]:
启用断点续爬? (y/n) [默认n]:
```

4. 命令行模式（推荐）

一条命令完成爬取：

```bash
python main.py -u https://example.com -d 3 -p 200
```

5. 等待完成

终端显示实时进度条：

```
📄 爬取进度 |████████░░░░░░░░| 60/200 [30.0%] 3.2页/s ETA 00:00:44
```

6. 查看结果

爬取完成后，在 yixn-output/ 目录中查看所有数据。

---

⚙️ 命令行参数

基础参数

参数 说明 默认
-u, --url 起始 URL 必填
-d, --depth 最大爬取深度 3
-p, --pages 最大页面数 100
-o, --output 输出目录 yixn-output

功能参数

参数 说明 默认
--cross-domain 允许跨域名 关闭
--no-images 不下载图片 下载
--no-pagination 不自动翻页 自动翻页
--concurrency N 并发线程数 8
--img-concurrency N 图片下载线程数 5
--format 导出格式 txt,json
--cookie FILE Cookie JSON 文件 无
--resume 断点续爬 关闭
--incremental 增量更新 关闭

其他参数

参数 说明
--config FILE 配置文件路径
--site NAME 配置中的站点名
-v, --verbose 详细日志
--debug 调试模式（打印完整堆栈）
--interactive 交互式输入
-h, --help 显示帮助

使用示例

```bash
# 最简用法
python main.py -u https://example.com

# 抓 200 页，深度 5，并发 10
python main.py -u https://example.com -d 5 -p 200 --concurrency 10

# 导出所有格式
python main.py -u https://example.com --format txt,json,md,csv

# 断点续爬
python main.py -u https://example.com --resume

# 增量更新
python main.py -u https://example.com --incremental

# 使用配置文件
python main.py --config config.json --site my-blog

# 允许跨域名 + 不下载图片
python main.py -u https://example.com --cross-domain --no-images
```

---

📁 输出结构

爬取完成后，yixn-output/ 目录结构如下：

```
yixn-output/
├── pages/                  页面元数据（每页一个 JSON）
│   └── <hash>.json
├── contents/               正文文本（每页一个 TXT）
│   └── <hash>.txt
├── links/                  每页提取的链接
│   └── <hash>.txt
├── images/                 每页提取的图片链接
│   └── <hash>.txt
├── data/                   导出文件
│   ├── result.json         JSON 汇总
│   ├── result.md           Markdown 汇总
│   ├── result.txt          TXT 汇总
│   └── pages.csv           CSV 表格
├── downloaded_images/      下载的图片
│   └── <hash>-<标题>/      按文章归档
│       ├── <hash>.jpg
│       └── <hash>.png
├── logs/                   运行日志
│   └── yixn.log            滚动日志（最大 5MB）
├── crawl_report.json       完整爬取报告
├── summary.txt             摘要
├── .yixn_state.json        断点续爬状态
└── .yixn_cache.json        增量更新缓存
```

---

🧠 核心功能详解

1. 并发爬取

· 使用 ThreadPoolExecutor 实现多线程
· 默认 8 个线程（可通过 --concurrency 调整）
· 图片下载使用独立线程池
· 使用 RLock 保证线程安全

建议：

网站类型 推荐并发数
个人博客 3~5
中型网站 8~10
高性能服务器 10~15
反爬严格 1~3

2. 断点续爬

进度保存到 .yixn_state.json：

```json
{
  "start_url": "https://example.com",
  "visited_urls": ["https://example.com/page1", "..."],
  "queued_urls": ["https://example.com/page2", "..."],
  "stats": {...},
  "saved_at": "2026-09-24T10:30:00"
}
```

使用：

```bash
python main.py -u https://example.com --resume
```

中断后重新运行同样命令即可继续。

3. 自动翻页

· 识别 <a rel="next">
· 匹配关键词：next / 下一页 / older / › / »
· 自动加入队列

4. 多格式导出

格式 说明
TXT 纯文本列表
JSON 结构化数据
Markdown 保留标题层级
CSV Excel 可打开

指定格式：

```bash
python main.py -u URL --format txt,json,md,csv
```

5. 图片归档

每篇文章对应一个子目录：

```
downloaded_images/
├── 1a2b3c4d-如何写好一篇博客/
│   ├── e5f6g7h8.jpg
│   └── i9j0k1l2.png
└── m3n4o5p6-爬虫入门指南/
    └── q7r8s9t0.webp
```

6. 正文提取

自研算法基于文本密度：

1. 移除 <script> / <style> / <nav> / <footer> / <aside> 等
2. 移除 id/class 含导航/广告关键词的标签
3. 候选容器：<article> / role=main / id/class 含 article/content/post
4. 计算每个候选容器的文本密度
5. 选出最优容器并提取纯文本

7. 失败重试

· 最多重试 3 次
· 指数退避：1s → 2s → 4s
· 区分可重试错误（超时/5xx）与不可重试错误（404）

8. Cookie 支持

准备 cookies.json：

```json
{
  "session_id": "abc123",
  "user_token": "xyz789"
}
```

使用：

```bash
python main.py -u URL --cookie cookies.json
```

9. 增量更新

· 记录每页内容的 MD5 哈希
· 下次运行时对比，跳过未变更页面
· 适合定期备份网站

```bash
python main.py -u URL --incremental
```

---

❓ 常见问题

Q1：提示"未提取到任何数据"怎么办？

1. 确认页面是静态渲染（右键查看源码能看到文章标题）
2. 有些博客首页只显示摘要，请换成文章列表页或归档页
3. 若页面完全是 JS 渲染，v3.1 无法识别

Q2：会自动安装依赖吗？

会。首次运行会自动 pip 安装：

· requests
· beautifulsoup4
· lxml

如果失败，手动执行：

```bash
pip install requests beautifulsoup4 lxml
```

Q3：并发数设置多少合适？

· 默认 8 线程，适用大多数站点
· 小型站点建议 3~5
· 高性能服务器可调到 10~15
· 过高容易被封 IP

Q4：断点续爬怎么用？

加 --resume 参数即可：

```bash
python main.py -u URL --resume
```

进度保存在 yixn-output/.yixn_state.json。

Q5：支持需要登录的网站吗？

支持。用 --cookie cookies.json 传入 Cookie 文件。

Q6：可以爬 JS 渲染的网站吗？

不能。v3.1 基于 requests 抓静态 HTML。React / Vue 等 SPA 应用需要 headless 浏览器（后续版本支持）。

Q7：支持 Windows / 手机吗？

支持。Windows / macOS / Linux / Termux / Pydroid 3 均可运行。

Q8：爬取速度太快会被封吗？

会。建议：

· 减小并发数（--concurrency 3）
· 减小最大页数（-p 50）
· 增大重试延迟（修改源码）

Q9：图片会占很多空间吗？

会。默认按格式分类下载到 downloaded_images/。图片多时可以：

```bash
python main.py -u URL --no-images
```

Q10：导出的文件是乱码怎么办？

所有文件均为 UTF-8 编码。请用支持 UTF-8 的编辑器：

· VSCode
· Notepad++
· Sublime Text
· 手机端 MT 管理器

---

📊 技术栈

项 说明
语言 Python 3.7+
网络 requests
解析 BeautifulSoup + lxml
并发 concurrent.futures
日志 logging + RotatingFileHandler
输出 TXT / JSON / Markdown / CSV

---

📄 开源协议

MIT License

---

⚠️ 免责声明

本项目仅供 学习研究 与 个人网站备份 使用。

使用时请遵守：

· ✅ 目标网站的 robots.txt 协议
· ✅ 相关法律法规
· ❌ 不得用于商业用途
· ❌ 不得抓取隐私数据
· ❌ 不得对目标服务器造成压力

使用本工具产生的一切后果由使用者自行承担。

---

🌟 支持项目

如果这个工具帮到了你：

· ⭐ 给项目点个 Star
· 🐛 提交 Issue 反馈问题
· 🔀 提交 PR 贡献代码
· 📢 分享给更多需要的人

---

📮 联系

· 项目主页：https://pan.131206.xyz/
· 官方博客：https://blog.3v4.top/
· 下载地址：https://pan.131206.xyz/pan/python/yixn-crawler/v3.1/main.py

---

📄 版本信息

项 内容
当前版本 v3.1
发布日期 2026-09-24
上一版本 v2.0
更新内容 并发 / 断点续爬 / 多格式导出 / 图片归档

---

<div align="center">

🕷️ Yixn 全能蜘蛛爬虫 v3.1

让网站备份变得简单

Made with ❤️ by Yixn

</div>
```