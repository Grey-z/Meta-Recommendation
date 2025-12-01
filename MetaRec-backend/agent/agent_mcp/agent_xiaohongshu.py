import requests
import json
import logging
from datetime import datetime
import os

# ==========================================日志配置==========================================

# 创建日志目录
log_dir = "/root/multiagent_model/agent_mcp/agent_log/xiaohongshu"
os.makedirs(log_dir, exist_ok=True)

# 创建日志文件名（包含时间戳）
log_time = datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = os.path.join(log_dir, f"xiaohongshu_{log_time}.log")

# 模块级 logger（不在导入时绑定处理器；由调用方或 __main__ 配置）
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ==========================================配置信息==========================================
HEADERS_TIKHUB = {
    "Authorization": "Bearer 16U7W9ky8E27kiuTM6WK3xuKFTuWfMJk+QDhqmi8dMLjtViCK2KBaBKiAQ=="
}
SEARCH_NOTES_URL = "https://api.tikhub.io/api/v1/xiaohongshu/app/search_notes"
SEARCH_NOTES_URL_302 = "https://api.302.ai/tools/xiaohongshu/app/search_notes"
GET_NOTE_CONTENT_URL = "https://api.tikhub.io/api/v1/xiaohongshu/app/get_note_info"
GET_NOTE_COMMENTS_URL = "https://api.tikhub.io/api/v1/xiaohongshu/app/get_note_comments"

HEADERS_302 = {
    "Authorization": "Bearer sk-nKJaec3zbywjpg1AaI8pnKU95Eq0jj5DjGYEdpqXDQwcToT5"
}


# ==========================================函数定义==========================================

def search_notes_by_keyword(keyword, sort="general", page=1, noteType="不限", noteTime="不限", max_results=10):
    """
    根据关键词搜索小红书笔记
    
    参数:
        keyword: 搜索关键词
        sort: 排序类型，默认"general"   302:sort_type
        page: 页码，默认1
        noteType: 笔记类型过滤，默认"不限"   302:filter_note_type
        noteTime: 时间过滤，默认"不限"   302:filter_note_time
        max_results: 最大返回结果数，默认10
    
    返回:
        成功返回笔记列表，失败返回None
    """
    search_notes_params = {
        "keyword": keyword,
        "sort": sort,
        "page": page,
        "noteType": noteType,
        "noteTime": noteTime
    }
    
    try:
        response = requests.request("GET", SEARCH_NOTES_URL, headers=HEADERS_TIKHUB, params=search_notes_params, timeout=10)
        data = json.loads(response.text)
        
        # 检查状态码
        if data.get('code') != 200:
            logger.error(f"❌ 搜索笔记失败 (code={data.get('code')}): {data.get('message', 'Unknown error')}")
            return None
        
        logger.info(f"✅ 搜索笔记成功 (code=200)")
        
        # 提取items列表
        items = data.get('data', {}).get('data', {}).get('items', [])
        
        # 筛选model_type为"note"的项，取前max_results项
        note_items = [item for item in items if item.get('model_type') == 'note'][:max_results]
        
        # 提取指定字段
        result = []
        for item in note_items:
            note_data = item.get('note', {})
            
            # 提取发布时间
            publish_time = None
            corner_tag_info = note_data.get('corner_tag_info', [])
            for tag in corner_tag_info:
                if tag.get('type') == 'publish_time':
                    publish_time = tag.get('text')
                    break
            
            extracted = {
                'id': note_data.get('id'),
                'title': note_data.get('title'),
                'desc': note_data.get('desc'),
                'collected_count': note_data.get('collected_count'),
                'comments_count': note_data.get('comments_count'),
                'liked_count': note_data.get('liked_count'),
                'shared_count': note_data.get('shared_count'),
                'publish_time': publish_time
            }
            result.append(extracted)
        
        logger.info(f"✅ 提取到 {len(result)} 条笔记信息")
        return result
        
    except requests.exceptions.Timeout:
        logger.error(f"❌ 搜索笔记超时(>10秒)")
        return None
    except Exception as e:
        logger.error(f"❌ 搜索笔记异常: {e}")
        return None

# ==========================================获取笔记详细信息==========================================

def get_note_detail(note_id):
    """
    根据笔记ID获取笔记详细信息
    
    参数:
        note_id: 笔记ID
    
    返回:
        成功返回笔记详情字典(包含desc和images_list)，失败返回None
    """
    get_note_content_params = {
        "note_id": note_id
    }
    
    try:
        response = requests.request("GET", GET_NOTE_CONTENT_URL, headers=HEADERS_TIKHUB, params=get_note_content_params, timeout=10)
        note_detail = json.loads(response.text)
        
        # 检查状态码
        if note_detail.get('code') != 200:
            logger.error(f"❌ 获取笔记 {note_id} 详情失败 (code={note_detail.get('code')}): {note_detail.get('message', 'Unknown error')}")
            return None
        
        # 从返回结果中提取desc和images_list
        data_list = note_detail.get('data', {}).get('data', [])
        note_list = data_list[0].get('note_list', []) if data_list else []
        note_data = note_list[0] if note_list else None
        result = {}
        if 'desc' in note_data:
            result['desc'] = note_data.get('desc')
        if 'images_list' in note_data:
            result['images_list'] = note_data.get('images_list')
        
        return result
        
    except requests.exceptions.Timeout:
        logger.error(f"❌ 获取笔记 {note_id} 详情超时(>10秒)")
        return None
    except Exception as e:
        logger.error(f"❌ 获取笔记 {note_id} 详情异常: {e}")
        return None

# ==========================================获取笔记评论==========================================

def get_note_comments(note_id):
    """
    根据笔记ID获取笔记评论
    
    参数:
        note_id: 笔记ID
    
    返回:
        成功返回评论列表，失败返回None
    """
    
    def extract_comment_fields(comment):
        """
        递归提取单个评论的指定字段
        
        参数:
            comment: 评论对象
        
        返回:
            提取的评论字典，如果comment为None则返回None
        """
        # 处理None和空列表的情况
        if comment is None or comment == []:
            return None
        
        # 确保comment是字典类型
        if not isinstance(comment, dict):
            logger.warning(f"  ⚠️  评论对象类型错误: {type(comment)}, 跳过该评论")
            return None
        
        extracted = {
            'time': comment.get('time'),
            'content': comment.get('content'),
            'like_count': comment.get('like_count'),
            'collected': comment.get('collected'),
            'score': comment.get('score')
        }
        
        # 递归处理sub_comments
        sub_comments = comment.get('sub_comments')
        if sub_comments:
            # sub_comments可能直接是列表，或者包含comments_list
            if isinstance(sub_comments, dict):
                # 如果是字典，尝试获取comments_list
                sub_comments_list = sub_comments.get('comments_list', [])
            elif isinstance(sub_comments, list):
                # 如果直接是列表
                sub_comments_list = sub_comments
            else:
                sub_comments_list = []
            
            # 递归处理每个子评论，过滤掉None值
            if sub_comments_list:
                processed_sub_comments = []
                for sub_comment in sub_comments_list:
                    result = extract_comment_fields(sub_comment)
                    if result is not None:  # 只添加非None的结果
                        processed_sub_comments.append(result)
                extracted['sub_comments'] = processed_sub_comments
            else:
                extracted['sub_comments'] = []
        else:
            extracted['sub_comments'] = []
        
        return extracted
    
    get_note_comments_params = {
        "note_id": note_id
    }
    
    try:
        response = requests.request("GET", GET_NOTE_COMMENTS_URL, headers=HEADERS_TIKHUB, params=get_note_comments_params, timeout=10)
        comments_data = json.loads(response.text)
        
        # 检查状态码
        if comments_data.get('code') != 200:
            logger.error(f"❌ 获取笔记 {note_id} 评论失败 (code={comments_data.get('code')}): {comments_data.get('message', 'Unknown error')}")
            return None
        
        logger.info(f"✅ 获取笔记 {note_id} 评论成功 (code=200)")
        
        # 提取评论列表：data.data.comments
        comments_list = comments_data.get('data', {}).get('data', {}).get('comments', [])
        
        # 递归提取所有评论及其子评论，过滤掉None值
        result = []
        for comment in comments_list:
            extracted = extract_comment_fields(comment)
            if extracted is not None:  # 只添加有效的评论
                result.append(extracted)
        
        # 统计总评论数（包括所有层级）
        def count_all_comments(comments):
            if not comments:
                return 0
            count = len(comments)
            for comment in comments:
                if comment and comment.get('sub_comments'):
                    count += count_all_comments(comment['sub_comments'])
            return count
        
        total_count = count_all_comments(result)
        logger.info(f"✅ 提取到 {len(result)} 条顶层评论，总计 {total_count} 条评论（包括所有子评论）")
        return result
        
    except requests.exceptions.Timeout:
        logger.error(f"❌ 获取笔记 {note_id} 评论超时(>10秒) comments: {comments_data}")
        return None
    except Exception as e:
        logger.error(f"❌ 获取笔记 {note_id} 评论异常: {e} comments: {comments_data}")
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
    logger.info(f"文件保存目录: {log_dir}")
    logger.info(f"日志文件: {log_filename}")
    logger.info("=" * 60)
    
    # 1. 搜索笔记
    logger.info("=" * 60)
    logger.info("开始搜索笔记...")
    logger.info("=" * 60)
    result = search_notes_by_keyword(keyword="帮我推荐新加坡东部的川菜馆")
    
    if result is None:
        logger.error("搜索失败，程序退出")
        exit(1)
    
    # 格式化输出搜索结果
    logger.info("\n===============关键词搜索结果===============")
    logger.info(json.dumps(result, ensure_ascii=False, indent=2))
    
    # 2. 获取每个笔记的详细信息和评论
    logger.info("\n" + "=" * 60)
    logger.info("开始获取笔记详细信息和评论...")
    logger.info("=" * 60)
    
    detail_success_count = 0
    detail_fail_count = 0
    comment_success_count = 0
    comment_fail_count = 0
    
    for idx, item in enumerate(result, 1):
        note_id = item.get('id')
        if note_id:
            logger.info(f"\n[{idx}/{len(result)}] 处理笔记 {note_id}...")
            
            # 获取详细信息
            logger.info(f"  ├── 获取详细信息...")
            detail = get_note_detail(note_id)
            
            if detail:
                # 更新desc
                if 'desc' in detail:
                    item['desc'] = detail['desc']
                    logger.info(f"  │   ✅ 已更新desc")
                
                # 添加images_list
                if 'images_list' in detail:
                    item['images_list'] = detail['images_list']
                    logger.info(f"  │   ✅ 已添加images_list (共{len(detail['images_list'])}张图片)")
                
                detail_success_count += 1
            else:
                logger.info(f"  │   ❌ 获取详细信息失败")
                detail_fail_count += 1
            
            # 获取评论
            logger.info(f"  └── 获取评论...")
            comments = get_note_comments(note_id)
            
            if comments is not None:
                item['comments'] = comments
                # 统计评论数
                def count_comments(comment_list):
                    if not comment_list:
                        return 0
                    count = len(comment_list)
                    for comment in comment_list:
                        if comment and comment.get('sub_comments'):
                            count += count_comments(comment['sub_comments'])
                    return count
                total_comments = count_comments(comments)
                logger.info(f"      ✅ 已添加评论 (顶层评论{len(comments)}条, 总计{total_comments}条)")
                comment_success_count += 1
            else:
                logger.info(f"      ❌ 获取评论失败")
                item['comments'] = []
                comment_fail_count += 1
    
    logger.info("\n" + "=" * 60)
    logger.info(f"笔记详情获取完成: 成功 {detail_success_count} 个, 失败 {detail_fail_count} 个")
    logger.info(f"笔记评论获取完成: 成功 {comment_success_count} 个, 失败 {comment_fail_count} 个")
    logger.info("=" * 60)
    
    # 3. 保存结果到JSON文件
    result_filename = os.path.join(log_dir, f"xiaohongshu_result_{log_time}.json")
    try:
        with open(result_filename, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"\n✅ 结果已保存到JSON文件: {result_filename}")
    except Exception as e:
        logger.error(f"\n❌ 保存JSON文件失败: {e}")
    
    # 4. 输出最终结果
    logger.info("\n===============最终结果===============")
    logger.info(json.dumps(result, ensure_ascii=False, indent=2))
    
    logger.info("\n" + "=" * 60)
    logger.info("程序执行完成")
    logger.info(f"文件保存目录: {log_dir}")
    logger.info(f"日志文件: {log_filename}")
    logger.info(f"结果文件: {result_filename}")
    logger.info("=" * 60)
