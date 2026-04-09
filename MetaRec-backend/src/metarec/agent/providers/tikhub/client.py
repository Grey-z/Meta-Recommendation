"""
# From agent/agent_mcp/agent_xiaohongshu.py
# * not tested as API requires payment
"""
from metarec.agent.providers.base import BaseAsyncClient
from typing import Optional

# from agent/agent_mcp/agent_xiaohongshu.py
# 统计总评论数（包括所有层级）
def count_all_comments(comments):
    if not comments:
        return 0
    count = len(comments)
    for comment in comments:
        if comment and comment.get('sub_comments'):
            count += count_all_comments(comment['sub_comments'])
    return count

# from agent/agent_mcp/agent_xiaohongshu.py
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
        #logger.warning(f"  ⚠️  评论对象类型错误: {type(comment)}, 跳过该评论")
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

class TikHubClient(BaseAsyncClient):
    def __init__(
        self,
        api_key: Optional[str]=None,
    ):
        headers = {
            'accept': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        super().__init__(
            base_url='https://api.tikhub.io',
            headers=headers,
        )
    
    async def search_xiaohongshu(
        self,
        keyword: str
    ):
        """
        *Note: Requires payment. Free credits on TikHub api does not work with this API endpoint.
        """
        
        params = {
            'keyword': keyword,
            'sort_type': 'general',
            'filter_note_type': '不限', # any
            'filter_note_time': '不限', # any
            'page': 1,
        }
            
        resp = await self.client.get('/api/v1/xiaohongshu/app/search_notes', params=params)
        resp.raise_for_status()

        data = resp.json()
        
        results = data.get('data', {}).get('data', {}).get('items', [])
        results = [result for result in results if result.get('model_type') == 'note']
        
        return results

    async def get_xiaohongshu_note_details(
        self,
        note_id: str
    ):
        params = {
            'note_id': note_id,
        }
            
        resp = await self.client.get('/api/v1/xiaohongshu/app/get_note_info', params=params)
        resp.raise_for_status()

        data = resp.json()
        
        results = data.get('data', {}).get('data', [])
        if len(results) < 1:
            return {}

        results = results[0].get('note_list', [])
        if len(results) < 1:
            return {}

        note_data = results[0]
        result = {}

        if 'desc' in note_data:
            result['desc'] = note_data.get('desc')
        if 'images_list' in note_data:
            result['images_list'] = note_data.get('images_list')
        
        return result

    async def get_xiaohongshu_note_comments(
        self,
        note_id: str
    ):
        params = {
            'note_id': note_id,
        }
            
        resp = await self.client.get('/api/v1/xiaohongshu/app/get_note_comments', params=params)
        resp.raise_for_status()

        comments_data = resp.json()

        # 提取评论列表：data.data.comments
        comments_list = comments_data.get('data', {}).get('data', {}).get('comments', [])

        result = []
        for comment in comments_list:
            extracted = extract_comment_fields(comment)
            if extracted is not None:  # 只添加有效的评论
                result.append(extracted)
        
        
        total_count = count_all_comments(result)
        #logger.info(f"✅ 提取到 {len(result)} 条顶层评论，总计 {total_count} 条评论（包括所有子评论）")
        return result
    
