"""Offline evidence for the original data.nba.com ordering fallback."""

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from types import SimpleNamespace

from pbpstats.data_loader.data_nba.pbp.loader import DataNbaPbpLoader

from .decoder import V3DecodeError


@dataclass(frozen=True)
class V3EventOrder:
    """An independently recorded provider response, reviewed for this V3 input.

    Event numbers must identify the same events in both sources. This binding
    is explicit; the adapter never fetches a replacement order from the network.
    """

    source_bytes: bytes
    source: str
    pbp_sha256: str

    def decode(self, decoded):
        if not isinstance(self.source, str) or not self.source.strip():
            raise V3DecodeError("Event-order evidence requires source provenance")
        if hashlib.sha256(decoded.source_bytes).hexdigest() != self.pbp_sha256:
            raise V3DecodeError("Event-order evidence does not match the raw PBP hash")
        if not isinstance(self.source_bytes, bytes):
            raise V3DecodeError("Event-order evidence must be recorded JSON bytes")
        try:
            payload = json.loads(self.source_bytes)
            if payload["g"]["gid"] != decoded.context.game_id:
                raise V3DecodeError("Event-order evidence game identity disagrees")
            loaded = DataNbaPbpLoader(
                decoded.context.game_id,
                SimpleNamespace(load_data=lambda _: payload),
            )
            order = [(event.evt, event.period) for event in loaded.items]
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            if isinstance(error, V3DecodeError):
                raise
            raise V3DecodeError("Invalid recorded provider event order") from error
        if any(
            type(n) is not int or n < 0 or type(p) is not int or p < 1 for n, p in order
        ):
            raise V3DecodeError("Invalid provider event number or period")
        periods = {row["EVENTNUM"]: row["PERIOD"] for row in decoded.projected}
        matched = [(n, p) for n, p in order if n in periods]
        if Counter(n for n, _ in matched) != Counter(periods.keys()):
            raise V3DecodeError(
                "Provider event order must cover each source event exactly once"
            )
        if any(periods[n] != p for n, p in matched):
            raise V3DecodeError("Provider event period disagrees with source")
        return [n for n, _ in matched], dict(
            code="recorded_provider_order",
            source=self.source,
            sha256=hashlib.sha256(self.source_bytes).hexdigest(),
            pbp_sha256=self.pbp_sha256,
        )
