import json
import asyncio
import logging
from datetime import datetime
from blessed import Terminal
from pydantic import ValidationError, BaseModel
from models import Message
from enum import Enum
from log import setup_logging

LOGGER_NAME = "tcp_client"


class Color(Enum):
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    RED = (255, 0, 0)
    GREEN = (0, 255, 0)
    BLUE = (0, 0, 255)


class ChatRenderConfig(BaseModel):
    background_color: Color = Color.WHITE
    border_color: Color = Color.BLACK
    input_marker: str = ">"
    input_border_symbol: str = "─"
    space_between_messages: int = 2
    user_identifier: str = "Me"


class ChatState(BaseModel):
    input_buffer: str = ""
    received_messages: list[Message] = []
    user_messages: list[Message] = []


class ChatInterfaceRenderer:
    def __init__(self, term: Terminal, chat_state: ChatState, config: ChatRenderConfig = ChatRenderConfig()):
        self._term = term
        self.state = chat_state
        self.render_config = config
        self.y_offset = 0
        self.input_box_height = 1

    async def handle_user_interface(self):
        try:
            with self._term.fullscreen(), self._term.cbreak(), self._term.hidden_cursor():
                while True:
                    self.y_offset = 0
                    self.clear()
                    self.render_input_box()
                    self.render_user_input()
                    self.render_messages()

                    await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in broadcast handler: {e}")
            raise

    def render_input_box(self):
        bar_height = 2
        input_marker_size = len(self.render_config.input_marker) + 1
        input_space = self._term.width - input_marker_size - 2
        extra_lines = (len(self.state.input_buffer) // input_space)

        print(
            self._term.move_xy(0, self._term.height - extra_lines - bar_height)
            + self._term.color_rgb(
                *self.render_config.border_color.value,
            )
            + self.render_config.input_border_symbol * self._term.width
            + self._term.move_down(1)
            + self._term.move_left(self._term.width)
            + self.render_config.input_marker
            + " ",
            end="",
            flush=True,
        )

    def render_user_input(self):
        input_marker_size = len(self.render_config.input_marker) + 1
        input_space = self._term.width - input_marker_size - 2
        extra_lines = (len(self.state.input_buffer) // input_space)

        input = []
        for x in range(0, len(self.state.input_buffer), input_space):
            input.append(self.state.input_buffer[x:x + input_space])
        input = "\n  ".join(input)

        print(
            self._term.move_xy(2, self._term.height - extra_lines - 1)
            + input
            + self._term.clear_eol,
            end="",
            flush=True,
        )

    def render_messages(
        self
    ):
        message_history = self.state.user_messages + self.state.received_messages
        message_history.sort(key=lambda msg: msg.timestamp)
        for message in message_history:
            if message.origin == "localhost":
                user_marker = f"{self.render_config.user_identifier}: "
                user_message = user_marker + message.content
                offset = len(user_message)
                formatted_message = " " * (self._term.width - offset) + user_message
            else:
                formatted_message = f"{message.origin} - {message.content}"
            print(
                self._term.move_xy(0, self.y_offset)
                + formatted_message
                + self._term.clear_eol,
                end="",
                flush=True,
            )
            self.y_offset += self.render_config.space_between_messages

    def clear(self):
        print(
            self._term.home
            + self._term.on_color_rgb(*self.render_config.background_color.value)
            + self._term.clear
        )


class ChatInterface:
    def __init__(self):
        self.term = Terminal()
        self.state = ChatState()
        self.ui = ChatInterfaceRenderer(term=self.term, chat_state=self.state)

    async def handle_broadcasts(self, stream_reader: asyncio.StreamReader):
        logger = logging.getLogger(LOGGER_NAME)
        read_limit = 1024
        try:
            while True:
                data = await stream_reader.read(read_limit)
                if not data or len(data) == 1 and data[0] in (10, 13):
                    continue
                decoded_message = json.loads(data.decode())
                logger.info(f"Received message from {decoded_message['origin']}")
                logger.debug(decoded_message)
                try:
                    client_message = Message.model_validate(decoded_message)
                    self.state.received_messages.append(client_message)
                except ValidationError as e:
                    logger.error(f"Invalid message format: {e}")
                    continue
                logger.info(
                    f"Broadcasts updated: {len(self.state.received_messages)} messages received"
                )
        except Exception as e:
            logger.error(f"Error in broadcast handler: {e}")
            raise

    async def handle_user_input(self, writer: asyncio.StreamWriter):
        while True:
            try:
                self.state.input_buffer = ""
                while True:
                    val = await asyncio.to_thread(self.term.inkey, timeout=0.1)
                    if val:
                        if val.name == "KEY_ENTER" or val == "\n":
                            break
                        elif val.name == "KEY_BACKSPACE" or val == "\x7f":
                            self.state.input_buffer = self.state.input_buffer[:-1]
                        elif val.name == "KEY_ESCAPE":
                            logger.info("User pressed escape, exiting input loop")
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
                writer.write(self.state.input_buffer.encode())
                await writer.drain()
            except Exception as e:
                logger.error(f"Error in user input handler: {e}")
                raise


async def main():
    server_address = ("localhost", 5050)
    try:
        stream_reader, stream_writer = await asyncio.open_connection(*server_address)
        logger.info(f"Connected to server at {server_address}")
        interface = ChatInterface()

        broadcast_task = asyncio.create_task(interface.handle_broadcasts(stream_reader))
        user_input_task = asyncio.create_task(
            interface.handle_user_input(stream_writer)
        )
        ui_render_task = asyncio.create_task(
            interface.ui.handle_user_interface()
        )

        await asyncio.gather(broadcast_task, user_input_task, ui_render_task)
    except ConnectionRefusedError:
        logger.error(
            f"Could not connect to server at {server_address}. Is the server running?"
        )
    except asyncio.TimeoutError:
        logger.error(
            "Connection attempt timed out. Please check the server address and port."
        )
    finally:
        if "broadcast_task" in locals():
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass
        if "user_input_task" in locals():
            user_input_task.cancel()
            try:
                await user_input_task
            except asyncio.CancelledError:
                pass
        if "ui_render_task" in locals():
            ui_render_task.cancel()
            try:
                await ui_render_task
            except asyncio.CancelledError:
                pass
        if "stream_writer" in locals():
            stream_writer.close()
            await stream_writer.wait_closed()
        logger.info("Connection closed")


if __name__ == "__main__":
    logger = setup_logging(LOGGER_NAME)
    logger.info("Starting client application")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Client interrupted by user (Ctrl+C). Shutting down cleanly.")
        print("\nDisconnected. Goodbye!")
