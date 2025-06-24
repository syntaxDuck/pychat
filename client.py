import json
import asyncio
import logging
from datetime import datetime
from blessed import Terminal
from pydantic import ValidationError, BaseModel
from models import ClientMessage, Client, Message
from log import setup_logging


class ChatState(BaseModel):
    input_buffer: str = ""
    received_messages: list[ClientMessage] = []
    sent_messages: list[ClientMessage] = []


class ChatInterfaceRenderer:
    def __init__(self, term: Terminal):
        self._term = term
        self.y_offset = 0
        self.client_message_rendering_queue: asyncio.Queue[Message] = asyncio.Queue(
            maxsize=100
        )
        self.broadcast_message_rendering_queue: asyncio.Queue[ClientMessage] = (
            asyncio.Queue(maxsize=100)
        )

    async def handle_user_interface(self, state: ChatState):
        with self._term.fullscreen(), self._term.cbreak(), self._term.hidden_cursor():
            while True:
                self.render_input_box()
                self.render_user_input(state.input_buffer)
                self.render_client_message()
                self.render_broadcast_message()
                await asyncio.sleep(0.1)

    def render_input_box(self):
        print(
            self._term.move_xy(0, self._term.height - 2)
            + "_" * self._term.width
            + self._term.move_down(1)
            + self._term.move_left(self._term.width)
            + "> ",
            end="",
            flush=True,
        )

    def render_user_input(self, input_buffer: str):
        print(
            self._term.move_xy(2, self._term.height)
            + input_buffer
            + self._term.clear_eol,
            end="",
            flush=True,
        )

    def render_broadcast_message(self):
        if self.broadcast_message_rendering_queue.empty():
            return
        broadcast_message = self.broadcast_message_rendering_queue.get_nowait()
        formatted_message = f"{broadcast_message.client.ip}:{broadcast_message.client.port} - {broadcast_message.message.content}"
        print(
            self._term.move_xy(0, self.y_offset)
            + formatted_message
            + self._term.clear_eol,
            end="",
            flush=True,
        )
        self.y_offset += 1

    def render_client_message(self):
        if self.client_message_rendering_queue.empty():
            return
        message = self.client_message_rendering_queue.get_nowait()
        print(
            self._term.move_xy(0, self.y_offset)
            + (" " * (self._term.width - len(message.content)))
            + message.content,
            end="",
            flush=True,
        )
        self.y_offset += 1

    def clear(self):
        print(self._term.home + self._term.on_blue + self._term.clear)


class ChatInterface:
    def __init__(self):
        self.term = Terminal()
        self.state = ChatState()
        self.ui = ChatInterfaceRenderer(term=self.term)

    async def handle_broadcasts(self, stream_reader: asyncio.StreamReader):
        logger = logging.getLogger(LOGGER_NAME)
        read_limit = 1024
        try:
            while True:
                data = await stream_reader.read(read_limit)
                if not data or len(data) == 1 and data[0] in (10, 13):
                    continue
                decoded_message = json.loads(data.decode())
                logger.info(f"Received message from {decoded_message['client']['ip']}")
                logger.debug(decoded_message)
                try:
                    client_message = ClientMessage.model_validate(decoded_message)
                    self.state.received_messages.append(client_message)
                    await self.ui.broadcast_message_rendering_queue.put(client_message)
                except ValidationError as e:
                    logger.error(f"Invalid message format: {e}")
                    continue
                logger.info(
                    f"Broadcasts updated: {len(self.state.received_messages)} messages received"
                )
        except KeyboardInterrupt:
            logger.info("Broadcast handler interrupted by user.")
        except asyncio.CancelledError:
            logger.info("Broadcast handler cancelled.")
        except Exception as e:
            logger.error(f"Error in broadcast handler: {e}")

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
                        elif '\x1b' in val:  # Handle escape sequences
                            pass
                        else:
                            self.state.input_buffer += str(val)

                if not self.state.input_buffer.strip():
                    continue

                new_message = Message(
                    timestamp=datetime.now(), content=self.state.input_buffer
                )

                self.state.sent_messages.append(new_message)
                await self.ui.client_message_rendering_queue.put(new_message)

                writer.write(self.state.input_buffer.encode())
                await writer.drain()
            except ConnectionRefusedError as e:
                logger.error(f"Connection error: {e}")
                break
            except (asyncio.CancelledError, KeyboardInterrupt):
                logger.info("User input loop cancelled or interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error in user input handler: {e}")
                break


LOGGER_NAME = "tcp_client"


async def main():
    server_address = ("localhost", 5000)
    try:
        stream_reader, stream_writer = await asyncio.open_connection(*server_address)
        logger.info(f"Connected to server at {server_address}")
        interface = ChatInterface()

        broadcast_task = asyncio.create_task(interface.handle_broadcasts(stream_reader))
        user_input_task = asyncio.create_task(
            interface.handle_user_input(stream_writer)
        )
        ui_render_task = asyncio.create_task(
            interface.ui.handle_user_interface(interface.state)
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

    except Exception as e:
        logger.error(f"Failed to connect to server: {e}")
    finally:
        if "broadcast_task" in locals():
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass
        if "stream_writer" in locals():
            stream_writer.close()
            await stream_writer.wait_closed()
        logger.info("Connection closed")


if __name__ == "__main__":
    logger = setup_logging(LOGGER_NAME)
    logger.info("Starting client application")
    asyncio.run(main())
