from pydantic import BaseModel, PrivateAttr
import asyncio
import logging
import os
from datetime import datetime

LOGGER_NAME = "tcp_server"
SERVER_ADDRESS = "localhost"
SERVER_PORT = 5000


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

    def __str__(self):
        return f"{self.client}: {self.message.content}\n"


broadcast_queue: asyncio.Queue[ClientMessage]
connected_clients: set[Client] = set()


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
    peername = writer.get_extra_info("peername")
    client = Client(
        ip=peername[0], port=peername[1], _reader=reader, _writer=writer
    )
    if client not in connected_clients:
        logger.info(f"Accepted connection from {client}")
        client._reader = reader
        client._writer = writer
        connected_clients.add(client)

    try:
        while True:
            data: bytes = await reader.read(read_limit)

            if not data:
                logger.info(f"No data received from {client}, disconnecting.")
                break
            elif len(data) == 1 and data[0] in (10, 13):
                continue
            else:
                received_message = Message(
                    timestamp=datetime.now(), content=data.decode().strip()
                )

                logger.info(f"Received from {client}: {received_message.content}")
                await broadcast_queue.put(
                    ClientMessage(client=client, message=received_message)
                )

    except asyncio.CancelledError:
        logger.exception(f"Client handler for {client} was canceled")
    except Exception as e:
        logger.exception(f"Error with client {client}: {e}")
    finally:
        if client in connected_clients:
            connected_clients.remove(client)
            logger.info(
                f"Client {client} disconnected, removing from connected clients"
            )
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                logger.error(f"Error closing connection for {client}: {e}")
        else:
            logger.warning(
                f"Client {client} was not in connected clients, skipping cleanup"
            )


async def broadcast_messages():
    logger = logging.getLogger(LOGGER_NAME)

    while True:
        client_message: ClientMessage = await broadcast_queue.get()
        try:
            disconnected_clients: list[Client] = []
            for client in list(connected_clients):
                if client != client_message.client:
                    try:
                        logger.info(
                            f"Broadcasting message from {client_message.client} -> {client}"
                        )
                        encoded_message = (client_message.model_dump_json() + "\n").encode()
                        client._writer.write(encoded_message)
                        await client._writer.drain()
                    except (
                        AttributeError,
                        ConnectionResetError,
                        BrokenPipeError,
                        asyncio.CancelledError,
                    ):
                        logger.warning(f"Client {client} disconnected, removing")
                        disconnected_clients.append(client)
                    except Exception as e:
                        logger.error(f"Error sending message to {client}: {e}")
                        disconnected_clients.append(client)

            for client in disconnected_clients:
                connected_clients.discard(client)
                logger.info(f"Removed disconnected client: {client}")

                try:
                    client._writer.close()
                    await client._writer.wait_closed()
                except Exception as e:
                    logger.error(f"Error closing connection for {client}: {e}")
        finally:
            broadcast_queue.task_done()


async def main():
    logger = logging.getLogger(LOGGER_NAME)
    server: asyncio.Server = await asyncio.start_server(
        handle_client, SERVER_ADDRESS, SERVER_PORT
    )
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    logger.info(f"Serving on {addrs}")

    global broadcast_queue
    broadcast_queue = asyncio.Queue(maxsize=100)
    broadcast_task = asyncio.create_task(broadcast_messages())
    logger.info("Broadcast task started")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    app_logger = setup_logging()
    app_logger.info("Starting TCP server")
    asyncio.run(main())
