# -*- coding: utf-8 -*-
"""Сборщик данных для Atomic Trainer: скачивает партии, извлекает пазлы, проверяет уроки."""
import os, sys, json, time, urllib.request, io, glob
import chess, chess.pgn, chess.variant

BASE = os.path.dirname(os.path.abspath(__file__))
PGN_DIR = os.path.join(BASE, "pgn")
os.makedirs(PGN_DIR, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AtomicTrainer/1.0", "Accept": "application/x-chess-pgn"}

def download(user, maxg):
    path = os.path.join(PGN_DIR, f"{user}.pgn")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        print(f"  {user}: уже скачано, пропускаю")
        return True
    url = f"https://lichess.org/api/games/user/{user}?perfType=atomic&max={maxg}&opening=true"
    try:
        req = urllib.request.Request(url, headers=UA)
        data = urllib.request.urlopen(req, timeout=30).read().decode()
        if data.count("[Event") == 0:
            print(f"  {user}: пусто ({len(data)} байт)")
            return False
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        print(f"  {user}: {data.count('[Event')} партий")
        return True
    except Exception as e:
        print(f"  {user}: ОШИБКА {e}")
        return False

print("== 1. Скачивание партий ==")
download("F55555", 25)
for u in ["maxwellssilvrhaMMer", "mss365", "ReChesster", "k1ll-shot", "sutcunuri"]:
    download(u, 6)
    time.sleep(25)  # лимит Lichess: 1 запрос за раз

print("== 2. Локальные партии бота ==")
local_dir = r"C:\Users\event\Downloads\SuperGame5\game_records"
bot_files = []
for p in glob.glob(os.path.join(local_dir, "*.pgn")):
    try:
        head = open(p, encoding="utf-8", errors="ignore").read(800)
        if 'Variant "Atomic"' in head:
            dst = os.path.join(PGN_DIR, "bot__" + os.path.basename(p))
            with open(p, encoding="utf-8", errors="ignore") as src, open(dst, "w", encoding="utf-8") as out:
                out.write(src.read())
            bot_files.append(dst)
    except Exception:
        pass
print(f"  Бот: {len(bot_files)} атомных партий")

print("== 3. Парсинг всех партий ==")
games = []
pgn_files = [os.path.join(PGN_DIR, f) for f in os.listdir(PGN_DIR) if f.endswith(".pgn")]
for path in pgn_files:
    src = "bot" if os.path.basename(path).startswith("bot__") else None
    with open(path, encoding="utf-8") as f:
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            if game.headers.get("Variant", "").lower() != "atomic":
                continue
            board = chess.variant.AtomicBoard()
            uci = []
            ok = True
            for mv in game.mainline_moves():
                if mv not in board.legal_moves:
                    ok = False
                    break
                uci.append(mv.uci())
                board.push(mv)
            if not ok or len(uci) < 4:
                continue
            white, black = game.headers.get("White","?"), game.headers.get("Black","?")
            if src == "bot":
                who = "bot"
            elif "F55555" in (white, black):
                who = "F55555"
            else:
                who = "top"
            games.append({
                "w": white, "b": black, "r": game.headers.get("Result","*"),
                "d": game.headers.get("UTCDate",""), "tc": game.headers.get("TimeControl",""),
                "term": game.headers.get("Termination",""), "we": game.headers.get("WhiteElo",""),
                "be": game.headers.get("BlackElo",""), "id": game.headers.get("GameId",""),
                "src": who, "m": uci
            })
print(f"  Всего распарсено: {len(games)} партий")
print("DBG_S3:", len(games), [len(g["m"]) for g in games[:5]])

print("== 4. Извлечение пазлов (взрыв короля / мат в 1) ==")
puzzles = []
seen_fen = set()
print("DBG_S4:", [len(g["m"]) for g in games[:5]])
per_game_limit = 2
for gi, g in enumerate(games):
    board = chess.variant.AtomicBoard()
    cnt = 0
    for ply, uci in enumerate(g["m"]):
        mv = chess.Move.from_uci(uci)
        if mv not in board.legal_moves:
            break
        # ищем все "решающие" ходы в этой позиции
        winners = []
        for cand in board.legal_moves:
            sim = board.copy()
            is_cap = board.is_capture(cand)
            sim.push(cand)
            opp_king_gone = sim.king(not board.turn) is None
            if (is_cap and opp_king_gone) or sim.is_checkmate():
                kind = "boom" if opp_king_gone else "mate"
                winners.append((cand.uci(), kind))
        if len(winners) == 1 and winners[0][0] == uci and cnt < per_game_limit:
            fen = board.fen()
            if fen not in seen_fen and ply >= 6:
                seen_fen.add(fen)
                kind = winners[0][1]
                mover_white = board.turn == chess.WHITE
                puzzles.append({
                    "fen": fen, "sol": uci, "type": kind,
                    "side": "w" if mover_white else "b",
                    "from": f"{g['w']} - {g['b']}" + ("" if not g["id"] else f" (lichess.org/{g['id']})"),
                    "n": len(puzzles) + 1
                })
                cnt += 1
        board.push(mv)
    if len(puzzles) >= 20:
        break
print(f"  Пазлов уровня 1 собрано: {len(puzzles)}")

print("== 4b. Сложные пазлы (мат в 2, материал, защита) ==")
import time as _time
PZ_VALS = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9}
mate2_cap, mat_cap, def_cap = 5, 4, 4
dl_mat = _time.time() + 45
dl_def = _time.time() + 45
dl_m2 = _time.time() + 170
print("DBG_S4b_start:", len(games), [len(g["m"]) for g in games[:5]])
def _mat_color(bd, color):
    v = 0
    for pc in bd.piece_map().values():
        if pc.color == color:
            v += PZ_VALS.get(pc.symbol().upper(), 0)
    return v
def _immediate_wins(bd):
    res = []
    for m in bd.legal_moves:
        sim = bd.copy()
        cap = bd.is_capture(m)
        sim.push(m)
        if (cap and sim.king(not bd.turn) is None) or sim.is_checkmate():
            res.append(m.uci())
    return res
def _boom_threats(bd):
    n = 0
    for m in bd.legal_moves:
        if not bd.is_capture(m): continue
        sim = bd.copy(); sim.push(m)
        if sim.king(not bd.turn) is None: n += 1
    return n
def _mate_in_2_moves(bd):
    S = bd.turn
    sols = []
    for m in bd.legal_moves:
        a = bd.copy(); a.push(m)
        if a.king(S) is None: continue
        replies = list(a.legal_moves)
        if not replies or len(replies) > 14: continue
        good = True
        for r in replies:
            b2 = a.copy(); b2.push(r)
            if b2.king(S) is None or not _immediate_wins(b2):
                good = False; break
        if good: sols.append(m.uci())
        if _time.time() > dl_m2: break
    return sols
def _add_pzl(fen, sol, typ, side_white, frm, lvl):
    global mate2_cap, mat_cap, def_cap
    if fen in seen_fen: return False
    for p in puzzles:
        if p["fen"] == fen: return False
    seen_fen.add(fen)
    puzzles.append({"fen": fen, "sol": sol, "type": typ, "side": "w" if side_white else "b",
                    "from": frm, "n": len(puzzles) + 1, "lvl": lvl})
    if typ == "mate2": mate2_cap -= 1
    elif typ == "material": mat_cap -= 1
    elif typ == "defense": def_cap -= 1
    return True

_dbg_games = 0; _dbg_plies = 0; _dbg_matscan = 0; _dbg_cands = 0
for gi, g in enumerate(games):
    if mate2_cap <= 0 and mat_cap <= 0 and def_cap <= 0: break
    _dbg_games += 1
    if gi == 0: print("DBG_g0:", len(g["m"]), g["m"][:3])
    board = chess.variant.AtomicBoard()
    frm = f"{g['w']} - {g['b']}" + ("" if not g["id"] else f" (lichess.org/{g['id']})")
    for ply, uci in enumerate(g["m"]):
        mv = chess.Move.from_uci(uci)
        if mv not in board.legal_moves: break
        if gi == 0 and ply < 12: print("DBG_PLY:", ply, uci, "| FEN:", board.fen().split(" ")[0])
        if ply < 8:
            board.push(mv)
            continue
        _dbg_plies += 1
        S_white = board.turn == chess.WHITE
        if mat_cap > 0 and _time.time() < dl_mat and not _immediate_wins(board):
            bal0 = _mat_color(board, board.turn) - _mat_color(board, not board.turn)
            best, best_d, second_d = None, 0, 0
            for m in board.legal_moves:
                if not board.is_capture(m): continue
                sim = board.copy(); sim.push(m)
                bal1 = _mat_color(sim, board.turn) - _mat_color(sim, not board.turn)
                d = bal1 - bal0
                if d > best_d:
                    second_d = best_d; best, best_d = m.uci(), d
                elif d > second_d: second_d = d
            if best and best_d >= 3 and best_d - second_d >= 1:
                _add_pzl(board.fen(), best, "material", S_white, frm, 2)
        if def_cap > 0 and _time.time() < dl_def:
            flip = board.copy(); flip.turn = not flip.turn
            if _boom_threats(flip) >= 1:
                safe = []
                for m in board.legal_moves:
                    sim = board.copy(); sim.push(m)
                    sim2 = sim.copy(); sim2.turn = not sim2.turn
                    if _boom_threats(sim2) == 0:
                        safe.append(m.uci())
                if len(safe) == 1:
                    _add_pzl(board.fen(), safe[0], "defense", S_white, frm, 2)
        if mate2_cap > 0 and _time.time() < dl_m2 and not _immediate_wins(board):
            m2 = _mate_in_2_moves(board)
            if len(m2) == 1:
                _add_pzl(board.fen(), m2[0], "mate2", S_white, frm, 3)
        board.push(mv)
print(f"  \u0421\u043b\u043e\u0436\u043d\u044b\u0435 \u043f\u0430\u0437\u043b\u044b: mate2={5 - mate2_cap}, \u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b={4 - mat_cap}, \u0437\u0430\u0449\u0438\u0442\u0430={4 - def_cap}, \u0432\u0440\u0435\u043c\u044f={_time.time() - dl_mat + 45:.0f}\u0441")
print(f"  DEBUG: games={_dbg_games}, plies={_dbg_plies}, matscans={_dbg_matscan}, cands={_dbg_cands}")

# сортировка по уровню сложности и перенумерация
puzzles.sort(key=lambda p: p.get("lvl", 1))
for i, p in enumerate(puzzles):
    p["n"] = i + 1
    p.setdefault("lvl", 1)

# --- Часть четвёртая: Дебюты ---


print("== 5. Проверка уроков движком ==")
lessons = []
def verify(fen, seq_uci):
    b = chess.variant.AtomicBoard(fen)
    for u in seq_uci:
        mv = chess.Move.from_uci(u)
        assert mv in b.legal_moves, f"ход {u} нелегален в {fen}"
        b.push(mv)
    return b

# Урок 1: взятие уничтожает обе фигуры
b0 = chess.variant.AtomicBoard("k7/8/8/8/4p3/3P4/8/K7 w - - 0 1")
assert chess.Move.from_uci("d3e4") in b0.legal_moves
b1 = verify("k7/8/8/8/4p3/3P4/8/K7 w - - 0 1", ["d3e4"])
assert b1.piece_at(chess.parse_square("d3")) is None and b1.piece_at(chess.parse_square("e4")) is None
lessons.append({"id":"boom-basic","fen":"k7/8/8/8/4p3/3P4/8/K7 w - - 0 1","moves":["d3e4"],
  "title":"Взятие = взрыв","text":"Пешка d3 берёт пешку e4. Обе фигуры исчезают — и бьющая, и битая!"})

# Урок 2: радиус взрыва
b2 = verify("6k1/8/8/5n2/4p3/3Q4/8/K7 w - - 0 1", ["d3e4"])
assert b2.piece_at(chess.parse_square("f5")) is None, "конь f5 должен взорваться"
assert b2.piece_at(chess.parse_square("d3")) is None
lessons.append({"id":"boom-radius","fen":"6k1/8/8/5n2/4p3/3Q4/8/K7 w - - 0 1","moves":["d3e4"],
  "title":"Радиус взрыва","text":"Ферля забирает пешку e4 — и взрыв уничтожает коня f5 рядом! Взрыв бьёт все небитые фигуры в 8 соседних клетках (кроме пешек)."})

# Урок 3: нельзя взрывать своего короля
b3 = chess.variant.AtomicBoard("k7/7K/7p/8/8/8/8/7R w - - 0 1")
assert chess.Move.from_uci("h1h6") not in b3.legal_moves, "Rxh6 должен быть нелегален"
assert chess.Move.from_uci("h1a1") in b3.legal_moves
lessons.append({"id":"own-king","fen":"k7/7K/7p/8/8/8/8/7R w - - 0 1","moves":[],
  "title":"Своего короля взрывать нельзя","text":"Ладья h1 хочет взять пешку h6 — но взрыв уничтожит короля h7! Такой ход ЗАПРЕЩЁН, ладье надо уходить (например, a1)."})

# Урок 4: короли могут стоять рядом
b4 = chess.variant.AtomicBoard("8/8/8/3kK3/8/8/8/8 w - - 0 1")
assert b4.is_valid(), "позиция с рядом стоящими королями должна быть валидна"
lessons.append({"id":"kings-adjacent","fen":"8/8/8/3kK3/8/8/8/8 w - - 0 1","moves":[],
  "title":"Короли могут стоять рядом!","text":"В атомных шахматах короли НЕ атакуют друг друга и могут стоять рядом. Мат ставится только настоящими фигурами или взрывом."})

# Урок 5: реальный мат из партии F55555 (vs FeodorPt, 2026)
bL = chess.variant.AtomicBoard()
seq = "e2e3 g8f6 f2f4 f6e4 d2d4 e7e6 f1b5 c7c6 g1f3 f7f5 f3e5 d7d5 e5f7 d8h4 g2g3 f8b4 c2c3 h4h3 d1h5 h3f1".split()
for u in seq[:-1]:
    bL.push(chess.Move.from_uci(u))
mate_fen = bL.fen()
assert chess.Move.from_uci("h3f1") in bL.legal_moves
bL.push(chess.Move.from_uci("h3f1"))
assert bL.is_checkmate(), "должен быть мат Qf1#"
lessons.append({"id":"real-mate","fen":mate_fen,"moves":["h3f1"],
  "title":"Мат из реальной партии F55555","text":"Позиция из вашей партии (чёрные). Ферль h4 идёт на f1 — мат! В обычных шахматах король просто взял бы ферзя, но в атоме взрыв уничтожил бы собственную охрану — это классический «тихий мат»."})

print(f"  Уроков проверено: {len(lessons)}")

print("== 6c. Упражнения тренажёра (в стиле lichess learn) ==")
EXERCISES = [
 {"id": "ex-first-boom", "fen": "k7/8/8/8/4p3/3P4/8/K7 w - - 0 1", "num": 1,
  "title_ru": "Первый взрыв", "title_en": "The first explosion",
  "goal_ru": "Возьми ЧЁРНУЮ пешку e4 своей пешкой d3 — обе исчезнут во взрыве! Ходи только БЕЛЫМИ.",
  "goal_en": "Capture the BLACK pawn on e4 with your pawn d3 — both vanish in the blast! Move WHITE only.",
  "check": {"kind": "capture-sq", "sq": "e4"}},
 {"id": "ex-double", "fen": "k7/8/8/4qn2/4p3/3Q4/8/1K6 w - - 0 1", "num": 2,
  "title_ru": "Двойной удар", "title_en": "Double strike",
  "goal_ru": "Ферзь берёт пешку e4 — взрыв уничтожает ферзя e5 и коня f5! Уничтожь 2 чёрные фигуры одним взрывом.",
  "goal_en": "The queen takes the pawn on e4 — the blast destroys the queen e5 and knight f5! Destroy 2 black pieces with one capture.",
  "check": {"kind": "destroy", "n": 2}},
 {"id": "ex-triple", "fen": "k7/8/8/4qn2/4pr2/3Q4/8/1K6 w - - 0 1", "num": 3,
  "title_ru": "Полная зачистка", "title_en": "Full cleanup",
  "goal_ru": "Один взрыв на e4 уничтожает ферзя e5, коня f5 и ладью f4! Уничтожь все 3 чёрные фигуры одним ударом.",
  "goal_en": "One blast on e4 destroys the queen e5, knight f5 and rook f4! Destroy all 3 black pieces in a single strike.",
  "check": {"kind": "destroy", "n": 3}},
 {"id": "ex-boom-king", "fen": "6k1/5p2/8/8/8/1Q6/8/K7 w - - 0 1", "num": 4,
  "title_ru": "Взрыв короля", "title_en": "King explosion",
  "goal_ru": "Ферзь бьёт пешку f7 — взрыв уничтожает короля g8! Это победа!",
  "goal_en": "The queen captures the pawn on f7 — the blast kills the king on g8! That is victory!",
  "check": {"kind": "boom-king"}},
 {"id": "ex-promote", "fen": "k7/1P6/8/8/8/8/8/K7 w - - 0 1", "num": 5,
  "title_ru": "Пешка становится ферзём", "title_en": "Pawn becomes a queen",
  "goal_ru": "Проведи пешку b7 на b8 и преврати её в ФЕРЗЯ.",
  "goal_en": "Push the pawn from b7 to b8 and promote it to a QUEEN.",
  "check": {"kind": "promote"}},
 {"id": "ex-quiet-mate", "fen": "6k1/8/5KQ1/8/8/8/8/8 w - - 0 1", "num": 6,
  "title_ru": "Тихий мат ферзём", "title_en": "Quiet queen mate",
  "goal_ru": "Поставь мат ферзём. Поле g7 защищает твой же король f6!",
  "goal_en": "Deliver mate with the queen. Your king on f6 guards g7!",
  "check": {"kind": "mate"}},
 {"id": "ex-maneuver", "fen": "7k/7K/7p/8/8/8/8/7R w - - 0 1", "num": 7,
  "title_ru": "Манёвр ладьи", "title_en": "The rook maneuver",
  "goal_ru": "Пешка h6 взрывоопасна — брать нельзя! Проведи ладью с h1 на a1 и не подорвись.",
  "goal_en": "The pawn on h6 is explosive — do not capture it! Take the rook from h1 to a1 without blowing yourself up.",
  "check": {"kind": "reach", "sq": "a1", "piece": "R"}},
 {"id": "ex-kill-attacker", "fen": "7k/8/8/8/5n2/6PR/8/7K w - - 0 1", "num": 8,
  "title_ru": "Убей нападающего", "title_en": "Kill the attacker",
  "goal_ru": "Конь f4 напал на ладью h3! Возьми его пешкой g3 — ВЗРЫВ УНИЧТОЖИТ ОБЕИХ: и коня, и твою пешку. Размен в твою пользу!",
  "goal_en": "The knight on f4 attacked the rook h3! Capture it with the g3 pawn — THE BLAST DESTROYS BOTH: the knight and your pawn. A trade in your favor.",
  "check": {"kind": "destroy", "n": 1}},
 {"id": "ex-pawn-armor", "fen": "6k1/8/8/3p1p2/4p3/3P2P1/8/6K1 w - - 0 1", "num": 9,
  "title_ru": "Пешки — броня", "title_en": "Pawns are armor",
  "goal_ru": "Уничтожь чёрную пешку e4, но НЕ тронь пешки d5 и f5 — они НЕ взрываются! Ходи d3:e4 или g3:e4.",
  "goal_en": "Destroy the black pawn on e4, but do NOT touch d5 and f5 — pawns do NOT explode! Play d3:e4 or g3:e4.",
  "check": {"kind": "capture-sq", "sq": "e4"}},
 {"id": "ex-en-passant", "fen": "6k1/8/8/3pP3/8/8/8/6K1 w - d6 0 1", "num": 10,
  "title_ru": "Взятие на проходе", "title_en": "En passant",
  "goal_ru": "Чёрная пешка только что сходила d7-d5. Возьми её на проходе: пешка e5 бьёт на d6! Обе исчезнут во взрыве.",
  "goal_en": "The black pawn just moved d7-d5. Capture it en passant: the e5 pawn takes on d6! Both vanish in the blast.",
  "check": {"kind": "capture-sq", "sq": "d6"}},
 {"id": "ex-castle", "fen": "4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1", "num": 11,
  "title_ru": "Рокировка", "title_en": "Castling",
  "goal_ru": "Сделай короткую рокировку: король e1 идёт на g1, ладья h1 перескакивает на f1.",
  "goal_en": "Castle short: the king from e1 goes to g1, the rook from h1 jumps to f1.",
  "check": {"kind": "reach", "sq": "f1", "piece": "R"}},
 {"id": "ex-double-boom", "fen": "6k1/5ppp/8/4q3/8/3B4/8/5K2 w - - 0 1", "num": 12,
  "title_ru": "Комбо-взрыв", "title_en": "Combo explosion",
  "goal_ru": "Возьми ФЕРЗЯ e5 слоном d3 — взрыв уничтожит их обоих. Пешки f7, g7, h7 выживут (пешки не взрываются), но чёрные потеряют ферзя!",
  "goal_en": "Capture the QUEEN on e5 with the bishop from d3 — the blast destroys both of them. Pawns f7, g7, h7 survive (pawns don't explode), but black loses their queen!",
  "check": {"kind": "destroy", "n": 1}},
 {"id": "ex-save-king", "fen": "6k1/5ppp/8/8/8/8/5PPP/5K1R w - - 0 1", "num": 13,
  "title_ru": "Укрой короля", "title_en": "Shelter the king",
  "goal_ru": "Чёрные вот-вот взорвут твоего короля через h7! Сходи h2-h3 — построй стену, которая усложнит подрыв.",
  "goal_en": "Black is about to explode your king through h7! Play h2-h3 — build a wall that makes the demolition harder.",
  "check": {"kind": "reach", "sq": "h3", "piece": "P"}}
]
# проверки всех упражнений движком
_b = chess.variant.AtomicBoard(EXERCISES[0]["fen"])
assert chess.Move.from_uci("d3e4") in _b.legal_moves
_b = chess.variant.AtomicBoard(EXERCISES[1]["fen"])
_m = chess.Move.from_uci("d3e4"); assert _m in _b.legal_moves
_b.push(_m)
assert _b.piece_at(chess.parse_square("e5")) is None and _b.piece_at(chess.parse_square("f5")) is None
_b = chess.variant.AtomicBoard(EXERCISES[2]["fen"])
_m = chess.Move.from_uci("d3e4"); assert _m in _b.legal_moves
_b.push(_m)
assert _b.piece_at(chess.parse_square("e5")) is None and _b.piece_at(chess.parse_square("f5")) is None and _b.piece_at(chess.parse_square("f4")) is None
_b = chess.variant.AtomicBoard(EXERCISES[3]["fen"])
_m = chess.Move.from_uci("b3f7"); assert _m in _b.legal_moves
_b.push(_m)
assert _b.king(chess.BLACK) is None, "король должен взорваться"
_b = chess.variant.AtomicBoard(EXERCISES[4]["fen"])
_m = chess.Move.from_uci("b7b8q"); assert _m in _b.legal_moves
_b.push(_m)
assert _b.piece_at(chess.parse_square("b8")).symbol() == "Q"
_b = chess.variant.AtomicBoard(EXERCISES[5]["fen"])
assert _b.is_valid() and not _b.is_check()
_m = chess.Move.from_uci("g6g7"); assert _m in _b.legal_moves
_b = chess.variant.AtomicBoard(EXERCISES[6]["fen"])
_m = chess.Move.from_uci("h1a1"); assert _m in _b.legal_moves
assert chess.Move.from_uci("h1h6") not in _b.legal_moves, "Rxh6 должен быть запрещён"
_b = chess.variant.AtomicBoard(EXERCISES[7]["fen"])
_m = chess.Move.from_uci("g3f4"); assert _m in _b.legal_moves
_b.push(_m)
assert _b.piece_at(chess.parse_square("f4")) is None, "конь должен исчезнуть"
assert _b.piece_at(chess.parse_square("h3")).symbol() == "R", "ладья h3 цела"
print(f"  Упражнений: {len(EXERCISES)} — все проверены движком")
# дополнительные проверки новых упражнений
def _check_ex(fen, moves, name):
    b = chess.variant.AtomicBoard(fen)
    for u in moves:
        m = chess.Move.from_uci(u)
        assert m in b.legal_moves, f"{name}: {u} нелегален"
        b.push(m)
    return b

_check_ex(EXERCISES[8]["fen"], ["d3e4"], "ex-pawn-armor")  # d3:e4
_b = _check_ex(EXERCISES[9]["fen"], ["e5d6"], "ex-en-passant")  # e5:d6 ep
assert _b.piece_at(chess.parse_square("d5")) is None, "битая пешка d5 должна исчезнуть"
assert _b.piece_at(chess.parse_square("d6")) is None, "бьющая пешка тоже гибнет"
_check_ex(EXERCISES[10]["fen"], ["e1g1"], "ex-castle")  # O-O
_b = _check_ex(EXERCISES[11]["fen"], ["d3e5"], "ex-double-boom")
assert _b.piece_at(chess.parse_square("e5")) is None, "ферзь и слон должны исчезнуть"
_check_ex(EXERCISES[12]["fen"], ["h2h3"], "ex-save-king")  # h2-h3
print("  Новые упражнения (9-13) проверены")
L = {l["id"]: l for l in lessons}

# --- новые проверки для глав ---
# Гл.3: пешки-броня (взрыв не трогает пешки)
bA = chess.variant.AtomicBoard("6k1/8/8/3p1p2/4p3/3Q4/8/K7 w - - 0 1")
assert chess.Move.from_uci("d3e4") in bA.legal_moves
bA.push(chess.Move.from_uci("d3e4"))
assert bA.piece_at(chess.parse_square("d5")) is not None, "пешка d5 должна уцелеть"
assert bA.piece_at(chess.parse_square("f5")) is not None, "пешка f5 должна уцелеть"
assert bA.piece_at(chess.parse_square("e4")) is None and bA.piece_at(chess.parse_square("d3")) is None

# Гл.8: ферзь-камикадзе (реальная позиция из партии ttMjlLEn, перед 13.Фа5×Фс7)
bK = chess.variant.AtomicBoard("r1b1k3/p1q5/n5pb/Qp1p1p2/2PP3P/4P3/PP4P1/RNB2RK1 w - - 13 24")
mvK = chess.Move.from_uci("a5c7")
assert mvK in bK.legal_moves
bK.push(mvK)
assert bK.piece_at(chess.parse_square("a5")) is None and bK.piece_at(chess.parse_square("c7")) is None, "оба ферзя исчезают"

# Гл.9/10: статичные иллюстрации валидны
bF = chess.variant.AtomicBoard("5rk1/5ppp/8/8/8/8/5PPP/5RK1 w - - 0 1")
assert bF.is_valid() and not bF.is_check()
bN = chess.variant.AtomicBoard("5rk1/5N2/8/8/8/8/8/K7 w - - 0 1")
assert bN.is_valid() and not bN.is_check()

COURSE = [
 {"part_ru": "Часть первая. Элементы", "part_en": "Part one. The elements", "chapters": [
   {"id": "boom-basic", "fen": L["boom-basic"]["fen"], "moves": L["boom-basic"]["moves"],
    "title_ru": "Взрыв — душа атомных шахмат", "title_en": "The explosion — the soul of atomic chess",
    "text_ru": "Вся партия держится на одном механизме. Правило: при взятии исчезают бьющая фигура, битая фигура и все фигуры вокруг точки взрыва. Не пешки — они бронированы. Здесь пешка d3×e4: обе пешки исчезают.",
    "text_en": "The whole game rests on one mechanism. Rule: on a capture, the capturing piece, the captured piece and every piece around the blast vanish. Not pawns — they are armored. Here d3×e4: both pawns vanish."},
   {"id": "boom-radius", "fen": L["boom-radius"]["fen"], "moves": L["boom-radius"]["moves"],
    "title_ru": "Радиус взрыва", "title_en": "The blast radius",
    "text_ru": "Взрыв бьёт на восемь клеток вокруг точки взятия. Ферзь d3×e4 уничтожает коня f5 — и погибает сама. Железное правило атома: перед каждым взятием считайте фигуры в радиусе.",
    "text_en": "The blast hits the eight squares around the capture. Queen d3×e4 destroys the knight f5 — and dies itself. The iron rule of atomic: before every capture, count the pieces in the radius."},
   {"id": "pawn-armor", "fen": "6k1/8/8/3p1p2/4p3/3Q4/8/K7 w - - 0 1", "moves": ["d3e4"],
    "title_ru": "Пешки — бронированная техника", "title_en": "Pawns — the armored force",
    "text_ru": "Пешки — единственные солдаты, которых взрыв не берёт. Чёрные пешки d5 и f5 стоят вплотную к полю взрыва e4 — и невредимы. Погибает только ферзь. Пешечная цепь — это крепость.",
    "text_en": "Pawns are the only soldiers the blast cannot touch. The black pawns d5 and f5 stand right next to the blast square e4 — unharmed. Only the queen dies. A pawn chain is a fortress."},
   {"id": "own-king", "fen": L["own-king"]["fen"], "moves": L["own-king"]["moves"],
    "title_ru": "Запрещённый подвиг", "title_en": "The forbidden exploit",
    "text_ru": "Ладья h1 бьёт пешку h6, но взрыв накрывает своего короля h7 — ход запрещён. Атом прощает всё, кроме самоубийства короля.",
    "text_en": "The rook h1 captures the pawn h6, but the blast covers your own king h7 — the move is forbidden. Atomic forgives everything except the king's suicide."},
   {"id": "kings-adjacent", "fen": L["kings-adjacent"]["fen"], "moves": L["kings-adjacent"]["moves"],
    "title_ru": "Короли — соседи", "title_en": "Kings — the neighbors",
    "text_ru": "Короли могут стоять вплотную: в атоме они не атакуют друг друга. Больше того — пока короли рядом, шахов нет вовсе. Чужой король — лучший щит.",
    "text_en": "Kings may stand side by side: in atomic they do not attack each other. Moreover — while the kings are adjacent, there are no checks at all. The enemy king is the best shield."}
 ]},
 {"part_ru": "Часть вторая. Тактика", "part_en": "Part two. Tactics", "chapters": [
   {"id": "boom-win", "fen": None, "moves": [],
    "title_ru": "Победа №1 — взрыв короля", "title_en": "Victory #1 — the king explosion",
    "text_ru": "Самая частая победа в атоме: белые бьют рядом с королём — король исчезает. Девять из десяти партий заканчиваются не матом, а взрывом. На доске — реальная задача из базы: найдите решающее взятие.",
    "text_en": "The most common win in atomic: White captures next to the king — the king vanishes. Nine of ten games end not with mate but with an explosion. The board shows a real task from the database: find the decisive capture."},
   {"id": "real-mate", "fen": L["real-mate"]["fen"], "moves": L["real-mate"]["moves"],
    "title_ru": "Победа №2 — тихий мат", "title_en": "Victory #2 — the quiet mate",
    "text_ru": "Ферзь идёт на f1 — прямо под бой белого короля — и это мат! Король не может взять ферзя: при взрыве погиб бы он сам. В атоме мат часто ставится фигурой, стоящей под боем, — классическая шахматная интуиция здесь подводит.",
    "text_en": "The queen steps to f1 — right into the white king's attack — and it is mate! The king cannot capture the queen: the explosion would kill the king itself. In atomic, mate is often delivered by a piece that is itself attacked — classical intuition fails here."},
   {"id": "queen-kamikaze", "fen": "r1b1k3/p1q5/n5pb/Qp1p1p2/2PP3P/4P3/PP4P1/RNB2RK1 w - - 13 24", "moves": ["a5c7"],
    "title_ru": "Ферзь-камикадзе", "title_en": "The kamikaze queen",
    "text_ru": "Из вашей партии: ферзь бьёт ферзя — и обе покидают доску. Размен через взрыв выгоден тому, кто заранее посчитал радиус и понял, чья позиция развалится. Нажмите «Показать ход».",
    "text_en": "From your own game: queen takes queen — and both leave the board. A trade through an explosion favors the one who counted the radius in advance and understood whose position falls apart. Press “Show the move”."}
 ]},
 {"part_ru": "Часть третья. Стратегия", "part_en": "Part three. Strategy", "chapters": [
   {"id": "pawn-chain", "fen": "5rk1/5ppp/8/8/8/8/5PPP/5RK1 w - - 0 1", "moves": [],
    "title_ru": "Пешечная цепь — крепость короля", "title_en": "The pawn chain — the king's fortress",
    "text_ru": "Классическая крепость: король за цепью f7-g6-h7. Взрыв не берёт пешки, конь и слон не пробивают их без помощи. Строите дом — стройте пешечную цепь. Ломаете чужую — зовите ферзя.",
    "text_en": "A classic fortress: the king behind the chain f7-g6-h7. The blast cannot take pawns; a knight or bishop cannot break them without help. Building a house? Build a pawn chain. Breaking someone else's? Call the queen."},
   {"id": "knight-hunter", "fen": "5rk1/5N2/8/8/8/8/8/K6 w - - 0 1", "moves": [],
    "title_ru": "Конь — охотник на королей", "title_en": "The knight — the king hunter",
    "text_ru": "Конь f7 уже бьёт ладью h8 и перепрыгивает пешечные заслоны, которые держат ферзя. Кони — главные охотники атома: они не боятся взрывов и атакуют поля, до которых ферзю не добраться.",
    "text_en": "The knight on f7 already attacks the rook h8 and jumps over the pawn screens that stop the queen. Knights are the chief hunters of atomic: they fear no blasts and reach what a queen cannot."},
   {"id": "checklist", "fen": None, "moves": [],
    "title_ru": "Контрольный список", "title_en": "The checklist",
    "text_ru": "Перед каждым взятием — три вопроса. 1) Кто исчезнет в радиусе? 2) Не взорвётся ли мой король? 3) Не открою ли я линию на своего короля? Считайте быстро — и вы будете играть на уровне F55555.",
    "text_en": "Before every capture — three questions. 1) Who vanishes in the radius? 2) Will my own king explode? 3) Am I opening a line against my king? Count fast — and you will play at the F55555 level."}
 ]}
]

print("== 6a. Дебюты ==")
bM = chess.variant.AtomicBoard()
_seqM = "g1f3 f7f6 b1c3 d7d5 e2e3 g7g6 d2d4 f8g7".split()
for _u in _seqM:
    _m = chess.Move.from_uci(_u)
    assert _m in bM.legal_moves, "нелегальный ход в табии: " + _u
    bM.push(_m)
main_fen = bM.fen()

COURSE.append({"part_ru": "Часть четвёртая. Дебюты", "part_en": "Part four. Openings", "chapters": [
  {"id": "opening-main", "fen": main_fen, "moves": [],
   "title_ru": "Главный дебют: 1.Кf3 f6 2.Кc3", "title_en": "The main opening: 1.Nf3 f6 2.Nc3",
   "text_ru": "Дебют №1 атома. Идеи: кони выходят первыми (f3/f6 — контроль e5/e4), пешки e3+d4 или e4 строят центр, слон c4/b5 нависает над f7/f2, конь прыгает g5. Чёрные отвечают d5/c6/e5 или g6. На доске — табия после 8 ходов.",
   "text_en": "Opening #1 of atomic. Ideas: knights come first (f3/f6 control e5/e4), pawns e3+d4 or e4 build the center, the bishop eyes c4/b5 against f7/f2, a knight jumps to g5. Black answers d5/c6/e5 or g6. The board shows the tabiya after 8 moves."},
  {"id": "openings-db", "fen": None, "moves": [],
   "title_ru": "Дебютный репертуар из базы", "title_en": "Opening repertoire from the database",
   "text_ru": "Статистика первых трёх ходов по всем 54 партиям базы: ваши, топ-игроков и бота. Смотрите, какие линии реально встречаются и с каким счётом.",
   "text_en": "Statistics of the first three moves across all 54 games of the database: yours, top players and the bot. See which lines really occur and with what score."},
  {"id": "opening-traps", "fen": None, "moves": [],
   "title_ru": "Дебютные ловушки", "title_en": "Opening traps",
   "text_ru": "Три классические ловушки атома. 1) Конь g5 прыгает f7/h7: двойной удар по пешкам и королю — не торопитесь их брать. 2) Ранний выход ферзя Qh5/Qh4: жертвуйте g3/g4 и гоните ферзя, теряя темп — у атакующего темп кончится. 3) Слоновые шахи b5/c4/g4 вынуждают ослаблять королевский фланг — заранее держите пешку f6/h6. Все три встречаются в партиях базы — смотрите раздел «Партии».",
   "text_en": "Three classic atomic traps. 1) A knight to g5 hits f7/h7: do not rush to capture those pawns. 2) An early queen raid Qh5/Qh4: push g3/g4 and chase it, gaining tempo — the attacker runs out of steam. 3) Bishop checks on b5/c4/g4 force king-side weakening — keep f6/h6 pawns ready. All three appear in the database games — see the Games section."}
]})

print("== 6b. Дебютная статистика из базы ==")
open_stats = {}
for g in games:
    bd = chess.variant.AtomicBoard()
    sans = []
    for u in g["m"][:6]:
        mvm = chess.Move.from_uci(u)
        sans.append(bd.san(mvm))
        bd.push(mvm)
    key = " ".join(sans)
    e = open_stats.setdefault(key, {"n": 0, "w": 0, "d": 0, "bl": 0, "sans": " ".join(sans)})
    e["n"] += 1
    if g["r"] == "1-0": e["w"] += 1
    elif g["r"] == "0-1": e["bl"] += 1
    else: e["d"] += 1
DATA_OPENINGS = sorted(open_stats.values(), key=lambda e: -e["n"])[:12]
print(f"  линий: {len(DATA_OPENINGS)}")

# приложим fen/moves из lessons (уже есть) + счётчик глав
n = 0
for part in COURSE:
    for ch in part["chapters"]:
        n += 1
        ch["num"] = n
        if ch["id"] in L and not ch["fen"]:
            ch["fen"] = L[ch["id"]]["fen"]
            ch["moves"] = L[ch["id"]]["moves"]
print(f"  Курс: {n} глав, {len(COURSE)} части")

from collections import Counter
openings = Counter()
for g in games:
    if g["src"] == "F55555":
        openings[" ".join(g["m"][:2])] += 1
top_open = openings.most_common(8)

print("== 7. Сохранение data.js ==")
out = {"games": games, "puzzles": puzzles, "lessons": lessons, "topOpen": top_open, "course": COURSE, "openings": DATA_OPENINGS, "exercises": EXERCISES}
with open(os.path.join(BASE, "data.js"), "w", encoding="utf-8") as f:
    f.write("const DATA = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";")
print(f"  games={len(games)}, puzzles={len(puzzles)}, lessons={len(lessons)}, size={os.path.getsize(os.path.join(BASE,'data.js'))//1024}KB")
print("ГОТОВО!")
