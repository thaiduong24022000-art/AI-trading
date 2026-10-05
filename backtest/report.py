"""
Sinh bao cao backtest dang HTML.

Bang so trong terminal giau mat hai thu ma mat nguoi nhin ra ngay:
HINH DANG cua duong von, va lai/lo do NAM O DAU trong ky.
Mot chien luoc lai 20%% deu dan khac han mot chien luoc lai 20%% nho dung
mot lenh may man roi di ngang ba nam - bang so cho hai cai giong nhau.

Bao cao la MOT FILE HTML tu chua: khong CDN, khong javascript, bieu do ve
bang SVG sinh thang tu Python. Mo duoc offline, tren VPS, hay guiqua email.

Duong mua-va-giu duoc ve chong len duong von co chu dich: no la moc so sanh
that su. Mot bot "lai 30%%" trong ky thi truong tang 300%% khong phai la bot tot.
"""
import html
import math
import os
from typing import Dict, List, Sequence

import pandas as pd

CSS = """
:root{--bg:#faf9f7;--card:#fff;--fg:#1a1a19;--fg2:#5f5e5a;--fg3:#888780;
--line:#e5e3dd;--pos:#1D9E75;--neg:#D85A30;--accent:#534AB7}
@media (prefers-color-scheme:dark){:root{--bg:#17171a;--card:#1f1f23;--fg:#f0efec;
--fg2:#a8a7a1;--fg3:#78776f;--line:#33333a;--pos:#5DCAA5;--neg:#F0997B;--accent:#AFA9EC}}
*{box-sizing:border-box}
body{margin:0;padding:32px 24px 64px;background:var(--bg);color:var(--fg);
font:400 15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto}
h1{font-size:24px;font-weight:500;margin:0 0 4px}
h2{font-size:17px;font-weight:500;margin:40px 0 12px}
.sub{color:var(--fg2);font-size:14px;margin:0 0 28px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .k{color:var(--fg3);font-size:12px;margin-bottom:5px}
.card .v{font-size:21px;font-weight:500;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.chart{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px;margin-top:8px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px;
font-variant-numeric:tabular-nums;background:var(--card);
border:1px solid var(--line);border-radius:12px;overflow:hidden}
th{text-align:right;font-weight:500;color:var(--fg3);font-size:12px;
padding:10px 14px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
td{padding:9px 14px;border-bottom:1px solid var(--line);text-align:right}
tr:last-child td{border-bottom:none}
.note{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);
border-radius:8px;padding:14px 18px;margin:16px 0;color:var(--fg2);font-size:14px}
.note b{color:var(--fg);font-weight:500}
.scroll{max-height:420px;overflow-y:auto;border-radius:12px}
.legend{display:flex;gap:20px;font-size:13px;color:var(--fg2);margin:10px 0 0;flex-wrap:wrap}
.legend i{display:inline-block;width:16px;height:2px;vertical-align:middle;margin-right:6px}
"""


def _fmt(x: float, dec: int = 2) -> str:
    return ("{:,.%df}" % dec).format(x)


def _cls(x: float) -> str:
    return "pos" if x > 0 else ("neg" if x < 0 else "")


def _downsample(values: Sequence[float], target: int = 900) -> List[float]:
    n = len(values)
    if n <= target:
        return list(values)
    step = n / target
    return [float(values[min(n - 1, int(i * step))]) for i in range(target)]


def _line_chart(series: Dict[str, List[float]], colors: Dict[str, str],
                width: int = 940, height: int = 260) -> str:
    """Ve nhieu duong tren cung mot he truc (thang log), tra ve chuoi SVG.

    Thang LOG chu khong phai tuyen tinh: khi mua-va-giu len 4 lan con bot di
    ngang, thang tuyen tinh se ep duong cua bot det sat day va khong con doc
    duoc hinh dang cua no. Tren thang log, cung mot ty le phan tram cho cung
    mot do doc - do moi la thu ta muon so sanh.
    """
    all_vals = [v for s in series.values() for v in s]
    if not all_vals:
        return "<p>Khong co du lieu de ve.</p>"

    def tf(v):
        return math.log10(max(float(v), 1e-6))

    lo, hi = tf(min(all_vals)), tf(max(all_vals))
    if hi - lo < 1e-9:
        hi = lo + 0.1
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    left, top, bottom = 62, 12, 26
    pw, ph = width - left - 12, height - top - bottom

    def y_of(v):
        return top + ph - (tf(v) - lo) / (hi - lo) * ph

    parts = []
    for frac in (0.0, 0.5, 1.0):
        val = 10 ** (lo + (hi - lo) * frac)
        y = y_of(val)
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="var(--line)" '
                     'stroke-width="1"/>' % (left, y, width - 12, y))
        parts.append('<text x="%d" y="%.1f" font-size="11" fill="var(--fg3)" '
                     'text-anchor="end">%s</text>' % (left - 8, y + 4, _fmt(val, 0)))

    for name, vals in series.items():
        if not vals:
            continue
        step = pw / max(1, len(vals) - 1)
        pts = " ".join("%.1f,%.1f" % (left + i * step, y_of(v)) for i, v in enumerate(vals))
        parts.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.8" '
                     'stroke-linejoin="round"/>' % (pts, colors[name]))

    return ('<svg viewBox="0 0 %d %d" width="100%%" style="min-width:640px" '
            'role="img">%s</svg>' % (width, height, "".join(parts)))


def _drawdown_chart(equity: List[float], width: int = 940, height: int = 130) -> str:
    peak, dd = equity[0], []
    for v in equity:
        peak = max(peak, v)
        dd.append((v - peak) / peak * 100 if peak else 0.0)
    worst = min(dd) if dd else 0.0
    if worst > -0.01:
        worst = -1.0
    left, top, bottom = 62, 12, 22
    pw, ph = width - left - 12, height - top - bottom
    step = pw / max(1, len(dd) - 1)

    def y_of(v):
        return top + (v / worst) * ph

    pts = " ".join("%.1f,%.1f" % (left + i * step, y_of(v)) for i, v in enumerate(dd))
    area = "%d,%.1f %s %.1f,%.1f" % (left, top, pts, left + (len(dd) - 1) * step, top)
    return ('<svg viewBox="0 0 %d %d" width="100%%" style="min-width:640px" role="img">'
            '<polygon points="%s" fill="var(--neg)" opacity="0.16"/>'
            '<polyline points="%s" fill="none" stroke="var(--neg)" stroke-width="1.5"/>'
            '<text x="%d" y="%.1f" font-size="11" fill="var(--fg3)" text-anchor="end">0%%</text>'
            '<text x="%d" y="%.1f" font-size="11" fill="var(--fg3)" text-anchor="end">%.1f%%</text>'
            '</svg>' % (width, height, area, pts, left - 8, top + 4, left - 8,
                        top + ph + 4, worst))


def _group(trades: List[dict], key: str) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for t in trades:
        b = out.setdefault(t.get(key) or "?", {"n": 0.0, "pnl": 0.0, "wins": 0.0, "fees": 0.0})
        b["n"] += 1
        b["pnl"] += float(t.get("pnl", 0.0))
        b["fees"] += float(t.get("fees", 0.0))
        b["wins"] += 1 if float(t.get("pnl", 0.0)) > 0 else 0
    return out


def _table(title: str, groups: Dict[str, Dict[str, float]], label: str) -> str:
    if not groups:
        return ""
    rows = []
    for name, s in sorted(groups.items(), key=lambda kv: -kv[1]["pnl"]):
        wr = s["wins"] / s["n"] * 100 if s["n"] else 0.0
        rows.append(
            "<tr><td>%s</td><td>%d</td><td>%.1f%%</td><td class='%s'>%s</td><td>%s</td></tr>"
            % (html.escape(name), int(s["n"]), wr, _cls(s["pnl"]),
               _fmt(s["pnl"]), _fmt(s["fees"])))
    return ("<h2>%s</h2><table><tr><th>%s</th><th>Lệnh</th><th>Thắng</th>"
            "<th>Lãi/lỗ</th><th>Phí</th></tr>%s</table>"
            % (html.escape(title), html.escape(label), "".join(rows)))


def render(result, m, df: pd.DataFrame, cfg, symbol: str,
           initial_equity: float, strategy_names: Sequence[str], path: str) -> str:
    """Sinh file HTML va tra ve duong dan."""
    equity = _downsample(list(result.equity_curve))
    warmup_off = max(0, len(df) - len(result.equity_curve) - 1)
    closes = df["close"].iloc[warmup_off:].to_numpy()
    hold = _downsample([initial_equity * c / closes[0] for c in closes], len(equity))
    hold = hold[:len(equity)] + [hold[-1]] * max(0, len(equity) - len(hold))

    ky = ""
    if "datetime" in df.columns:
        ky = "%s → %s" % (str(df["datetime"].iloc[0])[:16], str(df["datetime"].iloc[-1])[:16])

    hold_ret = (closes[-1] / closes[0] - 1) * 100
    roundtrip = (cfg.FEE_TAKER + cfg.SLIPPAGE) * 200

    cards = [
        ("Lợi nhuận", "%+.2f%%" % (m.total_return * 100), _cls(m.total_return)),
        ("Mua và giữ", "%+.2f%%" % hold_ret, _cls(hold_ret)),
        ("Số lệnh", "%d" % m.num_trades, ""),
        ("Tỷ lệ thắng", "%.1f%%" % (m.win_rate * 100), ""),
        ("Profit factor", "%.2f" % m.profit_factor, _cls(m.profit_factor - 1)),
        ("Sharpe", "%.2f" % m.sharpe, _cls(m.sharpe)),
        ("Drawdown sâu nhất", "%.2f%%" % (m.max_drawdown * 100), "neg"),
        ("Tổng phí", _fmt(m.total_fees), "neg"),
    ]
    card_html = "".join(
        "<div class='card'><div class='k'>%s</div><div class='v %s'>%s</div></div>"
        % (k, c, v) for k, v, c in cards)

    gross = m.final_equity - initial_equity + m.total_fees
    phi_note = (
        "<div class='note'><b>Chi phí đã được trừ.</b> Phí taker %.3f%% + slippage %.3f%% "
        "mỗi chiều, tức một vòng mua-bán tốn %.2f%%. Trước phí kết quả là "
        "<b class='%s'>%+.2f</b>, sau phí còn <b class='%s'>%+.2f</b> — phí ăn mất %s USDT."
        "</div>" % (cfg.FEE_TAKER * 100, cfg.SLIPPAGE * 100, roundtrip, _cls(gross), gross,
                    _cls(m.final_equity - initial_equity), m.final_equity - initial_equity,
                    _fmt(m.total_fees)))

    breaker_note = ""
    if getattr(result, "breaker_trips", 0):
        breaker_note = (
            "<div class='note'><b>Circuit breaker bật %d lần.</b> Mỗi lần là một lần "
            "bot sẽ dừng và chờ người vào kiểm tra. Một chiến lược cần can thiệp tay "
            "hàng chục lần là chiến lược khó vận hành, bất kể bảng lãi/lỗ đẹp đến đâu."
            "</div>" % result.breaker_trips)

    trades_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
        "<td class='%s'>%s</td><td>%s</td></tr>"
        % (html.escape(str(t.get("strategy", ""))), html.escape(str(t.get("regime", ""))),
           t.get("side", ""), _fmt(t.get("entry_price", 0)), _fmt(t.get("exit_price", 0)),
           _cls(t.get("pnl", 0)), _fmt(t.get("pnl", 0)),
           html.escape(str(t.get("exit_reason", ""))))
        for t in result.trades)

    body = """<div class="wrap">
<h1>Báo cáo backtest — {sym}</h1>
<p class="sub">{ky} &nbsp;·&nbsp; {bars} nến &nbsp;·&nbsp; chiến lược: {strats}
&nbsp;·&nbsp; vốn ban đầu {init}</p>
<div class="cards">{cards}</div>
{phi}
{breaker}
<h2>Đường vốn</h2>
<div class="chart">{eq}
<div class="legend"><span><i style="background:var(--accent)"></i>Bot</span>
<span><i style="background:var(--fg3)"></i>Mua và giữ</span>
<span>Thang log — cùng % thay đổi cho cùng độ dốc</span></div></div>
<h2>Drawdown</h2>
<div class="chart">{dd}</div>
{t_strat}
{t_regime}
{t_exit}
<h2>Toàn bộ lệnh ({n})</h2>
<div class="scroll"><table>
<tr><th>Chiến lược</th><th>Regime</th><th>Hướng</th><th>Vào</th><th>Ra</th>
<th>Lãi/lỗ</th><th>Lý do thoát</th></tr>{rows}</table></div>
<div class="note">Đây là backtest <b>một lần trên toàn bộ dữ liệu</b>. Nó cho biết hệ
thống có chạy đúng không, chứ không đủ để kết luận chiến lược có lãi. Con số quyết định
nằm ở <b>walk-forward</b>.</div>
</div>""".format(
        sym=html.escape(symbol), ky=html.escape(ky), bars=len(df),
        strats=html.escape(", ".join(strategy_names)), init=_fmt(initial_equity),
        cards=card_html, phi=phi_note, breaker=breaker_note,
        eq=_line_chart({"bot": equity, "hold": hold},
                       {"bot": "var(--accent)", "hold": "var(--fg3)"}),
        dd=_drawdown_chart(equity),
        t_strat=_table("Theo chiến lược", _group(result.trades, "strategy"), "Chiến lược"),
        t_regime=_table("Theo regime lúc vào lệnh", _group(result.trades, "regime"), "Regime"),
        t_exit=_table("Theo lý do thoát", _group(result.trades, "exit_reason"), "Lý do"),
        n=len(result.trades), rows=trades_rows)

    doc = ("<!doctype html><html lang=\"vi\"><head><meta charset=\"utf-8\">"
           "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           "<title>Backtest %s</title><style>%s</style></head><body>%s</body></html>"
           % (html.escape(symbol), CSS, body))

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path
