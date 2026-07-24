"""
Stage 5 — publication figures for the findings-first writeup.

Reads the Stage 5 cache (data/raw/stage5_*) — produced by `python -m src.stage5_run --rebuild` —
and writes six PNGs to reports/figures/. Pure plotting: no backtests here, so iterating on a
figure is instant. If the cache is missing it tells you to build it first.

    python -m src.figures            # regenerate every figure from the cache

Design: one CVD-validated categorical palette used by ROLE (ceiling=neutral, DP=blue,
comparators=warm), thin marks, recessive grid, direct labels, a legend whenever >=2 series, and
NO dual-axis charts (the duration figure is two stacked panels, never two y-scales).
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from src import stage5_run as S
from src import stage5_stats as st

FIGDIR = "reports/figures"

# CVD-validated categorical palette (light surface), assigned by ROLE not by rank.
C = {
    "ceiling": "#52514e",   # neutral ink — the clairvoyant bound
    "dp":      "#2a78d6",   # blue  — the optimal causal policy (the hero series)
    "learned": "#eb6834",   # orange — learned-forecast MPC
    "naive":   "#eda100",   # yellow — naive MPC
    "floor":   "#e34948",   # red    — do-nothing / dumb floor
    "pf":      "#1baf7a",   # aqua   — perfect-foresight value (duration fig)
    "psi":     "#4a3aa7",   # violet — the shadow price
    "grid":    "#d9d8d4",
    "ink":     "#0b0b0b",
    "muted":   "#8a8984",
    "win":     "#1baf7a",
    "loss":    "#e34948",
}


def _style():
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "savefig.dpi": 150, "savefig.bbox": "tight",
        "font.size": 11, "axes.titlesize": 13, "axes.titleweight": "bold",
        "axes.labelsize": 11, "axes.edgecolor": C["muted"], "axes.linewidth": 0.8,
        "axes.grid": True, "grid.color": C["grid"], "grid.linewidth": 0.7,
        "axes.axisbelow": True, "xtick.color": C["muted"], "ytick.color": C["muted"],
        "text.color": C["ink"], "axes.labelcolor": C["ink"],
        "legend.frameon": False, "figure.autolayout": False,
    })


def _load():
    for f in (S.CACHE_DAILY, S.CACHE_PSI, S.CACHE_DUR):
        if not os.path.exists(f):
            raise SystemExit(f"missing cache {f} — run `python -m src.stage5_run --rebuild` first")
    daily, psi = S._load_cache()
    dur = pd.read_parquet(S.CACHE_DUR)
    return daily, psi, dur


# --------------------------------------------------------------------------- #
def fig_ladder(daily, path):
    """Fig 1 — the value-of-foresight ladder (§IV.13). Horizontal bars, full-window $, with the
    clairvoyant ceiling as the neutral bound and the DP highlighted. Comparators use the MATCHED
    traded-window numbers (the honest ones); the two clairvoyant bounds are full-window and
    labelled as such in the writeup caption."""
    import matplotlib.pyplot as plt
    a = daily.attrs   # FULL-window profits, all computed in build_cache and read from the cache
    labels = ["ceiling\n(perfect foresight)", "clairvoyant MPC", "DP (optimal causal)",
              "learned MPC", "do-nothing", "naive MPC", "naive floor"]
    # Full-window ladder (every policy run start→finish). The DP holds through its 2-month
    # warm-up earning $0, so its full-window profit EQUALS its traded-window profit; the MPCs
    # trade and mostly lose in warm-up, which is why they sit lower here than on the matched
    # traded window (the matched-window fairness is Figs 4–5, not this ladder).
    vals = [a["ceiling_full"], a["clair_full"], a["dp_full"],
            a["learned_full"], 0.0, a["naive_full"], a["floor_full"]]
    cols = [C["ceiling"], C["ceiling"], C["dp"], C["learned"], C["muted"], C["naive"], C["floor"]]
    fig, ax = plt.subplots(figsize=(8.2, 4.3))
    y = np.arange(len(labels))[::-1]
    ax.barh(y, vals, color=cols, height=0.66, zorder=3)
    ax.axvline(0, color=C["muted"], lw=1)
    span = max(vals) - min(vals)
    for yi, v in zip(y, vals):
        off = 0.012 * span
        ax.text(v + (off if v >= 0 else -off), yi, f"${v:,.0f}",
                va="center", ha="left" if v >= 0 else "right", fontsize=10, color=C["ink"])
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlabel("realised profit over the window, $ (2 h battery, energy-only)")
    ax.set_title("The value-of-foresight ladder")
    ax.set_xlim(min(vals) - 0.16 * span, max(vals) + 0.14 * span)
    ax.grid(axis="y", visible=False)
    fig.savefig(path); plt.close(fig)


def fig_duration(dur, path):
    """Fig 2 — Q3 duration curves. TWO stacked panels (never a dual axis): top = the dollar
    value of perfect foresight V_PF(E) and the causal DP V_DP(E); bottom = the DP capture rate
    V_DP/V_PF. Both concave; capture rises from negative at 0.5 h to a plateau."""
    import matplotlib.pyplot as plt
    E = dur["E"].to_numpy()
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.6, 6.0), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 1], "hspace": 0.12})
    a1.plot(E, dur["v_pf"], "-o", color=C["pf"], lw=2, ms=6, label="perfect foresight $V^{PF}$", zorder=3)
    a1.plot(E, dur["v_dp"], "-o", color=C["dp"], lw=2, ms=6, label="causal DP $V^{DP}$", zorder=3)
    a1.set_ylabel("window value, $"); a1.set_title("Q3 — the marginal value of storage duration")
    a1.legend(loc="upper left", fontsize=10)
    for x, y in zip(E, dur["v_dp"]):
        a1.annotate(f"${y:,.0f}", (x, y), textcoords="offset points", xytext=(0, -14),
                    ha="center", fontsize=8.5, color=C["dp"])
    a2.axhline(0, color=C["muted"], lw=1)
    a2.plot(E, dur["capture"] * 100, "-o", color=C["dp"], lw=2, ms=6, zorder=3)
    for x, y in zip(E, dur["capture"] * 100):
        a2.annotate(f"{y:.0f}%", (x, y), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8.5, color=C["dp"])
    a2.set_ylabel("DP capture, %"); a2.set_xlabel("battery duration $E_{max}$, hours")
    fig.savefig(path); plt.close(fig)


def fig_concentration(daily, path):
    """Fig 3 — concentration of $V^{DP}$ across days. Per-day P&L sorted descending (bars) with a
    cumulative-share line: a handful of days carry the whole result. Shows, not asserts, the
    tail concentration that makes the mean untrustworthy and the sign test the headline."""
    import matplotlib.pyplot as plt
    x = np.sort(daily["dp_emp"].to_numpy())[::-1]
    total = x.sum()
    cum = np.cumsum(x) / total * 100
    n = len(x)
    fig, ax = plt.subplots(figsize=(8.2, 4.3))
    cols = np.where(x >= 0, C["dp"], C["floor"])
    ax.bar(np.arange(n), x, color=cols, width=1.0, zorder=3)
    ax.set_ylabel("daily $V^{DP}$  (\\$)", color=C["ink"])
    ax.set_xlabel("trading day (sorted best → worst)")
    ax.axhline(0, color=C["muted"], lw=1)
    ax.set_title("Fig 3 — the value is spike-concentrated")
    con = st.concentration(daily["dp_emp"].to_numpy())
    ax.annotate(f"top-1 day = {con['top1_share_of_total']:.0%} of net total\n"
                f"top-5 days = {con['top5_share_of_total']:.0%} of net total\n"
                f"(the other {n-5} days net ${x[5:].sum():,.0f})",
                xy=(0.42, 0.9), xycoords="axes fraction", fontsize=9.5,
                va="top", color=C["ink"])
    fig.savefig(path); plt.close(fig)


def fig_bootstrap(daily, path):
    """Fig 4 — the stationary block-bootstrap 95% CI on the paired edge (DP − learned MPC), swept
    over block length, with zero marked. Every interval straddles zero: the honest §VIII.5 result."""
    import matplotlib.pyplot as plt
    D = (daily["dp_emp"] - daily["mpc_learned"]).to_numpy()
    blocks = [1, 2, 5, 10, 20, 40]
    rows = st.block_length_sensitivity(D, blocks=blocks, stat_fn=np.sum)
    point = float(D.sum())
    fig, ax = plt.subplots(figsize=(8.0, 4.2))
    y = np.arange(len(blocks))[::-1]
    for yi, r in zip(y, rows):
        ax.plot([r["lo"], r["hi"]], [yi, yi], color=C["dp"], lw=3, solid_capstyle="round", zorder=3)
        ax.plot(point, yi, "o", color=C["ink"], ms=5, zorder=4)
    ax.axvline(0, color=C["loss"], lw=1.5, ls="--", label="zero (no edge)")
    ax.set_yticks(y); ax.set_yticklabels([f"{b} d" for b in blocks])
    ax.set_ylabel("bootstrap block length")
    ax.set_xlabel("95% CI on the paired edge $\\sum_i D_i$  (\\$)")
    ax.set_title("Fig 4 — the DP's edge is not separable from zero")
    ax.legend(loc="lower right", fontsize=9.5)
    ax.annotate(f"point estimate \\${point:,.0f}", xy=(point, y[0]), textcoords="offset points",
                xytext=(8, -14), fontsize=9, color=C["ink"])
    fig.savefig(path); plt.close(fig)


def fig_signtest(daily, path):
    """Fig 5 — histogram of daily paired differences (DP − learned MPC), colored by sign, with the
    sign-test verdict. A near-symmetric split (46% wins) is a coin flip — magnitude, not
    frequency, drives the total."""
    import matplotlib.pyplot as plt
    D = (daily["dp_emp"] - daily["mpc_learned"]).to_numpy()
    s = st.sign_test(D, tol=1e-6)
    nz = D[np.abs(D) > 1e-6]
    fig, ax = plt.subplots(figsize=(8.0, 4.2))
    lim = np.percentile(np.abs(nz), 96)
    bins = np.linspace(-lim, lim, 31)
    ax.hist(nz[nz > 0], bins=bins, color=C["win"], alpha=0.85, label=f"DP wins ({s.n_pos} days)", zorder=3)
    ax.hist(nz[nz < 0], bins=bins, color=C["loss"], alpha=0.85, label=f"MPC wins ({s.n_neg} days)", zorder=3)
    ax.axvline(0, color=C["muted"], lw=1)
    ax.set_xlabel("daily $V^{DP} - V^{MPC,learned}$  (\\$, clipped to 96th pct)")
    ax.set_ylabel("number of days")
    ax.set_title("Fig 5 — sign test: a coin flip vs a good forecast")
    ax.annotate(f"DP wins {s.prop_pos:.0%} of {s.n_eff} non-tied days\n"
                f"exact binomial p = {s.p_value:.2f}\n({s.n_zero} tied days, both idle)",
                xy=(0.03, 0.95), xycoords="axes fraction", va="top", fontsize=9.5, color=C["ink"])
    ax.legend(loc="upper right", fontsize=9.5)
    fig.savefig(path); plt.close(fig)


def fig_psi(psi, path):
    """Fig 6 — the $\\psi_{up}$ tail: complementary CDF (survival) of the binding shadow price on
    log-y, marking the Stage 0 clairvoyant max. A causal operator's tail EXCEEDS the clairvoyant
    (Decision 19). The bulk is ~0; the economics live in the tail."""
    import matplotlib.pyplot as plt
    p = psi["psi_iv"]
    p = p[p > 0]
    xs = np.sort(p)
    ccdf = 1.0 - np.arange(len(xs)) / len(xs)
    fig, ax = plt.subplots(figsize=(8.0, 4.2))
    ax.step(xs, ccdf * 100, where="post", color=C["psi"], lw=2, zorder=3)
    ax.set_yscale("log"); ax.set_xscale("symlog", linthresh=0.1)
    ax.set_xlim(-0.02, p.max() * 1.9)
    ax.axvline(32.75, color=C["ceiling"], lw=1.3, ls="--")
    ax.annotate("Stage 0 clairvoyant\nmax $32.75", xy=(32.75, 0.5), xytext=(6, 0),
                textcoords="offset points", fontsize=9, color=C["ceiling"], va="center")
    ax.axvline(p.max(), color=C["psi"], lw=1.3, ls=":")
    ax.annotate(f"causal max\n${p.max():.1f}", xy=(p.max(), 3), xytext=(6, 0),
                textcoords="offset points", fontsize=9, color=C["psi"], va="center")
    ax.set_xlabel("$\\psi_{up}$, \\$/MWh (interval MCPC at executed SOC, symlog)")
    ax.set_ylabel("% of binding intervals ≥ x (log)")
    ax.set_title("Fig 6 — $\\psi_{up}$ is a heavy-tailed scarcity price")
    fig.savefig(path); plt.close(fig)


def fig_fleet_capture(path):
    """Stage 7 — the real ERCOT fleet's energy-capture distribution with our DP located in it, plus
    the joint energy+AS capture that shows the fleet is well-run. Reads the Stage 7 caches."""
    import matplotlib.pyplot as plt
    xs = pd.read_parquet("data/raw/stage7_energy_cross_section.parquet")
    xs = xs[xs["capture"].notna()]
    real = xs["capture"].to_numpy() * 100
    joint = xs["joint_capture"].dropna().to_numpy() * 100 if "joint_capture" in xs else None
    loc = pd.read_parquet("data/raw/stage7_locate_policy.parquet") if os.path.exists(
        "data/raw/stage7_locate_policy.parquet") else None
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    ax.hist(real, bins=np.linspace(0, 100, 26), color=C["ceiling"], alpha=0.55,
            label=f"real fleet, energy-only (median {np.median(real):.0f}%)", zorder=2)
    ax.axvline(np.median(real), color=C["ceiling"], lw=1.5, ls="--")
    if loc is not None and loc["our_dp_capture"].notna().any():
        our = (loc["our_dp_capture"].dropna().to_numpy()) * 100
        ax.axvline(np.median(our), color=C["dp"], lw=2.5,
                   label=f"our DP, fair (median {np.median(our):.0f}%)")
    if joint is not None:
        ax.axvline(np.median(joint), color=C["pf"], lw=2,
                   label=f"real fleet, energy+AS joint (median {np.median(joint):.0f}%)")
    ax.set_xlabel("capture rate, % of the perfect-foresight ceiling")
    ax.set_ylabel("number of batteries")
    ax.set_title("Fig 7 — locating our DP in the real ERCOT fleet")
    ax.legend(fontsize=9, loc="upper right")
    fig.savefig(path); plt.close(fig)


def stage7_figures():
    _style(); os.makedirs(FIGDIR, exist_ok=True)
    fig_fleet_capture(f"{FIGDIR}/fig7_fleet_capture.png")
    print(f"wrote Stage 7 figure to {FIGDIR}/fig7_fleet_capture.png")


def main():
    _style()
    os.makedirs(FIGDIR, exist_ok=True)
    daily, psi, dur = _load()
    fig_ladder(daily, f"{FIGDIR}/fig1_ladder.png")
    fig_duration(dur, f"{FIGDIR}/fig2_duration.png")
    fig_concentration(daily, f"{FIGDIR}/fig3_concentration.png")
    fig_bootstrap(daily, f"{FIGDIR}/fig4_bootstrap.png")
    fig_signtest(daily, f"{FIGDIR}/fig5_signtest.png")
    fig_psi(psi, f"{FIGDIR}/fig6_psi.png")
    print(f"wrote 6 figures to {FIGDIR}/")


if __name__ == "__main__":
    main()
