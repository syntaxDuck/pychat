import logging
import asyncio

from .client import Client
from shared.models import Message
from shared.config import SERVER_LOGGER_NAME


class ChatServer:
    """
    A simple TCP server that handles client connections and broadcasts messages.
    """

    def __init__(self, address: str, port: int):
        self.logger = logging.getLogger(SERVER_LOGGER_NAME)
        self.logger.info(f"Initializing server at {address}:{port}")

        self.address = address
        self.port = port
        self.connected_clients: set[Client] = set()
        self.broadcast_queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=100)
        self.lifetime_messages: list[Message] = []

    async def init_server(self):
        """
        Initializes the TCP server and prepares it to accept connections.
        """
        self.logger.info(f"Initializing server at {self.address}:{self.port}")
        try:
            self.server = await asyncio.start_server(
                self.handle_client, self.address, self.port
            )
            self.logger.info(
                f"Server initialized successfully at {self.address}:{self.port}"
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize server: {e}")
            raise

    async def start_server(self):
        """
        Starts the TCP server and begins listening for incoming connections.
        """
        self.logger.info(f"Starting server on {self.address}:{self.port}")
        self._broadcast_task = asyncio.create_task(self.broadcast_messages())

        try:
            async with self.server:
                await self.server.serve_forever()
                self.logger.info("Chat Server Ready")
        except asyncio.CancelledError:
            self.logger.info("Server shutdown requested, stopping broadcast task")
            self._broadcast_task.cancel()
            await self._broadcast_task
        except Exception as e:
            self.logger.error(f"Server encountered an error: {e}")
            raise

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handles communication with a connected client."""
        peername = writer.get_extra_info("peername")
        client = Client(ip=peername[0], port=peername[1], reader=reader, writer=writer)

        await self._register_client(client)

        try:
            while True:
                message = await client.receive_message()
                if message is None:
                    break

                await self.broadcast_queue.put(message)
                self.lifetime_messages.append(message)

        except asyncio.CancelledError:
            self.logger.warning(f"Client handler for {client} was cancelled.")
        except ConnectionResetError:
            self.logger.warning(f"Client {client} connection reset.")
        except Exception as e:
            self.logger.exception(f"Error with client {client}: {e}")
        finally:
            await self.remove_client(client)

    async def stop_server(self):
        """Gracefully shuts down the server."""
        self.logger.info("Stopping server...")
        if self.server:
            self.server.close()
            await self.server.wait_closed()

        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass

        for client in list(self.connected_clients):
            await self.remove_client(client)

        self.logger.info("Server stopped.")

    async def _register_client(self, client: Client):
        """Registers a new client."""
        if client not in self.connected_clients:
            self.logger.info(f"Accepted connection from {client}")
            self.connected_clients.add(client)

    async def remove_client(self, client: Client):
        """
        Removes a client from the connected clients set and closes its connection.

        Args:
            client (Client): The client to remove.
        """
        if client in self.connected_clients:
            self.connected_clients.discard(client)
            self.logger.info(f"Removed disconnected client: {client}")
            try:
                client.writer.close()
                await client.writer.wait_closed()
            except Exception as e:
                self.logger.error(f"Error closing connection for {client}: {e}")
        else:
            self.logger.warning(f"Client {client} not found in connected clients")

    async def broadcast_messages(self):
        while True:
            try:
                message: Message = await self.broadcast_queue.get()
                disconnected_clients: list[Client] = []
                for client in list(self.connected_clients):
                    if str(client) != message.origin:
                        try:
                            self.logger.info(
                                f"Broadcasting message from {message.origin} -> {client}"
                            )
                            client.writer.write(message.byte_encode())
                            await client.writer.drain()
                        except (
                            AttributeError,
                            ConnectionResetError,
                            BrokenPipeError,
                            asyncio.CancelledError,
                        ):
                            self.logger.warning(
                                f"Client {client} disconnected, removing"
                            )
                            disconnected_clients.append(client)
                        except Exception as e:
                            self.logger.error(f"Error sending message to {client}: {e}")
                            disconnected_clients.append(client)

                for client in disconnected_clients:
                    await self.remove_client(client)
            finally:
                self.broadcast_queue.task_done()
