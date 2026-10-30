"""The V2 code recorded for each V3 label the parser accepts.

The V3 parser decides from labels and writes no V2 code. These codes are the
evidence its native event classes are checked against: tests make the
original's event from a label's V2 code and compare the two decisions, and
tests/parity/test_paired_season.py checks each code against the V2 exports.
"""

# Non-shot codes are the V2 codes recorded for the same events in the paired
# 2024-25 exports (tests/parity/paired-season-2024.json). Inbound, Personal
# Block and Shooting Block are unobserved there; they keep the original's own
# named codes. A blank subtype is V2 code 0, e.g. the original's no-turnover.
FOULS = {
    "": 0,
    "Personal": 1,
    "Shooting": 2,
    "Loose Ball": 3,
    "Offensive": 4,
    "Inbound": 5,
    "Away From Play": 6,
    "Punching": 8,
    "Clear Path": 9,
    "Double Personal": 10,
    "Technical": 11,
    "Non-Unsportsmanlike Technical": 12,
    "Hanging Technical": 13,
    "Flagrant Type 1": 14,
    "Flagrant Type 2": 15,
    "Double Technical": 16,
    "Defense 3 Second": 17,
    "Delay Technical": 18,
    "Excess Timeout Technical": 25,
    "Offensive Charge": 26,
    "Personal Block": 27,
    "Personal Take": 28,
    "Shooting Block": 29,
    "Too Many Players Technical": 30,
    "Transition Take": 31,
    "Flopping": 32,
    "Bench": 33,
}
TURNOVERS = {
    "": 0,
    "Bad Pass": 1,
    "Lost Ball": 2,
    "Traveling": 4,
    "Double Dribble": 6,
    "Discontinue Dribble": 7,
    "3 Second Violation": 8,
    "5 Second Violation": 9,
    "8 Second Violation": 10,
    "Shot Clock Turnover": 11,
    "Inbound Turnover": 12,
    "Backcourt Turnover": 13,
    "Offensive Goaltending": 15,
    "Lane Violation": 17,
    "Jump Ball Violation": 18,
    "Kicked Ball Violation": 19,
    "Illegal Assist Turnover": 20,
    "Palming Turnover": 21,
    "10 Second Violaton": 24,
    "Punched Ball Turnover": 33,
    "Swinging Elbows Turnover": 34,
    "Basket from Below Turnover": 35,
    "Illegal Screen Turnover": 36,
    "Offensive Foul Turnover": 37,
    "Step Out of Bounds Turnover": 39,
    "Out of Bounds Lost Ball Turnover": 40,
    "Excess Timeout Turnover": 42,
    "Too Many Players Turnover": 44,
    "Out of Bounds - Bad Pass Turnover": 45,
}
VIOLATIONS = {
    "Delay Of Game": 1,
    "Defensive Goaltending": 2,
    "Lane": 3,
    "Jump Ball": 4,
    "Kicked Ball": 5,
    "Double Lane": 6,
}
# Code 1 is V2's placeholder rebound, which the original's is_placeholder reads.
REBOUNDS = {"Unknown": 0, "Normal Rebound": 1}
# V3 records a short timeout in 2015-16, 2016-17 and again in 2026-27; V2 codes
# it 2.
TIMEOUTS = {"Regular": 1, "Short": 2, "Coach Challenge": 7}
JUMP_BALLS = {"": 0, "Coach Challenge": 1}
REPLAYS = {
    "Support Ruling": 0,
    "Overturn Ruling": 1,
    "Altercation Ruling": 2,
    "Ruling Stands": 3,
    "Coach Challenge Support Ruling": 4,
    "Coach Challenge Overturn Ruling": 5,
    "Coach Challenge Ruling Stands": 6,
    "Replay Center": 7,
}
# V3 labels a flagrant 2 ejection "Other" from 2017-18 to 2025-26, but "First
# Flagrant Type 2" in 2015-16, 2016-17 and again in 2026-27; V2 codes it 3. A
# second-technical ejection is likewise "Second Technical" in those seasons,
# which V2 codes 1. 2026-27 V3 also labels an ejection "Second Flagrant Type 1",
# which no V2 export records; the original never reads an ejection's code.
EJECTIONS = {"Other": 4, "First Flagrant Type 2": 3, "Second Technical": 1}
# Free throws by attempt and total. Recorded V2 codes and native V3 labels are
# pinned independently in tests/parity/free-throw-vocabulary.json.
FREE_THROWS = {(1, 1): 10, (1, 2): 11, (2, 2): 12, (1, 3): 13, (2, 3): 14, (3, 3): 15}
FLAGRANT_FREE_THROWS = {
    (1, 1): 20, (1, 2): 18, (2, 2): 19,
    (1, 3): 27, (2, 3): 28, (3, 3): 29,
}
CLEAR_PATH_FREE_THROWS = {(1, 2): 25, (2, 2): 26}
TECHNICAL_FREE_THROWS = {(1, 2): 21, (2, 2): 22}
# A lone technical free throw, "Free Throw Technical", which the original reads
# as technical from its text.
TECHNICAL_FREE_THROW = 16
# Recorded only in the paired WNBA 2025 exports (tests/parity/paired-season-wnba-2025.json).
WNBA_TIMEOUTS = {"Official": 4, "Reset": 6}
WNBA_CLEAR_PATH_FREE_THROWS = {(1, 1): 40}
# Every supported subtype has recorded evidence in shot-vocabulary.json, and
# the paired 2024-25 exports record exactly these codes. Other codes once used
# for the same labels are historical (unresolved_aliases).
SHOT_CODES = {
    "Alley Oop Dunk Shot": 52,
    "Alley Oop Layup shot": 43,
    "Cutting Dunk Shot": 108,
    "Cutting Finger Roll Layup Shot": 99,
    "Cutting Layup Shot": 98,
    "Driving Dunk Shot": 9,
    "Driving Bank Hook Shot": 93,
    "Driving Reverse Dunk Shot": 109,
    "Driving Finger Roll Layup Shot": 75,
    "Driving Floating Bank Jump Shot": 102,
    "Driving Floating Jump Shot": 101,
    "Driving Hook Shot": 57,
    "Driving Layup Shot": 6,
    "Driving Reverse Layup Shot": 73,
    "Dunk Shot": 7,
    "Fadeaway Jump Shot": 63,
    "Fadeaway Bank shot": 83,
    "Finger Roll Layup Shot": 71,
    "Floating Jump shot": 78,
    "Hook Shot": 3,
    "Hook Bank Shot": 67,
    "Jump Bank Shot": 66,
    "Jump Shot": 1,
    "Layup Shot": 5,
    "Pullup Jump shot": 79,
    "Putback Layup Shot": 72,
    "Putback Dunk Shot": 87,
    "Reverse Layup Shot": 44,
    "Reverse Dunk Shot": 51,
    "Running Alley Oop Layup Shot": 100,
    "Running Alley Oop Dunk Shot": 106,
    "Running Dunk Shot": 50,
    "Running Finger Roll Layup Shot": 76,
    "Running Jump Shot": 2,
    "Running Layup Shot": 41,
    "Running Reverse Layup Shot": 74,
    "Running Reverse Dunk Shot": 110,
    "Running Pull-Up Jump Shot": 103,
    "Step Back Jump shot": 80,
    "Step Back Bank Jump Shot": 104,
    "Tip Dunk Shot": 107,
    "Tip Layup Shot": 97,
    "Turnaround Bank Hook Shot": 96,
    "Turnaround Bank shot": 85,
    "Turnaround Fadeaway Bank Jump Shot": 105,
    "Turnaround Fadeaway shot": 86,
    "Turnaround Hook Shot": 58,
    "Turnaround Jump Shot": 47,
}
FREE_THROW_CATEGORIES = {
    "Free Throw": FREE_THROWS,
    "Free Throw Flagrant": FLAGRANT_FREE_THROWS,
    "Free Throw Clear Path": {**CLEAR_PATH_FREE_THROWS, **WNBA_CLEAR_PATH_FREE_THROWS},
    "Free Throw Technical": TECHNICAL_FREE_THROWS,
}
# (V3 action type, V3 subtype) -> (V2 event type, V2 action type).
CODES = {
    **{("Made Shot", label): (1, code) for label, code in SHOT_CODES.items()},
    **{("Missed Shot", label): (2, code) for label, code in SHOT_CODES.items()},
    ("Free Throw", "Free Throw Technical"): (3, TECHNICAL_FREE_THROW),
    **{
        ("Free Throw", f"{category} {attempt} of {total}"): (3, code)
        for category, table in FREE_THROW_CATEGORIES.items()
        for (attempt, total), code in table.items()
    },
    **{("Rebound", label): (4, code) for label, code in REBOUNDS.items()},
    **{("Turnover", label): (5, code) for label, code in TURNOVERS.items()},
    **{("Foul", label): (6, code) for label, code in FOULS.items()},
    **{("Violation", label): (7, code) for label, code in VIOLATIONS.items()},
    **{
        ("Timeout", label): (9, code)
        for label, code in {**TIMEOUTS, **WNBA_TIMEOUTS}.items()
    },
    **{("Jump Ball", label): (10, code) for label, code in JUMP_BALLS.items()},
    **{("Ejection", label): (11, code) for label, code in EJECTIONS.items()},
    **{("Instant Replay", label): (18, code) for label, code in REPLAYS.items()},
    # Events V2 records with action type 0, whose kind the original never reads.
    ("Substitution", ""): (8, 0),
    ("period", "start"): (12, 0),
    ("period", "end"): (13, 0),
}


def labels(kind):
    """A kind's (subtype, V2 action type) pairs, sorted."""
    return sorted((subtype, code) for (k, subtype), (_, code) in CODES.items() if k == kind)
