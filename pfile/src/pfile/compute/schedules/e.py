"""Schedule E — Supplemental Income and Loss (K-1 pass-through, Part II)."""

from __future__ import annotations

from decimal import Decimal

from pfile.models.documents import K1_1065, K1_1120S
from pfile.models.forms import ScheduleE, ScheduleEEntry


def _entity_name(k1: K1_1065 | K1_1120S) -> str:
    if isinstance(k1, K1_1120S):
        return k1.corporation.name
    return k1.partnership.name


def _entity_ein(k1: K1_1065 | K1_1120S) -> str | None:
    if isinstance(k1, K1_1120S):
        return k1.corporation.ein
    return k1.partnership.ein


def compute_schedule_e(
    k1_1065s: list[K1_1065],
    k1_1120ss: list[K1_1120S],
) -> ScheduleE:
    """
    Compute Schedule E Part II from all K-1 documents.

    For S-corp K-1s (1120S): ordinary business income flows to Schedule E.
    For partnership K-1s (1065): ordinary business income + guaranteed payments
    flow to Schedule E (self-employment income handled separately in Schedule SE).

    Source: Schedule E Part II instructions; IRC §702 (partnership), IRC §1366 (S-corp).
    """
    entries: list[ScheduleEEntry] = []

    for k1 in k1_1120ss:
        ordinary = k1.box1_ordinary_income
        section_179 = k1.box11_section_179
        net = ordinary - section_179
        entries.append(ScheduleEEntry(
            entity_name=_entity_name(k1),
            ein=_entity_ein(k1),
            ordinary_income=max(Decimal(0), ordinary),
            ordinary_loss=max(Decimal(0), -ordinary),
            section_179=section_179,
            net_income=net,
        ))

    for k1 in k1_1065s:
        # Guaranteed payments are separately reported; ordinary income goes on E
        ordinary = k1.box1_ordinary_income
        section_179 = k1.box11_section_179
        net = ordinary - section_179
        entries.append(ScheduleEEntry(
            entity_name=_entity_name(k1),
            ein=_entity_ein(k1),
            ordinary_income=max(Decimal(0), ordinary),
            ordinary_loss=max(Decimal(0), -ordinary),
            section_179=section_179,
            net_income=net,
        ))

    total_income = sum(e.ordinary_income for e in entries)
    total_loss = sum(e.ordinary_loss + e.section_179 for e in entries)

    return ScheduleE(
        entries=entries,
        total_income=total_income,
        total_loss=total_loss,
    )
