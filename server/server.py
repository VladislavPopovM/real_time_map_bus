import trio
import logging
import click
import time
import struct
import hashlib
from functools import partial
from contextlib import suppress
from dataclasses import dataclass, field
import orjson
from trio_websocket import serve_websocket, ConnectionClosed

logging.getLogger('trio-websocket').setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BusServer")

@dataclass
class Bus:
    busId: str
    lat: float
    lng: float
    route: str
    numeric_id: float = field(init=False)
    numeric_route: float = field(init=False)
    last_seen: float = field(default_factory=time.time)

    def __post_init__(self):
        self.numeric_id = float(int(hashlib.md5(self.busId.encode()).hexdigest(), 16) % 1000000)
        try:
            self.numeric_route = float(self.route)
        except ValueError:
            self.numeric_route = 0.0

@dataclass
class WindowBounds:
    south_lat: float = 0
    north_lat: float = 0
    west_lng: float = 0
    east_lng: float = 0

    def is_inside(self, lat: float, lng: float) -> bool:
        if not all([self.south_lat, self.north_lat, self.west_lng, self.east_lng]):
            return True
        return (self.south_lat <= lat <= self.north_lat) and \
               (self.west_lng <= lng <= self.east_lng)

buses = {} # Глобальная база автобусов

async def talk_to_browser(ws, bounds, buses_dict):
    """
    Высокоточная фильтрация и бинарная отдача.
    """
    while True:
        try:
            visible_data = []
            # Используем генератор для экономии памяти при фильтрации
            for bus in buses_dict.values():
                if bounds.is_inside(bus.lat, bus.lng):
                    visible_data.extend([bus.numeric_id, bus.lat, bus.lng, bus.numeric_route])
            
            if visible_data:
                binary_packet = struct.pack(f'<{len(visible_data)}f', *visible_data)
                await ws.send_message(binary_packet)
            
            await trio.sleep(0.2)
        except ConnectionClosed:
            break

async def gate_for_buses(request, buses_dict):
    ws = await request.accept()
    while True:
        try:
            message = await ws.get_message()
            data = orjson.loads(message)
            bus_id = data.get("busId")
            if not bus_id: continue

            if bus_id in buses_dict:
                bus = buses_dict[bus_id]
                bus.lat, bus.lng = data['lat'], data['lng']
                bus.last_seen = time.time()
            else:
                buses_dict[bus_id] = Bus(busId=bus_id, lat=data['lat'], lng=data['lng'], route=data['route'])
        except (orjson.JSONDecodeError, ConnectionClosed):
            break

async def cleanup_zombie_buses(buses_dict):
    while True:
        now = time.time()
        zombie_ids = [bid for bid, b in buses_dict.items() if now - b.last_seen > 10]
        for bid in zombie_ids:
            del buses_dict[bid]
        await trio.sleep(5)

@click.command()
@click.option("--bus_port", default=8080)
@click.option("--browser_port", default=8000)
def main(bus_port, browser_port):
    async def run_server():
        async with trio.open_nursery() as nursery:
            nursery.start_soon(cleanup_zombie_buses, buses)
            nursery.start_soon(serve_websocket, partial(gate_for_buses, buses_dict=buses), '127.0.0.1', bus_port, None)
            nursery.start_soon(serve_websocket, partial(browser_proxy, buses_dict=buses), '127.0.0.1', browser_port, None)
            logger.info(f"Server started. Bus port: {bus_port}, Browser port: {browser_port}")

    async def browser_proxy(request, buses_dict):
        ws = await request.accept()
        bounds = WindowBounds()
        async with trio.open_nursery() as nursery:
            # Слушаем границы от браузера
            async def listen_bounds():
                while True:
                    try:
                        msg = await ws.get_message()
                        data = orjson.loads(msg)
                        if data.get("msgType") == "newBounds":
                            d = data["data"]
                            bounds.south_lat = d['southWest']['lat']
                            bounds.north_lat = d['northEast']['lat']
                            bounds.west_lng = d['southWest']['lng']
                            bounds.east_lng = d['northEast']['lng']
                    except Exception: break
            
            nursery.start_soon(listen_bounds)
            nursery.start_soon(talk_to_browser, ws, bounds, buses_dict)

    with suppress(KeyboardInterrupt):
        trio.run(run_server)

if __name__ == "__main__":
    main()
