import asyncio
import logging

from server.chat_server import ChatServer
from shared.log import setup_logging
from shared.config import server_config


async def main():
    server = ChatServer(server_config.host, server_config.port)
    await server.init_server()

    try:
        await server.start_server()
    except KeyboardInterrupt:
        logging.getLogger(server_config.logger_name).info(
            "Server shutdown requested, stopping..."
        )
    except Exception as e:
        logging.getLogger().error(f"Server encountered an error: {e}")
    finally:
        await server.stop_server()


if __name__ == "__main__":
    server_logger = setup_logging(
        server_config.logger_name,
        console_handler_level=getattr(logging, server_config.log_level),
    )
    server_logger.info("Starting chat server")
    try:
        asyncio.run(main())
    finally:
        logging.shutdown()
