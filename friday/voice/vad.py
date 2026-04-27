"""Tiny VAD utility used by browser-upload voice mode tests and future providers."""

from __future__ import annotations


def has_speech(samples: list[float], *, threshold: float = 0.015) -> bool:
    if not samples:
        return False
    energy = sum(sample * sample for sample in samples) / len(samples)
    return energy ** 0.5 >= threshold
