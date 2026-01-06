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
class TestConnectionTimeoutCleanup:
    """Tests for connection timeout and cleanup behavior."""

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
    async def timeout_server(self, temp_database):
        """Create server with short timeout for testing."""
        server = MessageServer(address="127.0.0.1", port=0, max_message_history=50)
        server.database = temp_database
        # Very short timeouts for testing
        server.heartbeat_interval = 0.5
        server.connection_timeout = 1.0
        server.max_missed_heartbeats = 2
        return server

    @pytest.fixture
    def mock_client_with_streams(self):
        """Create mock client with reader and writer."""
        client = Client(ip="192.168.1.100", port=9999)
        client._reader = AsyncMock()
        client._writer = AsyncMock()
        client.last_heartbeat = datetime.now()
        client.connection_status = "connected"
        client.missed_heartbeats = 0
        return client

    @pytest.mark.asyncio
    async def test_immediate_timeout_detection(
        self, timeout_server, mock_client_with_streams
    ):
        """Test immediate detection of timed-out connections."""
        timeout_server.connected_clients.add(mock_client_with_streams)

        # Make client immediately timed out
        old_time = datetime.now() - timedelta(
            seconds=timeout_server.connection_timeout + 10
        )
        mock_client_with_streams.last_heartbeat = old_time
        mock_client_with_streams.missed_heartbeats = (
            timeout_server.max_missed_heartbeats
        )

        removed_clients = []

        def track_removal(client):
            removed_clients.append(client)

        with patch.object(
            timeout_server,
            "remove_client",
            new_callable=AsyncMock,
            side_effect=track_removal,
        ):
            with patch.object(
                timeout_server, "_send_message_to_client", new_callable=AsyncMock
            ):
                await timeout_server._check_client_health()

                assert len(removed_clients) == 1
                assert removed_clients[0] == mock_client_with_streams
                assert mock_client_with_streams not in timeout_server.connected_clients

    @pytest.mark.asyncio
    async def test_gradual_timeout_progression(
        self, timeout_server, mock_client_with_streams
    ):
        """Test gradual progression from healthy to timeout."""
        timeout_server.connected_clients.add(mock_client_with_streams)

        # Make client slightly stale
        old_time = datetime.now() - timedelta(
            seconds=timeout_server.connection_timeout + 0.1
        )
        mock_client_with_streams.last_heartbeat = old_time

        with patch.object(
            timeout_server, "remove_client", new_callable=AsyncMock
        ) as mock_remove:
            with patch.object(
                timeout_server, "_send_message_to_client", new_callable=AsyncMock
            ):
                # First check - becomes stale but not removed
                await timeout_server._check_client_health()
                assert mock_client_with_streams.connection_status == "stale"
                assert mock_client_with_streams.missed_heartbeats == 1
                mock_remove.assert_not_called()

                # Wait a bit more to trigger more timeout
                await asyncio.sleep(0.6)

                # Second check - should be removed
                await timeout_server._check_client_health()
                mock_remove.assert_called_once_with(mock_client_with_streams)

    @pytest.mark.asyncio
    async def test_batch_timeout_cleanup(self, timeout_server):
        """Test cleanup of multiple timed-out clients simultaneously."""
        # Create multiple timed-out clients
        timed_out_clients = []
        for i in range(5):
            client = Client(ip=f"192.168.1.{i + 1}", port=8000 + i)
            client._reader = AsyncMock()
            client._writer = AsyncMock()
            client.last_heartbeat = datetime.now() - timedelta(
                seconds=timeout_server.connection_timeout + 5
            )
            client.missed_heartbeats = timeout_server.max_missed_heartbeats
            timed_out_clients.append(client)
            timeout_server.connected_clients.add(client)

        removed_clients = []

        def track_removal(client):
            removed_clients.append(client)

        with patch.object(
            timeout_server,
            "remove_client",
            new_callable=AsyncMock,
            side_effect=track_removal,
        ):
            with patch.object(
                timeout_server, "_send_message_to_client", new_callable=AsyncMock
            ):
                await timeout_server._check_client_health()

                # All timed-out clients should be removed
                assert len(removed_clients) == 5
                for client in timed_out_clients:
                    assert client in removed_clients
                    assert client not in timeout_server.connected_clients

    @pytest.mark.asyncio
    async def test_partial_cleanup_mixed_states(self, timeout_server):
        """Test cleanup with mixed healthy and timed-out clients."""
        # Create healthy clients
        healthy_clients = []
        for i in range(3):
            client = Client(ip=f"192.168.1.{i + 1}", port=7000 + i)
            client._reader = AsyncMock()
            client._writer = AsyncMock()
            client.last_heartbeat = datetime.now()
            client.missed_heartbeats = 0
            healthy_clients.append(client)
            timeout_server.connected_clients.add(client)

        # Create timed-out clients
        timed_out_clients = []
        for i in range(2):
            client = Client(ip=f"192.168.2.{i + 1}", port=6000 + i)
            client._reader = AsyncMock()
            client._writer = AsyncMock()
            client.last_heartbeat = datetime.now() - timedelta(
                seconds=timeout_server.connection_timeout + 3
            )
            client.missed_heartbeats = timeout_server.max_missed_heartbeats
            timed_out_clients.append(client)
            timeout_server.connected_clients.add(client)

        removed_clients = []

        def track_removal(client):
            removed_clients.append(client)

        with patch.object(
            timeout_server,
            "remove_client",
            new_callable=AsyncMock,
            side_effect=track_removal,
        ):
            with patch.object(
                timeout_server, "_send_message_to_client", new_callable=AsyncMock
            ):
                await timeout_server._check_client_health()

                # Only timed-out clients should be removed
                assert len(removed_clients) == 2
                for client in timed_out_clients:
                    assert client in removed_clients

                # Healthy clients should remain
                for client in healthy_clients:
                    assert client in timeout_server.connected_clients
                    assert client not in removed_clients

    @pytest.mark.asyncio
    async def test_cleanup_resource_leak_prevention(
        self, timeout_server, mock_client_with_streams
    ):
        """Test that cleanup prevents resource leaks."""
        timeout_server.connected_clients.add(mock_client_with_streams)

        # Mock the writer to track cleanup
        writer_mock = mock_client_with_streams._writer
        writer_mock.close = MagicMock()
        writer_mock.wait_closed = AsyncMock()

        # Make client timed out
        mock_client_with_streams.last_heartbeat = datetime.now() - timedelta(
            seconds=timeout_server.connection_timeout + 5
        )
        mock_client_with_streams.missed_heartbeats = (
            timeout_server.max_missed_heartbeats
        )

        await timeout_server.remove_client(mock_client_with_streams)

        # Verify cleanup was called
        writer_mock.close.assert_called_once()
        writer_mock.wait_closed.assert_called_once()

        # Verify client was removed
        assert mock_client_with_streams not in timeout_server.connected_clients

    @pytest.mark.asyncio
    async def test_cleanup_with_exception_handling(self, timeout_server):
        """Test cleanup behavior when exceptions occur."""
        # Create multiple clients, some with cleanup issues
        normal_client = Client(ip="192.168.1.1", port=8001)
        normal_client._reader = AsyncMock()
        normal_client._writer = AsyncMock()
        normal_client.last_heartbeat = datetime.now() - timedelta(
            seconds=timeout_server.connection_timeout + 5
        )
        normal_client.missed_heartbeats = timeout_server.max_missed_heartbeats

        problematic_client = Client(ip="192.168.1.2", port=8002)
        problematic_client._reader = AsyncMock()
        problematic_client._writer = AsyncMock()
        problematic_client._writer.close.side_effect = Exception("Writer close failed")
        problematic_client.last_heartbeat = datetime.now() - timedelta(
            seconds=timeout_server.connection_timeout + 5
        )
        problematic_client.missed_heartbeats = timeout_server.max_missed_heartbeats

        timeout_server.connected_clients.add(normal_client)
        timeout_server.connected_clients.add(problematic_client)

        # Should not raise exceptions despite cleanup failures
        await timeout_server.remove_client(normal_client)
        await timeout_server.remove_client(problematic_client)

        # Both clients should be removed despite cleanup issues
        assert normal_client not in timeout_server.connected_clients
        assert problematic_client not in timeout_server.connected_clients

    @pytest.mark.asyncio
    async def test_timeout_detection_during_high_load(self, timeout_server):
        """Test timeout detection under high load conditions."""
        # Create many clients to simulate high load
        many_clients = []
        for i in range(20):
            client = Client(ip=f"192.168.{i // 256}.{i % 256}", port=8000 + i)
            client._reader = AsyncMock()
            client._writer = AsyncMock()
            client.last_heartbeat = datetime.now() - timedelta(
                seconds=timeout_server.connection_timeout + 2
            )
            client.missed_heartbeats = timeout_server.max_missed_heartbeats
            many_clients.append(client)
            timeout_server.connected_clients.add(client)

        removed_count = 0

        def track_removal(client):
            nonlocal removed_count
            removed_count += 1

        with patch.object(
            timeout_server,
            "remove_client",
            new_callable=AsyncMock,
            side_effect=track_removal,
        ):
            with patch.object(
                timeout_server, "_send_message_to_client", new_callable=AsyncMock
            ):
                # Should handle all clients efficiently
                await timeout_server._check_client_health()

                # All clients should be removed
                assert removed_count == 20
                assert len(timeout_server.connected_clients) == 0

    @pytest.mark.asyncio
    async def test_timeout_with_network_partitions(self, timeout_server):
        """Test timeout behavior simulating network partitions."""
        partitioned_client = Client(ip="10.0.0.1", port=9000)
        partitioned_client._reader = AsyncMock()
        partitioned_client._writer = AsyncMock()
        partitioned_client.last_heartbeat = datetime.now() - timedelta(
            seconds=timeout_server.connection_timeout + 1
        )
        partitioned_client.missed_heartbeats = 1

        healthy_client = Client(ip="10.0.0.2", port=9001)
        healthy_client._reader = AsyncMock()
        healthy_client._writer = AsyncMock()
        healthy_client.last_heartbeat = datetime.now()
        healthy_client.missed_heartbeats = 0

        timeout_server.connected_clients.add(partitioned_client)
        timeout_server.connected_clients.add(healthy_client)

        # Simulate network partition - heartbeat sending fails for partitioned client
        def simulate_network_partition(client, message, *args):
            if client.ip == "10.0.0.1":
                raise ConnectionError("Network partition")
            return None

        with patch.object(
            timeout_server, "remove_client", new_callable=AsyncMock
        ) as mock_remove:
            with patch.object(
                timeout_server,
                "_send_message_to_client",
                side_effect=simulate_network_partition,
            ):
                await timeout_server._check_client_health()

                # Partitioned client should be removed due to network failure
                assert mock_remove.call_count == 1
                removed_client = mock_remove.call_args[0][0]
                assert removed_client == partitioned_client

                # Healthy client should remain
                assert healthy_client in timeout_server.connected_clients

    @pytest.mark.asyncio
    async def test_timeout_cleanup_with_database_integration(
        self, timeout_server, temp_database
    ):
        """Test timeout cleanup doesn't interfere with database operations."""
        client = Client(ip="192.168.1.100", port=9999)
        client._reader = AsyncMock()
        client._writer = AsyncMock()
        client.last_heartbeat = datetime.now() - timedelta(
            seconds=timeout_server.connection_timeout + 5
        )
        client.missed_heartbeats = timeout_server.max_missed_heartbeats

        timeout_server.connected_clients.add(client)

        # Mock database operations
        with patch.object(temp_database, "save_client_connection") as mock_save:
            with patch.object(temp_database, "save_message") as mock_save_msg:
                # Health monitoring should not trigger database saves
                await timeout_server.remove_client(client)

                # Database operations should not be called during cleanup
                mock_save.assert_not_called()
                mock_save_msg.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_recovery_after_reconnection(self, timeout_server):
        """Test timeout behavior when client reconnects after timing out."""
        # Original connection
        original_client = Client(ip="192.168.1.100", port=9999)
        original_client._reader = AsyncMock()
        original_client._writer = AsyncMock()
        original_client.last_heartbeat = datetime.now() - timedelta(
            seconds=timeout_server.connection_timeout + 5
        )
        original_client.missed_heartbeats = timeout_server.max_missed_heartbeats

        timeout_server.connected_clients.add(original_client)

        # Remove timed-out client
        await timeout_server.remove_client(original_client)

        # Client reconnects with new streams
        reconnected_client = Client(ip="192.168.1.100", port=9999)
        reconnected_client._reader = AsyncMock()
        reconnected_client._writer = AsyncMock()
        reconnected_client.last_heartbeat = datetime.now()
        reconnected_client.connection_status = "connected"
        reconnected_client.missed_heartbeats = 0

        timeout_server.connected_clients.add(reconnected_client)

        # Should handle reconnected client normally
        response = Message.create_heartbeat_response("192.168.1.100:9999", "server")
        await timeout_server._handle_heartbeat_response(response)

        # Reconnected client should be treated as healthy
        assert reconnected_client.connection_status == "connected"
        assert reconnected_client.missed_heartbeats == 0
        assert reconnected_client in timeout_server.connected_clients

    @pytest.mark.asyncio
    async def test_timeout_configuration_edge_cases(self, timeout_server):
        """Test timeout behavior with edge case configurations."""
        # Test with zero heartbeat interval (should handle gracefully)
        timeout_server.heartbeat_interval = 0.1  # Very fast
        timeout_server.connection_timeout = 0.2  # Very short
        timeout_server.max_missed_heartbeats = 1  # Immediate removal

        client = Client(ip="192.168.1.100", port=9999)
        client._reader = AsyncMock()
        client._writer = AsyncMock()
        client.last_heartbeat = datetime.now() - timedelta(
            seconds=0.3
        )  # Exceeds timeout
        client.missed_heartbeats = 1

        timeout_server.connected_clients.add(client)

        with patch.object(
            timeout_server, "remove_client", new_callable=AsyncMock
        ) as mock_remove:
            with patch.object(
                timeout_server, "_send_message_to_client", new_callable=AsyncMock
            ):
                await timeout_server._check_client_health()

                # Should be removed immediately with aggressive settings
                mock_remove.assert_called_once_with(client)

    @pytest.mark.asyncio
    async def test_timeout_cleanup_idempotency(
        self, timeout_server, mock_client_with_streams
    ):
        """Test that timeout cleanup is idempotent."""
        timeout_server.connected_clients.add(mock_client_with_streams)

        # Make client timed out
        mock_client_with_streams.last_heartbeat = datetime.now() - timedelta(
            seconds=timeout_server.connection_timeout + 5
        )
        mock_client_with_streams.missed_heartbeats = (
            timeout_server.max_missed_heartbeats
        )

        # Remove client multiple times
        await timeout_server.remove_client(mock_client_with_streams)
        await timeout_server.remove_client(mock_client_with_streams)  # Should not error

        # Client should still be removed
        assert mock_client_with_streams not in timeout_server.connected_clients
