import trio
import json
from trio_websocket import open_websocket_url

async def get_error_message(ws):
    """Ждет и возвращает только сообщения об ошибках, пропуская обновления автобусов."""
    while True:
        message = await ws.get_message()
        data = json.loads(message)
        if data.get("msgType") == "Errors":
            return message

async def main():
    url = "ws://127.0.0.1:8000"
    async with open_websocket_url(url) as ws:
        # 1. Невалидный JSON
        await ws.send_message("not a json")
        resp = await get_error_message(ws)
        print(f"Response (invalid JSON): {resp}")

        # 2. Нет msgType
        await ws.send_message(json.dumps({"data": {}}))
        resp = await get_error_message(ws)
        print(f"Response (no msgType): {resp}")

        # 3. Неизвестный msgType
        await ws.send_message(json.dumps({"msgType": "killAllHumans"}))
        resp = await get_error_message(ws)
        print(f"Response (unknown type): {resp}")

if __name__ == "__main__":
    trio.run(main)
