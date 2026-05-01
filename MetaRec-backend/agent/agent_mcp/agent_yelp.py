import requests
import json
import logging
from datetime import datetime
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
# 从当前文件向上查找 MetaRec-backend 目录中的 .env 文件
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# ==========================================日志配置==========================================

# 创建日志目录（使用相对于当前文件的路径）
log_dir = Path(__file__).parent / "agent_log" / "yelp_organic_results"
os.makedirs(log_dir, exist_ok=True)

# 创建日志文件名（包含时间戳）
log_time = datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = os.path.join(log_dir, f"yelp_organic_results_{log_time}.log")

# 模块级 logger（不在导入时绑定处理器；由调用方或 __main__ 配置）
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ==========================================配置信息==========================================

# SerpAPI 配置
SERPAPI_URL = os.getenv("SERPAPI_URL", "https://serpapi.com/search.json")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
if not SERPAPI_KEY:
    logger.warning("SERPAPI_KEY environment variable is not set. Yelp tool will be disabled.")

# ==========================================函数定义==========================================

def search_yelp_organic_results(
        query, 
        location="Singapore",
        max_results=10,
        timeout=15,
    ):

    """
        Search Yelp via Serpapi
        see: https://serpapi.com/yelp-search-api
    """
    if not SERPAPI_KEY:
        logger.error("Serpapi Yelp Organic Results Search Error: SERPAPI_KEY is not configured")
        return None
    
    params = {
        "api_key": SERPAPI_KEY,
        "engine": "yelp",
        "find_desc": query,
        "find_loc": location,
        # 10 results per page, offset. 0,10,20,etc according to documentation
        #"start": 0,
    }
    
    try:
        response = requests.request("GET", SERPAPI_URL, params=params, timeout=timeout)
        
        text = response.text
        
        data = json.loads(text)

        results = []

        # use only organic results
        organic_results = data.get('organic_results', [])
        #ads_results = data.get('ads_results', [])
        
        for item in organic_results[:max_results]:
            extracted = {
                'position': item.get('position'), # yelp ranking within search results
                'place_ids': item.get('place_ids', []),
                'title': item.get('title'),
                'link': item.get('link'),
                'reviews_link': item.get('reviews_link'),
                'thumbnail': item.get('thumbnail'),
                'categories': item.get('categories', []),
                'price': item.get('price'), # price range $-$$$
                'rating': item.get('rating'), # average rating
                'reviews': item.get('reviews'), # number of reviews, not review content
                'highlights': item.get('highlights', []), # yelp highlighted keywords?
                'phone': item.get('phone'), # appears in some results, not all
                'neighborhoods': item.get('neighborhoods'), # appears in some results, not all
                'snippet': item.get('snippet'), # seems to be a featured review OR summary of reviews?
            }
            results.append(extracted)

        return results

    except requests.exceptions.Timeout:
        logger.error(f"Serpapi Yelp Organic Results Search Error: Request timed out ({timeout}s)")
        return None
    except Exception as e:
        logger.error(f"Serpapi Yelp Organic Results Search Error: {e}")
        return None


# ==========================================主程序==========================================

if __name__ == "__main__":
    # 仅在独立运行时，为本模块单独配置文件日志，且不向上冒泡
    if not logger.handlers:
        file_handler = logging.FileHandler(log_filename, encoding='utf-8')
        stream_handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
        logger.propagate = False

    logger.info("=" * 60)
    logger.info("程序开始运行")
    logger.info(f"日志目录: {log_dir}")
    logger.info(f"日志文件: {log_filename}")
    logger.info("=" * 60)
    
    # 测试搜索功能 - 新加坡东部的川菜馆
    logger.info("=" * 60)
    logger.info("测试 Yelp Organic Results 搜索")
    logger.info("=" * 60)
    
    # 新加坡东部的经纬度
    latitude = 1.3441568394739756
    longitude = 103.96390698619818
    
    query="sichuan food"
    location="Singapore"
    
    results = search_yelp_organic_results(
        query=query,
        location=location,
        max_results=10,
        timeout=12,
    )
    
    if results is None:
        logger.error("搜索失败，程序退出")
        exit(1)
    
    # 格式化输出搜索结果
    logger.info("===============Yelp 搜索结果===============")
    logger.info(json.dumps(results, ensure_ascii=False, indent=2))
    
    # 保存结果到JSON文件
    result_filename = os.path.join(log_dir, f"yelp_organic_results_result_{log_time}.json")
    try:
        with open(result_filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ 结果已保存到JSON文件: {result_filename}")
    except Exception as e:
        logger.error(f"❌ 保存JSON文件失败: {e}")
    
    logger.info("=" * 60)
    logger.info("程序执行完成")
    logger.info(f"日志目录: {log_dir}")
    logger.info(f"日志文件: {log_filename}")
    logger.info(f"结果文件: {result_filename}")
    logger.info(f"总共获取到 {len(results) if results else 0} 个地点")
    logger.info("=" * 60)
