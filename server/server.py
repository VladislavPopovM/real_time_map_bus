import trio
import logging
import click
import time
import struct
import hashlib
from collections import defaultdict
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
    grid_key: tuple = field(default=None)

    def __post_init__(self):
        self.numeric_id = float(int(hashlib.md5(self.busId.encode()).hexdigest(), 16) % 1000000)
        try:
            self.numeric_route = float(self.route)
        except ValueError:
            self.numeric_route = 0.0

@dataclass
class WindowBounds:
# ... (existing code)
    def is_inside(self, lat: float, lng: float) -> bool:
        # Если границы не заданы, шлем всё (Шаг: Мгновенный старт)
        if not any([self.south_lat, self.north_lat, self.west_lng, self.east_lng]):
            return True
        return (self.south_lat <= lat <= self.north_lat) and \
               (self.west_lng <= lng <= self.east_lng)

buses = {} # Глобальная база автобусов
GRID_SIZE = 0.1
grid_index = defaultdict(set)

def get_grid_key(lat, lng):
    return int(lat / GRID_SIZE), int(lng / GRID_SIZE)

async def talk_to_browser(ws, bounds, buses_dict):
    """
    Высокоточная фильтрация через Spatial Index и бинарная отдача.
    """
    while True:
        try:
            visible_data = []
            
            # Если границы не заданы, перебираем всё (только при старте)
            if not any([bounds.south_lat, bounds.north_lat, bounds.west_lng, bounds.east_lng]):
                for bus in buses_dict.values():
                    visible_data.extend([bus.numeric_id, bus.lat, bus.lng, bus.numeric_route])
            else:
                # Spatial Optimization: перебираем только нужные ячейки сетки
                lat_start, lat_end = get_grid_key(bounds.south_lat, 0)[0], get_grid_key(bounds.north_lat, 0)[0]
                lng_start, lng_end = get_grid_key(0, bounds.west_lng)[1], get_grid_key(0, bounds.east_lng)[1]
                
                for lat_idx in range(lat_start, lat_end + 1):
                    for lng_idx in range(lng_start, lng_end + 1):
                        for bus_id in grid_index.get((lat_idx, lng_idx), []):
                            bus = buses_dict[bus_id]
                            if bounds.is_inside(bus.lat, bus.lng):
                                visible_data.extend([bus.numeric_id, bus.lat, bus.lng, bus.numeric_route])
            
            if visible_data:
                binary_packet = struct.pack(f"{len(visible_data)}f", *visible_data)
                await ws.send_message(binary_packet)
            
            await trio.sleep(0.1)
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

            lat, lng = data['lat'], data['lng']
            new_key = get_grid_key(lat, lng)

            if bus_id in buses_dict:
                bus = buses_dict[bus_id]
                # Обновляем индекс если автобус переехал в другую ячейку
                if bus.grid_key != new_key:
                    grid_index[bus.grid_key].discard(bus_id)
                    grid_index[new_key].add(bus_id)
                    bus.grid_key = new_key
                bus.lat, bus.lng = lat, lng
                bus.last_seen = time.time()
            else:
                bus = Bus(busId=bus_id, lat=lat, lng=lng, route=data['route'])
                bus.grid_key = new_key
                grid_index[new_key].add(bus_id)
                buses_dict[bus_id] = bus
        except (orjson.JSONDecodeError, ConnectionClosed, KeyError):
            break

async def cleanup_zombie_buses(buses_dict):
    while True:
        now = time.time()
        zombie_ids = [bid for bid, b in buses_dict.items() if now - b.last_seen > 10]
        for bid in zombie_ids:
            bus = buses_dict[bid]
            grid_index[bus.grid_key].discard(bid)
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
