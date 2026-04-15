from datetime import datetime, timezone

class TimeService:
    def now(self):
        return datetime.now(timezone.utc).isoformat()
