"""
Спільна евристика "це, ймовірно, та сама нерухомість, виставлена на
іншому сайті" — той самий рієлтор часто публікує одне й те саме
оголошення одразу на кількох сайтах під різними номерами.

Ознака схожості: тип угоди, тип житла, поштовий індекс і ціна однакові
(і житлова площа — якщо відома на обох). Це евристика, не гарантія:
теоретично дві різні квартири в одному будинку з однаковою ціною й
площею можуть випадково "злипнутися" в одну — на практиці рідкість.

Використовується у двох місцях:
    * `aggregator/database.py` — при збереженні нових оголошень (уже
      знає й про старі, з попередніх проходів, завдяки базі);
    * `server/app.py` — живий AI-пошук по кількох сайтах одразу, без
      бази даних, лише в межах одного-єдиного списку результатів.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .models import Listing

# Різниця в житловій площі (м²), яку ще вважаємо "тим самим помешканням".
# Різні сайти інколи трохи по-різному округлюють площу.
LIVING_AREA_TOLERANCE = 3.0


def duplicate_key(listing: Listing) -> Optional[tuple]:
    """
    Груба ознака "це, ймовірно, та сама нерухомість": тип угоди, тип
    житла, поштовий індекс і ціна. None, якщо якогось із цих полів
    немає — тоді пошук дублікатів для оголошення не має сенсу.
    """
    if not listing.postal_code or listing.price is None or not listing.property_type:
        return None
    return (listing.transaction, listing.property_type, listing.postal_code, listing.price)


def values_compatible(a: Optional[float], b: Optional[float], tolerance: float = 0.0) -> bool:
    """Однакові (з точністю до tolerance) АБО хоча б одне з них невідоме."""
    if a is None or b is None:
        return True
    return abs(a - b) <= tolerance


def find_duplicate_in_batch(candidate: Listing, others: Sequence[Listing]) -> Optional[Listing]:
    """Шукає серед `others` (інші сайти) оголошення, схоже на `candidate`."""
    key = duplicate_key(candidate)
    if key is None:
        return None
    for other in others:
        if other.site == candidate.site:
            continue
        if duplicate_key(other) != key:
            continue
        if values_compatible(candidate.bedrooms, other.bedrooms) and values_compatible(
            candidate.living_area, other.living_area, LIVING_AREA_TOLERANCE
        ):
            return other
    return None


def dedupe_cross_site(listings: Sequence[Listing]) -> list[Listing]:
    """
    Повертає той самий список, лишаючи для кожної групи схожих
    оголошень (з різних сайтів) тільки перше. Для одноразового
    (без бази даних) списку результатів — напр. живого AI-пошуку,
    що опитує кілька сайтів одразу.
    """
    kept: list[Listing] = []
    for candidate in listings:
        if find_duplicate_in_batch(candidate, kept) is None:
            kept.append(candidate)
    return kept
