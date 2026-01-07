from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 5050
    max_connections: int = 100
    heartbeat_interval: float = 30.0
    log_level: str = "INFO"
    logger_name: str = "server_logger"

    model_config = SettingsConfigDict(
        env_prefix="CHAT_SERVER_", env_file=".env", extra="ignore"
    )


class ClientConfig(BaseSettings):
    host: str = "localhost"
    port: int = 5050
    reconnect_attempts: int = 3
    reconnect_delay: float = 1.0
    log_level: str = "INFO"
    logger_name: str = "chat_client"

    model_config = SettingsConfigDict(
        env_prefix="CHAT_CLIENT_", env_file=".env", extra="ignore"
    )


# Global instances (singleton pattern)
server_config = ServerConfig()
client_config = ClientConfig()

# Backwards compatibility
SERVER_HOST = server_config.host
SERVER_PORT = server_config.port
SERVER_LOGGER_NAME = server_config.logger_name
CLIENT_HOST = client_config.host

