from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass
class Event:
    title: str
    start_iso: str
    end_iso: str
    url: str = ""
    location: str = ""
    all_day: bool = False
    description: str = ""

