import asyncio
import logging
from datetime import datetime

from shared.models import Message
from shared.config import SERVER_LOGGER_NAME


class Client:
    def __init__(
        self,
        ip: str,
        port: int,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.logger = logging.getLogger(SERVER_LOGGER_NAME)
        self.ip: str = ip
        self.port: int = port
        self.reader: asyncio.StreamReader = reader
        self.writer: asyncio.StreamWriter = writer
        self.messages: list[Message] = []

    async def receive_message(self) -> Message | None:
        """Receives a message from a client."""
        read_limit = 1024

        if self.reader is None:
            self.logger.info("Client has no stream reader")

        data = await self.reader.read(read_limit)

        if not data:
            self.logger.info(f"No data received from {self}")
            return None

        if len(data) == 1 and data[0] in (10, 13):
            return None  # Ignore empty messages

        message_content = data.decode().strip()
        self.logger.info(f"Received from {self}: {message_content}")

        message = Message(
            origin=str(self), timestamp=datetime.now(), content=message_content
        )

        self.messages.append(message)
        return message

    def __str__(self) -> str:
        return f"{self.ip}:{self.port}"
