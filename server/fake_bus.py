import trio
import json
import logging
import os
import random
import click
from functools import wraps
from contextlib import suppress
from trio_websocket import open_websocket_url, ConnectionClosed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FakeBus")

# Глобальный кэш маршрутов
ROUTES_CACHE = {}

def load_route(filepath):
    if filepath not in ROUTES_CACHE:
        with open(filepath, "r", encoding='utf-8') as f:
            ROUTES_CACHE[filepath] = json.load(f)
    return ROUTES_CACHE[filepath]

# --- Шаг 12: Механизм переподключений ---

def relaunch_on_disconnect(async_fn):
    @wraps(async_fn)
    async def wrapper(*args, **kwargs):
        while True:
            try:
                await async_fn(*args, **kwargs)
            except (ConnectionClosed, OSError):
                logger.error("Connection lost. Retrying in 2 seconds...")
                await trio.sleep(2)
    return wrapper

# --- Логика имитатора ---

async def run_bus(send_channel, route_filepath, bus_id, refresh_timeout, start_offset=0):
    """Имитирует один автобус."""
    route_data = load_route(route_filepath)
    route_name = route_data["name"]
    coords = route_data["coordinates"]
    total_points = len(coords)
    idx = start_offset

    while True:
        lat, lng = coords[idx]
        message = {
            "busId": bus_id,
            "lat": lat,
            "lng": lng,
            "route": route_name,
        }
        await send_channel.send(json.dumps(message))
        await trio.sleep(refresh_timeout)
        idx = (idx + 1) % total_points

@relaunch_on_disconnect
async def send_updates(server_url, receive_channel):
    """Отправляет данные в WebSocket (Шаг 10 + Шаг 12)."""
    async with open_websocket_url(server_url) as ws:
        logger.info("Connected to server.")
        while True:
            message = await receive_channel.receive()
            await ws.send_message(message)

# --- Шаг 11: CLI для имитатора ---

@click.command()
@click.option("--server", default="ws://127.0.0.1:8080", help="Server address")
@click.option("--routes_dir", default="server/routes", help="Routes directory")
@click.option("--routes_number", default=0, type=int, help="Limit number of routes")
@click.option("--buses_per_route", default=5, type=int, help="Buses per route")
@click.option("--websockets_number", default=5, type=int, help="Number of websockets")
@click.option("--emulator_id", default="", help="Prefix for busId")
@click.option("--refresh_timeout", default=0.1, type=float, help="Refresh timeout")
@click.option("-v", "--verbose", count=True, help="Verbosity level")
def main(server, routes_dir, routes_number, buses_per_route, websockets_number, emulator_id, refresh_timeout, verbose):
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose > 1:
        level = logging.DEBUG
    logging.basicConfig(level=level, force=True)

    async def start_emulator():
        # Шаг 10: Каналы
        send_channel, receive_channel = trio.open_memory_channel(100)
        
        async with trio.open_nursery() as nursery:
            # Запускаем воркеры для отправки
            for _ in range(websockets_number):
                nursery.start_soon(send_updates, server, receive_channel)

            # Запускаем автобусы
            processed = 0
            for filename in os.listdir(routes_dir):
                if not filename.endswith(".json"):
                    continue
                if routes_number > 0 and processed >= routes_number:
                    break
                
                processed += 1
                route_filepath = os.path.join(routes_dir, filename)
                route_data = load_route(route_filepath)
                
                for i in range(buses_per_route):
                    bus_id = f"{emulator_id}{route_data['name']}-{i}"
                    offset = random.randint(0, len(route_data['coordinates']) - 1)
                    nursery.start_soon(run_bus, send_channel, route_filepath, bus_id, refresh_timeout, offset)
                    await trio.sleep(0.001)

    with suppress(KeyboardInterrupt):
        trio.run(start_emulator)

if __name__ == "__main__":
    main()
