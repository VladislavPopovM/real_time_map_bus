import trio
import json
import logging
import click
import time
from functools import partial
from contextlib import suppress
from dataclasses import dataclass, asdict, field
from collections import defaultdict
from trio_websocket import serve_websocket, ConnectionClosed

# Настройка логирования
logging.getLogger('trio-websocket').setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BusServer")

# --- Оптимизация: Сетчатый индекс ---
GRID_SIZE = 0.01 # Размер ячейки сетки (градусы)

def get_grid_pos(lat, lng):
    """Вычисляет координаты ячейки сетки."""
    return int(lat / GRID_SIZE), int(lng / GRID_SIZE)

# --- Модель данных ---

@dataclass
class Bus:
    busId: str
    lat: float
    lng: float
    route: str
    last_seen: float = field(default_factory=time.time)
    # Храним текущую ячейку, чтобы быстро переезжать
    grid_pos: tuple[int, int] = field(init=False)

    def __post_init__(self):
        self.grid_pos = get_grid_pos(self.lat, self.lng)

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

    def update(self, south_lat, north_lat, west_lng, east_lng):
        self.south_lat = south_lat
        self.north_lat = north_lat
        self.west_lng = west_lng
        self.east_lng = east_lng

# Глобальное состояние
buses = {}  # busId -> Bus
bus_grid = defaultdict(set)  # (grid_x, grid_y) -> {bus_id, ...}

# --- Вспомогательные функции ---

async def send_errors(ws, errors):
    msg = {"msgType": "Errors", "errors": errors}
    await ws.send_message(json.dumps(msg))

# --- Логика общения с браузером ---

async def listen_browser(ws, bounds):
    while True:
        try:
            message = await ws.get_message()
            msg_data = json.loads(message)
            if msg_data.get("msgType") == "newBounds":
                data = msg_data["data"]
                bounds.update(
                    south_lat=data['southWest']['lat'],
                    north_lat=data['northEast']['lat'],
                    west_lng=data['southWest']['lng'],
                    east_lng=data['northEast']['lng']
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        except ConnectionClosed:
            break

async def talk_to_browser(ws, bounds, buses_dict, grid):
    while True:
        visible_buses = []
        
        # ОПТИМИЗАЦИЯ: Вместо перебора ВСЕХ автобусов, берем только нужные ячейки
        if not all([bounds.south_lat, bounds.north_lat, bounds.west_lng, bounds.east_lng]):
            # Если границ нет, шлем пустой список или (как раньше) всё
            # Для производительности на 20к автобусах лучше слать пустой
            pass 
        else:
            min_x, min_y = get_grid_pos(bounds.south_lat, bounds.west_lng)
            max_x, max_y = get_grid_pos(bounds.north_lat, bounds.east_lng)
            
            # Проходим только по ячейкам, которые видит браузер
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    for bus_id in grid.get((x, y), set()):
                        bus = buses_dict.get(bus_id)
                        if bus and bounds.is_inside(bus.lat, bus.lng):
                            bus_data = asdict(bus)
                            del bus_data['last_seen']
                            del bus_data['grid_pos']
                            visible_buses.append(bus_data)
        
        payload = {"msgType": "Buses", "buses": visible_buses}
        try:
            await ws.send_message(json.dumps(payload))
        except ConnectionClosed:
            break
        await trio.sleep(1)

async def browser_proxy(request, buses_dict, grid):
    ws = await request.accept()
    bounds = WindowBounds()
    async with trio.open_nursery() as nursery:
        nursery.start_soon(listen_browser, ws, bounds)
        nursery.start_soon(talk_to_browser, ws, bounds, buses_dict, grid)

# --- Логика приема данных от автобусов ---

async def gate_for_buses(request, buses_dict, grid):
    ws = await request.accept()
    while True:
        try:
            message = await ws.get_message()
            data = json.loads(message)
            bus_id = data.get("busId")
            if not bus_id: continue

            new_lat, new_lng = data['lat'], data['lng']
            new_grid_pos = get_grid_pos(new_lat, new_lng)

            if bus_id in buses_dict:
                bus = buses_dict[bus_id]
                # ОПТИМИЗАЦИЯ: Если ячейка сменилась, переезжаем в индексе
                if bus.grid_pos != new_grid_pos:
                    grid[bus.grid_pos].discard(bus_id)
                    grid[new_grid_pos].add(bus_id)
                bus.lat, bus.lng = new_lat, new_lng
                bus.grid_pos = new_grid_pos
                bus.last_seen = time.time()
            else:
                # Новый автобус
                bus = Bus(**data)
                buses_dict[bus_id] = bus
                grid[bus.grid_pos].add(bus_id)

        except (json.JSONDecodeError, KeyError, TypeError, ConnectionClosed):
            break

async def cleanup_zombie_buses(buses_dict, grid):
    while True:
        now = time.time()
        zombie_ids = [bid for bid, b in buses_dict.items() if now - b.last_seen > 10]
        for bid in zombie_ids:
            bus = buses_dict.pop(bid)
            grid[bus.grid_pos].discard(bid)
            logger.debug(f"Removed zombie: {bid}")
        await trio.sleep(5)

# --- CLI ---

@click.command()
@click.option("--bus_port", default=8080)
@click.option("--browser_port", default=8000)
@click.option("-v", "--verbose", is_flag=True)
def main(bus_port, browser_port, verbose):
    if verbose: logger.setLevel(logging.DEBUG)
    
    async def run_server():
        async with trio.open_nursery() as nursery:
            nursery.start_soon(cleanup_zombie_buses, buses, bus_grid)
            nursery.start_soon(serve_websocket, partial(gate_for_buses, buses_dict=buses, grid=bus_grid), '127.0.0.1', bus_port, None)
            nursery.start_soon(serve_websocket, partial(browser_proxy, buses_dict=buses, grid=bus_grid), '127.0.0.1', browser_port, None)
            logger.info("Server optimized with Spatial Indexing.")

    with suppress(KeyboardInterrupt):
        trio.run(run_server)

if __name__ == "__main__":
    main()
