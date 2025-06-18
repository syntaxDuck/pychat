import asyncio
import logging
import os
from datetime import datetime
from typing import NamedTuple
from dataclasses import dataclass

LOGGER_NAME = "tcp_server"
SERVER_ADDRESS = "localhost"
SERVER_PORT = 5000


@dataclass
class Message:
    timestamp: datetime
    content: str

    def __eq__(self, value):
        if isinstance(value, Message):
            return self.timestamp == value.timestamp and self.content == value.content
        return False


@dataclass
class Client:
    ip: str
    port: int

    def __eq__(self, value):
        if isinstance(value, Client):
            return self.ip == value.ip and self.port == value.port
        return False

@dataclass
class ClientMessage:
    client: Client
    message: Message


clients: dict[tuple, Client] = {}
message_queue: asyncio.Queue = asyncio.Queue()


def setup_logging():
    os.makedirs("logs", exist_ok=True)
    log_file = os.path.join("logs", f"{LOGGER_NAME}.log")

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)

    if not logger.hasHandlers():
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """
    Handles communication with a connected client.

    Args:
        reader (asyncio.StreamReader): StreamReader object to read data from the client.
        writer (asyncio.StreamWriter): StreamWriter object to send data to the client.
    """
    logger = logging.getLogger(LOGGER_NAME)
    read_limit = 1024

    peername: tuple = writer.get_extra_info("peername")
    if peername not in clients:
        logger.debug(f"Client peername: {peername}")
        clients[peername] = Client(peername[0], peername[1])
        logger.info(f"Accepted connection from peername: {peername}")

    client: Client = clients[peername]
    messages: list[Message] = []

    try:
        while True:
            try:
                data: bytes = await asyncio.wait_for(reader.read(read_limit), 1)
            except asyncio.TimeoutError:
                data = None

            q1 = ClientMessage(client, None)
            if data is None or len(data) == 0:
                logger.warning(f"No/Empty message received from {peername}, skipping")
            else:
                q1.message = Message(datetime.now(), data.decode().strip())
                logger.info(f"Received from {q1.client}: {q1.message.content}")
                messages.append(q1.message)
                await message_queue.put(q1)

            try:
                q2: ClientMessage = message_queue.get_nowait()
            except asyncio.QueueEmpty:
                continue

            if q1.client == q2.client:
                await message_queue.put(q2)
            else:
                writer.write((q2.message.content + '\n').encode())
                await writer.drain()

    except asyncio.CancelledError:
        logger.exception(f"Client handler for {peername} was canceled")
        clients.pop(peername, None)
    except Exception as e:
        logger.exception(f"Error with client {peername}: {e}")
    finally:
        logger.info(f"Closing connection for peername: {peername}")
        writer.close()
        await writer.wait_closed()


async def main():
    logger = logging.getLogger(LOGGER_NAME)
    server: asyncio.Server = await asyncio.start_server(
        handle_client, SERVER_ADDRESS, SERVER_PORT
    )

    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    logger.info(f"Serving on {addrs}")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    app_logger = setup_logging()
    app_logger.info("Starting TCP server")
    asyncio.run(main())
