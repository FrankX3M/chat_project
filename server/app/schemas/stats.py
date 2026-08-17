from pydantic import BaseModel


class OnlineStatsResponse(BaseModel):
    online: int
