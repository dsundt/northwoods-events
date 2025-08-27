from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Event:
    title: str
    start: datetime
    end: Optional[datetime]
    url: str
    location: Optional[str] = None
    description: Optional[str] = None
