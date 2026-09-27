"""Validate [n] citations in model output against the sources actually given."""

import re
from dataclasses import dataclass, field

# [1] or [1, 3] or [1,2,3]
CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass
class Validated:
    text: str  # answer with bad refs removed and good ones renumbered 1..m
    order: list[int] = field(default_factory=list)  # new number i+1 -> original source number order[i]
    invalid: list[int] = field(default_factory=list)  # out-of-range numbers the model produced

    @property
    def valid(self) -> bool:
        return bool(self.order) and not self.invalid


def validate(answer: str, n_sources: int) -> Validated:
    order: list[int] = []
    invalid: list[int] = []

    def renumber(m: re.Match) -> str:
        new: list[int] = []
        for raw in m.group(1).split(","):
            n = int(raw)
            if not 1 <= n <= n_sources:
                invalid.append(n)
                continue
            if n not in order:
                order.append(n)
            k = order.index(n) + 1
            if k not in new:
                new.append(k)
        return "".join(f"[{k}]" for k in new)

    text = CITE_RE.sub(renumber, answer)
    text = re.sub(r"[ \t]+([.,;:!?؟،])", r"\1", text)  # tidy space left by removed refs
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return Validated(text=text, order=order, invalid=invalid)
