"""Interactive curses interface in the colours of the WebGUI PrTD theme."""
from __future__ import annotations

import curses
import locale
import threading
import time
from typing import Dict, List, Optional, Tuple

from nmb.tui import catalog, logs
from nmb.tui.catalog import Action, Tab
from nmb.tui.client import ApiClient, ApiError
from nmb.tui.logo import LOGO
from nmb.tui.render import to_lines

BLUE, PINK, TITLE, SELECTED, MUTED, ERROR = range(1, 7)
REFRESH_SEC = 5.0
SPLASH_SEC = 2.0
HEADER_LOGO_MIN_ROWS = 60  # Taller screens keep the logo above the menus.
LOG_VIEWS = {"/api/dev/logs": "dev", "/api/system/syslog": "system", "/api/dev/crashes": "crashes"}

TEXTS = {
    "en": ("Actions", "No actions on this screen", "Loading...", "Tab next subscreen  Left/Right screen  Up/Down select  PgUp/PgDn scroll  Enter run  r refresh  a auto  ? help  q quit",
           "Auto refresh", "on", "off", "Type {} to confirm", "Run", "Cancel", "blank = keep current value", "Saved to {}"),
    "hu": ("Műveletek", "Ezen a képernyőn nincs művelet", "Betöltés...", "Tab alfül  Bal/Jobb fül  Fel/Le választás  PgUp/PgDn görgetés  Enter futtatás  r frissítés  a auto  ? súgó  q kilépés",
           "Automatikus frissítés", "be", "ki", "A megerősítéshez írd be: {}", "Futtatás", "Mégse", "üres = marad a jelenlegi érték", "Mentve ide: {}"),
    "de": ("Aktionen", "Keine Aktionen auf dieser Seite", "Wird geladen...", "Tab Unterseite  Links/Rechts Seite  Auf/Ab Auswahl  PgUp/PgDn Scrollen  Enter Start  r Neu laden  a Auto  ? Hilfe  q Ende",
           "Automatisch aktualisieren", "ein", "aus", "Zum Bestätigen {} eingeben", "Start", "Abbrechen", "leer = aktueller Wert bleibt", "Gespeichert in {}"),
    "fr": ("Actions", "Aucune action sur cet écran", "Chargement...", "Tab sous-écran  Gauche/Droite écran  Haut/Bas choix  PgUp/PgDn défiler  Entrée lancer  r actualiser  a auto  ? aide  q quitter",
           "Actualisation auto", "oui", "non", "Saisissez {} pour confirmer", "Lancer", "Annuler", "vide = valeur actuelle conservée", "Enregistré dans {}"),
    "uk": ("Дії", "На цьому екрані немає дій", "Завантаження...", "Tab підекран  Вліво/Вправо екран  Вгору/Вниз вибір  PgUp/PgDn прокрутка  Enter запуск  r оновити  a авто  ? довідка  q вихід",
           "Автооновлення", "увімк", "вимк", "Введіть {} для підтвердження", "Запуск", "Скасувати", "порожньо = значення не зміниться", "Збережено в {}"),
}
ACTIONS, NO_ACTIONS, LOADING, KEYS, AUTO, ON, OFF, TYPE_CONFIRM, RUN, CANCEL, BLANK, SAVED = range(12)


def layout_tabs(labels: List[str], width: int) -> List[List[Tuple[int, int, int]]]:
    """Wrap labels into rows of (index, x, end_x) for drawing and for mouse clicks."""
    rows: List[List[Tuple[int, int, int]]] = [[]]
    x = 1
    for index, label in enumerate(labels):
        size = len(label) + 2
        if x + size > width - 1 and rows[-1]:
            rows.append([])
            x = 1
        rows[-1].append((index, x, x + size))
        x += size + 1
    return rows


class App:
    def __init__(self, stdscr, client: ApiClient, menu: List[Tab]):
        self.scr = stdscr
        self.client = client
        self.menu = menu
        self.tab = 0
        self.sub = 0
        self.sel = 0
        self.scroll = 0
        self.lines: List[str] = []
        self.message = ""
        self.message_error = False
        self.auto = False
        self.hits: List[Tuple[int, int, int, str, int]] = []  # y, x, end, kind, index
        self.cache: Dict[str, List[str]] = {}
        self.loaded_at = 0.0
        self.loading_key = ""
        self.lock = threading.Lock()
        self.lang = "en"
        self.translations: Dict[str, str] = {}
        self._load_language()

    def _load_language(self) -> None:
        try:
            lang = self.client.call("GET", "/api/i18n", timeout=5).get("lang") or "en"
            self.lang = lang if lang in TEXTS else "en"
            from nmb.web.i18n import TRANSLATIONS
            self.translations = TRANSLATIONS.get(self.lang, {})
        except (ApiError, ImportError):
            pass

    def tr(self, index: int) -> str:
        return TEXTS[self.lang][index]

    def label(self, i18n: str, fallback: str) -> str:
        return catalog.clean_label(self.translations.get(i18n, fallback)) or fallback

    @property
    def screen(self) -> catalog.Screen:
        tab = self.menu[self.tab]
        return tab.subs[self.sub] if tab.subs else tab.screen

    def put(self, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = self.scr.getmaxyx()
        if 0 <= y < height and 0 <= x < width:
            try:
                self.scr.addnstr(y, x, text, width - x - (1 if y == height - 1 else 0), attr)
            except curses.error:
                pass

    def color(self, pair: int) -> int:
        return curses.color_pair(pair) if curses.has_colors() else 0

    def refresh_data(self, force: bool = False) -> None:
        key = self.screen.key
        if not force and key in self.cache and not (self.auto and time.time() - self.loaded_at > REFRESH_SEC):
            with self.lock:
                self.lines = self.cache[key]
            return
        if self.loading_key == key:
            return
        self.loading_key = key
        screen = self.screen
        threading.Thread(target=self._fetch, args=(key, screen), daemon=True).start()

    def _fetch(self, key: str, screen: catalog.Screen) -> None:
        lines: List[str] = []
        for path in screen.views:
            lines.append(f"== {path} ==")
            try:
                source = LOG_VIEWS.get(path)
                if source:
                    # Newest first, because the top of the panel is what shows without scrolling.
                    lines += logs.read_lines(self.client, source, 500)[::-1]
                else:
                    lines += to_lines(self.client.call("GET", path))
            except ApiError as e:
                lines.append(str(e))
            lines.append("")
        with self.lock:
            self.cache[key] = lines
            self.loaded_at = time.time()
            self.loading_key = ""
            if self.screen.key == key:
                self.lines = lines

    def draw_logo(self, y: int, x: int) -> int:
        """Draw the three logo words in the PrTD blue, white and pink."""
        pairs = (self.color(BLUE), curses.A_BOLD, self.color(PINK))
        for row, text in enumerate(LOGO):
            self.put(y + row, x, text, pairs[min(row // 7, 2)] | curses.A_BOLD)
        return y + len(LOGO)

    def splash(self) -> None:
        """Show the logo at start; any key skips it, and a small window goes straight to the menu."""
        height, width = self.scr.getmaxyx()
        if width < len(LOGO[0]) - 1 or height < len(LOGO):
            return
        self.scr.erase()
        self.draw_logo(max(0, (height - len(LOGO)) // 2), max(0, (width - len(LOGO[0])) // 2))
        self.scr.refresh()
        self.scr.timeout(int(SPLASH_SEC * 1000))
        try:
            self.scr.get_wch()
        except curses.error:
            pass
        self.scr.timeout(250)

    def draw(self) -> None:
        self.scr.erase()
        self.hits = []
        height, width = self.scr.getmaxyx()
        y = 0
        if height >= HEADER_LOGO_MIN_ROWS and width >= len(LOGO[0]):
            y = self.draw_logo(0, 0)
        self.put(y, 0, " NetworkMeasureBox ".ljust(width), self.color(TITLE) | curses.A_BOLD)
        y += 1
        labels = [self.label(t.i18n, t.label) for t in self.menu]
        y = self._draw_row(y, labels, self.tab, "tab", width, BLUE)
        tab = self.menu[self.tab]
        if tab.subs:
            y = self._draw_row(y, [self.label(s.i18n, s.label) for s in tab.subs], self.sub, "sub", width, PINK)
        self.put(y, 0, "+" + "-" * (width - 2) + "+", self.color(BLUE))
        y += 1
        footer = height - 2
        actions = self.screen.actions
        narrow = width < 90
        panel = 0 if narrow else min(40, max(24, width // 3))
        top = y
        if narrow:
            shown = min(len(actions), max(0, (footer - top) // 2))
            start = max(0, self.sel - shown + 1)
            for row, index in enumerate(range(start, start + shown)):
                self._draw_action(top + row, 0, width, index)
            top += shown
            if shown:
                self.put(top, 0, "-" * width, self.color(BLUE))
                top += 1
            body_x, body_w = 0, width
        else:
            self.put(y, 1, self.tr(ACTIONS), self.color(PINK) | curses.A_BOLD)
            if not actions:
                self.put(y + 1, 1, self.tr(NO_ACTIONS), self.color(MUTED))
            start = max(0, self.sel - (footer - y - 2))
            for row, index in enumerate(range(start, len(actions))):
                if y + 1 + row >= footer:
                    break
                self._draw_action(y + 1 + row, 1, panel - 2, index)
            for row in range(y, footer):
                self.put(row, panel, "|", self.color(BLUE))
            body_x, body_w = panel + 2, width - panel - 3
        with self.lock:
            content = list(self.lines)
        if self.loading_key == self.screen.key and not content:
            content = [self.tr(LOADING)]
        self.body_rows = max(1, footer - top)
        self.max_scroll = max(0, len(content) - self.body_rows)
        self.scroll = min(self.scroll, self.max_scroll)
        for row, text in enumerate(content[self.scroll:self.scroll + self.body_rows]):
            attr = self.color(PINK) | curses.A_BOLD if text.startswith("==") else 0
            self.put(top + row, body_x, text[:body_w], attr)
        state = f"{self.tr(AUTO)}: {self.tr(ON) if self.auto else self.tr(OFF)}"
        self.put(footer, 0, (self.message or state)[:width - 1],
                 self.color(ERROR if self.message_error else BLUE) | curses.A_BOLD)
        self.put(height - 1, 0, self.tr(KEYS)[:width - 1], self.color(MUTED))
        self.scr.refresh()

    def _draw_row(self, y: int, labels: List[str], active: int, kind: str, width: int, pair: int) -> int:
        rows = layout_tabs(labels, width)
        # On a small screen the menus would leave no room for content, so keep the active row.
        if self.scr.getmaxyx()[0] < 30:
            rows = [row for row in rows if any(item[0] == active for item in row)]
        for row in rows:
            for index, x, end in row:
                attr = self.color(SELECTED) | curses.A_BOLD if index == active else self.color(pair)
                self.put(y, x, f"[{labels[index]}]", attr)
                self.hits.append((y, x, end, kind, index))
            y += 1
        return y

    def _draw_action(self, y: int, x: int, width: int, index: int) -> None:
        action = self.screen.actions[index]
        mark = "!" if action.confirm else " "
        attr = self.color(SELECTED) | curses.A_BOLD if index == self.sel else 0
        self.put(y, x, f"{mark} {action.label}"[:width].ljust(width), attr)
        self.hits.append((y, x, x + width, "action", index))

    def change_screen(self) -> None:
        self.sel = 0
        self.scroll = 0
        with self.lock:
            self.lines = self.cache.get(self.screen.key, [])
        self.refresh_data()

    def move_tab(self, step: int) -> None:
        self.tab = (self.tab + step) % len(self.menu)
        self.sub = 0
        self.change_screen()

    def move_sub(self, step: int) -> None:
        subs = self.menu[self.tab].subs
        if subs:
            self.sub = (self.sub + step) % len(subs)
            self.change_screen()
        else:
            self.move_tab(step)

    def form(self, action: Action) -> Optional[Dict[str, str]]:
        """Show a form; returns the values, or None when cancelled."""
        fields = list(action.fields)
        values = {f.name: "" for f in fields}
        confirm = ""
        pos = 0
        count = len(fields) + (1 if action.confirm else 0)
        self.scr.timeout(-1)
        try:
            return self._form_loop(action, fields, values, confirm, pos, count)
        finally:
            self.scr.timeout(250)

    def _form_loop(self, action, fields, values, confirm, pos, count) -> Optional[Dict[str, str]]:
        while True:
            self.scr.erase()
            hits = []
            height, width = self.scr.getmaxyx()
            self.put(0, 0, f" {action.label} ".ljust(width), self.color(TITLE) | curses.A_BOLD)
            self.put(1, 1, self.tr(BLANK), self.color(MUTED))
            first = max(0, pos - (height - 7))
            y = 2
            for index in range(first, count):
                if y >= height - 3:
                    break
                is_confirm = index == len(fields)
                name = self.tr(TYPE_CONFIRM).format(action.confirm) if is_confirm else fields[index].name
                text = confirm if is_confirm else values[name]
                hint = ""
                if not is_confirm and fields[index].kind == "choice":
                    hint = " (" + "/".join(fields[index].choices) + ", Space)"
                elif not is_confirm and fields[index].kind == "bool":
                    hint = " (yes/no, Space)"
                if not is_confirm and fields[index].kind == "secret":
                    text = "*" * len(text)
                attr = self.color(SELECTED) | curses.A_BOLD if index == pos else 0
                self.put(y, 1, f"{name}{hint}: {text}"[:width - 2].ljust(width - 2), attr)
                hits.append((y, index))
                y += 1
            buttons = f"[ F2 {self.tr(RUN)} ]"
            cancel = f"[ Esc {self.tr(CANCEL)} ]"
            self.put(height - 2, 1, buttons, self.color(PINK) | curses.A_BOLD)
            self.put(height - 2, 3 + len(buttons), cancel, self.color(BLUE))
            self.scr.refresh()
            key = self.scr.get_wch()
            if key == curses.KEY_RESIZE:
                continue
            if key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                except curses.error:
                    continue
                if my == height - 2 and 1 <= mx <= len(buttons):
                    key = curses.KEY_F2
                elif my == height - 2 and 3 + len(buttons) <= mx < 3 + len(buttons) + len(cancel):
                    return None
                else:
                    pos = next((i for row, i in hits if row == my), pos)
                    continue
            if key == "\x1b":
                return None
            if key in (curses.KEY_DOWN, "\t"):
                pos = (pos + 1) % max(1, count)
            elif key in (curses.KEY_UP, curses.KEY_BTAB):
                pos = (pos - 1) % max(1, count)
            elif key in ("\n", "\r", curses.KEY_ENTER, curses.KEY_F2):
                if key != curses.KEY_F2 and pos < count - 1:
                    pos += 1
                    continue
                if action.confirm and confirm != action.confirm:
                    pos = len(fields)
                    continue
                return values
            elif count == 0:
                continue
            elif pos == len(fields):
                if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    confirm = confirm[:-1]
                elif isinstance(key, str) and key.isprintable():
                    confirm += key
            else:
                field = fields[pos]
                current = values[field.name]
                if key == " " and field.kind in ("choice", "bool"):
                    options = field.choices if field.kind == "choice" else ("yes", "no")
                    values[field.name] = options[(options.index(current) + 1) % len(options)] if current in options else options[0]
                elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    values[field.name] = current[:-1]
                elif isinstance(key, str) and key.isprintable():
                    values[field.name] = current + key

    def run_action(self) -> None:
        actions = self.screen.actions
        if not actions:
            return
        action = actions[min(self.sel, len(actions) - 1)]
        values = self.form(action) if (action.fields or action.confirm) else {}
        if values is None:
            return
        try:
            body = catalog.build_body(action, values)
            if action.download:
                self.message = self.tr(SAVED).format(self.client.download(action.path, body))
                self.message_error = False
            else:
                answer = self.client.call(action.method, action.path, body, timeout=120)
                failed = answer.get("status") == "error" or answer.get("http_status", 200) >= 400
                self.message = str(answer.get("message") or answer.get("status") or f"HTTP {answer.get('http_status')}")
                self.message_error = failed
                with self.lock:
                    self.lines = [f"== {action.label} =="] + to_lines(answer) + [""] + self.lines
                self.scroll = 0
                return
        except (ApiError, ValueError) as e:
            self.message = str(e)
            self.message_error = True
        self.refresh_data(force=True)

    def click(self) -> None:
        try:
            _, x, y, _, state = curses.getmouse()
        except curses.error:
            return
        if state & curses.BUTTON4_PRESSED:
            self.scroll = max(0, self.scroll - 3)
            return
        if state & getattr(curses, "BUTTON5_PRESSED", 0x200000):
            self.scroll = min(self.max_scroll, self.scroll + 3)
            return
        for row, start, end, kind, index in self.hits:
            if row == y and start <= x < end:
                if kind == "tab":
                    self.tab, self.sub = index, 0
                    self.change_screen()
                elif kind == "sub":
                    self.sub = index
                    self.change_screen()
                else:
                    self.sel = index
                    self.run_action()
                return

    def help(self) -> None:
        self.scr.erase()
        lines = (LOGO + [""] if self.scr.getmaxyx()[0] >= len(LOGO) + 10 else ["NetworkMeasureBox", ""]) + [self.tr(KEYS), "",
                 "1-9 0: screens 1-10", "! = confirmation needed", "Mouse: click tabs and actions, wheel scrolls",
                 "", "JSON for scripts: nmb-cli menu | show | run | api"]
        for row, text in enumerate(lines):
            self.put(row, 1, text)
        self.scr.refresh()
        self.scr.timeout(-1)
        try:
            self.scr.get_wch()
        finally:
            self.scr.timeout(250)

    def loop(self) -> int:
        self.scr.timeout(250)
        self.refresh_data(force=True)
        self.splash()
        while True:
            self.draw()
            if self.auto:
                self.refresh_data()
            try:
                key = self.scr.get_wch()
            except curses.error:
                continue
            self.message = ""
            if key in ("q", "Q"):
                return 0
            if key == curses.KEY_MOUSE:
                self.click()
            elif key == curses.KEY_RIGHT:
                self.move_tab(1)
            elif key == curses.KEY_LEFT:
                self.move_tab(-1)
            elif key == "\t":
                self.move_sub(1)
            elif key == curses.KEY_BTAB:
                self.move_sub(-1)
            elif key == curses.KEY_DOWN:
                if self.screen.actions:
                    self.sel = min(self.sel + 1, len(self.screen.actions) - 1)
                else:
                    self.scroll = min(self.max_scroll, self.scroll + 1)
            elif key == curses.KEY_UP:
                if self.screen.actions:
                    self.sel = max(self.sel - 1, 0)
                else:
                    self.scroll = max(0, self.scroll - 1)
            elif key == curses.KEY_NPAGE:
                self.scroll = min(self.max_scroll, self.scroll + self.body_rows)
            elif key == curses.KEY_PPAGE:
                self.scroll = max(0, self.scroll - self.body_rows)
            elif key in ("\n", "\r", curses.KEY_ENTER):
                self.run_action()
            elif key == "r":
                self.refresh_data(force=True)
            elif key == "a":
                self.auto = not self.auto
            elif key == "?":
                self.help()
            elif isinstance(key, str) and key.isdigit():
                target = (int(key) - 1) % 10
                if target < len(self.menu):
                    self.tab, self.sub = target, 0
                    self.change_screen()


def _start(stdscr, client: ApiClient, menu: List[Tab]) -> int:
    curses.curs_set(0)
    curses.set_escdelay(25)
    curses.mousemask(curses.ALL_MOUSE_EVENTS)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        many = curses.COLORS >= 256
        blue = 117 if many else curses.COLOR_CYAN
        pink = 218 if many else curses.COLOR_MAGENTA
        white = 231 if many else curses.COLOR_WHITE
        muted = 250 if many else curses.COLOR_WHITE
        curses.init_pair(BLUE, blue, -1)
        curses.init_pair(PINK, pink, -1)
        curses.init_pair(TITLE, curses.COLOR_BLACK, blue)
        curses.init_pair(SELECTED, curses.COLOR_BLACK, pink)
        curses.init_pair(MUTED, muted, -1)
        curses.init_pair(ERROR, curses.COLOR_RED, -1)
    return App(stdscr, client, menu).loop()


def run_app(client: ApiClient, menu: List[Tab]) -> int:
    locale.setlocale(locale.LC_ALL, "")
    return curses.wrapper(_start, client, menu)
