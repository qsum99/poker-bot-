"""
Flask API server for the Poker AI frontend.
Bridges the browser UI to the existing PokerGame engine.
"""

import sys
import io

# Fix Windows console encoding — game.py prints Unicode card symbols (♥♦♣♠)
# which crash on cp1252. Force UTF-8 to prevent silent bot failures.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from flask import Flask, jsonify, request, send_from_directory
from game import PokerGame, GamePhase
from player import Player, PlayerAction, PlayerStatus
from card import Card, Rank, Suit
import os
import time

app = Flask(__name__, static_folder="static", static_url_path="")

# ── Global game state ────────────────────────────────────────────────────────
game_instance = None
human_player_index = 0
HUMAN_NAME = "You"
BOT_NAMES = ["Ace", "Maverick", "Viper"]
STARTING_STACK = 1000
BIG_BLIND = 20

# ── Helpers ──────────────────────────────────────────────────────────────────

RANK_NAMES = {
    Rank.TWO: "2", Rank.THREE: "3", Rank.FOUR: "4", Rank.FIVE: "5",
    Rank.SIX: "6", Rank.SEVEN: "7", Rank.EIGHT: "8", Rank.NINE: "9",
    Rank.TEN: "10", Rank.JACK: "J", Rank.QUEEN: "Q", Rank.KING: "K", Rank.ACE: "A"
}
SUIT_NAMES = {
    Suit.SPADES: "spades", Suit.HEARTS: "hearts",
    Suit.DIAMONDS: "diamonds", Suit.CLUBS: "clubs"
}
SUIT_SYMBOLS = {
    Suit.SPADES: "♠", Suit.HEARTS: "♥",
    Suit.DIAMONDS: "♦", Suit.CLUBS: "♣"
}


def card_to_dict(card: Card) -> dict:
    return {
        "rank": RANK_NAMES[card.rank],
        "suit": SUIT_NAMES[card.suit],
        "symbol": SUIT_SYMBOLS[card.suit],
        "display": f"{RANK_NAMES[card.rank]}{SUIT_SYMBOLS[card.suit]}"
    }


def get_full_state(reveal_all=False) -> dict:
    """Build the full game state dict for the frontend."""
    g = game_instance
    if g is None:
        return {"error": "No game in progress"}

    players = []
    for i, p in enumerate(g.players):
        player_data = {
            "name": p.name,
            "stack": p.stack,
            "status": p.status.value,
            "bet_amount": p.bet_amount,
            "is_human": i == human_player_index,
            "is_dealer": i == g.button_position,
            "is_active": i == g.active_player_index and p.can_make_action(),
            "cards": []
        }
        # Show cards for human player, and for all players at showdown
        if i == human_player_index or reveal_all or g.phase == GamePhase.SHOWDOWN:
            player_data["cards"] = [card_to_dict(c) for c in p.hole_cards]
        elif p.hole_cards:
            player_data["cards"] = [{"rank": "?", "suit": "back", "symbol": "", "display": "??"} for _ in p.hole_cards]

        players.append(player_data)

    community = [card_to_dict(c) for c in g.community_cards]

    # Determine what actions human can take
    human = g.players[human_player_index]
    call_amount = max(0, g.current_bet - human.bet_amount)
    can_act = (
        g.active_player_index == human_player_index
        and human.can_make_action()
        and g.phase != GamePhase.SHOWDOWN
    )

    actions = []
    if can_act:
        if call_amount == 0:
            actions.append({"type": "check", "label": "Check", "amount": 0})
            actions.append({"type": "bet", "label": "Bet", "min": g.big_blind, "max": human.stack})
        else:
            actions.append({"type": "fold", "label": "Fold", "amount": 0})
            actions.append({"type": "call", "label": f"Call ${call_amount}", "amount": call_amount})
            if human.stack > call_amount:
                actions.append({
                    "type": "raise", "label": "Raise",
                    "min": g.current_bet + g.big_blind,
                    "max": human.stack + human.bet_amount
                })
        actions.append({"type": "all_in", "label": f"All In ${human.stack}", "amount": human.stack})

    # Build action history for display
    history = []
    for phase_name, player_name, action_val, amount in g.action_history:
        history.append({
            "phase": phase_name,
            "player": player_name,
            "action": action_val,
            "amount": amount
        })

    return {
        "phase": g.phase.value,
        "pot": g.pot,
        "current_bet": g.current_bet,
        "big_blind": g.big_blind,
        "hand_number": g.hand_number,
        "community_cards": community,
        "players": players,
        "available_actions": actions,
        "action_history": history,
        "hand_winners": [
            {"game": w[0], "winner": w[1], "amount": w[2]}
            for w in g.hand_winners
        ] if g.hand_winners else [],
        "is_hand_over": g.phase == GamePhase.SHOWDOWN
    }


def auto_play_bots():
    """Advance the game by letting AI bots play until it's the human's turn or hand ends."""
    g = game_instance
    max_iters = 50  # safety limit
    iters = 0

    while iters < max_iters:
        iters += 1

        if g.phase == GamePhase.SHOWDOWN:
            break

        # Check if only one active player remains with matched bet
        current_player = g.players[g.active_player_index]
        if g.num_active_players() == 1 and current_player.bet_amount == g.current_bet:
            g.advance_game_phase()
            g.display_game_state()
            continue

        if g.active_player_index == human_player_index:
            if current_player.can_make_action():
                break  # Human's turn
            else:
                # Human is folded/all-in, advance
                g.active_player_index = (g.active_player_index + 1) % len(g.players)
                g._adjust_active_player_index()
                continue

        player = g.players[g.active_player_index]
        if not player.can_make_action():
            g.active_player_index = (g.active_player_index + 1) % len(g.players)
            g._adjust_active_player_index()
            continue

        # Let AI decide
        try:
            g.get_player_input()
        except Exception as e:
            print(f"Bot {player.name} error: {e}, forcing fold")
            g.player_action(PlayerAction.FOLD, 0)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def serve_index():
    return send_from_directory("static", "index.html")


@app.route("/api/new-game", methods=["POST"])
def new_game():
    global game_instance
    data = request.get_json(silent=True) or {}
    stack = data.get("stack", STARTING_STACK)
    blind = data.get("blind", BIG_BLIND)

    players = [Player(HUMAN_NAME, stack)]
    for name in BOT_NAMES:
        players.append(Player(name, stack))

    game_instance = PokerGame(players, big_blind=blind)
    game_instance.start_new_hand()

    # Let bots play if they act before human
    auto_play_bots()

    return jsonify(get_full_state())


@app.route("/api/action", methods=["POST"])
def player_action():
    g = game_instance
    if g is None:
        return jsonify({"error": "No game in progress"}), 400

    if g.phase == GamePhase.SHOWDOWN:
        return jsonify({"error": "Hand is over. Start a new hand."}), 400

    if g.active_player_index != human_player_index:
        return jsonify({"error": "Not your turn"}), 400

    data = request.get_json()
    action_type = data.get("action", "fold")
    amount = int(data.get("amount", 0))

    action_map = {
        "fold": PlayerAction.FOLD,
        "check": PlayerAction.CHECK,
        "call": PlayerAction.CALL,
        "bet": PlayerAction.BET,
        "raise": PlayerAction.RAISE,
        "all_in": PlayerAction.ALL_IN,
    }

    action = action_map.get(action_type, PlayerAction.FOLD)
    success = g.player_action(action, amount)

    if not success:
        return jsonify({"error": "Invalid action", "state": get_full_state()}), 400

    # Auto-play bots after human acts
    auto_play_bots()

    return jsonify(get_full_state())


@app.route("/api/next-hand", methods=["POST"])
def next_hand():
    g = game_instance
    if g is None:
        return jsonify({"error": "No game in progress"}), 400

    # Check if any players are out and reset if needed
    active_count = sum(1 for p in g.players if p.stack > 0)
    if active_count <= 1:
        return jsonify({"error": "Game over — not enough players", "game_over": True}), 400

    success = g.start_new_hand()
    if not success:
        return jsonify({"error": "Cannot start new hand", "game_over": True}), 400

    auto_play_bots()
    return jsonify(get_full_state())


@app.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(get_full_state())


if __name__ == "__main__":
    print("Starting Poker AI server on http://localhost:5000")
    app.run(debug=True, port=5000)
