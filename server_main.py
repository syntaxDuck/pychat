import asyncio
import logging

from server.chat_server import ChatServer
from shared.config import SERVER_HOST, SERVER_PORT
from shared.log import setup_logging
from shared.config import SERVER_LOGGER_NAME


async def main():
    server = ChatServer(SERVER_HOST, SERVER_PORT)
    await server.init_server()

    try:
        await server.start_server()
    except KeyboardInterrupt:
        logging.getLogger(SERVER_LOGGER_NAME).info(
            "Server shutdown requested, stopping..."
        )
    except Exception as e:
        logging.getLogger(SERVER_LOGGER_NAME).error(f"Server encountered an error: {e}")
    finally:
        await server.stop_server()


if __name__ == "__main__":
    app_logger = setup_logging(SERVER_LOGGER_NAME, console_handler_level=logging.INFO)
    app_logger.info("Starting TCP server")
    try:
        asyncio.run(main())
    finally:
        logging.shutdown()
