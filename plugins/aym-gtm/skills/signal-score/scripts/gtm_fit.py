"""One ICP-fit rule for every aym-gtm skill.

This file is copied, byte for byte, into the scripts folder of icp-define,
data-quality, account-book and signal-score, because each skill installs on its
own. tests/test_gtm_shared.py fails if the copies differ. Change all four.

fit(account, icp) -> (verdict, reason)
fit_points(account, cfg, points) -> (total, detail)

- verdict is "in", "out" or "unknown".
- A blank field is unknown, never out: enrich it before deciding.
- Any known reason to be out beats a blank field elsewhere.
- Status (hold, live deal, archived) is not fit. Each skill handles status itself.
"""

import math

IN, OUT, UNKNOWN = "in", "out", "unknown"


def _num(value):
    text = str(value if value is not None else "").replace(",", "").strip()
    if not text:
        return None
    try:
        n = float(text)
    except ValueError:
        return None
    return n if math.isfinite(n) else None  # "nan" and "inf" are not headcounts


def _lower_list(values):
    return [str(v).strip().lower() for v in (values or []) if str(v).strip()]


def _split(value):
    return [p.strip().lower() for p in str(value or "").replace(",", ";").split(";") if p.strip()]


def _fmt(n):
    return f"{n:g}"


def fit(account, icp):
    """Return (verdict, reason) for one account row against the gtm.json icp section."""
    icp = icp or {}
    outs, unknowns = [], []

    rel = (account.get("relationship") or "").strip().lower()
    if rel and rel in _lower_list(icp.get("exclude_relationships")):
        outs.append(f"excluded relationship: {rel}")

    countries = [c.upper() for c in _lower_list(icp.get("countries"))]
    if countries:
        country = (account.get("country") or "").strip().upper()
        if not country:
            unknowns.append("country unknown")
        elif country not in countries:
            outs.append(f"country {country} is not in the ICP")

    ind_in = _lower_list(icp.get("industries_in"))
    ind_out = _lower_list(icp.get("industries_out"))
    if ind_in or ind_out:
        industry = (account.get("industry") or "").strip().lower()
        if not industry:
            unknowns.append("industry unknown")
        elif industry in ind_out:
            outs.append(f"excluded industry: {industry}")
        elif ind_in and industry not in ind_in:
            outs.append(f"industry {industry} is not on the ICP list")

    size = icp.get("size") or {}
    lo, hi = _num(size.get("min")), _num(size.get("max"))
    if lo is not None or hi is not None:
        n = _num(account.get("employees"))
        if n is None:
            unknowns.append("headcount unknown")
        elif lo is not None and n < lo:
            outs.append(f"below the size floor ({_fmt(n)} < {_fmt(lo)})")
        elif hi is not None and n > hi:
            outs.append(f"above the size ceiling ({_fmt(n)} > {_fmt(hi)})")

    tech_rule = icp.get("technographics") or {}
    required = _lower_list(tech_rule.get("required_any"))
    excluded = _lower_list(tech_rule.get("excluded"))
    if required or excluded:
        tech = _split(account.get("tech"))
        if not tech:
            unknowns.append("tech stack unknown")
        else:
            bad = [t for t in tech if t in excluded]
            if bad:
                outs.append(f"uses excluded tech: {', '.join(bad)}")
            elif required and not any(t in required for t in tech):
                outs.append("uses none of the required tech")

    if outs:
        return OUT, outs[0]
    if unknowns:
        return UNKNOWN, "; ".join(unknowns) + ": enrich before deciding"
    return IN, "fits the ICP"


def fit_points(account, cfg, points):
    """Points for how well an in-ICP account fits: the size sweet spot (or just the band)
    and a segment match. Out or unknown fit scores 0. `points` maps sweet_spot, in_band
    and segment_match to numbers; each part is listed so a person can check it."""
    icp = (cfg or {}).get("icp") or {}
    verdict, _ = fit(account, icp)
    if verdict != IN:
        return 0, ""
    parts = []
    size = icp.get("size") or {}
    n = _num(account.get("employees"))
    s_lo, s_hi = _num(size.get("sweet_min")), _num(size.get("sweet_max"))
    if n is not None and s_lo is not None and s_hi is not None and s_lo <= n <= s_hi:
        parts.append(("sweet_spot", points.get("sweet_spot", 0)))
    elif n is not None:
        parts.append(("in_band", points.get("in_band", 0)))
    industry = (account.get("industry") or "").strip().lower()
    for seg in (cfg or {}).get("segments") or []:
        inds = _lower_list(seg.get("industries"))
        lo, hi = _num(seg.get("size_min")), _num(seg.get("size_max"))
        if (not inds or industry in inds) and n is not None and (lo is None or n >= lo) and (hi is None or n <= hi):
            parts.append(("segment_match", points.get("segment_match", 0)))
            break
    parts = [(k, v) for k, v in parts if v]
    return sum(v for _, v in parts), "; ".join(f"{k} {v:g}" for k, v in parts)
