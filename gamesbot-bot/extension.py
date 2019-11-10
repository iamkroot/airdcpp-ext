import argparse
import json
import asyncio
import websockets
import re
import requests
from pathlib import Path

WORK_DIR = Path(__file__).parent
WORDSET_FILE = WORK_DIR / 'words.json'
assert WORDSET_FILE.exists()


def read_config():
    try:
        with open(WORK_DIR / 'config.json') as f:
            return json.load(f)
    except FileNotFoundError:
        print("Config file not found in", WORK_DIR)
        exit(1)
    except json.JSONDecodeError:
        print("Invalid config")
        exit(1)


def get_wordset():
    with open(WORDSET_FILE) as f:
        return json.load(f)


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--apiUrl", help="API URL")
    parser.add_argument("--name", help="Extension name")
    parser.add_argument("--authToken", help="API session token")
    parser.add_argument("--settingsPath", help="Setting directory")
    parser.add_argument("--logPath", help="Log directory")
    return parser.parse_args()


args = get_args()
config = read_config()

heads = {
    'Authorization': args.authToken,
    'Content-Type': 'application/json'
}

api_url = 'http://' + args.apiUrl
games_bot_nick = '\u2022GamesBot\u2022'

PATTERNS = {
    'numbers':
        (r"Question [0-9]{1,2} of [0-9]{2}. Mathematics: What is ") +
        (r"(?P<num1>[0-9]{1,4}) (?P<op>[-+/x]{1}) (?P<num2>[0-9]{1,4}) ="),
    'anagrams':
        (r"Question [0-9]{1,2} of [0-9]{2}. The word is: ") +
        (r"(?P<anagram>[A-Z]{1}( [A-Z]){0,10}) ?"),
    'no_one':
        (r"No one got that. The correct answer is ") +
        (r"'(?P<new_word>[A-Z]{1,10})'"),
    'other_user':
        (r"(?P<nick>[a-zA-Z0-9 !@#$%^&*)(]{2,50}) got the correct answer ") +
        (r"'(?P<new_word>[A-Z]{1,10})' in [0-9]{1,3} seconds")
}

auth = {
    "method": "POST",
    "path": "/sessions/authorize",
    "callback_id": 1,
    "data": config['creds']
}

get_hub = {
    "method": "GET",
    "path": "/hubs",
    "callback_id": 2
}

set_lis = {
    "method": "POST",
    "path": "/hubs/{}/listeners/hub_message",
}


def eprint(text):
    print(text)
    post_url = api_url + 'events'
    message = {
        "text": str(text),
        "severity": 'info'
    }
    requests.post(post_url, json.dumps(message), headers=heads)


async def send_message(websocket, txt):
    eprint(f"Sending msg: {txt}")
    message = {
        "method": "POST",
        "path": "/hubs/chat_message",
        "callback_id": 3,
        "data": {
            "text": str(txt),
            "hub_urls": config["hub_urls"]
        }
    }
    await websocket.send(json.dumps(message))
    data = await websocket.recv()
    try:
        if json.loads(data)['sent'] != 1:
            eprint("Failed to send message")
    except (KeyError, json.JSONDecodeError):
        eprint("Error sending message.")


def update_dict(new_word):
    sorted_word = "".join(sorted(new_word))
    if sorted_word in word_anagrams:
        word_anagrams[sorted_word].append(new_word)
    else:
        word_anagrams[sorted_word] = [new_word]
    with open(WORDSET_FILE, 'w') as f:
        json.dump(word_anagrams, f, indent=4)


def solve_numbers(m):
    num1 = int(m.group('num1'))
    num2 = int(m.group('num2'))
    op = m.group('op')
    if op == '-':
        txt = str(num1 - num2)
    elif op == '+':
        txt = str(num1 + num2)
    elif op == '/':
        txt = str(int(num1 / num2))
    else:
        txt = str(num1 * num2)
    return txt


async def main_loop():
    async with websockets.connect('ws://' + args.apiUrl) as websocket:
        await websocket.send(json.dumps(auth))
        await websocket.recv()
        await websocket.send(json.dumps(get_hub))
        hubs = await websocket.recv()
        hub_id = json.loads(hubs)['data'][0]['id']

        # await websocket.send(json.dumps(outgoing_hook))
        # hook1 = await websocket.recv()

        set_lis['path'] = set_lis['path'].format(hub_id)
        await websocket.send(json.dumps(set_lis))

        while 1:
            b = await websocket.recv()
            eprint(b)
            try:
                data = json.loads(b)['data']
                msg = data['text']
            except KeyError:
                eprint(b)
                continue
            if data['from']['nick'] != games_bot_nick:
                continue

            txt_lst = []
            for name, pattern in PATTERNS.items():
                match = re.match(pattern, msg)
                if match:
                    break
            else:
                continue
            if name == 'numbers':
                txt_lst.append(solve_numbers(match))

            elif name == 'anagrams':
                anagram = match.group('anagram').replace(' ', '')
                try:
                    txt_lst = word_anagrams[''.join(sorted(anagram))]
                except KeyError:
                    eprint(b)

            elif name == 'no_one' or name == 'other_user':
                new_word = match.group('new_word')
                update_dict(new_word)
                msg = "New word learnt."
                if name == 'other_user':
                    nick = match.group('nick')
                    if nick == config["own_nick"]:
                        continue
                    msg += " Thanks " + nick
                await send_message(websocket, msg)

            for txt in txt_lst:
                await send_message(websocket, txt)


word_anagrams = get_wordset()
event_loop = asyncio.get_event_loop()
event_loop.run_until_complete(main_loop())
