"""
Step 4: draw the charts used in the README.

Input:  outputs/*.csv (from analyze.py)
Output: charts/light/*.png and charts/dark/*.png
        (two versions so the README matches GitHub's light and dark themes)
"""
import os

import matplotlib
import pandas as pd
from matplotlib import font_manager

matplotlib.use("Agg")  # draw to files, no window needed
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

OUTPUT_DIR = "outputs"
CHART_DIR = "charts"
SOURCE_NOTE = ("Source: SEC EDGAR XBRL filings, TSMC / Innolight / Eoptolink reports. "
               "GAAP operating profit, calendar-aligned. Analysis: Haoqi Luo")

# Colors follow GitHub's own light and dark backgrounds so the images blend in
THEMES = {
    "light": {
        "background": "#ffffff", "text": "#1f2328", "muted": "#59636e", "grid": "#e6e8eb",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
        "before": "#b4b3ad",
    },
    "dark": {
        "background": "#0d1117", "text": "#e6edf3", "muted": "#9198a1", "grid": "#262c36",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
        "before": "#5a6069",
    },
}


# ---------- Shared styling helpers ----------

def pick_font():
    """Use Inter when it is installed, otherwise matplotlib's default font."""
    installed = {font.name for font in font_manager.fontManager.ttflist}
    font = "Inter" if "Inter" in installed else "DejaVu Sans"
    return font


def new_figure(theme, height, rows=1, height_ratios=None):
    plt.rcParams["font.family"] = pick_font()
    plt.rcParams["text.parse_math"] = False  # so "$" prints as a dollar sign
    fig, axes = plt.subplots(rows, 1, figsize=(10, height), facecolor=theme["background"],
                             gridspec_kw={"height_ratios": height_ratios} if height_ratios else None)
    for ax in (axes if rows > 1 else [axes]):
        ax.set_facecolor(theme["background"])
        for side in ["top", "right", "left", "bottom"]:
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=theme["muted"], labelsize=10, length=0)
    return fig, axes


def add_titles(fig, theme, title, subtitle):
    fig.text(0.03, 0.965, title, fontsize=16, fontweight="semibold", color=theme["text"], va="top")
    fig.text(0.03, 0.905, subtitle, fontsize=10.5, color=theme["muted"], va="top")
    fig.text(0.03, 0.025, SOURCE_NOTE, fontsize=8, color=theme["muted"], va="bottom")


def add_grid(ax, theme, axis):
    ax.grid(axis=axis, color=theme["grid"], linewidth=1)
    ax.set_axisbelow(True)


def save(fig, theme_name, file_name):
    folder = f"{CHART_DIR}/{theme_name}"
    os.makedirs(folder, exist_ok=True)
    fig.savefig(f"{folder}/{file_name}", dpi=200, facecolor=fig.get_facecolor())
    plt.close(fig)


def label_layers(ax, theme, layers, companies):
    """Two-line category labels: layer name, then its companies in smaller grey text."""
    transform = ax.get_yaxis_transform()  # x in axes units, y in data units
    for position, (layer, tickers) in enumerate(zip(layers, companies)):
        ax.text(-0.02, position - 0.13, layer, transform=transform, ha="right", va="center",
                fontsize=11, color=theme["text"])
        ax.text(-0.02, position + 0.23, tickers, transform=transform, ha="right", va="center",
                fontsize=8.5, color=theme["muted"])
    ax.set_yticks([])


def short_tickers(companies):
    """'300308.SZ, COHR' -> 'Innolight · COHR' (readable names for the China listings)."""
    names = {"300308.SZ": "Innolight", "300502.SZ": "Eoptolink"}
    tickers = [names.get(ticker.strip(), ticker.strip()) for ticker in companies.split(",")]
    return " · ".join(tickers)


# ---------- Chart 1: where the new profit went ----------

def chart_new_profit(layer, company, theme, theme_name):
    data = layer.sort_values("new_operating_income", ascending=False).reset_index(drop=True)
    total = data["new_operating_income"].sum()
    nvidia = company.set_index("ticker").loc["NVDA"]

    fig, ax = new_figure(theme, height=5.6)
    fig.subplots_adjust(left=0.30, right=0.95, top=0.80, bottom=0.12)
    ax.barh(data.index, data["new_operating_income"], height=0.55, color=theme["series"][0])
    ax.invert_yaxis()
    label_layers(ax, theme, data["layer"], data["companies"].apply(short_tickers))

    # value label at the end of each bar
    for position, row in data.iterrows():
        text = f"${row['new_operating_income']:.0f}B  ·  {row['share_of_supplier_new_profit']:.0%}"
        ax.text(row["new_operating_income"] + total * 0.008, position, text,
                va="center", fontsize=10, color=theme["text"])
    ax.text(data.loc[0, "new_operating_income"] + total * 0.008, 0.33,
            f"NVIDIA alone: ${nvidia['new_operating_income']:.0f}B ({nvidia['share_of_supplier_new_profit']:.0%})",
            va="center", fontsize=8.5, color=theme["muted"])

    ax.set_xlim(0, data["new_operating_income"].max() * 1.32)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:.0f}B"))
    add_grid(ax, theme, "x")
    add_titles(fig, theme, "Two-thirds of the new profit went to AI chips",
               f"Increase in annual operating profit from CY2022 to the 12 months ending Q2 2026, "
               f"by layer (total ${total:.0f}B)")
    save(fig, theme_name, "1_new_profit_by_layer.png")


# ---------- Chart 2: profit per extra dollar of revenue ----------

def chart_profit_per_dollar(layer, theme, theme_name):
    data = layer.sort_values("profit_per_new_revenue_dollar", ascending=False).reset_index(drop=True)

    fig, ax = new_figure(theme, height=5.6)
    fig.subplots_adjust(left=0.30, right=0.95, top=0.80, bottom=0.12)
    ax.barh(data.index, data["profit_per_new_revenue_dollar"] * 100, height=0.55, color=theme["series"][0])
    ax.invert_yaxis()
    label_layers(ax, theme, data["layer"], data["companies"].apply(short_tickers))

    for position, row in data.iterrows():
        cents = row["profit_per_new_revenue_dollar"] * 100
        text = f"{cents:.0f}¢   (+${row['new_revenue']:.0f}B revenue)"
        ax.text(cents + 1, position, text, va="center", fontsize=10, color=theme["text"])

    ax.set_xlim(0, 125)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}¢"))
    add_grid(ax, theme, "x")
    add_titles(fig, theme, "Scarce parts turned new sales into profit; assembly did not",
               "Operating profit added for every $1 of revenue added, CY2022 to the 12 months ending Q2 2026")
    save(fig, theme_name, "2_profit_per_new_dollar.png")


# ---------- Chart 3: operating margin before and after ----------

def chart_margin_shift(layer, theme, theme_name):
    data = layer.sort_values("operating_margin_ttm", ascending=False).reset_index(drop=True)
    before = data["operating_margin_2022"] * 100
    after = data["operating_margin_ttm"] * 100

    fig, ax = new_figure(theme, height=5.6)
    fig.subplots_adjust(left=0.30, right=0.95, top=0.80, bottom=0.12)
    ax.hlines(data.index, before, after, color=theme["grid"], linewidth=3, zorder=1)
    ax.scatter(before, data.index, s=90, color=theme["before"], zorder=2,
               edgecolor=theme["background"], linewidth=2, label="CY2022")
    ax.scatter(after, data.index, s=90, color=theme["series"][0], zorder=3,
               edgecolor=theme["background"], linewidth=2, label="12 months to Q2 2026")
    ax.invert_yaxis()
    label_layers(ax, theme, data["layer"], data["companies"].apply(short_tickers))

    for position in data.index:
        ax.text(before[position] - 1.6, position, f"{before[position]:.0f}%", ha="right",
                va="center", fontsize=9, color=theme["muted"])
        ax.text(after[position] + 1.6, position, f"{after[position]:.0f}%", ha="left",
                va="center", fontsize=10, color=theme["text"], fontweight="semibold")

    ax.set_xlim(-6, 72)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
    add_grid(ax, theme, "x")
    ax.legend(loc="lower left", bbox_to_anchor=(-0.01, 1.0), ncol=2, frameon=False, fontsize=9.5,
              labelcolor=theme["text"])
    add_titles(fig, theme, "Margins jumped where supply was tight: memory and AI chips",
               "Operating margin by layer (operating profit ÷ revenue)")
    save(fig, theme_name, "3_margin_shift.png")


# ---------- Chart 4: share of supplier profit over time ----------

def chart_profit_share(profit_share, theme, theme_name):
    layers = ["AI chips", "Foundry", "Memory & storage"]
    labels = ["2022", "2023", "2024", "2025", "TTM Q2 '26"]
    data = profit_share.loc[layers] * 100
    others = 100 - data.sum()

    fig, ax = new_figure(theme, height=5.6)
    fig.subplots_adjust(left=0.08, right=0.80, top=0.80, bottom=0.19)
    for index, layer in enumerate(layers):
        values = data.loc[layer].values
        ax.plot(labels, values, color=theme["series"][index], linewidth=2.5, marker="o",
                markersize=7, markeredgecolor=theme["background"], markeredgewidth=2, label=layer)
        ax.text(len(labels) - 1 + 0.12, values[-1], f"{layer}  {values[-1]:.0f}%",
                va="center", fontsize=10, color=theme["text"])

    ax.axhline(0, color=theme["muted"], linewidth=1)
    ax.set_xlim(-0.5, len(labels) - 0.5)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
    add_grid(ax, theme, "y")
    ax.legend(loc="upper left", frameon=False, fontsize=9.5, labelcolor=theme["text"], ncol=3,
              bbox_to_anchor=(0, 1.04))
    fig.text(0.03, 0.075, f"Other layers (servers, networking, optical, power) together: "
                          f"{others.iloc[0]:.0f}% in 2022, {others.iloc[-1]:.0f}% in the latest 12 months.\n"
                          f"Memory is below zero in 2023 because Micron and Seagate both lost money that year.",
             fontsize=8.5, color=theme["muted"], va="bottom", linespacing=1.5)
    add_titles(fig, theme, "Profit moved from the foundry to chip designers, and memory is catching up",
               "Each layer's share of total operating profit across all AI hardware suppliers in this study")
    save(fig, theme_name, "4_profit_share_over_time.png")


# ---------- Chart 5: who pays, cloud capex vs cash flow ----------

def chart_cloud_capex(quarterly, cloud, theme, theme_name):
    companies = ["AMZN", "GOOGL", "MSFT", "META", "ORCL"]  # largest spender at the bottom
    names = {"AMZN": "Amazon", "GOOGL": "Alphabet", "MSFT": "Microsoft", "META": "Meta", "ORCL": "Oracle"}
    labels = [quarter.replace("Q", " Q") if quarter.endswith("Q1") else ""
              for quarter in quarterly.index]
    positions = range(len(quarterly))

    fig, (top, bottom) = new_figure(theme, height=7.4, rows=2, height_ratios=[2.2, 1])
    fig.subplots_adjust(left=0.08, right=0.84, top=0.82, bottom=0.10, hspace=0.38)

    # top panel: stacked quarterly capex, a thin surface-colored gap between segments
    stack_bottom = pd.Series(0.0, index=quarterly.index)
    for index, ticker in enumerate(companies):
        top.bar(positions, quarterly[ticker], bottom=stack_bottom, width=0.62,
                color=theme["series"][index], edgecolor=theme["background"], linewidth=0.8,
                label=names[ticker])
        stack_bottom = stack_bottom + quarterly[ticker]
    first, last = quarterly["total_capex"].iloc[0], quarterly["total_capex"].iloc[-1]
    top.text(0, first + 4, f"${first:.0f}B", ha="center", fontsize=9.5, color=theme["text"])
    top.text(len(quarterly) - 1, last + 4, f"${last:.0f}B", ha="center", fontsize=9.5,
             color=theme["text"], fontweight="semibold")
    handles, legend_labels = top.get_legend_handles_labels()
    top.legend(handles[::-1], legend_labels[::-1], loc="upper left", bbox_to_anchor=(1.01, 1),
               frameon=False, fontsize=9.5, labelcolor=theme["text"])
    top.set_title("Capital spending per quarter (USD billions)", loc="left", fontsize=10.5,
                  color=theme["muted"])
    top.set_xticks(list(positions))
    top.set_xticklabels([""] * len(quarterly))
    top.set_ylim(0, last * 1.15)
    add_grid(top, theme, "y")

    # bottom panel: capex as a share of operating cash flow (trailing four quarters)
    ratio = quarterly["capex_to_ocf_4q"] * 100
    bottom.plot(positions, ratio, color=theme["series"][0], linewidth=2.5)
    bottom.scatter([positions[-1]], [ratio.iloc[-1]], s=60, color=theme["series"][0],
                   edgecolor=theme["background"], linewidth=2, zorder=3)
    bottom.axhline(100, color=theme["muted"], linewidth=1, linestyle=(0, (1, 2)))
    bottom.text(0, 103, "100% = every dollar of operating cash goes back into capex",
                fontsize=8.5, color=theme["muted"], va="bottom")
    bottom.text(positions[-1] + 0.4, ratio.iloc[-1], f"{ratio.iloc[-1]:.0f}%", va="center",
                fontsize=10, color=theme["text"], fontweight="semibold")
    bottom.text(0, ratio.iloc[0] + 7, f"{ratio.iloc[0]:.0f}%", ha="center", va="bottom",
                fontsize=9.5, color=theme["muted"])
    bottom.set_title("Capex as % of operating cash flow (trailing 4 quarters)", loc="left",
                     fontsize=10.5, color=theme["muted"])
    bottom.set_xticks(list(positions))
    bottom.set_xticklabels(labels)
    bottom.set_ylim(0, 115)
    bottom.set_xlim(-0.8, len(quarterly) - 0.2)
    top.set_xlim(-0.8, len(quarterly) - 0.2)
    bottom.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
    add_grid(bottom, theme, "y")

    growth = cloud.loc["TTM 2Q26", "capex"] / cloud.loc["CY2022", "capex"]
    share_of_cash = cloud.loc["TTM 2Q26", "capex_to_operating_cash_flow"]
    add_titles(fig, theme, f"Cloud platforms now spend {share_of_cash:.0%} of their operating cash flow on capex",
               f"Amazon, Alphabet, Microsoft, Meta and Oracle: yearly capex up {growth:.1f}x, "
               f"from ${cloud.loc['CY2022', 'capex']:.0f}B (CY2022) to ${cloud.loc['TTM 2Q26', 'capex']:.0f}B "
               f"(12 months to Q2 2026)")
    save(fig, theme_name, "5_cloud_capex.png")


def main():
    company = pd.read_csv(f"{OUTPUT_DIR}/company_summary.csv")
    layer = pd.read_csv(f"{OUTPUT_DIR}/layer_summary.csv")
    profit_share = pd.read_csv(f"{OUTPUT_DIR}/profit_share_by_year.csv", index_col="layer")
    cloud = pd.read_csv(f"{OUTPUT_DIR}/cloud_capex.csv", index_col="period")
    quarterly = pd.read_csv(f"{OUTPUT_DIR}/cloud_capex_quarterly.csv", index_col="calendar_quarter")

    for theme_name, theme in THEMES.items():
        chart_new_profit(layer, company, theme, theme_name)
        chart_profit_per_dollar(layer, theme, theme_name)
        chart_margin_shift(layer, theme, theme_name)
        chart_profit_share(profit_share, theme, theme_name)
        chart_cloud_capex(quarterly, cloud, theme, theme_name)
    print(f"Saved charts to {CHART_DIR}/light and {CHART_DIR}/dark (font: {pick_font()})")


if __name__ == "__main__":
    main()
