import time
import asyncio


class Client:
    def __init__(self, peername):
        ip, port = peername
        self.ip = ip
        self.port = port
        self.messages = []


clients: dict[Client] = {}


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    read_limit = 1024
    peername: str = writer.get_extra_info("peername")

    if peername not in clients:
        clients[peername] = Client(peername)
        print(
            f"[{asyncio.get_event_loop().time():.2f}] Accepted connection from peername: {peername}"
        )

    client: Client = clients[peername]

    try:
        while True:
            data: bytes = await reader.read(read_limit)

            if not data:
                print(
                    f"[{asyncio.get_event_loop().time():.2f}] Client {peername} disconnected"
                )
                clients.pop(peername)
                break

            message = data.decode().strip()
            print(
                f"[{asyncio.get_event_loop().time():.2f}] Received from {peername}: {message}"
            )
            client.messages.append(message)

            response = f'[{asyncio.get_event_loop().time():.2f}] Received "{message}" from {peername}\n'
            writer.write(response.encode())
            await writer.drain()

            print(
                f"[{asyncio.get_event_loop().time():.2f}] Sent response to {peername}"
            )
    except asyncio.CancelledError:
        print(
            f"[{asyncio.get_event_loop().time():.2f}] Client handler for {peername} was canceled"
        )
        clients.pop(peername)
    except Exception as e:
        print(
            f"[{asyncio.get_event_loop().time():.2f}] Error with client {peername}: {e}"
        )
    finally:
        print(
            f"[{asyncio.get_event_loop().time():.2f}] Closing connection for peername: {peername}"
        )
        writer.close()
        await writer.wait_closed()


async def background_logger_task():
    print(f"[{time.time():.2f}] Background logger task started.")
    try:
        while True:
            await asyncio.sleep(5)

            total_messages = 0
            for client in clients.values():
                total_messages += len(client.messages)
            print(
                f"TCP Server handling {len(clients.keys())} with {total_messages} messages in memory"
            )
    except asyncio.CancelledError:
        print(f"[{time.time()}] Background logger task canceled")


async def main():
    host = "127.0.0.1"
    port = 5000
    server: asyncio.Server = await asyncio.start_server(handle_client, host, port)

    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    print(f"[{time.time():.2f}] Serving on {addrs}")


    logger_task = asyncio.create_task(background_logger_task(), name="background_logger")
    print(f"[{time.time():.2f}] Scheduled background logger task")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
