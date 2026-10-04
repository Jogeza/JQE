"""Verify the configured bot's channel rights without printing its token."""
import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config.settings import settings


def call(method, payload):
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("Telegram bot token is not configured")
    request = Request(f"https://api.telegram.org/bot{token}/{method}",
                      data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as exc:
        result = json.loads(exc.read(4096))
    except URLError:
        raise RuntimeError("Telegram connection failed") from None
    if not result.get("ok"):
        raise RuntimeError(f"Telegram rejected {method}: {result.get('description', 'unknown error')}")
    return result["result"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-status", action="store_true")
    args = parser.parse_args()
    try:
        bot = call("getMe", {})
        chat = call("getChat", {"chat_id": "@jqetrading"})
        member = call("getChatMember", {"chat_id": chat["id"], "user_id": bot["id"]})
        can_post = member.get("status") == "creator" or (
            member.get("status") == "administrator" and member.get("can_post_messages") is True)
        print(json.dumps({"bot": bot.get("username"), "channel": chat.get("username"),
                          "status": member.get("status"), "can_post": can_post}))
        if not can_post:
            raise RuntimeError("Add this bot as channel administrator with Post Messages permission")
        if args.send_status:
            sent = call("sendMessage", {"chat_id": chat["id"], "text":
                "JQE monitoring is online at https://jqe.jokiholdings.com. "
                "This channel will receive verified guarded-demo trade alerts. "
                "Orders remain subject to strategy, risk and broker checks. "
                "Demo research only; no guaranteed returns."})
            print(json.dumps({"delivered": True, "message_id": sent["message_id"]}))
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
