"""Pure game logic (no Discord code), so the odds and rules can be tested exactly."""

from __future__ import annotations

import itertools
import math
import random

# One shared, unpredictable RNG for every game.
rng = random.SystemRandom()

# ---- bet parsing --------------------------------------------------------


def parse_amount(text: str, balance: int) -> int:
    """'500', '1,000', '5k', '1.5m', 'half', 'all' -> int. Raises ValueError with a friendly message."""
    t = text.strip().lower().replace(",", "").replace("_", "")
    if t in {"all", "max"}:
        amount = balance
    elif t == "half":
        amount = balance // 2
    else:
        multiplier = 1
        if t and t[-1] in "kmb":
            multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[t[-1]]
            t = t[:-1]
        try:
            value = float(t)
        except ValueError:
            raise ValueError("I couldn't read that amount. Try `500`, `5k`, `half` or `all`.") from None
        if not math.isfinite(value):
            raise ValueError("I couldn't read that amount. Try `500`, `5k`, `half` or `all`.")
        amount = round(value * multiplier)
    if amount <= 0:
        raise ValueError("The bet has to be more than 0.")
    return amount


# ---- coinflip / dice ----------------------------------------------------

COINFLIP_PAYOUT = 1.95      # total returned on a win, per 1 bet (stake included)
DICE_HILO_PAYOUT = 1.95     # high (4-6) or low (1-3)
DICE_EXACT_PAYOUT = 5.7     # exact number, 1 in 6


def payout(bet: int, multiplier: float) -> int:
    """Total coins returned for a winning bet (stake included), rounded down."""
    return int(bet * multiplier)


# ---- slots --------------------------------------------------------------

SLOT_WEIGHTS = {"🍒": 30, "🍋": 25, "🔔": 20, "⭐": 15, "💎": 8, "7️⃣": 2}
SLOT_TRIPLE = {"🍒": 5, "🍋": 10, "🔔": 14, "⭐": 28, "💎": 100, "7️⃣": 500}
SLOT_TWO_CHERRIES = 2  # exactly two cherries anywhere


def spin_reels() -> list[str]:
    return rng.choices(list(SLOT_WEIGHTS), weights=list(SLOT_WEIGHTS.values()), k=3)


def slot_multiplier(reels: list[str]) -> int:
    if reels[0] == reels[1] == reels[2]:
        return SLOT_TRIPLE[reels[0]]
    if reels.count("🍒") == 2:
        return SLOT_TWO_CHERRIES
    return 0


def slots_rtp() -> float:
    """Exact return-to-player: expected payout per 1 coin bet."""
    total = sum(SLOT_WEIGHTS.values())
    rtp = 0.0
    for combo in itertools.product(SLOT_WEIGHTS, repeat=3):
        probability = math.prod(SLOT_WEIGHTS[s] / total for s in combo)
        rtp += probability * slot_multiplier(list(combo))
    return rtp


# ---- blackjack ----------------------------------------------------------

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]
Card = tuple[str, str]


def hand_value(cards: list[Card]) -> int:
    total, aces = 0, 0
    for rank, _ in cards:
        if rank == "A":
            aces += 1
            total += 11
        elif rank in {"10", "J", "Q", "K"}:
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards: list[Card]) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


def card_str(card: Card) -> str:
    return f"`{card[0]}{card[1]}`"


def hand_str(cards: list[Card]) -> str:
    return " ".join(card_str(c) for c in cards)


class BlackjackGame:
    """Single-deck blackjack. Dealer stands on all 17s. Blackjack pays 3:2."""

    def __init__(self, bet: int) -> None:
        self.bet = bet
        self.deck: list[Card] = [(r, s) for r in RANKS for s in SUITS]
        rng.shuffle(self.deck)
        self.player: list[Card] = [self.deck.pop(), self.deck.pop()]
        self.dealer: list[Card] = [self.deck.pop(), self.deck.pop()]

    def hit(self) -> None:
        self.player.append(self.deck.pop())

    def play_dealer(self) -> None:
        while hand_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())

    @property
    def player_total(self) -> int:
        return hand_value(self.player)

    @property
    def dealer_total(self) -> int:
        return hand_value(self.dealer)

    def natural_outcome(self) -> tuple[str, int] | None:
        """Result if either side was dealt blackjack, else None. Returns (result, coins returned)."""
        player_bj, dealer_bj = is_blackjack(self.player), is_blackjack(self.dealer)
        if player_bj and dealer_bj:
            return "push", self.bet
        if player_bj:
            return "blackjack", self.bet + self.bet * 3 // 2
        if dealer_bj:
            return "lose", 0
        return None

    def outcome(self) -> tuple[str, int]:
        """Final result once the player is done. Plays out the dealer's hand. (result, coins returned)"""
        if self.player_total > 21:
            return "bust", 0
        self.play_dealer()
        if self.dealer_total > 21 or self.player_total > self.dealer_total:
            return "win", self.bet * 2
        if self.player_total == self.dealer_total:
            return "push", self.bet
        return "lose", 0
