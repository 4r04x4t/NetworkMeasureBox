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


class TelegramDaemon:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.running = False
        self.client = TelegramClient(cfg.telegram.token)
        self.commands = CommandHandler(cfg, self.client)
        self.alerts = AlertMonitor(cfg, self.client)
        self.last_update_id: Optional[int] = None

    def handle_signal(self, signum: int, frame) -> None:
        if signum in (signal.SIGTERM, signal.SIGINT):
            log.info("received signal %d, stopping telegram daemon...", signum)
            self.running = False
        elif signum == signal.SIGHUP:
            log.info("received SIGHUP, reloading telegram daemon configuration")
            new_cfg = load_config()
            self.cfg = new_cfg
            self.client.token = new_cfg.telegram.token
            self.commands.cfg = new_cfg
            self.alerts.cfg = new_cfg

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
                updates = self.client.get_updates(offset=self.last_update_id, timeout=25)
                backoff = 2.0  # reset on successful poll

                for u in updates:
                    up_id = u.get("update_id")
                    if up_id is not None:
                        self.last_update_id = up_id + 1

                    msg = u.get("message") or u.get("edited_message")
                    if not msg:
                        continue

                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "")
                    if not chat_id or not text:
                        continue

                    # Strict Access Control
                    if chat_id not in self.cfg.telegram.allowed_chat_ids:
                        log.warning("rejected unauthorized message from chat_id %d", chat_id)
                        self.client.send_message(
                            chat_id,
                            f"⛔ <b>Access Denied</b>: Chat ID <code>{chat_id}</code> is not authorized in /etc/nmb/nmb.conf."
                        )
                        continue

                    self.commands.handle_command(chat_id, text)

            except Exception as e:
                if self.running:
                    log.warning("error in telegram polling loop: %s; retrying in %.1fs", e, backoff)
                    time.sleep(backoff)
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
