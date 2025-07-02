import asyncio
import logging
from log import setup_logging
from chat_session_manager import ChatSessionManager
from chat_renderer import ChatRenderer
from config import CLIENT_HOST, SERVER_PORT

LOGGER_NAME = "tcp_client"


async def main():
    server_address = (CLIENT_HOST, SERVER_PORT)

    session_manager = ChatSessionManager()
    renderer = ChatRenderer()
    await session_manager.init_session(server_address, renderer)


if __name__ == "__main__":    
    logger = setup_logging(LOGGER_NAME, console_handler_level=logging.INFO)    
    logger.info("Starting client application")
    try:        
        asyncio.run(main())    
    except KeyboardInterrupt:        
        logger.info("Client interrupted by user (Ctrl+C). Shutting down cleanly.")        
        print("\nDisconnected. Goodbye!")    
    finally:        logging.shutdown()
