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
log_dir = Path(__file__).parent / "agent_log" / "google_map"
os.makedirs(log_dir, exist_ok=True)

# 创建日志文件名（包含时间戳）
log_time = datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = os.path.join(log_dir, f"google_map_{log_time}.log")

# 模块级 logger（不在导入时绑定处理器；由调用方或 __main__ 配置）
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ==========================================配置信息==========================================

# SerpAPI 配置
SERPAPI_URL = os.getenv("SERPAPI_URL", "https://serpapi.com/search.json")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
if not SERPAPI_KEY:
    raise ValueError("SERPAPI_KEY environment variable is not set. Please set it in your .env file.")

# ==========================================函数定义==========================================

def search_google_maps(query, latitude=None, longitude=None, zoom=None, map_height=10000, search_type="search", max_results=20):
    """
    使用 Google Maps 搜索地点
    
    参数:
        query: 搜索关键词，例如 "sichuan food"
        latitude: 纬度，默认None
        longitude: 经度，默认None
        zoom: 地图缩放级别，默认None，最小为3z，最大为21z（当map_height为None时使用）
        map_height: 搜索范围半径（单位：米），默认10000
        search_type: 搜索类型，默认"search"
        max_results: 最大返回结果数，默认20
    
    返回:
        成功返回地点列表，失败返回None
    """
    params = {
        "engine": "google_maps",
        "q": query,
        "type": search_type,
        "api_key": SERPAPI_KEY
    }
    
    # 如果提供了经纬度，添加 ll 参数
    if latitude is not None and longitude is not None:
        # 优先使用map_height参数，如果map_height为None则使用zoom
        if map_height is not None:
            params["ll"] = f"@{latitude},{longitude},{map_height}m"
        elif zoom is not None:
            params["ll"] = f"@{latitude},{longitude},{zoom}z"
        else:
            # 如果两个参数都为None，使用默认的map_height
            params["ll"] = f"@{latitude},{longitude},{map_height}m"
    
    try:
        logger.info(f"开始搜索 Google Maps: 关键词='{query}'")
        if latitude and longitude:
            if map_height is not None:
                logger.info(f"  位置: ({latitude}, {longitude}), 搜索半径: {map_height}米")
            elif zoom is not None:
                logger.info(f"  位置: ({latitude}, {longitude}), 缩放级别: {zoom}")
            else:
                logger.info(f"  位置: ({latitude}, {longitude}), 搜索半径: {map_height}米")
        
        response = requests.request("GET", SERPAPI_URL, params=params, timeout=15)
        data = json.loads(response.text)
        
        # 检查是否有错误
        if "error" in data:
            logger.error(f"❌ Google Maps 搜索失败: {data.get('error')}")
            return None
        
        logger.info(f"✅ Google Maps 搜索成功")
        
        # 提取搜索结果
        local_results = data.get('local_results', [])
        
        if not local_results:
            logger.warning(f"⚠️  未找到任何结果")
            return []
        
        # 提取关键信息，限制结果数量
        results = []
        for item in local_results[:max_results]:
            extracted = {
                'title': item.get('title'),
                'rating': item.get('rating'),
                'reviews': item.get('reviews'),
                'reviews_link': item.get('reviews_link'),
                'photos_link': item.get('photos_link'),
                'price': item.get('price'),
                'type': item.get('type'),
                'address': item.get('address'),
                'phone': item.get('phone'),
                'hours': item.get('hours'),
                'service_options': item.get('service_options'),
                'gps_coordinates': item.get('gps_coordinates', {}),
                "user_reviews": item.get('user_reviews'),
                "operating_hours": item.get('operating_hours'),
                "open_state": item.get('open_state'),
                "extensions": item.get('extensions')
            }
            results.append(extracted)
        
        logger.info(f"✅ 提取到 {len(results)} 个地点信息")
        return results
        
    except requests.exceptions.Timeout:
        logger.error(f"❌ Google Maps 搜索超时(>15秒)")
        return None
    except Exception as e:
        logger.error(f"❌ Google Maps 搜索异常: {e}")
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
    logger.info("\n" + "=" * 60)
    logger.info("测试 Google Maps 搜索")
    logger.info("=" * 60)
    
    # 新加坡东部的经纬度
    latitude = 1.3441568394739756
    longitude = 103.96390698619818
    
    results = search_google_maps(
        query="sichuan food",
        latitude=latitude,
        longitude=longitude,
        # zoom=14,
        map_height=2000,
        max_results=10
    )
    
    if results is None:
        logger.error("搜索失败，程序退出")
        exit(1)
    
    # 格式化输出搜索结果
    logger.info("\n===============Google Maps 搜索结果===============")
    logger.info(json.dumps(results, ensure_ascii=False, indent=2))
    
    # 保存结果到JSON文件
    result_filename = os.path.join(log_dir, f"google_map_result_{log_time}.json")
    try:
        with open(result_filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"\n✅ 结果已保存到JSON文件: {result_filename}")
    except Exception as e:
        logger.error(f"\n❌ 保存JSON文件失败: {e}")
    
    logger.info("\n" + "=" * 60)
    logger.info("程序执行完成")
    logger.info(f"日志目录: {log_dir}")
    logger.info(f"日志文件: {log_filename}")
    logger.info(f"结果文件: {result_filename}")
    logger.info(f"总共获取到 {len(results) if results else 0} 个地点")
    logger.info("=" * 60)

