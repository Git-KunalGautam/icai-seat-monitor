from dataclasses import dataclass
import json


def normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass(frozen=True)
class Target:
    region: str
    pou: str
    course: str

    @property
    def identity(self) -> tuple[str, str, str]:
        return tuple(normalized(v) for v in (self.region, self.pou, self.course))


@dataclass(frozen=True)
class Batch:
    region: str
    pou: str
    course: str
    batch_number: str
    available_seats: int
    from_date: str
    to_date: str
    batch_time: str
    open_for: str
    last_checked_at: str

    @property
    def key(self) -> str:
        # JSON avoids delimiter collisions; preserve the original batch identifier.
        return json.dumps(
            [normalized(self.region), normalized(self.pou), normalized(self.course), self.batch_number],
            ensure_ascii=False, separators=(",", ":"),
        )


@dataclass(frozen=True)
class ScrapeResult:
    batches: list[Batch]
    no_batches: bool = False
