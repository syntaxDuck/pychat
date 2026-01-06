import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
import tempfile
import os

from models import Client, Message
from server import MessageServer
from database import ChatDatabase


@pytest.mark.skip(
    reason="Test file contains network-dependent tests that may block indefinitely"
)
class TestHealthMonitoringIntegration:
    """Integration tests for health monitoring with real server interactions."""

    @pytest.fixture
    async def temp_database(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
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
    async def integration_server(self, temp_database):
        """Create a server with realistic settings for integration testing."""
        server = MessageServer(
            address="127.0.0.1",
            port=0,  # Let OS choose port
            max_message_history=100,
        )
        server.database = temp_database
        # Realistic timing for integration tests (but faster than production)
        server.heartbeat_interval = 2.0
        server.connection_timeout = 6.0
        server.max_missed_heartbeats = 2
        return server

    @pytest.fixture
    def multiple_mock_clients(self):
        """Create multiple mock clients for testing."""
        clients = []
        for i in range(3):
            client = Client(ip=f"192.168.1.{i + 1}", port=8080 + i)
            client._reader = AsyncMock()
            client._writer = AsyncMock()
            client.last_heartbeat = datetime.now()
            client.connection_status = "connected"
            client.missed_heartbeats = 0
            clients.append(client)
        return clients

    @pytest.mark.asyncio
    async def test_full_heartbeat_cycle(
        self, integration_server, multiple_mock_clients
    ):
        """Test complete heartbeat cycle with multiple clients."""
        # Add multiple clients
        for client in multiple_mock_clients:
            integration_server.connected_clients.add(client)

        with patch.object(
            integration_server, "_send_message_to_client", new_callable=AsyncMock
        ) as mock_send:
            # First health check - all clients healthy
            await integration_server._check_client_health()

            # Should have sent heartbeat to all 3 clients
            assert mock_send.call_count == 3

            # Verify heartbeat messages
            for call in mock_send.call_args_list:
                args, kwargs = call
                client, message = args
                assert message.message_type == "heartbeat"
                assert message.content == "HEARTBEAT"
                assert client in multiple_mock_clients

    @pytest.mark.asyncio
    async def test_heartbeat_recovery_scenario(self, integration_server, mock_client):
        """Test scenario where client recovers from stale state."""
        integration_server.connected_clients.add(mock_client)

        # Make client appear stale
        old_time = datetime.now() - timedelta(
            seconds=integration_server.connection_timeout + 1
        )
        mock_client.last_heartbeat = old_time
        mock_client.connection_status = "stale"
        mock_client.missed_heartbeats = 1

        # Simulate heartbeat response
        response = Message.create_heartbeat_response("127.0.0.1:12345", "server")

        # Handle heartbeat response
        await integration_server._handle_heartbeat_response(response)

        # Client should be recovered
        assert mock_client.connection_status == "connected"
        assert mock_client.missed_heartbeats == 0
        assert (datetime.now() - mock_client.last_heartbeat).total_seconds() < 1

    @pytest.mark.asyncio
    async def test_gradual_client_timeout(self, integration_server, mock_client):
        """Test gradual timeout of a non-responsive client."""
        integration_server.connected_clients.add(mock_client)

        with patch.object(
            integration_server, "remove_client", new_callable=AsyncMock
        ) as mock_remove:
            with patch.object(
                integration_server, "_send_message_to_client", new_callable=AsyncMock
            ):
                # Make client stale but not yet timed out
                old_time = datetime.now() - timedelta(
                    seconds=integration_server.connection_timeout + 1
                )
                mock_client.last_heartbeat = old_time
                mock_client.missed_heartbeats = 1

                # First health check - client becomes more stale but not removed
                await integration_server._check_client_health()
                assert mock_client.connection_status == "stale"
                assert mock_client.missed_heartbeats == 2
                mock_remove.assert_not_called()

                # Second health check - client should be removed
                await integration_server._check_client_health()
                mock_remove.assert_called_once_with(mock_client)

    @pytest.mark.asyncio
    async def test_mixed_client_health_states(
        self, integration_server, multiple_mock_clients
    ):
        """Test health monitoring with clients in different states."""
        healthy_clients = multiple_mock_clients[:2]
        stale_client = multiple_mock_clients[2]

        # Setup clients in different states
        for client in healthy_clients:
            integration_server.connected_clients.add(client)
            client.last_heartbeat = datetime.now()
            client.missed_heartbeats = 0

        # Make one client stale
        integration_server.connected_clients.add(stale_client)
        stale_client.last_heartbeat = datetime.now() - timedelta(
            seconds=integration_server.connection_timeout + 1
        )
        stale_client.missed_heartbeats = 1

        removed_clients = []

        def track_removal(client):
            removed_clients.append(client)

        with patch.object(
            integration_server,
            "remove_client",
            new_callable=AsyncMock,
            side_effect=track_removal,
        ):
            with patch.object(
                integration_server, "_send_message_to_client", new_callable=AsyncMock
            ):
                await integration_server._check_client_health()

                # Healthy clients should remain connected
                for client in healthy_clients:
                    assert client in integration_server.connected_clients

                # Stale client should still be connected (below threshold)
                assert stale_client in integration_server.connected_clients
                assert stale_client.connection_status == "stale"

                # No clients should be removed yet
                assert len(removed_clients) == 0

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(
        self, integration_server, multiple_mock_clients
    ):
        """Test concurrent health check operations."""
        for client in multiple_mock_clients:
            integration_server.connected_clients.add(client)

        # Simulate concurrent health checks
        async def mock_health_check():
            await integration_server._check_client_health()

        with patch.object(
            integration_server, "_send_message_to_client", new_callable=AsyncMock
        ):
            # Run multiple health checks concurrently
            tasks = [mock_health_check() for _ in range(3)]
            await asyncio.gather(*tasks)

            # All clients should still be connected
            for client in multiple_mock_clients:
                assert client in integration_server.connected_clients

    @pytest.mark.asyncio
    async def test_heartbeat_with_message_broadcasting(
        self, integration_server, mock_client
    ):
        """Test heartbeat system coexisting with message broadcasting."""
        integration_server.connected_clients.add(mock_client)

        # Add a message to the broadcast queue
        test_message = Message(
            origin="test_client",
            recipient_id="all",
            timestamp=datetime.now(),
            content="Hello everyone!",
            message_type="chat",
        )

        with patch.object(
            integration_server, "_send_message_to_client", new_callable=AsyncMock
        ) as mock_send:
            # Send regular message
            await integration_server._send_message_to_client(
                mock_client, test_message, []
            )

            # Send heartbeat
            heartbeat = Message.create_heartbeat("server", "127.0.0.1:12345")
            await integration_server._send_message_to_client(mock_client, heartbeat, [])

            # Both messages should be sent
            assert mock_send.call_count == 2

            # Verify message types
            calls = mock_send.call_args_list
            assert calls[0][0][1].message_type == "chat"
            assert calls[1][0][1].message_type == "heartbeat"

    @pytest.mark.asyncio
    async def test_database_integration_with_health_monitoring(
        self, integration_server, temp_database, mock_client
    ):
        """Test that health monitoring works with database integration."""
        integration_server.connected_clients.add(mock_client)

        # Mock database save_client_connection
        with patch.object(temp_database, "save_client_connection") as mock_save_client:
            with patch.object(
                integration_server, "_send_message_to_client", new_callable=AsyncMock
            ):
                await integration_server._check_client_health()

                # Health monitoring should not interfere with database operations
                mock_save_client.assert_not_called()  # Only called during registration

    @pytest.mark.asyncio
    async def test_health_monitoring_error_recovery(
        self, integration_server, mock_client
    ):
        """Test health monitoring recovery from errors."""
        integration_server.connected_clients.add(mock_client)

        with patch.object(
            integration_server, "_send_message_to_client", new_callable=AsyncMock
        ) as mock_send:
            # First call succeeds, second fails, third succeeds again
            mock_send.side_effect = [None, Exception("Network error"), None]

            with patch.object(
                integration_server, "remove_client", new_callable=AsyncMock
            ) as mock_remove:
                # First health check - succeeds
                await integration_server._check_client_health()
                assert mock_client in integration_server.connected_clients

                # Second health check - fails, client removed
                await integration_server._check_client_health()
                mock_remove.assert_called_once_with(mock_client)

                # Client should be removed after failure
                assert mock_client not in integration_server.connected_clients

    @pytest.mark.asyncio
    async def test_heartbeat_timing_accuracy(self, integration_server, mock_client):
        """Test that heartbeat timing is accurate."""
        integration_server.connected_clients.add(mock_client)
        integration_server.heartbeat_interval = 0.1  # Very fast for testing

        heartbeat_times = []

        def capture_heartbeat(client, message, *args):
            if message.message_type == "heartbeat":
                heartbeat_times.append(datetime.now())

        with patch.object(
            integration_server, "_send_message_to_client", side_effect=capture_heartbeat
        ):
            start_time = datetime.now()

            # Run health check multiple times
            for _ in range(3):
                await integration_server._check_client_health()
                await asyncio.sleep(0.1)  # Wait between checks

            # Verify timing
            assert len(heartbeat_times) >= 3

            # Check that heartbeats are spaced appropriately
            for i in range(1, len(heartbeat_times)):
                interval = (heartbeat_times[i] - heartbeat_times[i - 1]).total_seconds()
                assert 0.08 <= interval <= 0.15  # Allow some variance

    @pytest.mark.asyncio
    async def test_server_shutdown_with_active_health_monitoring(
        self, integration_server, mock_client
    ):
        """Test server shutdown while health monitoring is active."""
        integration_server.connected_clients.add(mock_client)

        # Mock the server as running
        integration_server.server = MagicMock()

        # Create heartbeat task
        heartbeat_task = asyncio.create_task(integration_server.health_monitor_loop())

        # Let it run briefly
        await asyncio.sleep(0.1)

        # Cancel the task (simulating shutdown)
        heartbeat_task.cancel()

        # Should handle cancellation gracefully
        with pytest.raises(asyncio.CancelledError):
            await heartbeat_task

        # Task should be cancelled
        assert heartbeat_task.cancelled()

    @pytest.mark.asyncio
    async def test_heartbeat_with_client_reconnection(
        self, integration_server, mock_client
    ):
        """Test heartbeat handling when client reconnects after disconnection."""
        original_client_id = f"{mock_client.ip}:{mock_client.port}"

        # Add and then remove client (simulating disconnection)
        integration_server.connected_clients.add(mock_client)
        await integration_server.remove_client(mock_client)

        # Create new client with same ID (reconnection)
        new_client = Client(ip=mock_client.ip, port=mock_client.port)
        new_client._reader = AsyncMock()
        new_client._writer = AsyncMock()
        new_client.last_heartbeat = datetime.now()

        integration_server.connected_clients.add(new_client)

        # Handle heartbeat for reconnected client
        response = Message.create_heartbeat_response(original_client_id, "server")
        await integration_server._handle_heartbeat_response(response)

        # New client should be recognized and marked as healthy
        assert new_client in integration_server.connected_clients
        assert new_client.connection_status == "connected"
        assert new_client.missed_heartbeats == 0
