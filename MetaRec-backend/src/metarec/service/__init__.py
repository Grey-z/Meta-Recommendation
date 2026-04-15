from metarec.service.conversation import ConversationService
from metarec.service.session import SessionService
from metarec.service.time import TimeService
from metarec.storage import Storage
from metarec.storage import DiskStorage

class MetaRecService:
    def __init__(self):
        #storage = Storage()
        path = 'storage.pickle.db'
        storage = DiskStorage(path)
        time = TimeService()

        self.time = time
        self.storage = storage
        self.conversation = ConversationService()
        self.session = SessionService(storage)

async def test_service(service: MetaRecService):
    pass
