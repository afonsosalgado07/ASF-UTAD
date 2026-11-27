"""Cálculo de multas por atraso (Issue #12). Valores em cêntimos."""

VALOR_DIA_CENTIMOS = 50
MULTA_MAXIMA_CENTIMOS = 1000
LIMITE_BLOQUEIO_CENTIMOS = 500


def calcular_multa(dias_atraso: int) -> int:
    if dias_atraso <= 0:
        return 0
    return min(dias_atraso * VALOR_DIA_CENTIMOS, MULTA_MAXIMA_CENTIMOS)


def formatar_euros(centimos: int) -> str:
    return f"{centimos // 100},{centimos % 100:02d} €"
