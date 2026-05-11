from enum import Enum
from typing import List, Tuple
from dataclasses import dataclass
from card import Card
from math import ceil


class PlayerAction(Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all-in"


class PlayerStatus(Enum):
    ACTIVE = "active"
    FOLDED = "folded"
    ALL_IN = "all-in"
    OUT = "out"


@dataclass
class Player:
    name: str
    stack: int
    uuid: int = 0
    status: PlayerStatus = PlayerStatus.ACTIVE
    hole_cards: List[Card] = None
    bet_amount: int = 0

    # ── Class-level model cache (loaded once, shared) ─────────────────────
    _model_data: dict = None

    def __post_init__(self):
        if self.hole_cards is None:
            self.hole_cards = []

    def reset_for_new_hand(self):
        self.hole_cards = []
        self.status = PlayerStatus.ACTIVE if self.stack > 0 else PlayerStatus.OUT
        self.bet_amount = 0

    def can_make_action(self) -> bool:
        return self.status in [PlayerStatus.ACTIVE]

    def take_action(self, action: PlayerAction, amount: int = 0) -> Tuple[PlayerAction, int]:
        if amount < 0:
            raise ValueError("Amount cannot be negative.")

        amount = ceil(amount)
        if action == PlayerAction.FOLD:
            self.status = PlayerStatus.FOLDED
            return action, 0

        if action == PlayerAction.CALL:
            max_bet = min(amount, self.stack)
            self.stack -= max_bet
            self.bet_amount += max_bet
            if self.stack == 0:
                self.status = PlayerStatus.ALL_IN
                return PlayerAction.ALL_IN, max_bet
            return PlayerAction.CALL, max_bet

        if action in [PlayerAction.BET, PlayerAction.RAISE]:
            max_bet = min(amount, self.stack)
            delta = max_bet - self.bet_amount

            if action == PlayerAction.RAISE:
                max_bet = min(amount - self.bet_amount, self.stack)

            if max_bet == self.stack:
                self.stack -= max_bet
                self.bet_amount += max_bet
            else:
                self.stack -= delta
                self.bet_amount += delta

            if self.stack == 0:
                self.status = PlayerStatus.ALL_IN
                return PlayerAction.ALL_IN, max_bet

            return action, delta

        if action == PlayerAction.ALL_IN:
            actual = self.stack
            self.bet_amount += self.stack
            self.stack = 0
            self.status = PlayerStatus.ALL_IN
            return PlayerAction.ALL_IN, actual

        return action, 0

    def action(self, game_state: list, action_history: list) -> Tuple[PlayerAction, int]:
        """
        Uses the pre-trained CFR model (model1m.pkl) to choose the best action.

        Parameters:
            game_state     : list from game.get_game_state()
                             [card1, card2, comm1..5, pot, current_bet, blind,
                              active_idx, num_players, stacks..., hand_number]
            action_history : list of (phase, name, action, amount) tuples

        Returns:
            (PlayerAction, amount)
        """
        import os, pickle, random
        import numpy as np
        from card import Rank, Suit
        from hand_evaluator import HandEvaluator

        # DEBUG: Add early return to test
        #print(f"[DEBUG] {self.name}.action() called - hole cards: {[game_state[0], game_state[1]]}")

        # ── 1. Load model once ────────────────────────────────────────────
        if Player._model_data is None:
            model_path = os.path.join(os.path.dirname(__file__), "model1m.pkl")
            with open(model_path, "rb") as f:
                Player._model_data = pickle.load(f)

        strategy    = Player._model_data["strategy"]
        eq_clusters = Player._model_data["equity_clusters"]

        # ── 2. Parse game state ───────────────────────────────────────────
        hole        = [game_state[0], game_state[1]]
        comm        = list(game_state[2:7])
        pot         = int(game_state[7])
        current_bet = int(game_state[8])
        blind       = int(game_state[9])
        active_idx  = int(game_state[10])
        num_players = int(game_state[11])

        # ── 3. Determine street ───────────────────────────────────────────
        n_comm = sum(1 for c in comm if c != 0)
        street = 'pf' if n_comm == 0 else 'fl' if n_comm == 3 else 'tu' if n_comm == 4 else 'ri'

        # ── 4. Determine position ─────────────────────────────────────────
        positions = ['blind', 'ep', 'mp', 'lp', 'btn']
        n = max(num_players, 1)
        seat = active_idx % n
        if n <= 2:
            pos_idx = seat % 2
        elif n == 3:
            pos_idx = {0: 0, 1: 4, 2: 1}.get(seat, 1)
        elif n == 4:
            pos_idx = {0: 0, 1: 1, 2: 3, 3: 4}.get(seat, 1)
        else:
            pos_idx = seat % 5
        position = positions[min(pos_idx, 4)]

        # ── 5. Monte Carlo equity estimate ────────────────────────────────
        def card_from_idx(idx):
            suit_i   = (idx - 1) // 13
            rank_val = (idx - 1) % 13 + 2
            return Card(Rank(rank_val), Suit(suit_i))

        equity = 0.5  # default
        if hole[0] != 0:
            hole_cards = [card_from_idx(i) for i in hole if i != 0]
            comm_cards = [card_from_idx(i) for i in comm if i != 0]
            known      = set(hole + [c for c in comm if c != 0])
            remaining  = [i for i in range(1, 53) if i not in known]
            num_opponents = max(num_players - 1, 1)
            wins = ties = total = 0
            for _ in range(300):
                random.shuffle(remaining)
                ptr = 0
                opp_hands = []
                for _ in range(num_opponents):
                    opp_hands.append([remaining[ptr], remaining[ptr + 1]])
                    ptr += 2
                needed    = 5 - len(comm_cards)
                full_comm = comm_cards + [card_from_idx(i) for i in remaining[ptr: ptr + needed]]
                if len(full_comm) < 5:
                    continue
                our   = HandEvaluator.evaluate_hand(hole_cards, full_comm)
                our_s = (our.hand_rank.value, our.hand_value)
                best_opp = (0, (0,))
                for oh in opp_hands:
                    oc  = [card_from_idx(i) for i in oh]
                    o   = HandEvaluator.evaluate_hand(oc, full_comm)
                    o_s = (o.hand_rank.value, o.hand_value)
                    if o_s > best_opp:
                        best_opp = o_s
                if our_s > best_opp:
                    wins += 1
                elif our_s == best_opp:
                    ties += 1
                total += 1
            if total > 0:
                equity = (wins + 0.5 * ties) / total

        # ── 5a. Board Texture Evaluation (Wet vs Dry) ─────────────────────
        is_wet_board = False
        comm_eval = [card_from_idx(i) for i in comm if i != 0]
        if len(comm_eval) >= 3:
            suits = [c.suit.value for c in comm_eval]
            ranks = sorted([c.rank.value for c in comm_eval])
            max_suit = max([suits.count(s) for s in set(suits)]) if suits else 0
            straight_draw = any(ranks[i+2] - ranks[i] <= 4 for i in range(len(ranks) - 2)) if len(ranks) >= 3 else False
            if max_suit >= 3 or straight_draw:
                is_wet_board = True

        # ── 6. "Poker Master" Adjustments & Opponent Modeling ──────────────────
        hand_number = int(game_state[-1])
        call_amt    = max(0, current_bet - self.bet_amount)
        pot_odds    = call_amt / (pot + call_amt) if (pot + call_amt) > 0 else 0

        # Opponent Tracking (Wrapped tightly to prevent tournament crashes)
        is_maniac = False
        is_nit = False
        is_station = False
        aggressor = None
        avg_vpip = 0.0
        
        try:
            if not hasattr(self, 'opp_stats'):
                self.opp_stats = {}
                self.last_hist_len = 0
                
            while self.last_hist_len < len(action_history):
                item = action_history[self.last_hist_len]
                p_phase, p_name, act_val, p_amt = item
                
                if p_name != self.name:
                    if p_name not in self.opp_stats:
                        self.opp_stats[p_name] = {'vpip': 0, 'pfr': 0, 'bets': 0, 'calls': 0}
                    
                    if p_phase == "pre-flop":
                        if act_val in ["bet", "raise", "all-in"]:
                            self.opp_stats[p_name]['vpip'] += 1
                            self.opp_stats[p_name]['pfr'] += 1
                        elif act_val == "call":
                            self.opp_stats[p_name]['vpip'] += 1
                    else:
                        if act_val in ["bet", "raise", "all-in"]:
                            self.opp_stats[p_name]['bets'] += 1
                        elif act_val == "call":
                            self.opp_stats[p_name]['calls'] += 1
                
                self.last_hist_len += 1

            # Classify last aggressor or table mood
            recent_history = action_history[-30:] if len(action_history) > 30 else action_history
            for item in reversed(recent_history):
                if item[0] in ["showdown", "setup"]:
                    break
                if item[2] in ["raise", "bet", "all-in"] and item[1] != self.name:
                    aggressor = item[1]
                    break

            hands_played = max(1, hand_number)
            if aggressor and aggressor in self.opp_stats:
                stats = self.opp_stats[aggressor]
                vpip_idx = stats['vpip'] / hands_played
                pfr_idx = stats['pfr'] / hands_played
                
                if vpip_idx > 0.80 and pfr_idx > 0.50:
                    is_maniac = True
                elif vpip_idx < 0.25 and pfr_idx < 0.15 and hands_played > 5:
                    is_nit = True
            
            # If no explicit aggressor and table plays lots of post-flop hands
            avg_vpip = sum(st['vpip'] for st in self.opp_stats.values()) / (len(self.opp_stats) * hands_played) if self.opp_stats else 0
            if avg_vpip > 0.70 and not is_maniac:
                is_station = True
        except Exception:
            pass  # Failsafe: Continue with baseline GTO if tracking bugs out

        # Bayesian & Positional Equity Engine
        discounted_equity = equity
        
        # Texture penalty
        if is_wet_board:
            discounted_equity *= 0.85
            
        if pot > blind * 4 and street != 'pf':
            discounted_equity *= 0.85
        if pot > blind * 8:
            discounted_equity *= 0.80

        # Positional Modifier
        if position in ['BTN', 'CO']:
            discounted_equity *= 1.15
        elif position in ['SB', 'BB', 'UTG']:
            discounted_equity *= 0.90
            
        discounted_equity = min(1.0, discounted_equity)

        # Compute strategy key buckets with discounted equity
        centroids = eq_clusters.get(street, eq_clusters.get('pf'))
        eq_bkt    = int(np.argmin(np.abs(centroids - discounted_equity)))

        # Pot bucket: pot / blind ratio → 0-7
        ratio = pot / max(blind, 1)
        pot_bkt = 7
        for b, t in enumerate([1, 2, 4, 6, 10, 15, 20]):
            if ratio < t:
                pot_bkt = b
                break

        # Bet count this street (capped at 1)
        phase_map = {'pf': 'pre-flop', 'fl': 'flop', 'tu': 'turn', 'ri': 'river'}
        phase = phase_map.get(street, street)
        bet_cnt = min(
            sum(1 for e in action_history if e[0] == phase and e[2] in ('raise', 'bet')),
            1
        )

        # ── 7. Strategy table lookup ──────────────────────────────────────
        key   = f"{street}_{position}_{eq_bkt}_{pot_bkt}_{bet_cnt}"
        probs = strategy.get(key)

        # Fallback: try alternate bet_count
        if probs is None:
            for bc in [0, 1]:
                probs = strategy.get(f"{street}_{position}_{eq_bkt}_{pot_bkt}_{bc}")
                if probs is not None:
                    break

        # ── 8. Equity-based heuristic fallback ───────────────────────────
        if probs is None:
            if discounted_equity < 0.30:
                if call_amt == 0: return PlayerAction.CHECK, 0
                # Don't blindly fold if pot odds are insanely good
                if pot_odds < 0.10 and discounted_equity > pot_odds:
                    return PlayerAction.CALL, call_amt
                return PlayerAction.FOLD, 0
            if discounted_equity < 0.50:
                return (PlayerAction.CHECK, 0) if call_amt == 0 else (PlayerAction.CALL, call_amt)
            if discounted_equity < 0.70:
                if call_amt == 0:
                    return PlayerAction.BET, max(blind, int(0.75 * pot))
                return PlayerAction.CALL, call_amt
            target = int(current_bet + 1.5 * max(pot, blind))
            target = min(target, self.stack + self.bet_amount)
            if target <= current_bet or current_bet == 0:
                return PlayerAction.BET, max(blind * 2, int(pot * 0.75))
            return PlayerAction.RAISE, target

        # ── 9. Dynamic Sampling (Early Risk & Opponent Analysis) ────────
        probs = np.clip(np.array(probs, dtype=float), 0, None)
        if probs.sum() <= 0:
            probs = np.ones(len(probs))
        probs /= probs.sum()

        spr = self.stack / max(pot, blind)

        # Early game risk-taking: Play wider and more aggressively in first 10 hands pre-flop
        if hand_number < 10 and street == 'pf':
            # Boost raise probabilities to establish table presence
            probs[2] *= 1.2
            probs[3] *= 1.3
        
        # Stack-to-Pot Ratio dampening (prevents suicidal all-ins when deep)
        if spr > 10:
            probs[5] *= 0.05; probs[4] *= 0.2; probs[3] *= 0.5
        # ── Pure Tight-Aggressive (TAG) Mathematical Baseline ──
        # To win consistently against chaos bots, NEVER bleed chips on weak hands
        # while extracting maximum aggressive value on strong hands.
        
        if discounted_equity < 0.50:
            # Mathematically at a disadvantage. Play TIGHT: No raising, fold to aggression.
            probs[2] = probs[3] = probs[4] = probs[5] = 0.0
            if call_amt > blind:
                probs[1] = 0.0 # Don't just call
                probs[0] = 1.0 # Force fold

        elif discounted_equity > 0.65 and street in ['fl', 'tu', 'ri']:
            # Massive mathematical advantage. Play highly AGGRESSIVE!
            probs[0] = probs[1] = 0.0 # Do not fold, do not check!
            probs[3] *= 1.5
            probs[4] *= 2.0
            if discounted_equity > 0.80 and spr < 10:
                probs[5] *= 2.0 # Force all-ins if extremely strong

        probs = np.clip(probs, 0, None)
        s = probs.sum()
        probs /= s if s > 0 else 1.0

        idx = int(np.random.choice(len(probs), p=probs))

        # ── 10. Convert model index → PlayerAction ────────────────────────
        if idx == 0:
            action, amount = PlayerAction.FOLD, 0
        elif idx == 1:
            action = PlayerAction.CHECK if call_amt == 0 else PlayerAction.CALL
            amount = 0 if call_amt == 0 else call_amt
        elif idx == 5:
            action, amount = PlayerAction.ALL_IN, self.stack
        else:
            mult   = {2: 0.5, 3: 1.0, 4: 2.0}[idx]
            
            # ── Dynamic Sizing ──
            if is_nit and current_bet == 0:
                target_amount = blind * 2
            elif is_station and discounted_equity > 0.65:
                target_amount = int(3.0 * max(pot, blind))
            else:
                target_amount = int(current_bet + mult * max(pot, blind))
                
            target = max(target_amount, current_bet + blind)
            target = min(target, self.stack + self.bet_amount)
            if target <= current_bet:
                action = PlayerAction.CHECK if call_amt == 0 else PlayerAction.CALL
                amount = 0 if call_amt == 0 else call_amt
            elif current_bet == 0:
                action, amount = PlayerAction.BET, target
            else:
                action, amount = PlayerAction.RAISE, target

        # ── 11. Final "Master" Guardrails (Pure Math) ────────────────────

        # A. Pot Odds call guard
        if action == PlayerAction.FOLD:
            if call_amt > 0 and discounted_equity > (pot_odds + 0.05):
                action, amount = PlayerAction.CALL, call_amt

        # B. ALL-IN guard: Do not gamble standard stacks without massive equity (>80%)
        if action == PlayerAction.ALL_IN and spr > 2.0 and discounted_equity < 0.80:
            if discounted_equity < 0.55:
                action, amount = PlayerAction.FOLD, 0
            elif call_amt == 0:
                action, amount = PlayerAction.CHECK, 0
            else:
                action, amount = PlayerAction.CALL, call_amt

        # C. Bet/Raise size cap: scale max risk to equity weakness
        if action in [PlayerAction.RAISE, PlayerAction.BET]:
            max_risk = (
                0.30 * self.stack if discounted_equity < 0.55 else
                0.50 * self.stack if discounted_equity < 0.65 else
                1.00 * self.stack
            )
            if amount > max_risk:
                capped = int(max_risk)
                if capped <= current_bet + blind:
                    action = PlayerAction.CHECK if call_amt == 0 else PlayerAction.CALL
                    amount = 0 if call_amt == 0 else call_amt
                elif current_bet == 0:
                    action, amount = PlayerAction.BET, capped
                else:
                    action, amount = PlayerAction.RAISE, capped

        # Re-verify Pot Odds on the new action if it was downgraded to fold
        if action == PlayerAction.FOLD and call_amt == 0:
            action, amount = PlayerAction.CHECK, 0

        # Never CHECK when there's an outstanding bet
        if action == PlayerAction.CHECK and call_amt > 0:
            action, amount = PlayerAction.CALL, call_amt

        # Ensure we never return a negative amount
        amount = max(0, amount)

        return action, amount
