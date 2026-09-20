"""
Reusable Chart Components
==========================
Plotly chart factories for the dashboard.
Dark-themed, mobile-responsive, premium aesthetic.
"""

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from typing import Optional


# --------------------------------------------------------------------------- #
#                          THEME CONSTANTS                                     #
# --------------------------------------------------------------------------- #

COLORS = {
    'bg': '#0d1117',
    'card': '#161b22',
    'card_border': '#30363d',
    'text': '#e6edf3',
    'text_muted': '#8b949e',
    'accent': '#58a6ff',
    'accent2': '#bc8cff',
    'success': '#3fb950',
    'warning': '#d29922',
    'danger': '#f85149',
    'goldilocks': '#3fb950',
    'reflation': '#58a6ff',
    'stagflation': '#d29922',
    'deflation': '#f85149',
    'grid': '#21262d',
}

REGIME_COLORS = {
    'goldilocks': COLORS['goldilocks'],
    'reflation': COLORS['reflation'],
    'stagflation': COLORS['stagflation'],
    'deflation': COLORS['deflation'],
}

CHART_LAYOUT = dict(
    paper_bgcolor=COLORS['bg'],
    plot_bgcolor=COLORS['card'],
    font=dict(family="Inter, sans-serif", color=COLORS['text'], size=12),
    margin=dict(l=50, r=30, t=50, b=40),
    xaxis=dict(gridcolor=COLORS['grid'], zerolinecolor=COLORS['grid']),
    yaxis=dict(gridcolor=COLORS['grid'], zerolinecolor=COLORS['grid']),
    legend=dict(bgcolor='rgba(0,0,0,0)', font=dict(size=11)),
    hoverlabel=dict(bgcolor=COLORS['card'], font_size=12),
)


def _apply_layout(fig: go.Figure, title: str = "", height: int = 400) -> go.Figure:
    """Apply standard dark theme to a figure."""
    fig.update_layout(**CHART_LAYOUT, title=dict(text=title, font=dict(size=16)), height=height)
    return fig


# --------------------------------------------------------------------------- #
#                          CHART FACTORIES                                     #
# --------------------------------------------------------------------------- #

def create_equity_curve(
    equity_curves: dict[str, pd.Series],
    title: str = "Portfolio Equity Curve",
) -> go.Figure:
    """Create overlaid equity curves for multiple strategies."""
    fig = go.Figure()
    colors = [COLORS['accent'], COLORS['accent2'], COLORS['success'],
              COLORS['warning'], COLORS['danger'], '#f0883e']

    for i, (name, curve) in enumerate(equity_curves.items()):
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=curve.index, y=curve.values,
            mode='lines', name=name,
            line=dict(color=color, width=2 if i == 0 else 1.5),
            opacity=1.0 if i == 0 else 0.7,
        ))

    return _apply_layout(fig, title, height=450)


def create_drawdown_chart(
    drawdown: pd.Series,
    title: str = "Drawdown",
) -> go.Figure:
    """Create filled drawdown area chart."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=drawdown.index, y=drawdown.values * 100,
        fill='tozeroy', mode='lines',
        line=dict(color=COLORS['danger'], width=1),
        fillcolor='rgba(248,81,73,0.2)',
        name='Drawdown',
    ))

    # Add 15% threshold line
    fig.add_hline(y=-15, line_dash="dash", line_color=COLORS['warning'],
                  annotation_text="15% Max DD Limit")

    fig.update_yaxes(title_text="Drawdown %")
    return _apply_layout(fig, title, height=300)


def create_regime_timeline(
    regime_history: pd.DataFrame,
    title: str = "Economic Regime History",
) -> go.Figure:
    """Create horizontal bar chart of regime periods."""
    fig = go.Figure()

    if regime_history.empty:
        return _apply_layout(fig, title)

    # Create colored spans for each regime period
    df = regime_history.copy()
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')

    for regime, color in REGIME_COLORS.items():
        mask = df['regime'] == regime
        if mask.any():
            dates = df.index[mask]
            fig.add_trace(go.Scatter(
                x=dates, y=[regime.title()] * len(dates),
                mode='markers',
                marker=dict(color=color, size=8, symbol='square'),
                name=regime.title(),
                showlegend=True,
            ))

    fig.update_yaxes(categoryorder='array',
                     categoryarray=['Deflation', 'Stagflation', 'Reflation', 'Goldilocks'])
    return _apply_layout(fig, title, height=250)


def create_allocation_pie(
    weights: dict[str, float],
    title: str = "Current Allocation",
) -> go.Figure:
    """Create a donut chart showing portfolio allocation."""
    labels = list(weights.keys())
    values = [w * 100 for w in weights.values()]

    # Color palette
    palette = px.colors.qualitative.Set3 + px.colors.qualitative.Pastel

    fig = go.Figure(data=[go.Pie(
        labels=labels, values=values,
        hole=0.5,
        marker=dict(colors=palette[:len(labels)], line=dict(color=COLORS['bg'], width=2)),
        textinfo='label+percent',
        textfont=dict(size=11),
        hovertemplate='%{label}<br>%{value:.1f}%<extra></extra>',
    )])

    fig.update_layout(
        showlegend=False,
        annotations=[dict(text=title.split()[0], x=0.5, y=0.5,
                          font_size=16, showarrow=False, font_color=COLORS['text'])],
    )
    return _apply_layout(fig, title, height=400)


def create_monthly_heatmap(
    heatmap_data: pd.DataFrame,
    title: str = "Monthly Returns Heatmap",
) -> go.Figure:
    """Create a color-coded monthly returns heatmap."""
    if heatmap_data.empty:
        return _apply_layout(go.Figure(), title)

    # Drop 'Annual' column for the heatmap (show separately if needed)
    display = heatmap_data.drop(columns=['Annual'], errors='ignore')

    fig = go.Figure(data=go.Heatmap(
        z=display.values * 100,
        x=display.columns.tolist(),
        y=[str(y) for y in display.index.tolist()],
        colorscale=[
            [0, COLORS['danger']],
            [0.5, COLORS['card']],
            [1, COLORS['success']],
        ],
        zmid=0,
        text=[[f"{v * 100:.1f}%" if pd.notna(v) else "" for v in row]
              for row in display.values],
        texttemplate="%{text}",
        textfont=dict(size=10),
        hovertemplate='%{y} %{x}: %{z:.1f}%<extra></extra>',
        colorbar=dict(title="Return %", ticksuffix="%"),
    ))

    return _apply_layout(fig, title, height=max(250, len(display) * 30 + 100))


def create_metrics_gauge(
    value: float,
    title: str,
    min_val: float = 0,
    max_val: float = 3,
    threshold: Optional[float] = None,
) -> go.Figure:
    """Create a gauge chart for a single metric."""
    color = COLORS['success'] if (threshold and value >= threshold) else COLORS['accent']

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title=dict(text=title, font=dict(size=14, color=COLORS['text'])),
        number=dict(font=dict(size=28, color=COLORS['text'])),
        gauge=dict(
            axis=dict(range=[min_val, max_val], tickcolor=COLORS['text_muted']),
            bar=dict(color=color),
            bgcolor=COLORS['card'],
            borderwidth=0,
            steps=[
                dict(range=[min_val, threshold or max_val * 0.33], color='rgba(248,81,73,0.2)'),
                dict(range=[threshold or max_val * 0.33, max_val], color='rgba(63,185,80,0.1)'),
            ],
            threshold=dict(
                line=dict(color=COLORS['warning'], width=3),
                value=threshold or max_val * 0.5,
            ),
        ),
    ))

    return _apply_layout(fig, height=200)


def create_risk_status_indicators(checks: list[dict]) -> go.Figure:
    """Create risk check status panel with colored indicators."""
    fig = go.Figure()

    for i, check in enumerate(checks):
        color = COLORS['success'] if check.get('passed', True) else COLORS['danger']
        symbol = '✅' if check.get('passed', True) else '❌'

        fig.add_trace(go.Scatter(
            x=[0], y=[len(checks) - i],
            mode='text',
            text=[f"{symbol} {check.get('name', 'Check')}: {check.get('message', '')}"],
            textposition='middle right',
            textfont=dict(color=color, size=12),
            showlegend=False,
        ))

    fig.update_xaxes(visible=False, range=[-0.5, 10])
    fig.update_yaxes(visible=False, range=[0, len(checks) + 1])
    return _apply_layout(fig, "Risk Checks", height=max(200, len(checks) * 35))


def create_macro_indicators(snapshot: dict) -> go.Figure:
    """Create a panel showing current macro indicator values."""
    indicators = [
        ('VIX', snapshot.get('vix_level', 0), ''),
        ('CPI YoY', snapshot.get('cpi_yoy', 0) * 100, '%'),
        ('GDP Growth', snapshot.get('gdp_growth', 0), '%'),
        ('Fed Funds', snapshot.get('fed_funds_rate', 0), '%'),
        ('Yield Curve', snapshot.get('yield_curve', 0), '%'),
        ('HY Spread', snapshot.get('hy_spread', 0), '%'),
    ]

    fig = go.Figure()
    for i, (name, value, suffix) in enumerate(indicators):
        col = i % 3
        row = i // 3
        fig.add_trace(go.Indicator(
            mode="number",
            value=value if isinstance(value, (int, float)) else 0,
            title=dict(text=name, font=dict(size=12)),
            number=dict(suffix=suffix, font=dict(size=20)),
            domain=dict(
                x=[col * 0.33, (col + 1) * 0.33 - 0.02],
                y=[1 - (row + 1) * 0.5, 1 - row * 0.5 - 0.05],
            ),
        ))

    return _apply_layout(fig, "Macro Indicators", height=250)
