from datetime import datetime
import asyncio
from pydantic import BaseModel, PrivateAttr

class Message(BaseModel):
    timestamp: datetime
    content: str

    def __eq__(self, value):
        if isinstance(value, Message):
            return self.timestamp == value.timestamp and self.content == value.content
        return False

    def __hash__(self):
        return hash((self.timestamp, self.content))


class Client(BaseModel):
    ip: str
    port: int
    _writer: asyncio.StreamWriter = PrivateAttr(default=None)
    _reader: asyncio.StreamReader = PrivateAttr(default=None)

    def __str__(self):
        return f"{self.ip}:{self.port}"

    def __eq__(self, value):
        if isinstance(value, Client):
            return self.ip == value.ip and self.port == value.port
        return False

    def __hash__(self):
        return hash((self.ip, self.port))


class ClientMessage(BaseModel):
    client: Client
    message: Message

    def byte_encode(self) -> bytes:
        return self.model_dump_json().encode()
 
    def __str__(self):
        return f"{self.client}: {self.message.content}"