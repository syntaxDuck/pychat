import asyncio
from log import setup_logging
from chat_interface import ChatSessionManager
from chat_renderer import ChatRenderer

LOGGER_NAME = "tcp_client"


async def main():
    server_address = ("localhost", 5050)

    session_manager = ChatSessionManager()
    renderer = ChatRenderer()
    await session_manager.init_session(server_address, renderer)


if __name__ == "__main__":
    logger = setup_logging(LOGGER_NAME)
    logger.info("Starting client application")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Client interrupted by user (Ctrl+C). Shutting down cleanly.")
        print("\nDisconnected. Goodbye!")
