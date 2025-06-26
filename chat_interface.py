import asyncio
import logging
import json
from datetime import datetime
from blessed import Terminal
from pydantic import ValidationError

from models import Message, ChatState
from chat_renderer import ChatRenderer


class ChatSessionManager:
    def __init__(self):
        self.term = Terminal()
        self.state = ChatState()
        self.logger = logging.getLogger("chat_interface")
        self.message_queue = asyncio.Queue(maxsize=100)

        self._stream_reader: asyncio.StreamReader | None = None
        self._stream_writer: asyncio.StreamWriter | None = None
        self._renderer = None

    @property
    def renderer(self) -> ChatRenderer:
        if self._renderer is None:
            raise ValueError(
                "Renderer has not been initialized. Call init_session first."
            )
        return self._renderer

    @renderer.setter
    def renderer(self, value: ChatRenderer):
        if not isinstance(value, ChatRenderer):
            raise TypeError("renderer must be an instance of ChatRenderer")
        self._renderer = value

    async def init_session(
        self, server_address: tuple[str, int], renderer: ChatRenderer
    ):
        stream_reader, stream_writer = await asyncio.open_connection(*server_address)
        self._stream_reader = stream_reader
        self._stream_writer = stream_writer

        self._renderer = renderer

        broadcast_task = asyncio.create_task(self.handle_broadcasts(stream_reader))
        user_input_task = asyncio.create_task(self.handle_user_input(stream_writer))
        render_task = asyncio.create_task(self.handle_rendering(self._renderer))

        await asyncio.gather(broadcast_task, user_input_task, render_task)

    async def handle_rendering(self, renderer: ChatRenderer):
        logger = logging.getLogger("chat_renderer")
        try:
            renderer.term = self.term
            with self.term.fullscreen(), self.term.cbreak(), self.term.hidden_cursor():
                while True:
                    try:
                        new_messages = self.message_queue.get_nowait()
                        self.state.message_history.append(new_messages)
                    except asyncio.QueueEmpty:
                        pass

                    renderer.render_user_interface(
                        self.state.input_buffer, self.state.message_history
                    )
                    await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in rendering handler: {e}")
            raise

    async def handle_broadcasts(self, stream_reader: asyncio.StreamReader):
        read_limit = 1024
        try:
            while True:
                data = await stream_reader.read(read_limit)
                if not data or len(data) == 1 and data[0] in (10, 13):
                    continue
                decoded_message = json.loads(data.decode())
                self.logger.info(f"Received message from {decoded_message['origin']}")
                self.logger.debug(decoded_message)
                try:
                    client_message = Message.model_validate(decoded_message)
                    self.state.received_messages.append(client_message)
                    await self.message_queue.put(client_message)
                except ValidationError as e:
                    self.logger.error(f"Invalid message format: {e}")
                    continue
                self.logger.info(
                    f"Broadcasts updated: {len(self.state.received_messages)} messages received"
                )
        except Exception as e:
            self.logger.error(f"Error in broadcast handler: {e}")
            raise

    async def handle_user_input(self, writer: asyncio.StreamWriter):
        while True:
            try:
                self.state.input_buffer = ""
                while True:
                    val = await asyncio.to_thread(self.term.inkey, timeout=0.5)
                    if val:
                        if val.name == "KEY_ENTER" or val == "\n":
                            break
                        elif val.name == "KEY_BACKSPACE" or val == "\x7f":
                            self.state.input_buffer = self.state.input_buffer[:-1]
                        elif val.name == "KEY_ESCAPE":
                            self.logger.info("User pressed escape, exiting input loop")
                            return
                        elif "\x1b" in val:  # Handle escape sequences
                            pass
                        else:
                            self.state.input_buffer += str(val)

                if not self.state.input_buffer.strip():
                    continue

                message = Message(
                    origin="localhost",
                    timestamp=datetime.now(),
                    content=self.state.input_buffer,
                )

                self.state.user_messages.append(message)
                await self.message_queue.put(message)
                writer.write(self.state.input_buffer.encode())
                await writer.drain()
            except Exception as e:
                self.logger.error(f"Error in user input handler: {e}")
                raise
