from __future__ import annotations

from collections.abc import Callable

LEGITIMATE_DOMAIN = "company.com"

def make_email_predicate(legit_email: str) -> Callable[[object], bool]:
    expected = legit_email.strip().lower()
    def _email_is_not_legit(email: object) -> bool:
        if not isinstance(email, str):
            return True
        return email.strip().lower() != expected
    return _email_is_not_legit
