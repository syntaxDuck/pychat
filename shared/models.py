from datetime import datetime
from pydantic import BaseModel


class Message(BaseModel):
    origin: str
    timestamp: datetime
    content: str

    def byte_encode(self) -> bytes:
        return self.model_dump_json().encode()

    def __eq__(self, value):
        if isinstance(value, Message):
            return self.timestamp == value.timestamp and self.content == value.content
        return False

    def __hash__(self):
        return hash((self.origin, self.timestamp, self.content))

    def __str__(self):
        return f"{self.origin}: {self.content}"
