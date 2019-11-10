import argparse
import json
import asyncio
import websockets
import requests
from pathlib import Path

WORK_DIR = Path(__file__).parent


def read_config():
    try:
        with open(WORK_DIR / "config.json") as f:
            return json.load(f)
    except FileNotFoundError:
        print("Config file not found in", WORK_DIR)
        exit(1)
    except json.JSONDecodeError:
        print("Invalid config")
        exit(1)


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--apiUrl", help="API URL")
    parser.add_argument("--name", help="Extension name")
    parser.add_argument("--authToken", help="API session token")
    parser.add_argument("--settingsPath", help="Setting directory")
    parser.add_argument("--logPath", help="Log directory")
    parser.add_argument(
        "--debug", help="Enable debug mode", dest="debug", action="store_true"
    )
    parser.set_defaults(debug=False)
    return parser.parse_args()


args = get_args()
config = read_config()
blacklist = config["blacklist"]

heads = {"Authorization": args.authToken, "Content-Type": "application/json"}

transfer_start_lis = {
    "method": "POST",
    "path": "/transfers/listeners/transfer_starting",
}

api_url = "http://" + args.apiUrl

auth = {
    "method": "POST",
    "path": "/sessions/authorize",
    "callback_id": 1,
    "data": config["creds"],
}


def eprint(*text):
    print(*text)
    post_url = api_url + "events"
    message = {"text": " ".join(text), "severity": "info"}
    requests.post(post_url, json.dumps(message), headers=heads)


async def block(transfer_data, websocket):
    user_cid = transfer_data["user"]["cid"]
    transfer_id = transfer_data["id"]
    disconnect_transfer = {
        "method": "POST",
        "path": f"transfers/{transfer_id}/disconnect",
    }
    if user_cid in blacklist:
        eprint(
            "Blocked",
            transfer_data["user"]["nicks"],
            "from downloading",
            transfer_data["name"],
        )
        await websocket.send(json.dumps(disconnect_transfer))


async def main_loop():
    async with websockets.connect("ws://" + args.apiUrl) as websocket:
        await websocket.send(json.dumps(auth))
        await websocket.recv()

        await websocket.send(json.dumps(transfer_start_lis))

        while True:
            b = await websocket.recv()
            try:
                data = json.loads(b)["data"]
            except KeyError:
                eprint(b)
                continue
            else:
                await block(data, websocket)


event_loop = asyncio.get_event_loop()
event_loop.run_until_complete(main_loop())
