"""Entidades do domínio."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


@dataclass
class Livro:
    isbn: str
    titulo: str
    autor: str
    ano: int
    exemplares: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Socio:
    numero: int
    nome: str
    email: str
    ativo: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Emprestimo:
    id: int
    isbn: str
    numero_socio: int
    data_inicio: date
    data_limite: date
    data_devolucao: date | None = None

    @property
    def ativo(self) -> bool:
        return self.data_devolucao is None

    def dias_atraso(self, referencia: date) -> int:
        """Dias de atraso em relação à data limite (0 se não estiver atrasado).
        Para um empréstimo devolvido usa a data de devolução."""
        fim = self.data_devolucao or referencia
        return max(0, (fim - self.data_limite).days)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("data_inicio", "data_limite", "data_devolucao"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Emprestimo":
        d = dict(d)
        for k in ("data_inicio", "data_limite", "data_devolucao"):
            d[k] = date.fromisoformat(d[k]) if d.get(k) else None
        return cls(**d)
