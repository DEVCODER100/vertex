"""Quiz question generators and reward rolls. Pure logic, no Discord code."""

from __future__ import annotations

from collections.abc import Container
from dataclasses import dataclass

import config
from games import rng
from quiz_data import COUNTRIES, TRIVIA

LETTERS = ["A", "B", "C", "D"]


@dataclass
class Question:
    kind: str                 # "flag" | "math" | "trivia"
    title: str
    prompt: str
    options: list[str]
    answer_index: int
    key: str                  # identifies the question so recent ones aren't repeated
    letters: bool = False     # True: buttons are A-D and options are listed in the embed
    image_url: str | None = None

    @property
    def labels(self) -> list[str]:
        return LETTERS[: len(self.options)] if self.letters else self.options

    @property
    def answer_text(self) -> str:
        return self.options[self.answer_index]


@dataclass
class Reward:
    coins: int
    credits: int
    xp: int


def flag_emoji(code: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - ord("a")) for c in code.lower())


def _shuffled(correct: str, wrong: list[str]) -> tuple[list[str], int]:
    options = [correct, *wrong]
    rng.shuffle(options)
    return options, options.index(correct)


def _pick(pool: list, recent: Container[str], key_of) -> object:
    fresh = [item for item in pool if key_of(item) not in recent]
    return rng.choice(fresh or pool)


# ---- flags ----------------------------------------------------------------


def make_flag(recent: Container[str] = ()) -> Question:
    code, name = _pick(COUNTRIES, recent, lambda c: f"flag:{c[0]}")
    wrong = rng.sample([n for c, n in COUNTRIES if c != code], 3)
    options, answer = _shuffled(name, wrong)
    return Question(
        kind="flag",
        title="Guess the Flag",
        prompt=f"{flag_emoji(code)}  Which country does this flag belong to?",
        options=options,
        answer_index=answer,
        key=f"flag:{code}",
        image_url=f"https://flagcdn.com/w320/{code}.png",
    )


# ---- math -----------------------------------------------------------------


def _numeric_options(answer: int, hints: tuple[int, ...] = ()) -> tuple[list[str], int]:
    offsets = {1, -1, 2, -2, 10, -10, 100, -100, *hints, *(-h for h in hints)}
    candidates = sorted({answer + o for o in offsets if o and answer + o >= 0} - {answer})
    wrong = rng.sample(candidates, 3)
    return _shuffled(f"{answer:,}", [f"{w:,}" for w in wrong])


def make_math(recent: Container[str] = ()) -> Question:
    for _ in range(10):
        op = rng.choice(["add", "sub", "mul"])
        if op == "add":
            a, b = rng.randint(12, 999), rng.randint(12, 999)
            text, answer, hints = f"{a:,} + {b:,}", a + b, ()
        elif op == "sub":
            a = rng.randint(30, 999)
            b = rng.randint(11, a - 1)
            text, answer, hints = f"{a:,} - {b:,}", a - b, ()
        else:
            a, b = rng.randint(3, 25), rng.randint(3, 15)
            text, answer, hints = f"{a} × {b}", a * b, (a, b)
        if f"math:{text}" not in recent:
            break
    options, index = _numeric_options(answer, hints)
    return Question(
        kind="math",
        title="Quick Math",
        prompt=f"What is **{text}**?",
        options=options,
        answer_index=index,
        key=f"math:{text}",
    )


# ---- trivia ---------------------------------------------------------------


def make_trivia(recent: Container[str] = ()) -> Question:
    question, correct, wrong = _pick(TRIVIA, recent, lambda t: f"trivia:{t[0]}")
    options, answer = _shuffled(correct, list(wrong))
    return Question(
        kind="trivia",
        title="Trivia",
        prompt=question,
        options=options,
        answer_index=answer,
        key=f"trivia:{question}",
        letters=True,
    )


_MAKERS = {"flag": make_flag, "math": make_math, "trivia": make_trivia}


def make_question(kind: str | None = None, recent: Container[str] = ()) -> Question:
    if kind is None or kind == "random":
        kinds = list(config.QUIZ_KIND_WEIGHTS)
        kind = rng.choices(kinds, weights=list(config.QUIZ_KIND_WEIGHTS.values()))[0]
    return _MAKERS[kind](recent)


# ---- rewards ----------------------------------------------------------------


def roll_reward() -> Reward:
    """One random reward (coins OR Credits), plus XP every time."""
    xp = rng.randint(*config.QUIZ_XP_RANGE)
    if rng.random() < config.QUIZ_CREDITS_CHANCE:
        return Reward(coins=0, credits=rng.randint(*config.QUIZ_CREDITS_RANGE), xp=xp)
    return Reward(coins=rng.randint(*config.QUIZ_COINS_RANGE), credits=0, xp=xp)
