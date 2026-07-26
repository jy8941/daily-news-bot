import os, sys, json, logging, requests
from datetime import datetime, timedelta
from urllib.parse import quote

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_URL = os.getenv("AI_API_URL", "https://api.openai.com/v1/chat/completions")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")
NEWS_COUNT = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch_weibo_hot():
    try:
        url = "https://weibo.com/ajax/side/hotSearch"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        data = resp.json()
        news_list = []
        if "data" in data and "realtime" in data["data"]:
            for item in data["data"]["realtime"][:NEWS_COUNT + 3]:
                title = item.get("word", "").strip()
                if title and len(title) > 3:
                    news_list.append({"title": title, "url": f"https://s.weibo.com/weibo?q={quote(title)}", "hot": item.get("raw_hot", 0)})
        seen, filtered = set(), []
        for n in news_list:
            if n["title"] not in seen and len(filtered) < NEWS_COUNT:
                seen.add(n["title"]); filtered.append(n)
        logger.info(f"[微博] 获取 {len(filtered)} 条")
        return filtered
    except Exception as e:
        logger.error(f"[微博] 失败: {e}")
        return []

def fetch_baidu_hot():
    try:
        url = "https://top.baidu.com/api/board?tab=realtime"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        data = resp.json()
        news_list = []
        if "data" in data and "cards" in data["data"]:
            for card in data["data"]["cards"]:
                for item in card.get("content", [])[:NEWS_COUNT]:
                    title = item.get("word", "").strip()
                    if title:
                        news_list.append({"title": title, "url": item.get("url", ""), "hot": item.get("hotScore", 0)})
        return news_list[:NEWS_COUNT]
    except Exception as e:
        logger.error(f"[百度] 失败: {e}")
        return []

def fetch_news():
    news = fetch_weibo_hot()
    if not news:
        logger.info("微博失败，切换百度")
        news = fetch_baidu_hot()
    return news

SYSTEM_PROMPT = """你是一位精通中文互联网文化的脱口秀编剧，擅长用幽默、反讽、接地气的语言评论热点新闻。
要求：
1. 针对每条新闻，找出主流/官方/大众的常规观点
2. 用完全相反或故意抬杠的角度评论
3. 语言幽默犀利、贴近大众，像朋友间吐槽
4. 每条评论 80-150 字
5. 适当使用网络流行语、emoji、反问句
6. 不人身攻击，不涉及政治敏感
输出 JSON：
{"comments": [{"title": "标题", "ironic_comment": "评论"}]}"""

def generate_comments(news_list):
    if not news_list:
        return []
    if not AI_API_KEY:
        return [{"title": n["title"], "ironic_comment": "（未配置AI密钥）"} for n in news_list]
    
    news_text = "\n".join([f"{i+1}. {n['title']}" for i, n in enumerate(news_list)])
    user_prompt = f"今天是 {datetime.now().strftime('%Y年%m月%d日')}。\n\n以下是热度最高的 {len(news_list)} 条新闻，请生成反讽评论：\n\n{news_text}\n\n直接返回 JSON，不要其他解释。"
    
    try:
        payload = {"model": AI_MODEL, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}], "temperature": 0.85, "max_tokens": 2000}
        headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
        logger.info(f"[AI] 生成中... 模型: {AI_MODEL}")
        resp = requests.post(AI_API_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        try:
            data = json.loads(content)
        except:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            data = json.loads(content.strip())
        comments = data.get("comments", [])
        logger.info(f"[AI] 生成 {len(comments)} 条评论")
        return comments
    except Exception as e:
        logger.error(f"[AI] 失败: {e}")
        return [{"title": n["title"], "ironic_comment": "（AI生成失败）"} for n in news_list]

def push(news_list, comments):
    if not PUSHPLUS_TOKEN:
        logger.error("[PushPlus] 未配置 Token")
        return False
    
    date_str = (datetime.now() - timedelta(days=1)).strftime("%m月%d日")
    lines = [f"📰 {date_str} 反讽早报", ""]
    emojis = ["🔥", "⚡", "💥", "🎯", "🤡"]
    
    for i, (news, comment) in enumerate(zip(news_list, comments)):
        emoji = emojis[i % len(emojis)]
        lines.append(f"{emoji} {comment.get('title', news['title'])}")
        lines.append(f"💬 {comment.get('ironic_comment', '暂无评论')}")
        lines.append("")
    
    lines.append("—"); lines.append("🤖 AI自动生成")
    content = "\n".join(lines)
    
    try:
        resp = requests.post("http://www.pushplus.plus/send", json={"token": PUSHPLUS_TOKEN, "title": f"{date_str} 反讽早报", "content": content, "template": "txt"}, timeout=15)
        result = resp.json()
        if result.get("code") == 200:
            logger.info("[PushPlus] 推送成功")
            return True
        else:
            logger.error(f"[PushPlus] 失败: {result}")
            return False
    except Exception as e:
        logger.error(f"[PushPlus] 异常: {e}")
        return False

def main():
    logger.info("=" * 40); logger.info("🚀 每日反讽新闻任务开始"); logger.info("=" * 40)
    news = fetch_news()
    if not news:
        logger.error("❌ 新闻获取失败"); sys.exit(1)
    comments = generate_comments(news)
    success = push(news, comments)
    if success:
        logger.info("✅ 任务完成")
    else:
        logger.error("❌ 推送失败"); sys.exit(1)

if __name__ == "__main__":
    main()
