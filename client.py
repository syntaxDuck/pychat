import os
import json
import asyncio
import logging
from datetime import datetime
from blessed import Terminal
from pydantic import ValidationError
from server import ClientMessage


class TerminalUI:
    def __init__(self):
        self.term = Terminal()
        self.print_y_offset = 0

    def print_text_box(self):
        print(
            self.term.move_xy(0, self.term.height - 2)
            + "_" * self.term.width
            + self.term.move_down(1)
            + self.term.move_left(self.term.width)
            + "> ",
            end="",
            flush=True,
        )

    def print_user_input(self, user_input: str):
        print(
            self.term.move_xy(2, self.term.height) + user_input,
            end="",
            flush=True,
        )

    def print_broadcast(self, message: str):
        print(
            self.term.move_xy(0, self.print_y_offset) + message,
            end="",
            flush=True,
        )

        self.print_y_offset += 1

    def print_message(self, message: str):
        print(
            self.term.move_xy(0, self.print_y_offset)
            + (" " * (self.term.width - len(message)))
            + message,
            end="",
            flush=True,
        )

        self.print_y_offset += 1

        # for i, broadcast in enumerate(broadcasts):
        #     if i >= self.term.height - 3:
        #         break
        #     print(
        #         self.term.move_xy(0, i)
        #         + f"{broadcast.client.ip}:{broadcast.client.port} - {broadcast.message.content}"
        #     )
        # print(self.term.move_xy(0, self.term.height - 2), end="", flush=True)

    def clear(self):
        print(self.term.home + self.term.on_blue + self.term.clear)


terminal_ui = TerminalUI()
broadcasts: list[ClientMessage] = []
LOGGER_NAME = "tcp_client"


def setup_logging():
    os.makedirs("logs", exist_ok=True)
    log_file = os.path.join(
        "logs", f"{LOGGER_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

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
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


async def handle_broadcasts(stream_reader: asyncio.StreamReader):
    logger = logging.getLogger(LOGGER_NAME)
    read_limit = 1024
    print_line = 0
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
                broadcasts.append(client_message)
                terminal_ui.print_broadcast(
                    f"{client_message.client.ip}:{client_message.client.port} - {client_message.message.content}"
                )
            except ValidationError as e:
                logger.error(f"Invalid message format: {e}")
                continue
            logger.info(f"Broadcasts updated: {len(broadcasts)} messages received")
    except asyncio.CancelledError:
        logger.info("Broadcast handler cancelled.")
    except Exception as e:
        logger.error(f"Error in broadcast handler: {e}")


async def main():
    logger = setup_logging()
    logger.info("Client started")
    server_address = ("localhost", 5000)
    try:
        stream_reader, stream_writer = await asyncio.open_connection(*server_address)
        logger.info(f"Connected to server at {server_address}")
        broadcast_task = asyncio.create_task(handle_broadcasts(stream_reader))
        with terminal_ui.term.fullscreen(), terminal_ui.term.cbreak(), terminal_ui.term.hidden_cursor():

            async def user_input_loop():
                while True:
                    try:
                        user_input = ""
                        terminal_ui.print_text_box()
                        while True:
                            val = await asyncio.to_thread(
                                terminal_ui.term.inkey, timeout=0.1
                            )
                            if val:
                                if val.name == "KEY_ENTER" or val == "\n":
                                    break
                                elif val.name == "KEY_BACKSPACE" or val == "\x7f":
                                    user_input = user_input[:-1]
                                elif val.name == "KEY_ESCAPE":
                                    logger.info(
                                        "User pressed escape, exiting input loop"
                                    )
                                    return
                                else:
                                    user_input += str(val)
                                terminal_ui.print_user_input(
                                    user_input + terminal_ui.term.clear_eol
                                )

                        print(terminal_ui.term.clear_bol, end="", flush=True)
                        if not user_input.strip():
                            continue
                        terminal_ui.print_message(user_input)
                        stream_writer.write(user_input.encode() + b"\n")
                        await stream_writer.drain()
                    except ConnectionRefusedError as e:
                        logger.error(f"Connection error: {e}")
                        break
                    except (asyncio.CancelledError, KeyboardInterrupt):
                        logger.info("User input loop cancelled or interrupted by user")
                        break

            await user_input_loop()
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
    asyncio.run(main())
