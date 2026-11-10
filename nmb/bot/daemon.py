"""Main Telegram Bot daemon loop and proactive alert coordinator (nmb-telegram).
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from typing import Optional

from nmb.bot.alerts import AlertMonitor
from nmb.bot.client import TelegramClient
from nmb.bot.commands import CommandHandler
from nmb.config import Config, load_config

log = logging.getLogger("nmb.bot.daemon")

# Every command one of the bot's own inline buttons carries (commands.py, i18n.py). A callback with
# anything else is ignored: the client can put any text in callback_data.
CALLBACK_COMMANDS = frozenset({
    "/menu", "/status", "/test", "/test rtr", "/test ookla", "/test cloudflare", "/test fastcom",
    "/report", "/ping", "/tasks", "/tailscale", "/adblock", "/adblock on", "/adblock off",
    "/adblock update", "/vpn", "/vpn clients", "/wifi", "/wifi scan",
})


class TelegramDaemon:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.running = False
        self.client = TelegramClient(cfg.telegram.token)
        self.commands = CommandHandler(cfg, self.client)
        self.alerts = AlertMonitor(cfg, self.client)
        self.last_update_id: Optional[int] = None
        self._denied_at: dict = {}

    def handle_signal(self, signum: int, frame) -> None:
        if signum in (signal.SIGTERM, signal.SIGINT):
            log.info("received signal %d, stopping telegram daemon...", signum)
            self.running = False
            sys.exit(0)
        elif signum == signal.SIGHUP:
            log.info("received SIGHUP, reloading telegram daemon configuration")
            new_cfg = load_config()
            self.cfg = new_cfg
            self.client.token = new_cfg.telegram.token
            self.commands.cfg = new_cfg
            self.alerts.cfg = new_cfg
            self.alerts.recipients = new_cfg.telegram.allowed_chat_ids

    def _alert_loop(self) -> None:
        """Background thread executing periodic alert rule checks."""
        log.info("starting proactive alert monitor thread")
        while self.running:
            try:
                self.alerts.run_checks()
            except Exception as e:
                log.error("exception in alert loop: %s", e)
            for _ in range(15):
                if not self.running:
                    break
                time.sleep(1.0)

    # Updates older than this are dropped: after a reboot or an outage Telegram hands back the queued
    # commands (/kill <pid>, /reboot, /mode ...), and running them minutes or hours later is wrong.
    STALE_SEC = 120

    def _callback_allowed(self, data: str) -> bool:
        """Only the exact commands the bot's own buttons carry; callback_data is client-supplied."""
        from nmb.bot.i18n import LANG_INFO
        if data in CALLBACK_COMMANDS:
            return True
        parts = data.split()
        return len(parts) == 2 and parts[0] == "/lang" and parts[1] in LANG_INFO

    def is_authorized(self, chat: dict, sender: dict) -> bool:
        """The person, not just the chat. A private chat must be the listed user's own chat. A listed
        group needs the sender's own user id in the list too; otherwise every member was an admin."""
        allowed = set(self.cfg.telegram.allowed_chat_ids or [])
        chat_id = chat.get("id")
        user_id = sender.get("id") if isinstance(sender, dict) else None
        if not isinstance(chat_id, int) or not isinstance(user_id, int) or sender.get("is_bot"):
            return False
        if chat_id not in allowed or user_id not in allowed:
            return False
        if chat.get("type", "private") == "private":
            return chat_id == user_id
        return True

    def _deny(self, chat: dict, what: str) -> None:
        chat_id = chat.get("id")
        log.warning("rejected unauthorized %s from chat %s", what, chat_id)
        # Only a private chat is told its id (that is the setup hint), and at most every 10 minutes:
        # an allowed group's other members are ignored silently, and nobody can make the bot spam.
        if chat.get("type", "private") != "private" or not isinstance(chat_id, int):
            return
        now = time.monotonic()
        last = self._denied_at.get(chat_id)
        if last is not None and now - last < 600:
            return
        if len(self._denied_at) > 1000:
            self._denied_at.clear()
        self._denied_at[chat_id] = now
        self.client.send_message(
            chat_id,
            f"⛔ <b>Access Denied</b>: Chat ID <code>{chat_id}</code> is not authorized in /etc/nmb/nmb.conf."
        )

    def handle_update(self, u: dict) -> None:
        cb = u.get("callback_query")
        if cb:
            cb_id = cb.get("id")
            if cb_id:
                self.client.answer_callback_query(cb_id)
            sender = cb.get("from") or {}
            chat = (cb.get("message") or {}).get("chat") or {"id": sender.get("id"), "type": "private"}
            if not self.is_authorized(chat, sender):
                self._deny(chat, "callback")
                return
            data = cb.get("data") or ""
            if not self._callback_allowed(data):
                log.warning("ignored unknown button data %r", data[:64])
                return
            self._dispatch(chat["id"], data)
            return

        # Edited messages are not commands: editing an old message must not run it again.
        msg = u.get("message")
        if not msg:
            return
        chat = msg.get("chat") or {}
        text = msg.get("text", "")
        if not chat.get("id") or not text:
            return
        if not self.is_authorized(chat, msg.get("from") or {}):
            self._deny(chat, "message")
            return
        date = msg.get("date")
        if isinstance(date, (int, float)) and time.time() - date > self.STALE_SEC:
            log.warning("ignored a command sent %.0f s ago (queued while the bot was down)", time.time() - date)
            return
        self._dispatch(chat["id"], text)

    _LONG = ("/test", "/speedtest", "/speed")

    def _dispatch(self, chat_id: int, text: str) -> None:
        """Speed tests run in their own thread, so the bot keeps answering meanwhile (2026-11-09: it was
        silent for the whole test, several minutes with all engines)."""
        from nmb.bot.i18n import get_chat_lang, get_menu_aliases, t
        raw = (text or "").strip()
        alias = get_menu_aliases().get(raw.lower(), raw)
        cmd = alias.split()[0].lower().split("@")[0] if alias else ""
        if cmd not in self._LONG:
            self.commands.handle_command(chat_id, text)
            return
        if getattr(self, "_long_job", None) and self._long_job.is_alive():
            self.client.send_message(chat_id, "⏳ " + t("speed_already_running", get_chat_lang(chat_id, self.cfg)))
            return

        def job() -> None:
            try:
                self.commands.handle_command(chat_id, text)
            except Exception as e:
                log.warning("speed test command failed: %s", e)

        self._long_job = threading.Thread(target=job, daemon=True, name="telegram-speedtest")
        self._long_job.start()

    def run(self) -> None:
        if not self.cfg.telegram.token:
            log.error("cannot start telegram daemon: no bot token configured")
            return

        if not self.cfg.telegram.allowed_chat_ids:
            log.error(
                "cannot start telegram daemon: allowed_chat_ids is empty in configuration. "
                "Specify your authorized Telegram chat ID in /etc/nmb/nmb.conf to prevent unauthorized access."
            )
            return

        self.running = True
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self.handle_signal)

        # Write PID file for process reload
        pid_file = self.cfg.system.run_dir / "telegram.pid"
        try:
            self.cfg.system.run_dir.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(os.getpid()))
        except Exception as e:
            log.debug("could not write telegram.pid: %s", e)

        # Start background alert monitor
        alert_thread = threading.Thread(target=self._alert_loop, daemon=True)
        alert_thread.start()

        log.info("starting nmb-telegram long polling loop (authorized_chats=%s)",
                 self.cfg.telegram.allowed_chat_ids)

        backoff = 2.0
        while self.running:
            try:
                updates = self.client.get_updates(offset=self.last_update_id, timeout=5)
                backoff = 2.0  # reset on successful poll

                for u in updates:
                    up_id = u.get("update_id")
                    if up_id is not None:
                        self.last_update_id = up_id + 1
                    self.handle_update(u)

            except Exception as e:
                if self.running:
                    wait = max(backoff, float(getattr(e, "retry_after", 0) or 0))
                    log.warning("error in telegram polling loop: %s; retrying in %.1fs", e, wait)
                    time.sleep(wait)
                    backoff = min(60.0, backoff * 1.5)

        pid_file.unlink(missing_ok=True)
        log.info("nmb-telegram daemon shutdown complete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nmb-telegram", description="NetworkMeasureBox Telegram Bot Daemon")
    parser.add_argument("--config", "-c", help="Path to nmb.conf")
    parser.add_argument("--token", "-t", help="Telegram Bot API Token (overrides config)")
    parser.add_argument("--chat-id", type=int, help="Authorized chat ID (appends to config)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    cfg = load_config(args.config)
    if args.token:
        cfg.telegram.token = args.token
    if args.chat_id:
        if args.chat_id not in cfg.telegram.allowed_chat_ids:
            cfg.telegram.allowed_chat_ids.append(args.chat_id)

    if not cfg.telegram.token:
        print("Error: Telegram bot token not set. Configure in /etc/nmb/nmb.conf or pass --token.", file=sys.stderr)
        return 1

    if not cfg.telegram.allowed_chat_ids:
        print(
            "Error: allowed_chat_ids is empty in configuration. "
            "Configure allowed_chat_ids in /etc/nmb/nmb.conf or pass --chat-id to secure your bot.",
            file=sys.stderr
        )
        return 1

    daemon = TelegramDaemon(cfg)
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
