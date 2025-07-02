from datetime import datetime
import asyncio
from pydantic import BaseModel, PrivateAttr
from typing import Optional

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


class Client(BaseModel):
    ip: str
    port: Optional[int] = None
    _writer: Optional[asyncio.StreamWriter] = PrivateAttr(default=None)
    _reader: Optional[asyncio.StreamReader] = PrivateAttr(default=None)

    def __str__(self):
        return f"{self.ip}:{self.port}"

    def __eq__(self, value):
        if isinstance(value, Client):
            return self.ip == value.ip and self.port == value.port
        return False

    def __hash__(self):
        return hash((self.ip, self.port))

class ChatState(BaseModel):
    input_buffer: str = ""
    received_messages: list[Message] = []
    user_messages: list[Message] = []
    message_history: list[Message] = []