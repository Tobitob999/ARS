"""
audio/tag_filter.py — Stream-bewusster Tag-Filter fuer TTS

Wraps einen LLM-Text-Chunk-Iterator und yieldet nur narrativen Text.
Control-Tags ([PROBE:...], [FAKT:...], [INVENTAR:...], etc.) werden
intern gepuffert und sind nach Iteration via .tags abrufbar.

Usage:
    filtered = TagFilteredStream(llm_chunks)
    for narrative_chunk in filtered:
        tts.speak_sentence(narrative_chunk)

    tags = filtered.tags    # Liste extrahierter Tag-Strings
    full = filtered.full    # Volltext inkl. Tags (fuer History)
"""

from __future__ import annotations

import re
from typing import Callable, Iterator

# Alle bekannten Control-Tag-Prefixe
_CONTROL_PREFIXES = (
    "PROBE",
    "HP_VERLUST",
    "HP_HEILUNG",
    "STABILITAET_VERLUST",
    "FERTIGKEIT_GENUTZT",
    "XP_GEWINN",
    "FAKT",
    "INVENTAR",
    "ZEIT_VERGEHT",
    "TAGESZEIT",
    "WETTER",
    "WUERFELERGEBNIS",
    "STIMME",
)

_TAG_RE = re.compile(
    r"\[(?:" + "|".join(_CONTROL_PREFIXES) + r")[^\]]*\]",
    re.IGNORECASE,
)

# Maximale Puffer-Laenge bevor ein offenes [ als narrativer Text behandelt wird
_MAX_BRACKET_BUFFER = 300


class TagFilteredStream:
    """
    Wraps einen LLM-Chunk-Iterator.

    Yieldet nur narrativen Text (ohne Control-Tags) — ideal fuer TTS.
    Tags werden intern gesammelt und sind nach Iteration abrufbar.
    """

    _VOICE_RE = re.compile(r"\[STIMME:(\w+)\]", re.IGNORECASE)

    def __init__(
        self,
        source: Iterator[str],
        voice_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._source = source
        self._tags: list[str] = []
        self._full_parts: list[str] = []
        self._buffer = ""
        self._voice_callback = voice_callback

    @property
    def tags(self) -> list[str]:
        """Alle extrahierten Control-Tags."""
        return self._tags

    @property
    def full(self) -> str:
        """Vollstaendiger Originaltext inkl. Tags."""
        return "".join(self._full_parts)

    def __iter__(self) -> Iterator[str]:
        for chunk in self._source:
            self._full_parts.append(chunk)
            self._buffer += chunk

            # Puffer verarbeiten: narrativen Text yielden, Tags sammeln
            yield from self._flush_buffer(partial=True)

        # Rest-Puffer am Ende leeren
        yield from self._flush_buffer(partial=False)

    def _flush_buffer(self, partial: bool) -> Iterator[str]:
        """Verarbeitet den internen Puffer.

        partial=True: Behaelt unvollstaendige Tags (offenes [) zurueck.
        partial=False: Flusht alles (Stream-Ende).
        """
        while self._buffer:
            bracket_pos = self._buffer.find("[")

            if bracket_pos == -1:
                # Kein [ im Puffer — alles ist narrativer Text
                yield self._buffer
                self._buffer = ""
                break

            if bracket_pos > 0:
                # Narrativer Text vor dem [
                yield self._buffer[:bracket_pos]
                self._buffer = self._buffer[bracket_pos:]

            # Puffer beginnt mit [
            close_pos = self._buffer.find("]")

            if close_pos == -1:
                if partial:
                    # Unvollstaendiger Tag — warten auf mehr Chunks
                    if len(self._buffer) > _MAX_BRACKET_BUFFER:
                        # Zu lang ohne ] — kein Tag, als Text behandeln
                        yield self._buffer
                        self._buffer = ""
                    break
                else:
                    # Stream-Ende: pruefen ob es ein Tag-Fragment ist
                    if _TAG_RE.match(self._buffer + "]"):
                        self._tags.append(self._buffer + "]")
                    else:
                        yield self._buffer
                    self._buffer = ""
                    break

            # Vollstaendiges [...] Segment
            candidate = self._buffer[:close_pos + 1]
            if _TAG_RE.match(candidate):
                # Control-Tag — sammeln, nicht yielden
                self._tags.append(candidate)
                # STIMME-Tag: Stimmenwechsel auslösen
                if self._voice_callback:
                    vm = self._VOICE_RE.match(candidate)
                    if vm:
                        self._voice_callback(vm.group(1).lower())
            else:
                # Kein Control-Tag — als narrativen Text yielden
                yield candidate
            self._buffer = self._buffer[close_pos + 1:]
