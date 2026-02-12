import trio
import json
from trio_websocket import open_websocket_url

async def main():
    url = "ws://127.0.0.1:8080"
    async with open_websocket_url(url) as ws:
        # 1. Невалидный JSON
        await ws.send_message("I am not a bus")
        resp = await ws.get_message()
        print(f"Response (invalid JSON): {resp}")

        # 2. Нет busId
        await ws.send_message(json.dumps({"lat": 55.7, "lng": 37.6}))
        resp = await ws.get_message()
        print(f"Response (no busId): {resp}")

if __name__ == "__main__":
    trio.run(main)
