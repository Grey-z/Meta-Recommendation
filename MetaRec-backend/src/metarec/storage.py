#from lightdb import LightDB
from pickledb import PickleDB

class Storage:
    """ Simple memory KV-store """
    def __init__(self):
        self.data = {}
        
    def get(self, key, default=None) -> any:
        return self.data.get(key, default)
    
    def set(self, key, data) -> None:
        self.data.set(key, data)
    
class DiskStorage:
    def __init__(self, path):
        self.db = PickleDB(path)
    
    async def get(self, key, default=None) -> any:
        await self.db.load()
        data = await self.db.get(key, default)
        return data
    
    async def set(self, key, value) -> None:
        await self.db.set(key, value)
        await self.db.save()

