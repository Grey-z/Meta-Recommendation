import uuid
from metarec.storage import Storage
from typing import List
        
class SessionService:
    def __init__(self, storage: Storage):
        self.storage = storage
        pass
    
    ################
    # Conversation #
    ################
    async def create_conversation(self, user_id):
        new_id = str(uuid.uuid4())
        conversations = await self.storage.get(f'conversations:{user_id}', [])
        conversations = [*conversations, new_id]
        await self.storage.set(f'conversations:{user_id}', conversations)
        return new_id

    async def get_conversations(self, user_id):
        conversations = await self.storage.get(f'conversations:{user_id}', [])
        return conversations

    async def has_conversation(self, user_id, conversation_id):
        conversations = await self.storage.get(f'conversations:{user_id}', [])
        conversation = set(conversations)
        return conversation_id in conversations
    
    async def delete_conversation(self, user_id, conversation_id):
        conversations = await self.storage.get(f'conversations:{user_id}', [])
        before = len(conversations)
        conversations = [cid for cid in conversations if cid != conversation_id]
        await self.storage.set(f'conversations:{user_id}', conversations)

    #############################
    # Session Level Preferences #
    #############################
    async def get_preferences(self, user_id):
        preferences = await self.storage.get(f'preferences:{user_id}', {})
        return preferences

    async def update_preferences(self, user_id, updates):
        preferences = await self.storage.get(f'preferences:{user_id}', {})
        preferences = {**preferences, **updates}
        await self.storage.set(f'preferences:{user_id}', preferences)

