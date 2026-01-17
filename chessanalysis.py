import chess
import chess.pgn
import chess.engine
import sys
import argparse
import os
import random
from gtts import gTTS
from datetime import datetime
from pathlib import Path
from stockfish import Stockfish

# === CONFIGURATION ===
STOCKFISH_PATH = "C:/Users/admin/Downloads/Compressed/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"  # Change to your Stockfish binary path
# PGN_FILE = "C:/Users/admin/Downloads/123.pgn"                  # Change to your PGN file path
PGN_FILE = "C:/Users/admin/Downloads/Van Foreest, Jorden_vs_Jobava, Baadur_2025.11.30.pgn"
ENGINE_DEPTH = 15                      # Search depth for evaluation

game_data = {}

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
    global game_data

    game_data['white_move'] = 0
    game_data['black_move'] = 0

    game_data["White_Good"] = 0
    game_data["White_Blunder"] = 0
    game_data["White_Mistake"] = 0
    game_data["White_Neutral"] = 0

    game_data["Black_Good"] = 0
    game_data["Black_Blunder"] = 0
    game_data["Black_Mistake"] = 0
    game_data["Black_Neutral"] = 0

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
            # print(f"{board.fullmove_number}. {move.uci()} -> {verdict} ({diff:+} cp)")
            if eva_res == "": eva_res = verdict
            else: eva_res = eva_res + "," + verdict

            if board.turn == chess.BLACK:  # White just moved
                game_data['white_move'] += 1
                if verdict == "Good": game_data["White_Good"] += 1
                elif verdict == "Blunder": game_data["White_Blunder"] += 1
                elif verdict == "Mistake": game_data["White_Mistake"] += 1
                elif verdict == "Inaccuracy": game_data["White_Mistake"] += 1
                else: game_data["White_Neutral"] += 1
            else:  # Black just moved
                game_data['black_move'] += 1
                if verdict == "Good": game_data["Black_Good"] += 1
                elif verdict == "Blunder": game_data["Black_Blunder"] += 1
                elif verdict == "Mistake": game_data["Black_Mistake"] += 1
                elif verdict == "Inaccuracy": game_data["Black_Mistake"] += 1
                else: game_data["Black_Neutral"] += 1

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

# documentary feature
# Generate introduction text for the beginning
## Event, number of rounds, winner
# Generate brief introduction for each game
## Round number, who is black, who is white
## Evaluate the game is easy/medium/hard
## Highlight the important steps in game, how’d they impact to result

def readPGNFile(filepath):
    global game_data
    infor = {}
    with open(filepath) as pgn:
        game = chess.pgn.read_game(pgn)
        infor['Event'] = game.headers.get('Event', 'Unknown')
        infor['Date'] = game.headers.get('Date', 'Unknown')
        infor['Round'] = game.headers.get('Round', 'Unknown')
        infor['White'] = game.headers.get('White', 'Unknown')
        infor['Black'] = game.headers.get('Black', 'Unknown')
        infor['Result'] = game.headers.get('Result', 'Unknown')

        game_data = {}
        analyze_pgn(filepath)

        infor['white_move'] = game_data['white_move']
        infor['black_move'] = game_data['black_move']
        infor['White_Good'] = game_data['White_Good']
        infor['White_Blunder'] = game_data['White_Blunder']
        infor['White_Mistake'] = game_data['White_Mistake']
        infor['White_Neutral'] = game_data['White_Neutral']
        infor['Black_Good'] = game_data['Black_Good']
        infor['Black_Blunder'] = game_data['Black_Blunder']
        infor['Black_Mistake'] = game_data['Black_Mistake']
        infor['Black_Neutral'] = game_data['Black_Neutral']
        # print(game_data)
    
    return infor

overview_text = [
    'At the {Event} chess event, held on {Date}, {Winner} emerged as the champion after {Rounds} rounds, achieving {Win} victories, {Draw} draw, and {Lose} loss.', \
    '{Winner} claimed the championship title at the {Event} chess event, held on {Date}, concluding {Rounds} rounds with an outstanding record of {Win} victories, {Draw} draw, and {Lose} loss.', \
    '{Winner} clinched the {Event} chess championship, held on {Date}, finishing {Rounds} rounds with {Win} wins, {Draw} draw, and {Lose} loss.', \
    'At the renowned {Event} chess tournament, held on {Date}, Grandmaster {Winner} captured the championship title with a commanding performance. Over the course of {Rounds} competitive rounds, he distinguished himself by securing {Win} victories, earning {Draw} draw, and conceding only {Lose} loss, a record that underscored both his strategic brilliance and remarkable consistency.', \
    'Grandmaster {Winner} secured the championship title at the {Event} chess tournament, held on {Date}, delivering a commanding performance across {Rounds} rounds. His record of {Win} victories, {Draw} draw, and only {Lose} defeat underscored both his strategic brilliance and remarkable consistency against a strong field of competitors.'
]

round_text = [
    'In Round {Round}, {White} (White) faced {Black} (Black) in a {white_move}-move battle. {White} committed {White_Blunder} blunders and {White_Mistake} mistakes, while {Black} made {Black_Blunder} blunder and {Black_Mistake} mistakes. Despite the inaccuracies on both sides, {Winner} ultimately prevailed and secured the victory.',
    'In Round {Round}, {White} (White) faced {Black} (Black) in a {white_move}-move encounter. {White} committed {White_Blunder} blunders and {White_Mistake} mistakes, while {Black} recorded {Black_Blunder} blunder and {Black_Mistake} mistakes. Despite inaccuracies from both sides, {Winner} ultimately capitalized on his opponent’s errors and secured the victory.',
    'Round {Round} saw {White}, commanding the white pieces, clash with {Black} in black. The battle stretched across {white_move} moves, marked by tension and missteps. {White} faltered with {White_Blunder} blunders and {White_Mistake} mistakes, while {Black} stumbled once but pressed on despite {Black_Blunder} blunder and {Black_Mistake} mistakes of his own. In the end, it was {Winner} who seized the initiative, turning the tide and emerging triumphant.'
]

round_text_draw = [
    'In Round {Round}, {White} (White) faced {Black} (Black) in a {white_move}-move battle. {White} committed {White_Blunder} blunders and {White_Mistake} mistakes, while {Black} made {Black_Blunder} blunder and {Black_Mistake} mistakes. {White} and {Black} battled to a draw, with neither player able to break through.',
    'In Round {Round}, {White} (White) faced {Black} (Black) in a {white_move}-move encounter. {White} committed {White_Blunder} blunders and {White_Mistake} mistakes, while {Black} recorded {Black_Blunder} blunder and {Black_Mistake} mistakes. {White} and {Black} battled to a draw, with neither player able to break through.',
    'Round {Round} saw {White}, commanding the white pieces, clash with {Black} in black. The battle stretched across {white_move} moves, marked by tension and missteps. {White} faltered with {White_Blunder} blunders and {White_Mistake} mistakes, while {Black} stumbled once but pressed on despite {Black_Blunder} blunder and {Black_Mistake} mistakes of his own. {White} and {Black} battled to a draw, with neither player able to break through.'
]

overview = {}
players = {}
famous_player = {'Carlsen, Magnus', 'Nakamura, Hikaru', 'Caruana, Fabiano', 'Keymer, Vincent', 'Erigaisi Arjun', \
                 'Giri, Anish', 'Firouzja, Alireza', 'Praggnanandhaa R', 'Gukesh D', 'Wei, Yi', 'So, Wesley', \
                 'Abdusattorov, Nodirbek', 'Anand, Viswanathan', 'Rapport, Richard', 'Dominguez Perez, Leinier', \
                 'Vachier-Lagrave, Maxime', 'Duda, Jan-Krzysztof', 'Le, Quang Liem', 'Mamedyarov, Shakhriyar', \
                 'Aronian, Levon'}
famous_player_in_event = []
rounds_text = {}

def readPGNFiles(listdir):
    global overview
    global players
    global famous_player
    global famous_player_in_event
    global round_text
    global round_text_draw
    global rounds_text

    overview['Event'] = ""
    overview['Rounds'] = 0

    for f in os.listdir(listdir):
        file_path = os.path.join(listdir, f)
        if os.path.isfile(file_path):
            file_name, file_extension = os.path.splitext(file_path)
            if file_extension == ".pgn":
                print(file_name)
                infor = readPGNFile(file_path)
                
                if overview['Event'] == "":
                    overview['Event'] = infor['Event']
                    overview['Date'] = infor['Date']
                overview['Rounds'] += 1
                refine_result = infor['Result'].replace('1/2', '0.5')

                white_point = (float)(refine_result.split('-')[0])
                black_point = (float)(refine_result.split('-')[1])
                text_for_round = ""
                if white_point == black_point:
                    infor["Winner"] = ""
                    len_of_round_text_draw = len(round_text_draw)
                    num = random.randint(0, len_of_round_text_draw - 1)
                    text_for_round = round_text_draw[num]
                elif white_point > black_point:
                    infor["Winner"] = infor['White']
                    len_of_row_text = len(round_text)
                    num = random.randint(0, len_of_row_text - 1)
                    text_for_round = round_text[num]
                else:
                    infor["Winner"] = infor['Black']
                    len_of_row_text = len(round_text)
                    num = random.randint(0, len_of_row_text - 1)
                    text_for_round = round_text[num]

                text_for_round = text_for_round.replace('{Round}', (str)(infor['Round']))
                text_for_round = text_for_round.replace('{White}', (str)(infor['White']))
                text_for_round = text_for_round.replace('{Black}', (str)(infor['Black']))
                text_for_round = text_for_round.replace('{White_Blunder}', (str)(infor['White_Blunder']))
                text_for_round = text_for_round.replace('{White_Mistake}', (str)(infor['White_Mistake']))
                text_for_round = text_for_round.replace('{Black_Mistake}', (str)(infor['Black_Mistake']))
                text_for_round = text_for_round.replace('{Black_Blunder}', (str)(infor['Black_Blunder']))
                text_for_round = text_for_round.replace('{Winner}', (str)(infor['Winner']))
                text_for_round = text_for_round.replace('{white_move}', (str)(infor['white_move']))

                rounds_text[(str)(infor['Round'])] = text_for_round

                # print(infor)
                # print(round_text)

                if infor['White'] not in players:
                    player = {}
                    player['point'] = white_point
                    player['draw'] = 0
                    player['win'] = 0
                    player['lose'] = 0
                    if white_point == 0.5: player['draw'] = 1
                    elif white_point == 1: player['win'] = 1
                    elif white_point == 0: player['lose'] = 1
                    players[infor['White']] = player
                else:
                    if white_point == 0.5: players[infor['White']]['draw'] += 1
                    elif white_point == 1: players[infor['White']]['win'] += 1
                    elif white_point == 0: players[infor['White']]['lose'] += 1
                    players[infor['White']]['point'] += white_point

                if infor['Black'] not in players:
                    player = {}
                    player['point'] = black_point
                    player['draw'] = 0
                    player['win'] = 0
                    player['lose'] = 0
                    if black_point == 0.5: player['draw'] = 1
                    elif black_point == 1: player['win'] = 1
                    elif black_point == 0: player['lose'] = 1
                    players[infor['Black']] = player
                else:
                    if black_point == 0.5: players[infor['Black']]['draw'] += 1
                    elif black_point == 1: players[infor['Black']]['win'] += 1
                    elif black_point == 0: players[infor['Black']]['lose'] += 1
                    players[infor['Black']]['point'] += black_point

                # Check if player is famous
                if infor['White'] in famous_player:
                    famous_player_in_event.append(infor['White'])
                if infor['Black'] in famous_player:
                    famous_player_in_event.append(infor['Black'])

def findWinner():
    global players
    max_point = 0
    winner = ""
    for player in players:
        if players[player]['point'] > max_point:
            max_point = players[player]['point']
            winner = player
    return winner

if __name__ == "__main__":
    global args

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-in", help="PGN input", default="")
    parser.add_argument("--evaluation", "-eval", default=False, action="store_true", help="Add evaluation to PGN input")
    parser.add_argument("--documentary", "-doc", default=False, action="store_true", help="Create document base on PGN file")
    args = parser.parse_args()

    if args.evaluation is True:
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
    elif args.documentary is True:
        readPGNFiles(args.input)
        overview['Winner'] = findWinner()
        overview['Draw'] = players[overview['Winner']]['draw']
        overview['Win'] = players[overview['Winner']]['win']
        overview['Lose'] = players[overview['Winner']]['lose']
        print(f'Overview: {overview}')
        # print(famous_player_in_event)
        len_of_overview_text = len(overview_text)
        num = random.randint(0, len_of_overview_text - 1)
        introduction_text = overview_text[num]

        # Swap name from Carlsen, Magnus to Magnus Carlsen
        refine_name = ""
        if ", " in overview['Winner']:
            temp_name = overview['Winner'].split(", ")
            refine_name = temp_name[1] + ' ' + temp_name[0]
        else:
            refine_name = overview['Winner']
        introduction_text = introduction_text.replace('{Winner}', refine_name)

        introduction_text = introduction_text.replace('{Event}', overview['Event'])

        # Reformat datetime
        dt = datetime.strptime(overview['Date'], "%Y.%m.%d")
        formatted_date = dt.strftime("%B %d, %Y")
        introduction_text = introduction_text.replace('{Date}', formatted_date)

        introduction_text = introduction_text.replace('{Rounds}', (str)(overview['Rounds']))
        introduction_text = introduction_text.replace('{Win}', (str)(overview['Win']))
        introduction_text = introduction_text.replace('{Draw}', (str)(overview['Draw']))
        introduction_text = introduction_text.replace('{Lose}', (str)(overview['Lose']))
        print(introduction_text)
        print(rounds_text)

        speech = gTTS(text=introduction_text, lang="en", slow=False)
        speech.save("introduction_text.mp3")

        for one_round in rounds_text:
            round_speech = gTTS(text=rounds_text[one_round], lang="en", slow=False)
            round_speech.save(f'{one_round}_text.mp3')
