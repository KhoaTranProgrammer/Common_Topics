#!/usr/bin/env python3
"""
pgn_explainer.py - Explain a PGN chess file step by step, starting with @
spoiler-free introduction (event, players, date, round, short summary), with a chatty,
slightly sarcastic human commentator. Supports English and Vietnamese

Giai thich file PGN cB vua timg budc, kém binh lugn vién hai huic.

Usage:

python pgn_explainer.py # sample game, English
python pgn_explainer.py --lang vi # sample game, Vietnamese
python pgn_explainer.py game.pgn --lang vi 8 your file, Vietnamese
python pgn_explainer.py game.pgn -g 3 # 3rd game in the file
python pgn_explainer.py game.pgn --board @ draw board after each move
Python pgn_explainer.py game.pgn --step # press Enter between moves
python pgn_explainer.py game.pgn --seed 7 # same jokes every run
python pgn_explainer.py game.pgn --serious # no jokes, only facts
python pgn_explainer.py game.pgn --no-intro # skip the game introduction
python pgn_explainer.py game.pgn --summary-words 80 @ longer introduction summary
python pgn_explainer.py game.pgn --audio out.mp3 # read the comments aloud (gTTS)
Python pgn_explainer.py @ame.pgn -1 vi --audio auto --audio-content narration
python pgn_explainer.py game.pgn --audio clips --audio-split # one MP3 per step in clips/
python pgn_explainer.py game.pgn -o out.txt # save to a file
python pgn_explainer.py Game.pgn -o auto # save as game_explained_en.txt
python pgn_explainer.py @ame.pgn -o out.txt --tee # save AND show on screen
python pgn_explainer.py game.pgn -o out.txt --append @ add to an existing file
python pgn_explainer.py games.pgn --all -1 vi -o all.txt # every game in the file

Languages: the texts live in lang/en.json and lang/vi.json (next to this script).
            Edit them, or add lang/<code>.json for a new language; --lang-dir DIR uses another folder.

Requires: pip install chess (and, only for --audio: pip install gts)
"""
import argparse
import contextlib
from email.mime import text
import json
from operator import index
from operator import index
import os
import random
from struct import pack
import sys
import re
import textwrap
from typing import Self
from wsgiref import headers
import chess
import chess.pgn
import io

SAMPLE_PGN = """[Event "Casual Game"]
[Site "Online"]
[Date "2024.05.12"]
[Round "1"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]
[WhiteElo "1500"]
[BlackElo "1480"]
[ECO "C20"]
[TimeControl "600"]
[Termination "Normal"]
1. e4 eS 2. Bc4 Nc6 3. QhS {White eyes the weak f7 square} 3... NF6?? 4. Qxf7# 1-0
"""

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9}

# ======================================================== #
# LANGUAGE DATA (lang/*.json - one file per language)
# ======================================================== #
# Every file holds all the texts of one language: piece names, interface strings,
# explanations, jokes ... To add a language, copy lang/en.json, translate it and save
# it as e.g. lang/fr.json - it appears automatically in *--lang™ .
# JSON cannot hold python objects, so a few parts are stored in a simple form and
# converted when the file is loaded (see _convert_pack):
#   "pieces":     {"pawn": "...", "knight": "...", ...} -> keys become chess constants
#   "sides":      {"white": "...", "black": "..."}      -> keys become chess.WHITE/BLACK
#   "step_quips": {"1": "...", ...}                     -> keys become integers
#   "meta":       {"code": "en", "name": "English", "tts": "en"} (tts = gITS voice code)
LANG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang")

PIECE_KEYS = {"pawn": chess.PAWN, "knight": chess.KNIGHT, "bishop": chess.BISHOP,
              "rook": chess.ROOK, "queen": chess.QUEEN, "king": chess.KING}
REQUIRED_KEYS = ("pieces", "sides", "months", "nouns", "eco_family", "eco_flavor",
                 "speak_subs", "ui", "tag_help", "tag_quips", "syntax_help",
                 "step_quips", "pools")

class LanguageError(Exception):
    """A language file is missing, unreadable or incomplete."""

def _convert_pack(pack, source):
    missing = [key for key in REQUIRED_KEYS if key not in pack]
    if missing:
        raise LanguageError(f"{source}: missing keys: {', '.join(missing)}")

    names = ", ".join(PIECE_KEYS)
    unknown = [name for name in pack["pieces"] if name not in PIECE_KEYS]
    if unknown or len(pack["pieces"]) != len(PIECE_KEYS):
        raise LanguageError(f"{source}: 'pieces' must have exactly these keys: {names}"
                            + (f" (unknown: {', '.join(unknown)})" if unknown else ""))
    if not all(side in pack["sides"] for side in ("white", "black")):
        raise LanguageError(f"{source}: 'sides' needs the keys 'white' and 'black'")
    if len(pack["months"]) != 12:
        raise LanguageError(f"{source}: 'months' must contain 12 names")
    if not all(str(number).isdigit() for number in pack["step_quips"]):
        raise LanguageError(f"{source}: 'step_quips' keys must be numbers (\"1\" to \"5\")")

    pack["pieces"] = {PIECE_KEYS[name]: text for name, text in pack["pieces"].items()}
    pack["sides"] = {chess.WHITE: pack["sides"]["white"], chess.BLACK: pack["sides"]["black"]}
    pack["step_quips"] = {int(number): text for number, text in pack["step_quips"].items()}
    return pack

def load_languages(directory=None):
    """Read every *.json file in "directory (default: ./lang next to this script)
    and return {code: pack}. Texts missing from a translation are taken from the
    English file, so a partly translated language still works."""
    directory = directory or LANG_DIR
    if not os.path.isdir(directory):
        raise LanguageError(f"language folder not found: {directory}")
    packs = {}
    for filename in sorted(os.listdir(directory)):
        if not filename.lower().endswith(".json"):
            continue
        path = os.path.join(directory, filename)
        try:
            with open(path, encoding="utf-8") as handle:
                pack = json.load(handle)
        except (OSError, ValueError) as e:
            raise LanguageError(f"{path}: {e}")
        code = pack.get("meta", {}).get("code") or os.path.splitext(filename)[0]
        packs[code] = _convert_pack(pack, path)
    if not packs:
        raise LanguageError(f"no .json language files in {directory}")

    base = packs.get("en")
    if base:
        for code, pack in packs.items():
            if code == "en":
                continue
            for part in ("ui", "tag_help", "tag_quips", "step_quips", "pools"):
                for key, value in base[part].items():
                    pack[part].setdefault(key, value)

    return packs

LANGS = {}
try:    # default folder; main() reloads it (and reports errors)
    LANGS.update(load_languages())
except LanguageError:
    pass

# language helper
# -------------------------------------------------------------------------- #
class Lang:
    """Access the texts of a language pack, with fallbacks to English and hardcoded defaults."""

    def __init__(self, code):
        pack = LANGS[code]
        self.code = code
        self.tts = pack.get("meta", {}).get("tts", code)
        self.ui = pack["ui"]
        self.tag_help = pack["tag_help"]
        self.tag_quips = pack["tag_quips"]
        self.syntax_help = pack["syntax_help"]
        self.step_quips = pack["step_quips"]
        self.pools = pack["pools"]
        self.months = pack["months"]
        self.nouns = pack["nouns"]
        self.eco_family = pack["eco_family"]
        self.eco_flavor = pack["eco_flavor"]
        self.speak_subs = pack["speak_subs"]
        self._pieces = pack["pieces"]
        self._sides = pack["sides"]

    def piece(self, piece_type):
        return self._pieces[piece_type]

    def side(self, color):
        return self._sides[color]

    def count(self, key, n):
        one, many = self.nouns[key]
        return f"{n} {one if n == 1 else many}"

CENTER_SQUARES = {chess.D4, chess.E4, chess.D5, chess.E5}

QUIET_BY_PIECE = {
    chess.KNIGHT: "quiet_knight",
    chess.BISHOP: "quiet_bishop",
    chess.ROOK: "quiet_rook",
    chess.QUEEN: "quiet_queen",
    chess.PAWN: "quiet_pawn",
}

class Bag:
    """Shuffle-bag: ce tees cet ee ee ee eee
    and never repeats the last line when the bag refills."""

    def _init__(self, items, rng):
        self.items = list(items)
        self.rng = rng
        self.queue = []
        self.last = None

    def draw(self):
        if not self.queue:
            self.queue = self.items[:]
            self.rng.shuffle(self.queue)
            if len(self.queue) > 1 and self.queue[-1] == self.last:
                self.queue[0], self.queue[-1] = self.queue[-1], self.queue[0]
        self.last = self.queue.pop()
        return self.last

class Commentator:
    """Random, context-aware commentator.

    Variety comes from five layers:
    1. big pools of lines per situation, drawn from shuffle-bags
       (no line returns until all the others have been used);
    2. piece-specific lines for quiet moves (knight, bishop, rook ...);
    3. random interjections before / after the main line ("spice");
    4. context remarks: repeated piece, trade streaks, centre, retreat,
       game phase, move milestones, first capture ...;
    5. placeholders for names, squares, pieces and sides.
    Pools that a language does not define are simply skipped.
    """

    def __init__(self, T, seed=None, enabled=True):
        self.T = T
        self.rng = random.Random(seed)
        self.enabled = enabled
        self.bags = {}
        self.last_sq = {chess.WHITE: None, chess.BLACK: None}
        self.cap_streak = 0
        self.check_streak = 0
        self.seen_capture = False
        self.said_middle = False
        self.said_end = False

    # ------------------------------------------------------------------------ #
    def pick(self, key, **kw):
        pool = self.T.pools.get(key)
        if not pool:
            return None
        bag = self.bags.get(key)
        if bag is None:
            bag = self.bags[key] = Bag(pool, self.rng)
        return bag.draw().format(**kw)

    def chance(self, p):
        return self.rng.random() < p

    @staticmethod
    def _add(lines, text):
        if text:
            lines.append(text)

    def spice(self, text, mood, kw):
        """Randomly wrap a line with an interjection and/or a closing remark."""
        pre = self.pick("pre_" + mood, **kw) if self.chance(0.28) else None
        post = self.pick("post_" + mood, **kw) if self.chance(0.28) else None
        return " ".join(part for part in (pre, text, post) if part)

    def step_quip(self, n):
        return self.T.step_quips[n] if self.enabled else None

    def tag_quip(self, key):
        return self.T.tag_quips.get(key) if self.enabled else None

    def intro_quip(self):
        return self.pick("intro_quip") if self.enabled else None

    # ---- per-move commentary -------------------- 2-02 eee eee e nen ecenee #
    def for_move(self, before, move, after, ply, nags, names):
        """Commentary lines for one half-move.
        `before` = board before the move, `after` = board after it."""
        if not self.enabled:
            return []

        T = self.T
        mover = before.turn
        piece = before.piece_at(move.from_square)
        ptype = piece.piece_type
        is_cap = before.is_capture(move)
        kw = dict(
            who=names[mover], opp=names[not mover],
            side=T.side(mover), opp_side=T.side(not mover),
            piece=T.piece(ptype), Piece=T.piece(ptype).capitalize(),
            to=chess.square_name(move.to_square),
            frm=chess.square_name(move.from_square),
            captured="?", promo="?", num=before.fullmove_number, amount=0,
        )

        # state used by the "context" remarks
        repeated = self.last_sq[mover] == move.from_square
        self.last_sq[mover] = move.to_square
        self.cap_streak = self.cap_streak + 1 if is_cap else 0
        self.check_streak = self.check_streak + 1 if after.is_check() else 0

        lines = []
        if ply == 1:
            self._add(lines, self.pick("game_start", **kw))

        # ---- the main line: first matching situation wins ----
        mood = "calm"
        if after.is_checkmate():
            key, mood = "mate", "big"
        elif after.is_stalemate():
            key, mood = "stalemate", "big"
        elif move.promotion:
            kw["promo"] = T.piece(move.promotion)
            key, mood = "promotion", "action"
        elif before.is_castling(move):
            key = "castle_k" if before.is_kingside_castling(move) else "castle_q"
            mood = "action"
        elif before.is_en_passant(move):
            key, mood = "en_passant", "action"
        elif is_cap:
            cap = before.piece_at(move.to_square)
            kw["captured"] = T.piece(cap.piece_type)
            key = {chess.PAWN: "cap_pawn", chess.QUEEN: "cap_queen",
                   chess.ROOK: "cap_rook"}.get(cap.piece_type, "cap_minor")
            mood = "big" if cap.piece_type == chess.QUEEN else "action"
        elif ptype == chess.QUEEN and before.fullmove_number <= 5:
            key = "queen_early"
        elif ptype == chess.KNIGHT and chess.square_file(move.to_square) in (0, 7):
            key = "knight_rim"
        elif ptype == chess.KING:
            key = "king_walk"
        elif ptype == chess.PAWN and before.fullmove_number <= 6:
            key = "pawn_open"
        elif ptype in (chess.KNIGHT, chess.BISHOP) and before.fullmove_number <= 10:
            key = "develop"
        else:
            by_piece = QUIET_BY_PIECE.get(ptype)
            key = by_piece if (by_piece in T.pools and self.chance(0.75)) else "quiet"

        main = self.pick(key, **kw)
        self._add(lines, self.spice(main, mood, kw))

        # ---- extras (skipped on checkmate to keep the finale clean) ----
        if not after.is_checkmate():
            if is_cap and not self.seen_capture:
                self.seen_capture = True
                self._add(lines, self.pick("first_blood", **kw))

            n_pieces = len(after.piece_map())
            if not self.said_end and n_pieces <= 12:
                self.said_end = self.said_middle = True
                self._add(lines, self.pick("phase_end", **kw))
            elif (not self.said_middle and mover == chess.WHITE
                  and before.fullmove_number >= 11):
                self.said_middle = True
                self._add(lines, self.pick("phase_middle", **kw))

            if after.is_check():
                self._add(lines, self.pick("check", **kw))

            gain = self._balance(after, mover) - self._balance(before, mover)
            if gain >= 3:
                kw["amount"] = gain
                self._add(lines, self.pick("swing", **kw))

            if len(lines) < 3 and self.chance(0.5):
                cand = []
                if repeated:
                    cand.append("repeat_piece")
                if self.cap_streak >= 2:
                    cand.append("trade_streak")
                if self.check_streak >= 2:
                    cand.append("check_streak")
                if mover == chess.WHITE and before.fullmove_number in (10, 20, 30, 40, 50, 60):
                    cand.append("milestone")
                if ply >= 80 and ply % 10 == 0:
                    cand.append("long_game")
                if (not is_cap and move.to_square in CENTER_SQUARES
                    and ptype != chess.KING):
                    cand.append("center")
                r_from = chess.square_rank(move.from_square)
                r_to = chess.square_rank(move.to_square)
                backward = r_to < r_from if mover == chess.WHITE else r_to > r_from
                if backward and not is_cap and ptype not in (chess.PAWN, chess.KING):
                    cand.append("retreat")
                cand = [c for c in cand if c in T.pools]
                if cand:
                    self._add(lines, self.pick(self.rng.choice(cand), **kw))

        # ---- the annotator's marks ----
        for nag, nkey in ((4, "nag_blunder"), (2, "nag_mistake"), (6, "nag_mistake"),
                        (1, "nag_good"), (3, "nag_brilliant"), (5, "nag_interesting")):
            if nag in nags:
                self._add(lines, self.pick(nkey, **kw))
                break
        return lines

    def ending(self, result, names):
        if not self.enabled:
            return None
        key = {"1-0": "end_white", "0-1": "end_black", "1/2-1/2": "end_draw"}.get(result, "end_none")
        return self.pick(key, white=names[chess.WHITE], black=names[chess.BLACK])

    @staticmethod
    def _balance(board, color):
        return material(board, color) - material(board, not color)

# ------------------------- #
# helpers
# ------------------------- #

def title(text, quip=None):
    print("\n" + "=" * 64)
    print(text)
    print("=" * 64)
    if quip:
        print(f"\"{quip}\"")

def material(board, color):
    return sum(len(board.pieces(pt, color)) * v for pt, v in PIECE_VALUES.items())

def player_names(game, T):
    return {chess.WHITE: game.headers.get("White", T.side(chess.WHITE)),
            chess.BLACK: game.headers.get("Black", T.side(chess.BLACK))}

def describe_move(board, move, T):
    """Plain-language description of "move" (board = position BEFORE the move)."""
    ui = T.ui
    piece = board.piece_at(move.from_square)
    who = T.side(board.turn)
    frm = chess.square_name(move.from_square)
    to = chess.square_name(move.to_square)

    if board.is_castling(move):
        wing = ui["wing_k"] if board.is_kingside_castling(move) else ui["wing_q"]
        return ui["castle"].format(who=who, wing=wing)

    text = ui["move"].format(who=who, piece=T.piece(piece.piece_type), frm=frm, to=to)

    if board.is_en_passant(move):
        text += ui["ep"]
    elif board.is_capture(move):
        captured = board.piece_at(move.to_square)
        text += ui["cap"].format(captured=T.piece(captured.piece_type))

    if move.promotion:
        text += ui["promo"].format(promo=T.piece(move.promotion))

    return text + "."

def describe_result_of_move(board_after, T):
    ui = T.ui
    notes = []

    if board_after.is_checkmate():
        notes.append(ui["n_mate"])
    elif board_after.is_check():
        notes.append(ui["n_check"].format(side=T.side(board_after.turn)))
    if board_after.is_stalemate():
        notes.append(ui["n_stale"])
    if board_after.is_insufficient_material():
        notes.append(ui["n_insuf"])
    return notes

def clean(value):
    """Return a stripped header value, or None if it is empty / unknown."""
    v = (value or "").strip()
    return None if v in ("", "?", "??", "-", "????.??.??") else v

def format_date(raw, T):
    """'2024.05.12' -> '12 May 2024' (or the Vietnamese form); None if unknown."""
    parts = (raw or "").split(".")
    if len(parts) != 3:
        return None
    y, m, d = (int(p) if p.isdigit() else None for p in parts)
    if not y:
        return None
    if m is not None and not 1 <= m <= 12:
        m = d = None
    if d is not None and not 1 <= d <= 31:
        d = None
    if m is None:
        return T.ui["date_y"].format(y=y)
    if d is None:
        return T.ui["date_my"].format(m=T.months[m - 1], y=y)
    return T.ui["date_full"].format(d=d, m=T.months[m - 1], y=y)

def format_time_control(raw, T):
    """'600' -> '16 min’, '180+2' -> "3 min + 2 s per move'; unknown formats pass through."""
    raw = clean(raw)
    if not raw:
        return None
    found = re.fullmatch(r"(\d+)(?:\+(\d+))?", raw)
    if not found:
        return raw
    base, inc = int(found.group(1)), found.group(2)
    text = (T.ui["tc_min"].format(n=base // 60) if base % 60 == 0
            else T.ui["tc_sec"].format(n=base))
    if inc:
        text += " + " + T.ui["tc_inc"].format(n=int(inc))
    return text

def time_control_seconds(raw):
    """Rough game length in seconds (base + 40 moves of increment), or None."""
    raw = clean(raw)
    found = re.fullmatch(r"(\d+)(?:\+(\d+))?", raw) if raw else None
    if not found:
        return None
    return int(found.group(1)) + 40 * int(found.group(2) or 0)


def game_stats(game):
    """Spoiler-free numbers about the game (never looks at the result)."""
    board = game.board()
    st = {"plies": 0, "captures": 0, "checks": 0, "promotions": 0,
          "castles": {chess.WHITE: 0, chess.BLACK: 0},
          "queens_at_start": False, "queens_off": False}
    st["queens_at_start"] = bool(len(board.pieces(chess.QUEEN, chess.WHITE)) or
                                 len(board.pieces(chess.QUEEN, chess.BLACK)))
    for move in game.mainline_moves():
        st["plies"] += 1
        mover = board.turn
        if board.is_capture(move):
            st["captures"] += 1
        if board.is_castling(move):
            st["castles"][mover] += 1
        if move.promotion:
            st["promotions"] += 1
        gives_check = board.gives_check(move)
        board.push(move)
        if gives_check:
            st["checks"] += 1
        if (st["queens_at_start"] and not st["queens_off"]
                and not len(board.pieces(chess.QUEEN, chess.WHITE))
                and not len(board.pieces(chess.QUEEN, chess.BLACK))):
            st["queens_off"] = True
    return st

def fit_summary(core_options, topics, budget):
    """Choose the sentences of the summary so that it fits "budget* words.

    core_options: alternatives for the opening sentence (exactly one is used).

    : ({(importance, [alternative sentences...}), ...] in reading order;
    | | at most one alternative per topic is used, and a topic may be skipped.
    Rule: cover as many important topics as possible first (short alternatives make
    room), then use longer alternatives to get as close to "budget* words as possible.
    """

    def wc(text):
        return len(text.split())
    
    dp = {} # words used -> (score, sentences)
    for option in core_options:
        if wc(option) <= budget:
            dp.setdefault(wc(option), (0, [option]))
    if not dp: # even the shortest core is too long
        shortest = min(core_options, key=wc)
        return [shortest]

    for weight, options in topics:
        new = dict(dp) # skipping the topic is always allowed
        for words, (score, picks) in dp.items():
            for option in options:
                total = words + wc(option)
                if total <= budget and (total not in new or score + weight > new[total][0]):
                    new[total] = (score + weight, picks + [option])

        dp = new

    best = max(dp.items(), key=lambda item: item[1][0] * 1000 + item[0])
    return best[1][1]

def build_summary(game, st, T, budget=50):
    """Build a spoiler-free summary of the game (event, players, date, round, short summary)."""
    ui, h = T.ui, game.headers
    names = player_names(game, T)
    white, black = names[chess.WHITE], names[chess.BLACK]

    # ---- opening sentence: who Plays whom, where and when (longest variant that fits) --..
    event, rnd = clean(h.get("Event")), clean(h.get("Round"))
    site = clean(h.get("Site"))
    date = format_date(h.get("Date"), T)
    date_key = "f_date_y" if date and date.isdigit() else "f_date"

    def core(use_event, use_round, use_date, use_site):
        return ui["sum_main"].format(
            white=white, black=black,
            event=ui["f_event"].format(event=event) if use_event and event else "",
            round=ui["f_round"].format(round=rnd) if use_round and rnd else "",
            date=ui[date_key].format(date=date) if use_date and date else "",
            site=ui["f_site"].format(site=site) if use_site and site else "")

    core_options = list(dict.fromkeys([
        core(1, 1, 1, 1), core(1, 1, 1, 0), core(1, 0, 1, 0),
        core(1, 0, 0, 0), core(0, 0, 0, 0)]))

    topics = []  # (importance, [long form, short form}) in reading order

    # ---- time control ----
    secs = time_control_seconds(h.get("TimeControl"))
    if secs is not None:
        kind = ("bullet" if secs < 180 else "blitz" if secs < 480
                else "rapid" if secs < 1500 else "classical")
        topics.append((8, [ui["sum_tc_" + kind], ui["sum_kind"].format(kind=ui["kind_" + kind])]))

    # ---- players ----
    we, be = clean(h.get("WhiteElo")), clean(h.get("BlackElo"))
    if we and be and we.isdigit() and be.isdigit():
        w_elo, b_elo = int(we), int(be)
        avg = (w_elo + b_elo) // 2
        level = 1 if avg < 1200 else 2 if avg < 1800 else 3 if avg < 2200 else 4 if avg < 2500 else 5
        topics.append((7, [ui["sum_level"].format(avg=avg, level=ui[f"lvl_{level}"]),
                            ui["sum_level_s"].format(avg=avg)]))
        gap = abs(w_elo - b_elo)
        fav, other = (white, black) if w_elo >= b_elo else (black, white)
        band = "eq" if gap <= 30 else "small" if gap <= 100 else "clear" if gap <= 250 else "big"
        fmt = dict(white=white, black=black, name=fav, other=other, diff=gap)
        topics.append((9, [ui[f"sum_gap_{band}"].format(**fmt),
                    ui[f"sum_gap_{band}_s"].format(**fmt)]))

    # ---- opening ----
    opening, eco = clean(h.get("Opening")), clean(h.get("ECO"))
    letter = eco[0].upper() if eco else None
    family = T.eco_family.get(letter)
    if opening and eco and family:
        topics.append((10, [ui["sum_opening_full"].format(opening=opening, eco=eco, family=family),
                            ui["sum_opening_s_full"].format(opening=opening, eco=eco)]))
    elif opening:
        topics.append((10, [ui["sum_opening_name"].format(opening=opening),
                            ui["sum_opening_s_name"].format(opening=opening)]))
    elif eco and family:
        topics.append((10, [ui["sum_opening_eco"].format(eco=eco, family=family),
                            ui["sum_opening_s_eco"].format(eco=eco, family=family)]))
    if family and letter in T.eco_flavor:
        topics.append((3, [T.eco_flavor[letter]]))

    # ---- character of the game ----
    if st["plies"] == 0:
        topics.append((8, [ui["sum_empty"]]))
    else:
        full_moves = (st["plies"] + 1) // 2
        size = "short" if full_moves <= 20 else "medium" if full_moves <= 50 else "long"
        topics.append((7, [ui[f"sum_len_{size}"], ui["sum_len_s"].format(len=ui[f"len_{size}"])]))

        ratio = st["captures"] / st["plies"]
        band = "low" if ratio < 0.12 else "mid" if ratio < 0.30 else "high"
        topics.append((7, [ui[f"sum_cap_{band}"], ui[f"sum_cap_{band}_s"]]))
        if st["checks"] >= 4:
            topics.append((4, [ui["sum_checks"], ui["sum_checks_s"]]))

        cw, cb = st["castles"][chess.WHITE], st["castles"][chess.BLACK]
        side = T.side(chess.WHITE if cw else chess.BLACK)
        band = "both" if cw and cb else "one" if cw or cb else "none"
        topics.append((6, [ui[f"sum_castle_{band}"].format(side=side),
                            ui[f"sum_castle_{band}_s"].format(side=side)]))

        if st["queens_off"]:
            topics.append((6, [ui["sum_queens_off"], ui["sum_queens_off_s"]]))
        elif st["queens_at_start"] and full_moves >= 30:
            topics.append((6, [ui["sum_queens_on"], ui["sum_queens_on_s"]]))
        if st["promotions"]:
            band = "one" if st["promotions"] == 1 else "many"
            topics.append((5, [ui[f"sum_promo_{band}"].format(n=st["promotions"]),
                            ui[f"sum_promo_{band}_s"].format(n=st["promotions"])]))

    topics.append((5, [ui["sum_tail"], ui["sum_tail_s"]]))
    return fit_summary(core_options, topics, budget)

def intro(game, T, fun, words=50, narr=None):
    """Introduction block: who / what / when / where + @ spoiler-free sumary."""
    ui, h = T.ui, game.headers
    quip = fun.intro_quip()
    title(ui["i_title"], quip)
    if narr:
        narr.begin("intro")
        narr.heading(ui["i_title"])
        narr.comment(quip)

    def row(label, value):
        if value:
            print(f" {label:<14}: {value}")

    def player(color, elo_tag):
        name = h.get("White" if color == chess.WHITE else "Black", "?")
        elo = clean(h.get(elo_tag))
        extra = f"{T.side(color)}, {ui['i_elo']} {elo}" if elo else T.side(color)
        return f"{name} ({extra})"

    row(ui["i_event"], clean(h.get("Event")))
    row(ui["players"], f"{player(chess.WHITE, 'WhiteElo')}  vs  {player(chess.BLACK, 'BlackElo')}")
    row(ui["i_date"], format_date(h.get("Date"), T))
    row(ui["i_round"], clean(h.get("Round")))
    row(ui["i_site"], clean(h.get("Site")))
    opening, eco = clean(h.get("Opening")), clean(h.get("ECO"))
    row(ui["i_opening"], f"{opening} ({eco})" if opening and eco else opening or eco)
    row(ui["i_tc"], format_time_control(h.get("TimeControl"), T))

    print(f"\n {ui['i_summary']}:")
    sentences = build_summary(game, game_stats(game), T, budget=words)
    if narr:
        narr.explain(" ".join(sentences))
    print(textwrap.fill(" ".join(sentences), width=76,
                        initial_indent="    ", subsequent_indent="    "))
    print(f"\n {ui['i_note']}")

def step1_structure(game, T, fun):
    title(T.ui["step1"], fun.step_quip(1))
    print(T.ui["step1_body"])

def step2_headers(game, T, fun):
    title(T.ui["step2"], fun.step_quip(2))
    for key, value in game.headers.items():
        print(f" [{key} \"{value}\"]")
        print(f"    -> {T.tag_help.get(key, T.ui['custom_tag'])}")
        quip = fun.tag_quip(key)
        if quip:
            print(f"    ~~ {quip}")

def step3_syntax(game, T, fun):
    title(T.ui["step3"], fun.step_quip(3))
    exporter = chess.pgn.StringExporter(headers=False, variations=True, comments=True)
    movetext = game.accept(exporter)

    print(T.ui["movetext_of"] + "\n")
    print(" " + movetext.replace("\n", "\n "))
    print("\n" + T.ui["symbols_intro"] + "\n")

    probes = {
        "1. 2. 3.": "1.", "e4, Nf3": "e4", "x": "x", "+": "+", "#": "#",
        "O-O": "O-O", "=Q": "=", "Nbd2": None, "{ ... }": "{",
        "( ... )": "(", "$1, !, ??": "$", "1-0": "-",
    }

    for symbol, meaning in T.syntax_help:
        probe = probes.get(symbol)
        present = probe is not None and probe in movetext
        if symbol == "$1, !, ??":
            present = present or "!" in movetext or "?" in movetext
        mark = "*" if present else " "
        print(f" {mark} {symbol:<10} {meaning}")

def step4_moves(game, T, fun, show_board=False, pause=False, narr=None):
    ui = T.ui
    title(ui["step4"], fun.step_quip(4))
    names = player_names(game, T)
    board = game.board()
    print(f"{ui['start_fen']}: {board.fen()}\n")
    if show_board:
        print(board, "\n")

    ply = 0
    for node in game.mainline():
        move = node.move
        number = board.fullmove_number
        dots = "." if board.turn == chess.WHITE else "..."

        san = board.san(move) # gust be computed BEFORE push
        side_tag = "w" if board.turn == chess.WHITE else "b"
        explanation = describe_move(board, move, T)
        before = board.copy()

        board.push(move)
        ply += 1

        print(f"[{ply:>3}] {number}{dots} {san}")
        print(f"      {explanation}")

        for note in describe_result_of_move(board, T):
            print(f"      ! {note}")
        if node.nags:
            print(f"      {ui['nags']}: {sorted(node.nags)}")
        if node.comment:
            print(f"      {ui['comment']}: {node.comment.strip()}")
        diff = material(board, chess.WHITE) - material(board, chess.BLACK)
        if diff == 0:
            lead = ui["equal"]
        else:
            lead = f"{T.side(chess.WHITE if diff > 0 else chess.BLACK)} +{abs(diff)}"
        print(f"      {ui['material']}: {lead}")

        lines = fun.for_move(before, move, board, ply, node.nags, names)
        for line in lines:
            print(f"      >> {line}")

        if narr:
            narr.begin(f"move-{ply:03d}-{number}{side_tag}-{safe_name(san)}")
            narr.explain(f"{ui['audio_move'].format(n=number)} {explanation}")
            for line in lines:
                narr.comment(line)
            if node.comment:
                narr.comment(node.comment.strip())

        if show_board:
            print()
            print("      " + str(board).replace("\n", "\n       "))
        print()

        if pause:
            input("      " + ui["press_enter"])

    return board

def step5_summary(game, board, T, fun, narr=None):
    ui = T.ui
    title(ui["step5"], fun.step_quip(5))
    h = game.headers
    full = (board.ply() + 1) // 2
    print(f" {ui['players']:<9}: {h.get('White', '?')} vs {h.get('Black', '?')}")
    print(f" {ui['result']:<9}: {h.get('Result', '*')}")
    print(f" {ui['length']:<9}: " + ui["length_val"].format(ply=board.ply(), full=full))

    if board.is_checkmate():
        ending = ui["end_mate"].format(winner=T.side(not board.turn))
    elif board.is_stalemate():
        ending = ui["end_stale"]
    elif board.is_insufficient_material():
        ending = ui["end_insuf"]
    else:
        ending = h.get("Termination", ui["end_other"])
    print(f" {ui['ending']:<9}: {ending}")

    mats = ui["mat_line"].format(w=material(board, chess.WHITE), b=material(board, chess.BLACK))
    print(f" {ui['material']:<9}: {mats}")
    print(f" {ui['final_fen']}: {board.fen()}")
    print("\n " + ui["fen_note"])

    closing = fun.ending(h.get("Result", "*"), player_names(game, T))
    if closing:
        print(f"\n >> {closing}")
    if narr:
        narr.begin("ending")
        narr.explain(f"{ui['ending']}: {ending}")
        narr.comment(closing)


class Narrator:
    """Collects the text that will be read aloud, grouped into segments
    (the introduction, one per move, the ending ...) so that it can be saved
    either as one MP3 or as one MP3 per segment.

    mode "comments”: only the commentator’s remarks (and comments written in the PGN)
    mode "narration”: the same, plus the introduction summary, a short plain-language

    description of every move, and the ending, so it can be followed
    without looking at the board.
    """

    def __init__(self, mode="comments"):
        self.mode = mode
        self.tag = "" # prefix for segment labels (e.g. "g2-" for game 2)
        self.raw = [] # [(label, [paragraphs]) ]

    def begin(self, label):
        """Start a new segment; everything added next belongs to it."""
        self.raw.append((self.tag + label, []))

    def _add(self, text):
        text = (text or "").strip()
        if text:
            if text[-1] not in ".!?":
                text += "."
            if not self.raw:
                self.begin("start")
            self.raw[-1][1].append(text)

    def heading(self, text):
        if self.mode == "narration":
            self._add(text)

    def explain(self, text):
        if self.mode == "narration":
            self._add(text)

    def comment(self, text):
        self._add(text)

    def segments(self, T):
        out = []
        for label, parts in self.raw:
            cleaned = [c for c in (speakable(p, T) for p in parts) if c]
            if cleaned:
                out.append((label, cleaned))
        return out

    def script(self, T):
        """All paragraphs of all segments, in order."""
        return [p for _, parts in self.segments(T) for p in parts]

def safe_name(text):
    """Make a SAN move such as 'Qxf7#' safe to use inside a file name."""
    text = text.replace("#", "mate").replace("+", "check").replace("=", "promo")
    return re.sub(r"[^A-Za-z0-9-]", "", text)

def speakable(text, T):
    """Replace chess shorthand that a voice would mangle ("0-0", '??', '1-0°, 'vs*)."""
    for pattern, spoken in T.speak_subs:
        rx = re.escape(pattern)
        if pattern[0].isalnum():
            rx = r"(?<![\w/])" + rx
        if pattern[-1].isalnum():
            rx += r"(?![\w/])"
        text = re.sub(rx, spoken, text)
    return re.sub(r"\s+", " ", text).strip()

def chunk_parts(parts, limit=1500):
    """Group paragraphs into chunks of at most ~*limit™ characters, so a long game is
    sent to gITS in several small requests instead of one huge one."""
    chunks, current = [], ""
    for part in parts:
        if current and len(current) + len(part) + 1 > limit:
            chunks.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
    if current:
        chunks.append(current)
    return chunks

def audio_output_name(args):
    base = os.path.splitext(os.path.basename(args.pgn))[0] if args.pgn else "sample"
    return f"{base}_commentary_{args.lang}.mp3"

def require_gtts(T):
    """Fail early (before any work is done) if gTTS is missing."""
    try:
        import gtts # noga: F401
    except ImportError:
        sys.exit(T.ui["audio_missing"])

def save_audio(path, chunks, T, slow=False):
    from gtts import gTTS
    try:
        with open(path, "wb") as handle:
            for number, chunk in enumerate(chunks, 1):
                print(T.ui["audio_part"].format(i=number, n=len(chunks)), file=sys.stderr)
                gTTS(text=chunk, lang=T.tts, slow=slow).write_to_fp(handle)
    except Exception as err: # network down, rate limit, bad path ...
        try:
            os.remove(path)
        except OSError:
            pass
        sys.exit(T.ui["audio_err"].format(err=err))

def audio_output_dir(args):
    base = os.path.splitext(os.path.basename(args.pgn))[0] if args.pgn else "sample"
    return f"{base}_commentary_{args.lang}"

def save_audio_split(folder, segments, T, slow=False):
    """One MP3 per segment inside "folder”, plus index.txt listing what each file says."""
    from gtts import gTTS
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as err:
        sys.exit(T.ui["audio_err"].format(err=err))
    index = []
    for number, (label, parts) in enumerate(segments, 1):
        name = f"{number:03d}_{label[:60]}.mp3"
        path = os.path.join(folder, name)
        print(T.ui["audio_file"].format(i=number, n=len(segments), name=name), file=sys.stderr)
        try:
            with open(path, "wb") as handle:
                for chunk in chunk_parts(parts):
                    gTTS(text=chunk, lang=T.tts, slow=slow).write_to_fp(handle)
        except Exception as err:
            try:
                os.remove(path)
            except OSError:
                pass
            sys.exit(T.ui["audio_err"].format(err=err))
        index.append(f"{name}\t{' '.join(parts)}")
    with open(os.path.join(folder, "index.txt"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(index) + "\n")

# ----------------------------------------------------------------- #
# main
# ----------------------------------------------------------------- #
def load_game(path, index):
    handle = io.StringIO(SAMPLE_PGN) if path is None else open(path, encoding="utf-8", errors="replace")
    with handle:
        game = None
        for _ in range(index):
            game = chess.pgn.read_game(handle)
        if game is None:
            return None
        return game

class Tee:
    """File-like object that writes everything to several streams at once."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()

def iter_games(path):
    """Yield every game found in the PGN file (or the sample game)."""
    handle = io.StringIO(SAMPLE_PGN) if path is None else open(path, encoding="utf-8", errors="replace")
    with handle:
        while True:
            game = chess.pgn.read_game(handle)
            if game is None:
                return
            yield game

def auto_output_name(args):
    base = os.path.splitext(os.path.basename(args.pgn))[0] if args.pgn else "sample"
    return f"{base}_explained_{args.lang}.txt"

def explain_game(game, T, args, seed, narr=None):
    """Explain the game in plain language, optionally saving an audio version."""
    fun = Commentator(T, seed=seed, enabled=not args.serious)
    if not args.no_intro:
        intro(game, T, fun, args.summary_words, narr)
    step1_structure(game, T, fun)
    step2_headers(game, T, fun)
    step3_syntax(game, T, fun)
    board = step4_moves(game, T, fun, show_board=args.show,
                        pause=args.step, narr=narr)
    step5_summary(game, board, T, fun, narr)

def main():
    # make Vietnamese (and any Unicode) print correctly, also on Windows
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # read the language files first, so ~--lang’ can offer whatever languages exist
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--lang-dir")
    try:
        loaded = load_languages(pre.parse_known_args()[0].lang_dir)
    except LanguageError as err:
        sys.exit(f"Language data problem: {err}")
    LANGS.clear()
    LANGS.update(loaded)

    parser = argparse.ArgumentParser(description="Explain a PGN file step by step.")
    parser.add_argument("pgn", nargs="?", help="PGN file (omit to use the sample game)")
    parser.add_argument("-g", "--game", type=int, default=1, help="which game in the file to explain (default 1)")
    parser.add_argument("--all", action="store_true", help="explain every game in the file, one after another")
    parser.add_argument("-l", "--lang", choices=sorted(LANGS), default="en" if "en" in LANGS else sorted(LANGS)[0],
            help="output language, from the files in the lang folder: " + ", ".join(sorted(LANGS)) + " (default en)")
    parser.add_argument("--lang-dir", metavar="DIR", help="folder with the language .json files (default: lang/ next to the script)")
    parser.add_argument("-o", "--output", metavar="FILE", help="write the explanation to FILE instead of the screen "
                        "('auto' = name it after the PGN file)")
    parser.add_argument("--append", action="store_true", help="with -o: add to the end of FILE instead of overwriting it")
    parser.add_argument("--tee", action="store_true", help="with -o: write to FILE and also show it on screen")
    parser.add_argument("--board", action="store_true", help="print the board after every move")
    parser.add_argument("--step", action="store_true", help="wait for Enter between moves")
    parser.add_argument("--seed", type=int, default=None, help="fixed seed for repeatable jokes")
    parser.add_argument("--serious", action="store_true", help="turn the commentator off")
    parser.add_argument("--no-intro", action="store_true", help="skip the spoiler-free game introduction")
    parser.add_argument("--summary-words", type=int, default=50, metavar="N", help="length of the introduction sumary in words (default 50)")
    parser.add_argument("--audio", metavar="FILE", help="read the comments aloud and save them as an MP3 with gTTs "
            "('auto' = name it after the PGM file; needs internet)")
    parser.add_argument("--audio-content", choices=("comments", "narration"), default="comments",
        help="comments = only the commentator’s remarks (default); narration = "
            "also the summary, a description of each move and the ending")
    parser.add_argument("--audio-slow", action="store_true", help="speak more slowly")
    parser.add_argument("--audio-split", action="store_true", help="one MP3 per step (intro, each move, ending) saved in a folder; "
                        "with this option the --audio value is a folder name")

    args = parser.parse_args()
    if args.game < 1:
        parser.error("--game must be 1 or higher")
    if args.audio_split and not args.audio:
        parser.error("--audio-split needs --audio")

    T = Lang(args.lang)

    # ---- audio preflight: fail early, before doing any work ----
    narr, audio_path = None, None
    if args.audio:
        require_gtts(T)
        if args.audio_split: # the value a folder, not a file
            audio_path = audio_output_dir(args) if args.audio == "auto" else args.audio
        if audio_path.lower().endswith(".mp3"):
            audio_path = audio_path[:-4]
    else:
        audio_path = audio_output_name(args) if args.audio == "auto" else args.audio
    folder = os.path.dirname(os.path.abspath(audio_path))

    if not os.access(folder, os.W_OK):
        sys.exit(T.ui["audio_bad_path"].format(path=audio_path))
    narr = Narrator(args.audio_content)

    # pick the game(s) BEFORE touching the output file, so a bad -g leaves no empty file
    if args.all:
        games = iter_games(args.pgn)
    else:
        game = load_game(args.pgn, args.game)
        if game is None:
            sys.exit(T.ui["no_game"].format(n=args.game))
        games = [game]

    # ---- output destination ----
    out_path, out_file, ctx = None, None, contextlib.nullcontext()
    if args.output:
        out_path = auto_output_name(args) if args.output == "auto" else args.output
        if args.step:
            print(T.ui["step_off"], file=sys.stderr)
            args.step = False # prompts cannot go into a file
        try:
            out_file = open(out_path, "a" if args.append else "w", encoding="utf-8", newline="\n")
        except OSError as err:
            sys.exit(T.ui["out_err"].format(path=out_path, err=err))
        target = Tee(out_file, sys.stdout) if args.tee else out_file
        ctx = contextlib.redirect_stdout(target)

    count = 0
    try:
        with ctx:
            for i, game in enumerate(games, 1):
                if args.all:
                    h = game.headers
                    print("\n" + "#" * 64)
                    print(T.ui["game_banner"].format(
                        i=i, white=h.get("White", "?"), black=h.get("Black", "?")))
                    print("#" * 64)
                    if narr:
                        narr.tag = f"g{i}-"
                        narr.begin("title")
                        narr.heading(T.ui["game_banner"].format(
                            i=i, white=h.get("White", "?"), black=h.get("Black", "?")))
                seed = None if args.seed is None else args.seed + i
                explain_game(game, T, args, seed, narr)
                count += 1
    finally:
        if out_file:
            out_file.close()

    if count == 0:
        sys.exit(T.ui["no_game"].format(n=args.game))
    if out_path:
        print(T.ui["saved"].format(path=os.path.abspath(out_path)), file=sys.stderr)

    if narr is not None:
        segments = narr.segments(T)
        if not segments:
            print(T.ui["audio_empty"], file=sys.stderr)
        elif args.audio_split:
            save_audio_split(audio_path, segments, T, slow=args.audio_slow)
            print(T.ui["audio_saved_dir"].format(
                n=len(segments), path=os.path.abspath(audio_path)), file=sys.stderr)
        else:
            save_audio(audio_path, chunk_parts(narr.script(T)), T, slow=args.audio_slow)
            print(T.ui["audio_saved"].format(path=os.path.abspath(audio_path)), file=sys.stderr)

if __name__ == "__main__":
    main()
