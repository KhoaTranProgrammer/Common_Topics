import chess
import chess.pgn
import chess.engine
import sys
import argparse
import os
from pathlib import Path
from stockfish import Stockfish

# === CONFIGURATION ===
STOCKFISH_PATH = "C:/Users/admin/Downloads/Compressed/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"  # Change to your Stockfish binary path
# PGN_FILE = "C:/Users/admin/Downloads/123.pgn"                  # Change to your PGN file path
PGN_FILE = "C:/Users/admin/Downloads/Van Foreest, Jorden_vs_Jobava, Baadur_2025.11.30.pgn"
ENGINE_DEPTH = 15                      # Search depth for evaluation

def evaluate_pgn(pgn_path, engine_path, depth=15):
    # Validate file paths
    if not Path(pgn_path).is_file():
        print(f"Error: PGN file '{pgn_path}' not found.")
        sys.exit(1)
    if not Path(engine_path).is_file():
        print(f"Error: Stockfish executable '{engine_path}' not found.")
        sys.exit(1)

    # Open PGN file
    with open(pgn_path, encoding="utf-8") as pgn:
        game = chess.pgn.read_game(pgn)
        print(game.mainline_moves())

    if game is None:
        print("Error: No valid game found in PGN.")
        sys.exit(1)

    # Start Stockfish engine
    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        board = game.board()
        move_number = 1

        print(f"Evaluating game: {game.headers.get('Event', 'Unknown Event')}")
        print("=" * 50)

        print(game.mainline_moves())

        # move = chess.Move.from_uci("e2e4")
        # board.san(move)

        for move in game.mainline_moves():
            board.push(move)

            # Get evaluation from Stockfish
            info = engine.analyse(board, chess.engine.Limit(depth=depth))
            score = info["score"].pov(board.turn)  # POV: perspective of side to move

            print(score)

            # Convert score to human-readable
            if score.is_mate():
                eval_str = f"# {score.mate()}"  # Mate in N
            else:
                eval_str = f"{score.score()/100:.2f}"  # Centipawns to pawns

            refine_move = str(move)
            refine_move = refine_move[2:]
            print(f"Move {move_number}: {refine_move} | Eval: {eval_str}")
            
            move_number += 1

THRESHOLDS = {
    "good": 50,       # cp gain >= 0.5 pawn
    "inaccuracy": -50, # cp loss between -0.5 and -1.0 pawn
    "mistake": -100,   # cp loss between -1.0 and -2.0 pawns
    "blunder": -200    # cp loss worse than -2.0 pawns
}

stockfish = Stockfish(path=STOCKFISH_PATH, parameters={"Threads": 2, "Minimum Thinking Time": 30})
stockfish.set_depth(ENGINE_DEPTH)

def eval_cp():
    """Return evaluation in centipawns (positive = white better)."""
    eval_info = stockfish.get_evaluation()
    if eval_info["type"] == "cp":
        return eval_info["value"]
    elif eval_info["type"] == "mate":
        # Large positive for mate in N for white, large negative for mate in N for black
        return 100000 if eval_info["value"] > 0 else -100000
    return 0

def classify_move(diff):
    """Classify move based on evaluation difference."""
    if diff >= THRESHOLDS["good"]:
        return "Good"
    elif diff <= THRESHOLDS["blunder"]:
        return "Blunder"
    elif diff <= THRESHOLDS["mistake"]:
        return "Mistake"
    elif diff <= THRESHOLDS["inaccuracy"]:
        return "Inaccuracy"
    else:
        return "Neutral"

def analyze_pgn(pgn_path):
    with open(pgn_path) as pgn:
        game = chess.pgn.read_game(pgn)
        board = game.board()

        print(f"Analyzing game: {game.headers.get('Event', 'Unknown')}")
        print("=" * 50)

        eva_res = ""

        for move in game.mainline_moves():
            # Set Stockfish to current position
            stockfish.set_fen_position(board.fen())
            before_eval = eval_cp()

            # Play the move
            board.push(move)
            stockfish.set_fen_position(board.fen())
            after_eval = eval_cp()

            # Determine evaluation change from the perspective of the side who moved
            if board.turn == chess.BLACK:  # White just moved
                diff = after_eval - before_eval
            else:  # Black just moved
                diff = before_eval - after_eval

            verdict = classify_move(diff)
            print(f"{board.fullmove_number}. {move.uci()} -> {verdict} ({diff:+} cp)")
            if eva_res == "": eva_res = verdict
            else: eva_res = eva_res + "," + verdict
    return eva_res

def append_to_file(filename, data):
    """
    Appends the given data to the specified file.
    Creates the file if it does not exist.
    """
    try:
        # Open file in append mode ('a') with UTF-8 encoding
        with open(filename, 'a', encoding='utf-8') as file:
            file.write('\n' + "Evaluate:" + data + '\n')  # Add newline after data
        print(f"Data appended successfully to '{filename}'.")
    except (OSError, IOError) as e:
        print(f"Error appending to file: {e}")

if __name__ == "__main__":
    global args

    # evaluate_pgn(PGN_FILE, STOCKFISH_PATH, ENGINE_DEPTH)
    # res = analyze_pgn(PGN_FILE)
    # append_to_file(PGN_FILE, res)

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-in", help="PGN input", default="")
    args = parser.parse_args()
    
    if os.path.isfile(args.input):
        res = analyze_pgn(args.input)
        append_to_file(args.input, res)
    else:
        for f in os.listdir(args.input):
            file_path = os.path.join(args.input, f)
            if os.path.isfile(file_path):
                file_name, file_extension = os.path.splitext(file_path)
                if file_extension == ".pgn":
                    res = analyze_pgn(file_path)
                    append_to_file(file_path, res)
