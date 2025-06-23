import json
import asyncio
import logging
from blessed import Terminal
from pydantic import ValidationError, BaseModel
from models import ClientMessage
from log import setup_logging


class ClientUIState(BaseModel):
    print_y_offset: int = 0
    input_buffer: str = ""
    received_messages: list[ClientMessage] = []
    sent_messages: list[ClientMessage] = []


class ClientUI:
    def __init__(self):
        self.term = Terminal()
        self.state = ClientUIState(term=self.term)

    def render_input_box(self):
        print(
            self.term.move_xy(0, self.term.height - 2)
            + "_" * self.term.width
            + self.term.move_down(1)
            + self.term.move_left(self.term.width)
            + "> ",
            end="",
            flush=True,
        )

    def render_user_input(self):
        print(
            self.term.move_xy(2, self.term.height)
            + self.state.input_buffer
            + self.term.clear_eol,
            end="",
            flush=True,
        )

    def render_broadcast_message(self):
        if len(self.state.received_messages) == 0:
            return
        broadcast_message = self.state.received_messages.pop(0)
        formatted_message = f"{broadcast_message.client.ip}:{broadcast_message.client.port} - {broadcast_message.message.content}"
        print(
            self.term.move_xy(0, self.state.print_y_offset)
            + formatted_message
            + self.term.clear_eol,
            end="",
            flush=True,
        )
        self.state.print_y_offset += 1

    def render_client_message(self):
        if len(self.state.sent_messages) == 0:
            return
        message = self.state.sent_messages.pop(0)
        print(
            self.term.move_xy(0, self.state.print_y_offset)
            + (" " * (self.term.width - len(message)))
            + message,
            end="",
            flush=True,
        )
        self.state.print_y_offset += 1

    def clear(self):
        print(self.term.home + self.term.on_blue + self.term.clear)


broadcasts: list[ClientMessage] = []
LOGGER_NAME = "tcp_client"


async def handle_broadcasts(stream_reader: asyncio.StreamReader, ui: ClientUI):
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
                ui.state.received_messages.append(client_message)
            except ValidationError as e:
                logger.error(f"Invalid message format: {e}")
                continue
            logger.info(f"Broadcasts updated: {len(broadcasts)} messages received")
    except KeyboardInterrupt:
        logger.info("Broadcast handler interrupted by user.")
    except asyncio.CancelledError:
        logger.info("Broadcast handler cancelled.")
    except Exception as e:
        logger.error(f"Error in broadcast handler: {e}")


async def handle_user_input(writer: asyncio.StreamWriter, ui: ClientUI):
    while True:
        try:
            ui.state.input_buffer = ""
            while True:
                val = await asyncio.to_thread(ui.term.inkey, timeout=0.1)
                if val:
                    if val.name == "KEY_ENTER" or val == "\n":
                        break
                    elif val.name == "KEY_BACKSPACE" or val == "\x7f":
                        ui.state.input_buffer = ui.state.input_buffer[:-1]
                    elif val.name == "KEY_ESCAPE":
                        logger.info("User pressed escape, exiting input loop")
                        return
                    else:
                        ui.state.input_buffer += str(val)

            if not ui.state.input_buffer.strip():
                continue
            ui.state.sent_messages.append(ui.state.input_buffer)
            writer.write(ui.state.input_buffer.encode())
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


async def handle_user_interface(ui: ClientUI):
    while True:
        ui.render_input_box()
        ui.render_user_input()
        ui.render_client_message()
        ui.render_broadcast_message()
        await asyncio.sleep(0.1)


async def main():
    server_address = ("localhost", 5000)
    try:
        stream_reader, stream_writer = await asyncio.open_connection(*server_address)
        logger.info(f"Connected to server at {server_address}")
        ui = ClientUI()

        broadcast_task = asyncio.create_task(handle_broadcasts(stream_reader, ui))
        user_input_task = asyncio.create_task(handle_user_input(stream_writer, ui))

        with ui.term.fullscreen(), ui.term.cbreak(), ui.term.hidden_cursor():
            await handle_user_interface(ui)

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
