"""Recorded FT vocabulary, independent of the adapter and frozen encoder."""

import itertools

from tools.parity.scenarios import HOME, AWAY, e, encode_v2, encode_v3, wrap
from tools.parity.shot_cases import shot_snapshot
from tools.parity.snapshot import scalar, stats_rows
from tools.parity.vocabulary_evidence import free_throw_vocabulary


def catalog():
    families = [
        ("Flagrant", total, "Flagrant Type 1") for total in (1, 2, 3)
    ] + [("Clear Path", 2, "Clear Path")]
    families += [("", total, "Shooting") for total in (1, 2, 3)]
    families += [("Technical", total, "Technical") for total in (1, 2)]
    facts = {m["subtype"]: m["v2_action_type"] for m in free_throw_vocabulary()["mappings"]}
    for category, total, foul_type in families:
        subtypes = [
            "Free Throw" + (" " + category if category else "")
            + ("" if category == "Technical" and total == 1 else f" {i} of {total}")
            for i in range(1, total + 1)
        ]
        for outcomes in itertools.product((False, True), repeat=total):
            for substitute in (False, True):
                events = [
                    e("miss", 620),
                    e("rebound", 619),
                    e("foul", 600, AWAY, 11, subtype=foul_type),
                ]
                for attempt, made in enumerate(outcomes, 1):
                    if substitute and attempt == total:
                        events.append(e("sub", 600, HOME, 2, incoming=6))
                    events.append(
                        e(
                            "ft",
                            category=category,
                            attempt=attempt,
                            total=total,
                            made=made,
                        )
                    )
                    if not made:
                        if not category and attempt == total:
                            events.append(e("rebound", 599, AWAY, 11))
                        else:
                            events.append(e("rebound", 600, HOME, 0))
                if category:
                    events += [e("make", 580), e("make", 560, AWAY, 11)]
                else:
                    events += [e("make", 580, AWAY, 11), e("make", 560)]
                yield dict(
                    name="{}_{}_{}_sub{}".format(
                        (category or "regular").lower().replace(" ", "_"),
                        total,
                        "".join("M" if m else "X" for m in outcomes),
                        int(substitute),
                    ),
                    total=total,
                    category=category,
                    subtypes=subtypes,
                    v2_action_types=[facts[s] for s in subtypes],
                    outcomes=outcomes,
                    substitute=substitute,
                    events=wrap(events),
                )


def v2_inputs(case):
    rows = encode_v2(case["events"])
    for row, code, subtype, made in zip(
        (r for r in rows if r["EVENTMSGTYPE"] == 3),
        case["v2_action_types"], case["subtypes"], case["outcomes"],
    ):
        row["EVENTMSGACTIONTYPE"] = code
        row["NEUTRALDESCRIPTION"] = ("" if made else "MISS ") + "Player1 " + subtype
    coordinates = {
        r["EVENTNUM"]: (100, 120) for r in rows if r["EVENTMSGTYPE"] in (1, 2)
    }
    return rows, coordinates


def v3_inputs(case):
    rows = encode_v3(case["events"])
    for row, subtype, made in zip(
        (r for r in rows if r["actionType"] == "Free Throw"),
        case["subtypes"], case["outcomes"],
    ):
        row["subType"] = subtype
        row["description"] = ("" if made else "MISS ") + "Player1 " + subtype
    for row in rows:
        if row["actionType"] in ("Made Shot", "Missed Shot"):
            row.update(xLegacy=100, yLegacy=120)
    return rows


def free_throw_snapshot(loaded):
    result = shot_snapshot(loaded)
    result["free_throw_details"] = [
        scalar(
            dict(
                event_id=event.event_num,
                properties={
                    name: getattr(event, name)
                    for name in (
                        "event_action_type",
                        "is_made",
                        "is_ft_1_of_1",
                        "is_ft_1_of_2",
                        "is_ft_2_of_2",
                        "is_ft_1_of_3",
                        "is_ft_2_of_3",
                        "is_ft_3_of_3",
                        "is_first_ft",
                        "is_end_ft",
                        "is_flagrant_ft",
                        "is_technical_ft",
                        "is_away_from_play_ft",
                        "is_inbound_foul_ft",
                        "is_transition_take_foul_ft",
                        "is_ft_1pt",
                        "is_ft_2pt",
                        "is_ft_3pt",
                        "shot_value",
                        "num_ft_for_trip",
                        "free_throw_type",
                    )
                },
                foul=(event.foul_that_led_to_ft.event_num
                      if event.foul_that_led_to_ft is not None else None),
                efficiency_event=event.event_for_efficiency_stats.event_num,
                event_stats=stats_rows(event.event_stats),
            )
        )
        for event in loaded.events
        if event.event_type == 3
    ]
    return result
