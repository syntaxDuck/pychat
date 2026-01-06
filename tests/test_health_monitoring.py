import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
import tempfile
import os

from models import Client, Message
from server import MessageServer
from database import ChatDatabase
from settings import server_settings


class TestHealthMonitoring:
    """Test suite for connection health monitoring and heartbeat functionality."""

    @pytest.fixture
    async def temp_database(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_file:
            db_path = temp_file.name
        
        db = ChatDatabase(db_path)
        yield db
        db.close()
        os.unlink(db_path)
        # Clean up WAL files if they exist
        for wal_file in [f"{db_path}-wal", f"{db_path}-shm"]:
            if os.path.exists(wal_file):
                os.unlink(wal_file)

    @pytest.fixture
    async def server(self, temp_database):
        """Create a MessageServer instance for testing."""
        # Use a random port to avoid conflicts
        server = MessageServer(
            address="127.0.0.1",
            port=0,  # Let OS choose port
            max_message_history=10
        )
        server.database = temp_database
        server.heartbeat_interval = 1.0  # Short interval for testing
        server.connection_timeout = 3.0   # Short timeout for testing
        server.max_missed_heartbeats = 2  # Low threshold for testing
        return server

    @pytest.fixture
    def mock_client(self):
        """Create a mock client for testing."""
        client = Client(ip="127.0.0.1", port=12345)
        client._reader = AsyncMock()
        client._writer = AsyncMock()
        client.last_heartbeat = datetime.now()
        client.connection_status = "connected"
        client.missed_heartbeats = 0
        return client

    def test_heartbeat_message_creation(self):
        """Test creation of heartbeat messages."""
        heartbeat = Message.create_heartbeat("server", "client1")
        assert heartbeat.origin == "server"
        assert heartbeat.recipient_id == "client1"
        assert heartbeat.content == "HEARTBEAT"
        assert heartbeat.message_type == "heartbeat"

        response = Message.create_heartbeat_response("client1", "server")
        assert response.origin == "client1"
        assert response.recipient_id == "server"
        assert response.content == "HEARTBEAT_RESPONSE"
        assert response.message_type == "heartbeat_response"

    def test_client_heartbeat_fields(self):
        """Test Client model heartbeat fields."""
        client = Client(ip="192.168.1.1", port=8080)
        
        assert client.last_heartbeat is not None
        assert client.connection_status == "connected"
        assert client.missed_heartbeats == 0
        
        # Test updating fields
        client.last_heartbeat = datetime.now()
        client.connection_status = "stale"
        client.missed_heartbeats = 2
        
        assert client.connection_status == "stale"
        assert client.missed_heartbeats == 2

    @pytest.mark.asyncio
    async def test_health_monitor_loop_start_stop(self, server):
        """Test starting and stopping the health monitoring loop."""
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = asyncio.CancelledError("Test cancellation")
            
            server.server = MagicMock()  # Mock server to make loop think it's running
            
            with pytest.raises(asyncio.CancelledError):
                await server.health_monitor_loop()
            
            mock_sleep.assert_called_once_with(server.heartbeat_interval)

    @pytest.mark.asyncio
    async def test_check_client_health_healthy_client(self, server, mock_client):
        """Test health check for a healthy client."""
        # Add healthy client
        mock_client.last_heartbeat = datetime.now()
        mock_client.missed_heartbeats = 0
        server.connected_clients.add(mock_client)
        
        with patch.object(server, '_send_message_to_client', new_callable=AsyncMock) as mock_send:
            await server._check_client_health()
            
            # Should send heartbeat to healthy client
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            assert args[0] == mock_client
            assert args[1].message_type == "heartbeat"
            
            # Client should still be connected
            assert mock_client in server.connected_clients
            assert mock_client.connection_status == "connected"

    @pytest.mark.asyncio
    async def test_check_client_health_stale_client(self, server, mock_client):
        """Test health check for a stale client."""
        # Add stale client (old heartbeat)
        old_time = datetime.now() - timedelta(seconds=server.connection_timeout + 1)
        mock_client.last_heartbeat = old_time
        mock_client.missed_heartbeats = 1
        server.connected_clients.add(mock_client)
        
        with patch.object(server, '_send_message_to_client', new_callable=AsyncMock) as mock_send:
            with patch.object(server, 'remove_client', new_callable=AsyncMock) as mock_remove:
                await server._check_client_health()
                
                # Should send heartbeat and mark as stale
                mock_send.assert_called_once()
                assert mock_client.connection_status == "stale"
                assert mock_client.missed_heartbeats == 2
                
                # Should not be removed yet (below threshold)
                mock_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_client_health_remove_stale_client(self, server, mock_client):
        """Test removal of client with too many missed heartbeats."""
        # Add client with many missed heartbeats
        old_time = datetime.now() - timedelta(seconds=server.connection_timeout + 1)
        mock_client.last_heartbeat = old_time
        mock_client.missed_heartbeats = server.max_missed_heartbeats  # At threshold
        server.connected_clients.add(mock_client)
        
        with patch.object(server, '_send_message_to_client', new_callable=AsyncMock) as mock_send:
            with patch.object(server, 'remove_client', new_callable=AsyncMock) as mock_remove:
                await server._check_client_health()
                
                # Should remove client
                mock_remove.assert_called_once_with(mock_client)
                assert mock_client not in server.connected_clients

    @pytest.mark.asyncio
    async def test_handle_heartbeat_response_valid_client(self, server, mock_client):
        """Test handling heartbeat response from known client."""
        server.connected_clients.add(mock_client)
        
        response = Message.create_heartbeat_response("127.0.0.1:12345", "server")
        
        # Make client appear slightly stale
        mock_client.last_heartbeat = datetime.now() - timedelta(seconds=10)
        mock_client.connection_status = "stale"
        mock_client.missed_heartbeats = 1
        
        await server._handle_heartbeat_response(response)
        
        # Client should be marked as healthy again
        assert mock_client.connection_status == "connected"
        assert mock_client.missed_heartbeats == 0
        assert (datetime.now() - mock_client.last_heartbeat).total_seconds() < 1

    @pytest.mark.asyncio
    async def test_handle_heartbeat_response_unknown_client(self, server):
        """Test handling heartbeat response from unknown client."""
        response = Message.create_heartbeat_response("unknown:9999", "server")
        
        # Should not raise exception, just log warning
        await server._handle_heartbeat_response(response)
        
        # No clients should be added
        assert len(server.connected_clients) == 0

    @pytest.mark.asyncio
    async def test_heartbeat_send_failure(self, server, mock_client):
        """Test handling of heartbeat send failures."""
        server.connected_clients.add(mock_client)
        
        with patch.object(server, '_send_message_to_client', new_callable=AsyncMock) as mock_send:
            with patch.object(server, 'remove_client', new_callable=AsyncMock) as mock_remove:
                # Make heartbeat sending fail
                mock_send.side_effect = Exception("Connection failed")
                
                await server._check_client_health()
                
                # Failed client should be removed
                mock_remove.assert_called_once_with(mock_client)

    @pytest.mark.asyncio
    async def test_remove_client_cleanup(self, server, mock_client):
        """Test client removal and resource cleanup."""
        server.connected_clients.add(mock_client)
        mock_writer = AsyncMock()
        mock_client._writer = mock_writer
        
        await server.remove_client(mock_client)
        
        # Client should be removed from connected clients
        assert mock_client not in server.connected_clients
        
        # Writer should be closed
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_client_cleanup_failure(self, server, mock_client):
        """Test handling cleanup failures during client removal."""
        server.connected_clients.add(mock_client)
        mock_writer = AsyncMock()
        mock_writer.close.side_effect = Exception("Close failed")
        mock_client._writer = mock_writer
        
        # Should not raise exception despite cleanup failure
        await server.remove_client(mock_client)
        
        # Client should still be removed
        assert mock_client not in server.connected_clients

    @pytest.mark.asyncio
    async def test_server_start_includes_heartbeat_task(self, server, temp_database):
        """Test that server start includes heartbeat monitoring."""
        with patch.object(server, 'init_server', new_callable=AsyncMock):
            with patch('asyncio.start_server', new_callable=AsyncMock) as mock_start_server:
                mock_server_instance = MagicMock()
                mock_server_instance.__aenter__ = AsyncMock(return_value=mock_server_instance)
                mock_server_instance.serve_forever = AsyncMock(side_effect=asyncio.CancelledError("Test"))
                mock_start_server.return_value = mock_server_instance
                
                with patch.object(temp_database, 'start_server_session', return_value='session123'):
                    with pytest.raises(asyncio.CancelledError):
                        await server.start_server()
                    
                    # Heartbeat task should be created
                    assert server._heartbeat_task is not None

    @pytest.mark.asyncio
    async def test_server_stop_includes_heartbeat_task(self, server):
        """Test that server stop includes heartbeat task cleanup."""
        # Mock tasks
        mock_broadcast_task = MagicMock()
        mock_heartbeat_task = MagicMock()
        
        server._broadcast_task = mock_broadcast_task
        server._heartbeat_task = mock_heartbeat_task
        server.server = MagicMock()
        server.connected_clients = {MagicMock(), MagicMock()}
        
        with patch.object(server, 'remove_client', new_callable=AsyncMock):
            await server.stop_server()
            
            # Both tasks should be cancelled
            mock_broadcast_task.cancel.assert_called_once()
            mock_heartbeat_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_integration_with_message_handling(self, server, mock_client):
        """Test integration of heartbeat system with message handling."""
        server.connected_clients.add(mock_client)
        
        # Test regular message processing (unchanged)
        regular_msg = Message(
            origin="127.0.0.1:12345",
            recipient_id="all",
            timestamp=datetime.now(),
            content="Hello world",
            message_type="chat"
        )
        
        with patch.object(server.broadcast_queue, 'put', new_callable=AsyncMock) as mock_put:
            with patch.object(server.lifetime_messages, 'append'):
                with patch.object(server.database, 'save_message'):
                    # This would normally be called in handle_client loop
                    await server.broadcast_queue.put(regular_msg)
                    
                    mock_put.assert_called_once_with(regular_msg)

    def test_health_monitoring_configuration(self, server):
        """Test health monitoring configuration values."""
        assert server.heartbeat_interval == 1.0  # Set in fixture
        assert server.connection_timeout == 3.0   # Set in fixture
        assert server.max_missed_heartbeats == 2  # Set in fixture

    @pytest.mark.asyncio
    async def test_health_monitor_loop_exception_handling(self, server):
        """Test health monitoring loop exception handling."""
        server.server = MagicMock()  # Mock server as running
        
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            with patch.object(server, '_check_client_health', side_effect=Exception("Health check failed")):
                # First call succeeds, second fails, third cancelled
                mock_sleep.side_effect = [None, asyncio.CancelledError("Test")]
                
                with pytest.raises(asyncio.CancelledError):
                    await server.health_monitor_loop()
                
                # Should have attempted sleep twice
                assert mock_sleep.call_count == 2
                # Should have attempted health check once
                server._check_client_health.assert_called_once()