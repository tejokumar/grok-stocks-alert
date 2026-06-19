import logging
from datetime import datetime, timedelta, timezone

from src.config import Settings
from src.data.fmp_client import FMPClient
from src.models import Alert, AlertType, AnalystGrade, StockSnapshot
from src.utils.dedup import catalyst_dedup_key

logger = logging.getLogger(__name__)


class AnalystGradesAnalyzer:
    """Detect recent top-analyst upgrades and downgrades via FMP grades."""

    def __init__(self, settings: Settings, fmp: FMPClient):
        self.settings = settings
        self.fmp = fmp

    def scan_symbols(
        self,
        symbols: list[str],
        watchlist_by_symbol: dict[str, StockSnapshot],
    ) -> tuple[list[Alert], list[Alert]]:
        upgrades: list[Alert] = []
        downgrades: list[Alert] = []
        if not self.settings.enable_analyst_grades:
            return upgrades, downgrades

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.analyst_grade_lookback_days)
        for symbol in symbols[:25]:
            try:
                grades = self.fmp.get_grades(symbol, limit=40)
            except Exception as exc:
                logger.warning("FMP grades for %s failed: %s", symbol, exc)
                continue

            recent = [g for g in grades if self._is_recent(g, cutoff)]
            symbol_upgrades = [g for g in recent if g.action == "upgrade" and g.is_top_firm]
            symbol_downgrades = [g for g in recent if g.action == "downgrade" and g.is_top_firm]

            if symbol_upgrades:
                upgrades.append(self._grade_to_alert(symbol_upgrades[0], watchlist_by_symbol, bullish=True))
            if symbol_downgrades:
                downgrades.append(self._grade_to_alert(symbol_downgrades[0], watchlist_by_symbol, bullish=False))

        return upgrades, downgrades

    def _is_recent(self, grade: AnalystGrade, cutoff: datetime) -> bool:
        if not grade.date:
            return False
        try:
            grade_dt = datetime.strptime(grade.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return grade_dt >= cutoff
        except ValueError:
            return False

    def _grade_to_alert(
        self,
        grade: AnalystGrade,
        watchlist_by_symbol: dict[str, StockSnapshot],
        bullish: bool,
    ) -> Alert:
        snap = watchlist_by_symbol.get(grade.symbol)
        price_note = ""
        if snap and snap.price > 0:
            price_note = f"\nPrice: ${snap.price:.2f} ({snap.change_pct:+.1f}%)"

        action_label = "upgrade" if bullish else "downgrade"
        title = (
            f"Top analyst {action_label} — {grade.grading_company}: "
            f"{grade.previous_grade} → {grade.new_grade}"
        )
        message = (
            f"{grade.grading_company} {action_label}d {grade.symbol} on {grade.date}.\n"
            f"Rating: {grade.previous_grade} → {grade.new_grade}"
            f"{price_note}"
        )
        alert_type = AlertType.ANALYST_UPGRADE if bullish else AlertType.ANALYST_DOWNGRADE
        ref_url = f"https://financialmodelingprep.com/stable/grades?symbol={grade.symbol}"

        return Alert(
            alert_type=alert_type,
            symbol=grade.symbol,
            title=title,
            message=message,
            confidence=0.88 if grade.is_top_firm else 0.75,
            metadata={
                "source": "fmp_grades",
                "grading_company": grade.grading_company,
                "previous_grade": grade.previous_grade,
                "new_grade": grade.new_grade,
                "grade_date": grade.date,
                "action": grade.action,
                "thesis_direction": "bullish" if bullish else "bearish",
                "url": ref_url,
                "references": [{
                    "title": f"{grade.grading_company} {action_label} ({grade.date})",
                    "url": ref_url,
                    "source": "fmp_grades",
                }],
                "catalyst_key": catalyst_dedup_key(
                    grade.symbol,
                    f"{grade.grading_company}:{grade.previous_grade}:{grade.new_grade}:{grade.date}",
                    "analyst_grade",
                ),
            },
        )