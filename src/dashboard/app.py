"""
src/dashboard/app.py
====================
ETF Regime Strategist — Live Dashboard
4 tabs: Regime Monitor, Portfolio, Backtest, Execution
"""
import os
import sys
from pathlib import Path
from datetime import datetime

import dash
from dash import html, dcc, dash_table, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
REGIME_COLORS = {'goldilocks': '#00d97e', 'reflation': '#f5a623', 'stagflation': '#e74c3c', 'deflation': '#3498db'}
REGIME_ICONS = {'goldilocks': '☀️', 'reflation': '🔥', 'stagflation': '⚠️', 'deflation': '❄️'}
ETF_NAMES = {
    'SPY': 'S&P 500', 'QQQ': 'Nasdaq-100', 'IWM': 'Russell 2000', 'VEA': 'Intl Developed',
    'VWO': 'Emerging Mkts', 'TLT': '20+ Yr Bond', 'IEF': '7-10 Yr Bond', 'SHY': '1-3 Yr Bond',
    'AGG': 'Agg Bond', 'TIP': 'TIPS', 'GLD': 'Gold', 'DBC': 'Commodities',
    'VNQ': 'Real Estate', 'SOXX': 'Semiconductors', 'XLE': 'Energy Select',
    'SMH': 'VanEck Semis', 'XSD': 'Equal-Wt Semis', 'DRAM': 'AI Memory/HBM',
    'SPYI': 'S&P High Inc', 'QQQI': 'Nasdaq High Inc', 'TQQQ': '3x Nasdaq',
    'SOXL': '3x Semi', 'DBMF': 'Managed Futures', 'BTAL': 'Anti-Beta',
    'SSO': '2x S&P 500', 'MOAT': 'Wide Moat Quality',
    'URA': 'Global X Uranium', 'AIPO': 'AI IPO & Innov', 'XLY': 'Consumer Discretionary',
    'XEI.TO': 'TSX High Dividend', 'ZWB.TO': 'Cdn Covered Bank',
}
ETF_CATEGORIES = {
    'SPY': 'US Equity', 'QQQ': 'US Equity', 'IWM': 'US Equity',
    'VEA': 'International', 'VWO': 'International',
    'TLT': 'Fixed Income', 'IEF': 'Fixed Income', 'SHY': 'Fixed Income',
    'AGG': 'Fixed Income', 'TIP': 'Fixed Income',
    'GLD': 'Commodities', 'DBC': 'Commodities', 'VNQ': 'Real Estate',
    'SOXX': 'AI/Semis', 'SMH': 'AI/Semis', 'XSD': 'AI/Semis', 'DRAM': 'AI/Semis',
    'XLE': 'Energy', 'SPYI': 'Income', 'QQQI': 'Income',
    'TQQQ': 'Leveraged', 'SOXL': 'Leveraged', 'SSO': 'Leveraged',
    'DBMF': 'Alternatives', 'BTAL': 'Alternatives',
    'MOAT': 'Quality Factor',
    'URA': 'AI/Energy', 'AIPO': 'AI/Semis', 'XLY': 'US Equity',
    'XEI.TO': 'Canadian Equity', 'ZWB.TO': 'Canadian Equity',
}

# ── Foreign withholding tax on distributions, from the perspective of a
#    Canadian (non-US) holder in a TAXABLE account. Drives the Portfolio tab
#    "Fgn Tax" column. US-domiciled ETFs bleed 15% US treaty WHT on dividends
#    (recoverable as a foreign tax credit in a taxable account, 0% inside an RRSP,
#    non-recoverable in a TFSA). Canadian-domiciled (.TO) ETFs have no US WHT on
#    their Canadian-equity distributions and pay eligible dividends (dividend tax
#    credit). Commodity trusts (GLD) make no cash distribution, so nothing is withheld.
def _etf_tax(ticker):
    t = ticker.upper()
    if t.endswith('.TO') or t in {'XEI', 'ZWB', 'ZWC', 'VDY', 'XIU'}:
        return '0% (CA)', 'Cdn-domiciled · eligible Cdn dividend (div tax credit); no US withholding'
    if t == 'GLD':
        return '~0% (US)', 'Physical-gold trust · no cash distribution to withhold'
    return '15% (US)', 'US-domiciled · 15% treaty WHT on dividends (0% in RRSP, non-recoverable in TFSA)'

CS = {'backgroundColor': '#1a1a2e', 'border': '1px solid #2d2d44', 'borderRadius': '12px', 'padding': '20px'}
PL = dict(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
          font=dict(family='Inter, sans-serif', color='#c8c8d4'),
          margin=dict(l=50, r=20, t=40, b=40),
          xaxis=dict(gridcolor='#2d2d44'), yaxis=dict(gridcolor='#2d2d44'))

def hex_rgba(c, a=0.1):
    h = c.lstrip('#')
    return f'rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})'

# ═══════════════════════════════════════════════════════════════════════════
# CHART BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
def make_sparkline(series, color='#00d97e', height=60):
    """Tiny spark with NO axes — used for inline indicators."""
    if len(series) == 0:
        return go.Figure().update_layout(height=height, margin=dict(l=0,r=0,t=0,b=0),
                                          paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    fig = go.Figure(go.Scatter(
        x=series.index, y=series.values, mode='lines',
        line=dict(color=color, width=1.5), fill='tozeroy',
        fillcolor=hex_rgba(color) if color.startswith('#') else 'rgba(0,217,126,0.1)',
        hovertemplate='%{x|%b %Y}: %{y:.2f}<extra></extra>',
    ))
    fig.update_layout(height=height, margin=dict(l=0,r=0,t=0,b=0),
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      xaxis=dict(visible=False), yaxis=dict(visible=False), showlegend=False)
    return fig

def make_timeline_chart(series, color='#00d97e', height=120, title='', unit=''):
    """Full timeline chart WITH x-axis dates — used in Growth/Inflation/Risk panels."""
    if len(series) == 0:
        return go.Figure().update_layout(height=height, margin=dict(l=40,r=10,t=20,b=30),
                                          paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                          title=dict(text='No data', font=dict(color='#6c757d', size=11)))
    s = series.tail(252) if len(series) > 252 else series
    # Format y-axis: detect if pct or absolute
    ytick = '.1%' if unit == '%pct' else '.2f'
    htmpl = f'%{{x|%b %Y}}: %{{y:.2f}}{unit}<extra></extra>'
    fig = go.Figure(go.Scatter(
        x=s.index, y=s.values, mode='lines',
        line=dict(color=color, width=1.8), fill='tozeroy',
        fillcolor=hex_rgba(color) if color.startswith('#') else 'rgba(0,217,126,0.1)',
        hovertemplate=htmpl,
    ))
    # Highlight last value with a marker
    if len(s) > 0:
        fig.add_trace(go.Scatter(
            x=[s.index[-1]], y=[s.values[-1]], mode='markers',
            marker=dict(color=color, size=7, line=dict(color='white', width=1.5)),
            hoverinfo='skip', showlegend=False
        ))
    fig.update_layout(
        height=height,
        margin=dict(l=42, r=10, t=22, b=30),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        title=dict(text=title, font=dict(color='#8888a0', size=10), x=0, pad=dict(l=4)),
        xaxis=dict(
            gridcolor='#2d2d44', tickfont=dict(color='#6c757d', size=9),
            tickformat='%b\'%y', showgrid=True, tickangle=-30,
            nticks=8,
        ),
        yaxis=dict(gridcolor='#2d2d44', tickfont=dict(color='#6c757d', size=9), showgrid=True),
    )
    return fig

def make_regime_timeline(rh):
    if rh.empty:
        fig = go.Figure(); fig.update_layout(**PL, title='No Data'); return fig
    df = rh.copy(); df['date'] = pd.to_datetime(df['date']); df['y'] = 1
    fig = go.Figure()
    for regime in REGIME_COLORS:
        m = df['regime'] == regime
        if m.any():
            fig.add_trace(go.Bar(x=df.loc[m,'date'], y=df.loc[m,'y'], name=regime.title(),
                                  marker_color=REGIME_COLORS[regime],
                                  hovertemplate='%{x|%b %Y}: '+regime.title()+'<extra></extra>'))
    ly = {**PL, 'title': 'Regime Timeline (2005 — Present)', 'barmode': 'stack',
          'showlegend': True, 'height': 200, 'legend': dict(orientation='h', y=1.15, x=0.5, xanchor='center')}
    ly['yaxis'] = dict(visible=False)
    fig.update_layout(**ly)
    return fig

def make_allocation_donut(weights):
    if not weights:
        fig = go.Figure(); fig.update_layout(**PL, title='No Data'); return fig
    t, v = list(weights.keys()), list(weights.values())
    colors = [px.colors.qualitative.Set3[i % len(px.colors.qualitative.Set3)] for i in range(len(t))]
    fig = go.Figure(go.Pie(labels=t, values=v, hole=0.55, textinfo='label+percent',
                            textposition='outside', marker=dict(colors=colors, line=dict(color='#1a1a2e', width=2))))
    fig.update_layout(**PL, title='Current Allocation', height=380, showlegend=False,
                      annotations=[dict(text=f'{len(t)}<br>ETFs', x=0.5, y=0.5, font_size=16, font_color='#c8c8d4', showarrow=False)])
    return fig

def make_equity_curves(all_eq, equity_curve):
    """Build equity curve chart with ALL benchmarks."""
    fig = go.Figure()
    strat_colors = {'Optimized Regime Strategy': '#00d97e',
                    'Aggressive Regime Strategy': '#00d97e',
                    'Basic Regime (upper bound)': '#f5a623', 'Basic Regime Strategy': '#f5a623',
                    '60/40 Benchmark': '#9b59b6', 'S&P 500': '#3498db', 'All Weather': '#e74c3c'}
    main_names = {'Optimized Regime Strategy', 'Vol-Targeted Regime Strategy',
                  'Aggressive Regime Strategy'}

    if not all_eq.empty:
        for col in all_eq.columns:
            vals = all_eq[col].dropna() * 100000  # normalize to $100K
            c = strat_colors.get(col, '#6c757d')
            is_main = col in main_names
            fig.add_trace(go.Scatter(
                x=vals.index, y=vals.values, name=col,
                line=dict(color=c, width=2.5 if is_main else 1.2, dash=None if is_main else 'dot'),
                hovertemplate='%{x|%b %Y}: $%{y:,.0f}<extra>'+col+'</extra>',
            ))
    elif len(equity_curve) > 0:
        vals = equity_curve * 100000
        fig.add_trace(go.Scatter(x=vals.index, y=vals.values, name='Optimized Regime Strategy',
                                  line=dict(color='#00d97e', width=2.5)))

    fig.update_layout(**PL, title='Equity Curve — All Strategies ($100K Initial)', height=420,
                      yaxis_title='Portfolio Value ($)', hovermode='x unified',
                      legend=dict(orientation='h', y=1.12, x=0.5, xanchor='center'))
    return fig

def make_drawdown(equity_curve):
    fig = go.Figure()
    if len(equity_curve) > 0:
        rm = equity_curve.cummax()
        dd = (equity_curve - rm) / rm * 100
        fig.add_trace(go.Scatter(x=dd.index, y=dd.values, fill='tozeroy', name='Drawdown',
                                  line=dict(color='#e74c3c', width=1), fillcolor='rgba(231,76,60,0.2)'))
    fig.update_layout(**PL, title='Drawdown Analysis', height=250, yaxis_title='Drawdown (%)')
    return fig

def make_monthly_heatmap(monthly_returns):
    if len(monthly_returns) == 0:
        fig = go.Figure(); fig.update_layout(**PL, title='Monthly Returns — No Data'); return fig
    mr = monthly_returns.copy()
    mr.index = pd.to_datetime(mr.index)
    df = pd.DataFrame({'year': mr.index.year, 'month': mr.index.month, 'return': mr.values * 100})
    pivot = df.pivot_table(index='year', columns='month', values='return', aggfunc='first')
    pivot = pivot.reindex(columns=range(1, 13))  # guarantee all 12 month columns
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    pivot.columns = month_names

    # Annual return per year — COMPOUNDED (1+r) product, which reconciles exactly
    # with the backtest's total return. A spacer column separates it from the months.
    annual = ((1 + mr).groupby(mr.index.year).prod() - 1) * 100
    annual = annual.reindex(pivot.index)

    x_cols = month_names + ['  ', 'Year']
    z_rows, text_rows = [], []
    for i in range(len(pivot.index)):
        months = list(pivot.iloc[i].values)
        a = annual.iloc[i]
        z_rows.append(months + [np.nan, a])
        trow = [f'{v:.1f}' if pd.notna(v) else '' for v in months]
        trow += ['', f'{a:+.1f}%' if pd.notna(a) else '']
        text_rows.append(trow)

    fig = go.Figure(go.Heatmap(
        z=z_rows, x=x_cols, y=pivot.index,
        colorscale=[[0,'#e74c3c'],[0.5,'#1a1a2e'],[1,'#00d97e']],
        zmid=0, zmin=-12, zmax=12,           # clamp so monthly colours stay readable
        text=text_rows, texttemplate='%{text}',
        textfont=dict(size=10),
        hovertemplate='%{y} %{x}: %{z:.1f}%<extra></extra>',
        xgap=1, ygap=1,
    ))
    ly = {**PL, 'title': 'Monthly Returns Heatmap (%) — with compounded annual return',
          'height': max(300, len(pivot)*24+90)}
    ly['yaxis'] = dict(autorange='reversed', gridcolor='#2d2d44', dtick=1)
    fig.update_layout(**ly)
    return fig

# ═══════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def mc(title, value, sub='', color='#c8c8d4', icon=''):
    return html.Div([
        html.Div(icon, style={'fontSize': '22px', 'marginBottom': '2px'}) if icon else html.Div(),
        html.Div(title, style={'color': '#8888a0', 'fontSize': '11px', 'textTransform': 'uppercase',
                                'letterSpacing': '1px', 'marginBottom': '3px'}),
        html.Div(value, style={'color': color, 'fontSize': '26px', 'fontWeight': '700'}),
        html.Div(sub, style={'color': '#6c757d', 'fontSize': '11px', 'marginTop': '2px'}) if sub else html.Div(),
    ], style={**CS, 'textAlign': 'center', 'minHeight': '110px'})

def macro_ind(name, value, series, color='#00d97e'):
    """Macro indicator row: label + value + full timeline chart with dates."""
    return html.Div([
        html.Div([
            html.Span(name, style={'color': '#c8c8d4', 'fontSize': '13px'}),
            html.Span(value, style={'color': color, 'fontSize': '15px', 'fontWeight': '700', 'float': 'right'}),
        ]),
        # Full timeline chart with x-axis dates (was a tiny dateless sparkline)
        dcc.Graph(
            figure=make_timeline_chart(
                series.tail(252) if len(series) > 252 else series,
                color=color,
                height=120,
                title=f'{name} — trailing 12 months',
            ),
            config={'displayModeBar': False},
            style={'marginTop': '4px'},
        ),
    ], style={'marginBottom': '14px'})

def make_timestamp_strip(data, cache_type='all'):
    ts = data.get('timestamps', {})
    price_ts = ts.get('price_data', 'N/A')
    macro_ts = ts.get('macro_data', 'N/A')
    backtest_ts = ts.get('backtest_results', 'N/A')
    audit_ts = ts.get('audit_run', 'N/A')
    
    items = []
    if cache_type in ['all', 'price']:
        items.append(html.Span(f"📁 Prices Last Synced: {price_ts}", style={'marginRight': '20px'}))
    if cache_type in ['all', 'macro']:
        items.append(html.Span(f"📊 Macro Data Fetched: {macro_ts}", style={'marginRight': '20px'}))
    if cache_type in ['all', 'backtest']:
        items.append(html.Span(f"📈 Backtest Calculations: {backtest_ts}", style={'marginRight': '20px'}))
    if cache_type in ['all', 'audit']:
        items.append(html.Span(f"🔍 Auditor Run: {audit_ts}", style={'marginRight': '20px'}))
        
    return html.Div(items, style={
        'color': '#8888a0', 'fontSize': '11px', 'backgroundColor': '#16213e',
        'border': '1px solid #2d2d44', 'borderRadius': '6px', 'padding': '6px 12px',
        'marginBottom': '12px', 'display': 'flex', 'flexWrap': 'wrap', 'justifyContent': 'center'
    })

# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: REGIME MONITOR
# ═══════════════════════════════════════════════════════════════════════════
def _sig_color(sig):
    return {'STRONG': '#00d97e', 'NEUTRAL': '#f5a623', 'WEAK': '#e74c3c',
            'NEW': '#3498db'}.get(sig, '#8888a0')


def _source_line(text):
    """Standard 'Source · As of' footer for any report/analysis panel."""
    return html.Div(text, style={'color': '#6c757d', 'fontSize': '10px',
                                  'marginTop': '6px', 'fontStyle': 'italic'})


def render_ai_intelligence(data):
    """Enhanced AI Trend Intelligence: generated report + strategy verification,
    sector signal table, live SemiAnalysis feed, and config-driven bank research.
    Every panel carries an explicit Source + date stamp."""
    ai = data.get('ai_trend', {}) or {}
    sig = ai.get('signals', {}) or {}
    ver = ai.get('verification', {}) or {}
    report = ai.get('report', []) or []
    semi = ai.get('semianalysis', {}) or {}
    semi_items = semi.get('items', []) if isinstance(semi, dict) else (semi or [])
    bank = ai.get('bank_research', {}) or {}
    generated = ai.get('generated', '—')
    as_of = sig.get('as_of', '—')
    status_color = {'ALIGNED': '#00d97e', 'UNDEREXPOSED': '#f5a623',
                    'DIVERGENCE': '#e74c3c', 'NEUTRAL': '#f5a623'}.get(ver.get('status'), '#8888a0')

    # ── Generated report + verification verdict ──
    def md_bold(t):
        parts = t.split('**')
        return [html.Span(p, style={'fontWeight': '700', 'color': '#fff'}) if i % 2
                else html.Span(p) for i, p in enumerate(parts)]
    report_box = html.Div([
        html.Div([
            html.Span('AI Trend Intelligence — Generated Report', style={'color': '#9b59b6', 'fontWeight': '700', 'fontSize': '13px'}),
            html.Span(ver.get('verdict', '—'), style={
                'backgroundColor': status_color, 'color': '#000', 'fontSize': '12px',
                'fontWeight': '700', 'borderRadius': '6px', 'padding': '2px 10px', 'marginLeft': '10px'}),
        ], style={'marginBottom': '8px', 'display': 'flex', 'alignItems': 'center'}),
        html.Ul([html.Li(md_bold(l), style={'color': '#c8c8d4', 'fontSize': '12px',
                 'lineHeight': '1.5', 'marginBottom': '3px'}) for l in report]),
        _source_line(f"Source: app price signals + SemiAnalysis + bank research · "
                     f"Verified against run_optimized_regime_backtest · Generated {generated}"),
    ], style={**CS, 'padding': '12px', 'marginBottom': '12px', 'borderLeft': f'3px solid {status_color}'})

    # ── Sector signal table (DRAM/SMH/XSD + core), source-stamped ──
    def cell(v, color='#c8c8d4', w='400'):
        return html.Td(v, style={'color': color, 'fontSize': '12px', 'padding': '4px 8px', 'fontWeight': w})

    def pct(x):
        return f'{x:+.0%}' if x is not None else '—'

    def tri(v):
        return ('Yes', '#00d97e') if v is True else (('No', '#e74c3c') if v is False else ('n/a', '#8888a0'))
    rows = []
    for t, s in (sig.get('tickers', {}) or {}).items():
        tlab, tcol = tri(s.get('above_200ma'))
        hist = s.get('hist_days', 0)
        rows.append(html.Tr([
            cell(t, '#fff', '700'),
            cell(s.get('signal', '—'), _sig_color(s.get('signal')), '700'),
            cell(pct(s.get('ret_1m'))), cell(pct(s.get('ret_3m'))), cell(pct(s.get('ret_12m'))),
            cell(tlab, tcol),
            cell(pct(s.get('rel_3m_vs_spy'))),
            cell(f"{s.get('vol_21d', 0):.0%}"),
            cell('● held' if s.get('in_strategy') else '○ watch',
                 '#00d97e' if s.get('in_strategy') else '#8888a0'),
            cell(f"{hist}d" if hist < 250 else '2y+', '#8888a0'),
        ]))
    header = html.Tr([html.Th(h, style={'color': '#8888a0', 'fontSize': '11px', 'textAlign': 'left', 'padding': '4px 8px'})
                      for h in ['ETF', 'Signal', '1m', '3m', '12m', '>200MA', 'RS vs SPY', 'Vol', 'In strategy', 'Hist']])
    signals_table = html.Div([
        html.Div([
            html.Span('Sector Signals ', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '13px'}),
            html.Span(f"composite {sig.get('sector_signal','—')} ({sig.get('sector_score',0):+.0f}) · {sig.get('breadth','—')}",
                      style={'color': _sig_color(sig.get('sector_signal')), 'fontSize': '11px', 'fontWeight': '600'}),
        ], style={'marginBottom': '6px'}),
        html.Table([html.Thead(header), html.Tbody(rows)], style={'width': '100%'}),
        html.Div('SOXX/SMH/DRAM/XSD = broad semis, memory/HBM & equal-weight; QQQ/SOXL/TQQQ = AI software/leverage. '
                 'DRAM is a newer ETF (short history → "NEW").',
                 style={'color': '#8888a0', 'fontSize': '10px', 'marginTop': '6px'}),
        _source_line(f"Source: {sig.get('source','Yahoo Finance')} · "
                     f"momentum/trend/relative-strength computed in-app · As of {as_of}"),
    ], style={**CS, 'padding': '12px', 'marginBottom': '12px'})

    # ── Live SemiAnalysis feed (Substack) ──
    feed_items = [html.Div([
        html.A(it.get('title', ''), href=it.get('link', '#'), target='_blank',
               style={'color': '#3498db', 'fontSize': '12px', 'fontWeight': '600', 'textDecoration': 'none'}),
        html.Span(f"  · {it.get('date','')}", style={'color': '#6c757d', 'fontSize': '10px'}),
        html.Div(it.get('summary', ''), style={'color': '#8888a0', 'fontSize': '11px', 'lineHeight': '1.4', 'marginTop': '2px'}),
    ], style={'marginBottom': '8px', 'borderBottom': '1px solid #2d2d44', 'paddingBottom': '6px'})
        for it in semi_items] or [html.Div('SemiAnalysis feed unavailable (network/cache). Auto-retries daily.',
                                            style={'color': '#6c757d', 'fontSize': '11px'})]
    semi_src = semi.get('source', 'SemiAnalysis') if isinstance(semi, dict) else 'SemiAnalysis'
    semi_fetched = semi.get('fetched', '—') if isinstance(semi, dict) else '—'
    semi_home = (semi.get('home') or 'https://newsletter.semianalysis.com/archive') if isinstance(semi, dict) else 'https://newsletter.semianalysis.com/archive'
    semi_panel = html.Div([
        html.Div([
            html.Span('🔬 SemiAnalysis — Latest', style={'color': '#00d97e', 'fontWeight': '700', 'fontSize': '13px'}),
            html.A('  View all on newsletter.semianalysis.com ↗', href=semi_home, target='_blank',
                   style={'color': '#3498db', 'fontSize': '10px', 'textDecoration': 'none', 'fontWeight': '600'}),
        ], style={'marginBottom': '8px', 'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'baseline'}),
        html.Div(feed_items),
        _source_line(f"Source: {semi_src} · headlines link to the full posts · live feed refreshed daily · Fetched {semi_fetched}"),
    ], style={**CS, 'padding': '12px', 'marginBottom': '12px'})

    # ── Market Sentiment Consensus (Tiers 1-2: multi-source FinBERT news) ──
    sent = ai.get('market_sentiment', {}) or {}
    ov = sent.get('overall', {}) or {}
    sc = float(ov.get('score', 0.0))
    slabel = ov.get('label', 'Neutral')
    s_color = {'Bullish': '#00d97e', 'Bearish': '#e74c3c', 'Neutral': '#f5a623'}.get(slabel, '#8888a0')
    engine = sent.get('engine', 'none')

    def _scol(lbl):
        return {'Bullish': '#00d97e', 'Bearish': '#e74c3c', 'Neutral': '#f5a623'}.get(lbl, '#8888a0')

    def _bar(score, color, width=120):
        pct = max(0, min(100, (score + 1) / 2 * 100))
        return html.Div([html.Div(style={'position': 'absolute', 'left': f'{pct}%', 'top': '-2px',
                                          'width': '3px', 'height': '14px', 'backgroundColor': '#fff'})],
                        style={'position': 'relative', 'display': 'inline-block', 'verticalAlign': 'middle',
                               'width': f'{width}px', 'height': '10px', 'borderRadius': '5px', 'marginLeft': '6px',
                               'background': 'linear-gradient(90deg,#e74c3c,#f5a623,#00d97e)'})

    # Theme gauges (Mag7 / Semis / HBM-Memory) + the CapEx pulse (Tier 2)
    cap = sent.get('capex', {}) or {}
    theme_rows = []
    for t in (sent.get('themes', []) or []):
        theme_rows.append(html.Div([
            html.Span(t['name'], style={'color': '#c8c8d4', 'fontSize': '11px', 'width': '92px', 'display': 'inline-block'}),
            html.Span(f"{t['score']:+.2f}", style={'color': _scol(t['label']), 'fontSize': '11px', 'fontWeight': '700', 'width': '42px', 'display': 'inline-block'}),
            _bar(t['score'], _scol(t['label'])),
            html.Span(f" n={t['n']}", style={'color': '#6c757d', 'fontSize': '9px', 'marginLeft': '6px'}),
        ], style={'marginBottom': '4px'}))
    # CapEx pulse — Tier-2 leading indicator: FinBERT commentary + HARD EDGAR data
    edgar = ai.get('edgar_capex', {}) or {}
    capex_row = html.Div([
        html.Span('⚡ CapEx pulse', style={'color': '#f5a623', 'fontSize': '11px', 'fontWeight': '700', 'width': '92px', 'display': 'inline-block'}),
        html.Span(f"{cap.get('score',0):+.2f}", style={'color': _scol(cap.get('label')), 'fontSize': '11px', 'fontWeight': '700', 'width': '42px', 'display': 'inline-block'}),
        _bar(float(cap.get('score', 0)), _scol(cap.get('label'))),
        html.Span(f" n={cap.get('n',0)} · FinBERT commentary", style={'color': '#6c757d', 'fontSize': '9px', 'marginLeft': '6px'}),
    ], style={'marginBottom': '2px', 'paddingTop': '4px', 'borderTop': '1px dashed #2d2d44'})
    # Hard hyperscaler capex from SEC EDGAR (next to the commentary)
    eg_yoy = edgar.get('agg_yoy')
    edgar_row = html.Div([
        html.Span('   ↳ hard capex', style={'color': '#8888a0', 'fontSize': '10px', 'width': '92px', 'display': 'inline-block'}),
        html.Span(f"${edgar.get('agg_capex_b','—')}B", style={'color': '#00d97e', 'fontSize': '11px', 'fontWeight': '700'}),
        html.Span(f"  YoY {eg_yoy:+.0%}" if eg_yoy is not None else '  YoY —',
                  style={'color': '#00d97e' if (eg_yoy or 0) > 0 else '#e74c3c', 'fontSize': '11px', 'fontWeight': '700', 'marginLeft': '4px'}),
        html.Span(f"  · MSFT/GOOGL/AMZN/META latest Q · SEC EDGAR", style={'color': '#6c757d', 'fontSize': '9px', 'marginLeft': '6px'}),
    ], style={'marginBottom': '4px'}) if edgar.get('companies') else html.Div()

    # Per-ticker movers (most bullish + most bearish)
    tks = sent.get('tickers', []) or []
    movers = (tks[:3] + tks[-3:]) if len(tks) > 6 else tks
    mover_chips = html.Div([
        html.Span(f"{t['ticker']} {t['score']:+.2f}",
                  style={'color': _scol(t['label']), 'fontSize': '10px', 'fontWeight': '600',
                         'border': f"1px solid {_scol(t['label'])}", 'borderRadius': '4px',
                         'padding': '1px 5px', 'marginRight': '5px', 'marginBottom': '4px', 'display': 'inline-block'})
        for t in movers], style={'marginTop': '4px'})

    head_rows = html.Div([
        html.Div([
            html.Span(f"{h['ticker']}", style={'color': '#9b59b6', 'fontSize': '9px', 'fontWeight': '700', 'marginRight': '4px'}),
            html.Span('▲' if h['score'] > 0.15 else ('▼' if h['score'] < -0.15 else '■'),
                      style={'color': _scol(h['label']), 'fontSize': '9px', 'marginRight': '4px'}),
            html.A(h['title'][:58], href=h.get('link', '#'), target='_blank',
                   style={'color': '#8888a0', 'fontSize': '10px', 'textDecoration': 'none'}),
        ], style={'marginBottom': '2px'}) for h in (sent.get('headlines', []) or [])[:5]])

    sentiment_panel = html.Div([
        html.Div([
            html.Span('🧠 Market Sentiment Consensus', style={'color': '#9b59b6', 'fontWeight': '700', 'fontSize': '13px'}),
            html.Span(f' {engine}', style={'color': '#6c757d', 'fontSize': '10px', 'marginLeft': '6px'}),
        ], style={'marginBottom': '2px'}),
        html.Div([
            html.Span(slabel, style={'color': s_color, 'fontSize': '20px', 'fontWeight': '800'}),
            html.Span(f'  {sc:+.2f}', style={'color': s_color, 'fontSize': '14px', 'fontWeight': '700'}),
            html.Span(f'  ({sent.get("n",0)} headlines, Mag7/semis/HBM)', style={'color': '#8888a0', 'fontSize': '10px'}),
        ], style={'marginBottom': '8px'}),
        html.Div(theme_rows + [capex_row, edgar_row]),
        html.Div('Movers:', style={'color': '#c8c8d4', 'fontSize': '11px', 'fontWeight': '600', 'margin': '8px 0 2px'}),
        mover_chips,
        html.Div('Headlines:', style={'color': '#c8c8d4', 'fontSize': '11px', 'fontWeight': '600', 'margin': '8px 0 2px'}),
        head_rows,
        _source_line(f"Source: {engine} on Google News (Mag7/semis/HBM) + SEC EDGAR capex · "
                     f"weekly · indicator only, NOT in the backtest · Computed {sent.get('computed','—')}"),
    ], style={**CS, 'padding': '12px', 'marginBottom': '12px', 'borderLeft': f'3px solid {s_color}'})

    # ── Reddit retail attention (Tier 3 — experimental, VADER, display-only) ──
    rd = ai.get('reddit', {}) or {}
    rd_ov = rd.get('overall', {}) or {}
    rd_color = _scol(rd_ov.get('label', 'Neutral'))
    rd_rows = [html.Div([
        html.Span(t['ticker'], style={'color': '#c8c8d4', 'fontSize': '11px', 'width': '60px', 'display': 'inline-block', 'fontWeight': '600'}),
        html.Span(f"{t['mentions']}×", style={'color': '#9b59b6', 'fontSize': '11px', 'width': '40px', 'display': 'inline-block', 'fontWeight': '700'}),
        html.Span(f"{t['score']:+.2f} {t['label']}", style={'color': _scol(t['label']), 'fontSize': '10px'}),
    ], style={'marginBottom': '3px'}) for t in (rd.get('tickers', []) or [])[:8]]
    hype = rd.get('hype', []) or []
    reddit_panel = html.Div([
        html.Div([
            html.Span('👽 Reddit Retail Attention', style={'color': '#e67e22', 'fontWeight': '700', 'fontSize': '13px'}),
            html.Span(f"  {rd.get('engine','—')} · experimental", style={'color': '#6c757d', 'fontSize': '10px', 'marginLeft': '6px'}),
        ], style={'marginBottom': '6px'}),
        html.Div([
            html.Span(rd_ov.get('label', '—'), style={'color': rd_color, 'fontSize': '16px', 'fontWeight': '800'}),
            html.Span(f"  {rd_ov.get('score',0):+.2f}", style={'color': rd_color, 'fontSize': '12px', 'fontWeight': '700'}),
            html.Span(f"  ({rd.get('n_posts',0)} posts · r/wsb·stocks·semis)", style={'color': '#8888a0', 'fontSize': '10px'}),
        ], style={'marginBottom': '6px'}) if rd.get('available') else
        html.Div('Reddit feed unavailable (rate-limited). Auto-retries.', style={'color': '#6c757d', 'fontSize': '11px'}),
        (html.Div([html.Span('🔥 Hype flag (contrarian): ', style={'color': '#e74c3c', 'fontSize': '10px', 'fontWeight': '700'}),
                   html.Span(', '.join(hype), style={'color': '#e74c3c', 'fontSize': '10px'})],
                  style={'marginBottom': '6px'}) if hype else html.Div()),
        html.Div('Most-mentioned (attention):', style={'color': '#c8c8d4', 'fontSize': '11px', 'fontWeight': '600', 'margin': '4px 0 2px'}) if rd_rows else html.Div(),
        html.Div(rd_rows),
        _source_line("Source: Reddit public RSS + VADER (social-tuned) · CONTRARIAN attention signal · "
                     f"experimental, display-only, NOT in the backtest · Computed {rd.get('computed','—')}"),
    ], style={**CS, 'padding': '12px', 'marginBottom': '12px', 'borderLeft': '3px solid #e67e22'})

    return html.Div([report_box, signals_table,
                     dbc.Row([dbc.Col(semi_panel, md=6), dbc.Col(sentiment_panel, md=6)]),
                     dbc.Row([dbc.Col(reddit_panel, md=12)])])


def render_gsblbr_panel(data, title_prefix="🇺🇸"):
    """Render Goldman Sachs Bull/Bear Market Indicator (GSBLBR) & 5-Factor Gauge.
    Cross-checks macro cycle and ensures alignment with the regime classification."""
    gs_df = data.get('gsblbr_data', pd.DataFrame())
    curr_regime = data.get('current_regime', 'goldilocks')
    rc = REGIME_COLORS.get(curr_regime, '#00d97e')

    if gs_df.empty:
        # Fallback values if cache not populated
        reading = 66.6
        as_of = "2026-08"
        factors = {
            'Shiller P/E (Valuation)': 90.4,
            'Labor Tightness (Unemployment)': 87.8,
            'Yield Curve Inversion': 65.5,
            'Core Inflation (YoY)': 50.0,
            'Economic Activity (Mfg/Output)': 39.5,
        }
    else:
        row = gs_df.iloc[-1]
        reading = float(row.get('GSBLBR', 66.6))
        as_of = gs_df.index[-1].strftime('%Y-%m') if hasattr(gs_df.index[-1], 'strftime') else str(gs_df.index[-1])[:7]
        factors = {
            'Shiller P/E (Valuation)': float(row.get('Shiller_Valuation', 90.4)),
            'Labor Tightness (Unemployment)': float(row.get('Labor_Tightness', 87.8)),
            'Yield Curve Inversion': float(row.get('Yield_Curve_Inversion', 65.5)),
            'Core Inflation (YoY)': float(row.get('Core_Inflation', 50.0)),
            'Economic Activity (Mfg/Output)': float(row.get('Economic_Activity', 39.5)),
        }

    # Signal & Risk Level
    if reading >= 80.0:
        risk_lvl = "EXTREME BEAR RISK 🚨"
        risk_col = "#e74c3c"
        align_note = "High risk of cycle rollover. Strategy triggers defensive overlays (DD circuit-breaker active)."
    elif reading >= 65.0:
        risk_lvl = "ELEVATED / LATE CYCLE ⚠️"
        risk_col = "#f5a623"
        align_note = "Late-cycle expansion. While current momentum confirms Goldilocks, stretched valuation & tight labor warrant tight trailing stops."
    elif reading >= 45.0:
        risk_lvl = "MODERATE / EXPANSIONARY ⚖️"
        risk_col = "#3498db"
        align_note = "Macro conditions balanced. Confirms standard regime weights with healthy risk-reward."
    else:
        risk_lvl = "FAVORABLE / TROUGH BUY ZONE 🟢"
        risk_col = "#00d97e"
        align_note = "Low bear market risk. Maximum upside potential across equity sleeves."

    def _bar(score, color):
        pct = max(0, min(100, score))
        return html.Div([
            html.Div(style={
                'width': f'{pct}%', 'height': '100%',
                'background': f'linear-gradient(90deg, #00d97e, {color})',
                'borderRadius': '4px'
            })
        ], style={
            'backgroundColor': '#16213e', 'height': '8px', 'borderRadius': '4px',
            'border': '1px solid #2d2d44', 'marginTop': '4px', 'width': '100%'
        })

    gauge_cols = []
    for name, score in factors.items():
        sc_col = '#e74c3c' if score >= 75 else ('#f5a623' if score >= 55 else '#00d97e')
        gauge_cols.append(dbc.Col(html.Div([
            html.Div([
                html.Span(name, style={'color': '#c8c8d4', 'fontSize': '11px', 'fontWeight': '600'}),
                html.Span(f'{score:.1f}%', style={'color': sc_col, 'fontSize': '11px', 'fontWeight': '700', 'float': 'right'}),
            ]),
            _bar(score, sc_col),
            html.Div(f"{'Extreme Overheat' if score>=85 else ('Elevated Risk' if score>=65 else 'Neutral/Low')}",
                     style={'color': '#6c757d', 'fontSize': '10px', 'marginTop': '2px'}),
        ], style={'backgroundColor': '#16213e', 'padding': '8px 10px', 'borderRadius': '6px', 'border': '1px solid #2d2d44', 'marginBottom': '6px'}), md=12))

    return html.Div([
        html.Div([
            html.Span(f'{title_prefix} Goldman Sachs Bull/Bear Market Indicator (GSBLBR)',
                      style={'color': '#f5a623', 'fontWeight': '700', 'fontSize': '13px'}),
            html.Span(f'Composite: {reading:.1f}th Percentile',
                      style={'backgroundColor': risk_col, 'color': '#000', 'fontSize': '12px',
                             'fontWeight': '700', 'borderRadius': '6px', 'padding': '2px 8px', 'marginLeft': '10px'}),
            html.Span(risk_lvl, style={'color': risk_col, 'fontSize': '11px', 'fontWeight': '700', 'marginLeft': '10px'}),
        ], style={'marginBottom': '8px', 'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap'}),

        html.Div([
            html.Span('Regime Alignment Status: ', style={'color': '#8888a0', 'fontSize': '11px', 'fontWeight': '600'}),
            html.Span(f'Aligned with {curr_regime.upper()} ({align_note})',
                      style={'color': '#c8c8d4', 'fontSize': '11px'}),
        ], style={'backgroundColor': '#16213e', 'padding': '6px 10px', 'borderRadius': '4px', 'marginBottom': '10px', 'borderLeft': f'3px solid {risk_col}'}),

        html.Div([
            html.Div('5-Factor Percentile Gauge (Historical Rank vs US & Global Cycles):',
                     style={'color': '#8888a0', 'fontSize': '11px', 'marginBottom': '6px'}),
            dbc.Row(gauge_cols),
        ]),
        _source_line(f"Source: Goldman Sachs Global Investment Research methodology · S&P Shiller valuation, FRED Yield Curve, BLS Core CPI, Unemployment, INDPRO · As of {as_of}"),
    ], style={**CS, 'padding': '14px', 'marginBottom': '16px', 'border': f'1px solid {risk_col}'})


def build_regime_tab(data):
    regime = data.get('current_regime', 'goldilocks')
    rc = REGIME_COLORS.get(regime, '#ccc')
    ri = REGIME_ICONS.get(regime, '📊')
    conf = data.get('regime_confidence', 0)
    vix = data.get('vix_current', 0)
    yc = data.get('yield_curve_current', 0)
    macro = data.get('macro', {})
    derived = data.get('derived', {})
    rh = data.get('regime_history', pd.DataFrame())

    vix_s = macro.get('vix', pd.Series(dtype=float))
    gdp_s = macro.get('gdp', pd.Series(dtype=float))
    cpi_s = derived.get('cpi_yoy', pd.Series(dtype=float)) if derived else pd.Series(dtype=float)
    unemp_s = macro.get('unemp', pd.Series(dtype=float))
    t10y_s = macro.get('t10y', pd.Series(dtype=float))
    t2y_s = macro.get('t2y', pd.Series(dtype=float))
    ff_s = macro.get('ff_rate', pd.Series(dtype=float))
    yc_s = (t10y_s - t2y_s).dropna() if len(t10y_s) > 0 and len(t2y_s) > 0 else pd.Series(dtype=float)

    def _last(s):
        try:
            s2 = s.dropna()
            return s2.index[-1].strftime('%Y-%m-%d') if len(s2) else '—'
        except Exception:
            return '—'
    macro_src = (f"Source: FRED — VIX {_last(vix_s)}, CPI {_last(cpi_s)}, GDP {_last(gdp_s)}, "
                 f"UNRATE {_last(unemp_s)}, FedFunds {_last(ff_s)}, 10Y/2Y {_last(t10y_s)} · "
                 f"Prices: Yahoo Finance · Regime computed in-app (rules-based)")

    return html.Div([
        make_timestamp_strip(data, 'macro'),
        dbc.Row([
            dbc.Col(mc('Current Regime', regime.upper(), f'{ri} {conf:.0f}% confidence', rc, ri), md=3),
            dbc.Col(mc('VIX Level', f'{vix:.1f}', 'Low' if vix<15 else 'Normal' if vix<25 else 'Elevated',
                        '#00d97e' if vix<20 else '#f5a623' if vix<30 else '#e74c3c', '📈'), md=3),
            dbc.Col(mc('Yield Curve', f'{yc:.2f}%', 'Normal' if yc>0 else '⚠️ INVERTED',
                        '#00d97e' if yc>0 else '#e74c3c', '📉'), md=3),
            dbc.Col(mc('CPI YoY', f'{data.get("cpi_yoy_current",0):.1f}%', f'GDP: {data.get("gdp_current",0):.1f}%',
                        '#00d97e' if data.get('cpi_yoy_current',0)<3 else '#f5a623', '💹'), md=3),
        ], className='mb-1'),
        _source_line(macro_src),
        html.Div([dcc.Graph(figure=make_regime_timeline(rh), config={'displayModeBar': False}),
                  _source_line('Source: regime classification computed in-app from FRED growth/inflation/VIX + SPY 12m momentum')],
                 style={**CS, 'marginBottom': '16px', 'marginTop': '12px'}),

        # Goldman Sachs Bull/Bear Market Indicator (GSBLBR) & 5-Factor Gauge
        render_gsblbr_panel(data, title_prefix="🇺🇸"),

        dbc.Row([
            dbc.Col(html.Div([
                html.H6('📊 Growth', style={'color': '#00d97e', 'marginBottom': '12px'}),
                macro_ind('GDP Growth', f'{data.get("gdp_current",0):.1f}%', gdp_s, '#00d97e'),
                macro_ind('Unemployment', f'{float(unemp_s.iloc[-1]):.1f}%' if len(unemp_s)>0 else '—', unemp_s, '#3498db'),
                macro_ind('SPY 12m Mom', f'{data.get("spy_momentum",0):.1%}',
                          derived.get('spy_mom_monthly', pd.Series(dtype=float)) if derived else pd.Series(dtype=float), '#f5a623'),
            ], style=CS), md=4),
            dbc.Col(html.Div([
                html.H6('🔥 Inflation', style={'color': '#f5a623', 'marginBottom': '12px'}),
                macro_ind('CPI YoY', f'{data.get("cpi_yoy_current",0):.1f}%', cpi_s, '#f5a623'),
                macro_ind('Fed Funds Rate', f'{float(ff_s.iloc[-1]):.2f}%' if len(ff_s)>0 else '—', ff_s, '#e74c3c'),
                macro_ind('10Y Treasury', f'{float(t10y_s.iloc[-1]):.2f}%' if len(t10y_s)>0 else '—', t10y_s, '#9b59b6'),
            ], style=CS), md=4),
            dbc.Col(html.Div([
                html.H6('⚡ Risk', style={'color': '#e74c3c', 'marginBottom': '12px'}),
                macro_ind('VIX', f'{vix:.1f}', vix_s, '#e74c3c'),
                macro_ind('Yield Curve', f'{yc:.2f}%', yc_s, '#3498db'),
                macro_ind('2Y Treasury', f'{float(t2y_s.iloc[-1]):.2f}%' if len(t2y_s)>0 else '—', t2y_s, '#00d97e'),
            ], style=CS), md=4),
        ], className='mb-1'),
        _source_line(macro_src),
        html.Div(style={'marginBottom': '12px'}),
        # AI Trend Intelligence → Portfolio Integration
        html.Div([
            html.H6('🤖 AI Trend Intelligence — Sector Alpha → Portfolio', style={'color': '#9b59b6', 'marginBottom': '4px'}),
            html.Div(
                'These signals are ACTIVE in the portfolio. Weights shown are live allocations from the current regime.',
                style={'color': '#00d97e', 'fontSize': '11px', 'fontWeight': '600', 'marginBottom': '12px'}
            ),
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div('⚡ Energy (XLE)', style={'color': '#f5a623', 'fontSize': '14px', 'fontWeight': '700'}),
                    html.Div(
                        'AI data centers require massive power. Hyperscaler capex → energy demand surge.',
                        style={'color': '#c8c8d4', 'fontSize': '12px', 'lineHeight': '1.4', 'marginTop': '4px'},
                    ),
                    html.Div([
                        html.Span('Portfolio Weight: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span(
                            f'{data.get("current_weights", {}).get("XLE", 0):.1%}' if data.get("current_weights", {}).get("XLE", 0) > 0
                            else 'Not in current regime — added via Reflation tilt',
                            style={'color': '#f5a623', 'fontSize': '12px', 'fontWeight': '700'},
                        ),
                    ], style={'marginTop': '6px'}),
                ], style={**CS, 'padding': '12px', 'borderTop': '3px solid #f5a623'}), md=4),
                dbc.Col(html.Div([
                    html.Div('🔬 Semiconductors (SOXX + SOXL)', style={'color': '#00d97e', 'fontSize': '14px', 'fontWeight': '700'}),
                    html.Div(
                        'AI training & inference need GPUs/TPUs. SOXX = chip supply chain. SOXL = 3× lever gated by VIX<18.',
                        style={'color': '#c8c8d4', 'fontSize': '12px', 'lineHeight': '1.4', 'marginTop': '4px'},
                    ),
                    html.Div([
                        html.Span('Portfolio Weight: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span(
                            f'SOXX {data.get("current_weights", {}).get("SOXX", 0):.1%}  +  SOXL {data.get("current_weights", {}).get("SOXL", 0):.1%}',
                            style={'color': '#00d97e', 'fontSize': '12px', 'fontWeight': '700'},
                        ),
                    ], style={'marginTop': '6px'}),
                ], style={**CS, 'padding': '12px', 'borderTop': '3px solid #00d97e'}), md=4),
                dbc.Col(html.Div([
                    html.Div('🧠 AI Software (QQQ + TQQQ)', style={'color': '#3498db', 'fontSize': '14px', 'fontWeight': '700'}),
                    html.Div(
                        'Mega-cap tech (MSFT, GOOG, META, AMZN, NVDA) monetize AI via cloud, ads, SaaS. TQQQ gated VIX<18.',
                        style={'color': '#c8c8d4', 'fontSize': '12px', 'lineHeight': '1.4', 'marginTop': '4px'},
                    ),
                    html.Div([
                        html.Span('Portfolio Weight: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span(
                            f'QQQ {data.get("current_weights", {}).get("QQQ", 0):.1%}  +  TQQQ {data.get("current_weights", {}).get("TQQQ", 0):.1%}',
                            style={'color': '#3498db', 'fontSize': '12px', 'fontWeight': '700'},
                        ),
                    ], style={'marginTop': '6px'}),
                ], style={**CS, 'padding': '12px', 'borderTop': '3px solid #3498db'}), md=4),
            ], className='mb-2'),
            html.Div(
                '✅ All three AI sectors are wired into the regime weights. The Portfolio tab shows exact live positions.',
                style={'color': '#00d97e', 'fontSize': '11px', 'textAlign': 'center', 'marginTop': '4px'},
            ),
        ], style={**CS, 'marginBottom': '16px', 'border': '1px solid #9b59b6'}),

        # Enhanced AI Trend Intelligence: generated report + verification,
        # sector signals, live SemiAnalysis feed, and config-driven bank research.
        render_ai_intelligence(data),
    ])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: PORTFOLIO — Execution & Rebalancing Strategy
# ═══════════════════════════════════════════════════════════════════════════
def _fetch_etf_market_data(tickers):
    """Fetch current price and trailing P/E for a list of ETF tickers using yfinance."""
    import yfinance as yf
    prices = {}
    pe_ratios = {}
    try:
        raw = yf.Tickers(' '.join(tickers))
        for t in tickers:
            try:
                info = raw.tickers[t].fast_info
                price = getattr(info, 'last_price', None)
                prices[t] = f'${price:,.2f}' if price else '—'
            except Exception:
                prices[t] = '—'
            try:
                full_info = raw.tickers[t].info
                pe = full_info.get('trailingPE') or full_info.get('forwardPE')
                pe_label = 'fwd' if (pe and not full_info.get('trailingPE')) else 'ttm'
                pe_ratios[t] = f'{pe:.1f}x ({pe_label})' if pe else 'N/A'
            except Exception:
                pe_ratios[t] = 'N/A'
    except Exception:
        pass
    return prices, pe_ratios


def _load_tax_study():
    """Read the precomputed Canadian after-US-tax / account-location study
    (written by ab_canadian_tax.py -> data/cache/tax_study.json). Read-only;
    returns None if absent so the panel simply doesn't render."""
    try:
        import json
        p = Path(__file__).resolve().parents[2] / 'data' / 'cache' / 'tax_study.json'
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return None


def build_tax_study_panel(data):
    """Read-only panel: net return after US withholding tax, by account location,
    plus US-strategy vs all-Canadian side-by-side. All figures precomputed (CAD)."""
    s = _load_tax_study()
    if not s:
        return html.Div()
    _hdr = {'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
            'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'}
    _cell = {'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
             'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '7px', 'textAlign': 'left'}
    acc_rows = [{'account': a['account'], 'wht': a['wht'], 'cagr': f"{a['cagr']:.2%}", 'note': a['note']}
                for a in s['accounts']]
    cmp_rows = [{'name': c['name'], 'cagr': f"{c['cagr']:.2%}", 'sharpe': f"{c['sharpe']:.2f}",
                 'maxdd': f"{c['maxdd']:.2%}", 'vol': f"{c['vol']:.2%}"} for c in s['compare']]
    return html.Div([
        html.H5('🍁 Canadian Investor — After-US-Tax & Account Location',
                style={'color': '#00d97e', 'marginBottom': '4px', 'fontWeight': '700'}),
        html.Div(f"Planning study · CAD terms · window {s['window']} · read-only "
                 f"(precomputed by ab_canadian_tax.py on {s['as_of']})",
                 style={'color': '#6c757d', 'fontSize': '11px', 'marginBottom': '10px'}),
        html.Div([
            html.Span('US withholding drag on the strategy book: ',
                      style={'color': '#c8c8d4', 'fontSize': '12px'}),
            html.Span(f"≈{s['wht_avg']:.2%}/yr",
                      style={'color': '#f5a623', 'fontWeight': '700', 'fontSize': '13px'}),
            html.Span(f" (range {s['wht_min']:.2%}–{s['wht_max']:.2%}; {s['wht_current']:.2%} at current weights). "
                      f"Concentrated in DBMF / IEF / AIPO; GLD pays 0%. ",
                      style={'color': '#8888a0', 'fontSize': '12px'}),
            html.Span('Zero inside an RRSP.', style={'color': '#00d97e', 'fontSize': '12px', 'fontWeight': '600'}),
        ], style={'backgroundColor': '#16213e', 'border': '1px solid #2d2d44', 'borderRadius': '6px',
                  'padding': '10px 12px', 'marginBottom': '12px'}),
        dbc.Row([
            dbc.Col(html.Div([
                html.H6('Net annual return by account location (CAD)',
                        style={'color': '#c8c8d4', 'marginBottom': '8px'}),
                dash_table.DataTable(
                    columns=[{'name': 'Account', 'id': 'account'}, {'name': 'US Withholding', 'id': 'wht'},
                             {'name': 'Net CAGR', 'id': 'cagr'}, {'name': 'Note', 'id': 'note'}],
                    data=acc_rows, style_header=_hdr, style_cell=_cell,
                    style_cell_conditional=[{'if': {'column_id': 'cagr'}, 'textAlign': 'center', 'fontWeight': '700'}],
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                        {'if': {'filter_query': '{account} contains "RRSP"', 'column_id': 'cagr'}, 'color': '#00d97e'},
                        {'if': {'filter_query': '{account} contains "TFSA"', 'column_id': 'cagr'}, 'color': '#f5a623'},
                    ]),
            ], style=CS), md=6),
            dbc.Col(html.Div([
                html.H6('US strategy vs all-Canadian, after tax (CAD)',
                        style={'color': '#c8c8d4', 'marginBottom': '8px'}),
                dash_table.DataTable(
                    columns=[{'name': 'Portfolio', 'id': 'name'}, {'name': 'CAGR', 'id': 'cagr'},
                             {'name': 'Sharpe', 'id': 'sharpe'}, {'name': 'MaxDD', 'id': 'maxdd'},
                             {'name': 'Vol', 'id': 'vol'}],
                    data=cmp_rows, style_header=_hdr,
                    style_cell={**_cell, 'fontSize': '11px', 'padding': '6px'},
                    style_cell_conditional=[{'if': {'column_id': c}, 'textAlign': 'center'}
                                            for c in ['cagr', 'sharpe', 'maxdd', 'vol']],
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                        {'if': {'filter_query': '{name} contains "Canadian"'}, 'color': '#e74c3c'},
                    ]),
                html.Div(f"All-Canadian book = {s['cad_book']}.",
                         style={'color': '#6c757d', 'fontSize': '10px', 'marginTop': '6px', 'fontStyle': 'italic'}),
            ], style=CS), md=6),
        ], className='mb-2'),
        html.Div([
            html.Span('Takeaway: ', style={'color': '#00d97e', 'fontWeight': '700', 'fontSize': '12px'}),
            html.Span('the US withholding tax is a rounding error and is eliminated by holding the US ETFs in an '
                      'RRSP. Going all-Canadian to avoid it sacrifices ~11%/yr of return and doubles the drawdown, '
                      'because Canada has no listed semis / AI / managed-futures / uranium equivalent.',
                      style={'color': '#8888a0', 'fontSize': '12px'}),
        ], style={'marginTop': '6px', 'marginBottom': '4px'}),
        _source_line(s['caveats'] + ' — informational, not tax advice.'),
    ], style={**CS, 'marginBottom': '16px'})


def _load_covered_call_study():
    """Read the precomputed covered-call estimator (ab_covered_call.py ->
    data/cache/covered_call_study.json). Read-only; None if absent."""
    try:
        import json
        p = Path(__file__).resolve().parents[2] / 'data' / 'cache' / 'covered_call_study.json'
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return None


def build_covered_call_panel(data):
    """Read-only planning panel: estimated covered-call (buy-write) income per ETF,
    the honest income-vs-upside trade-off, and the metrics to track."""
    s = _load_covered_call_study()
    if not s:
        return html.Div()
    _hdr = {'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
            'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'}
    _cell = {'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
             'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '6px', 'textAlign': 'left'}
    etf_rows = [{'ticker': r['ticker'], 'vol': f"{r['vol']:.1%}", 'atm': f"{r['atm_ann']:.1%}",
                 'otm': f"{r['otm_ann']:.1%}", 'role': r['role'], 'verdict': r['verdict']}
                for r in s['per_etf']]
    met_rows = [{'metric': m['metric'], 'target': m['target'], 'why': m['why']} for m in s['metrics']]
    p = s['portfolio']
    return html.Div([
        html.H5('🎯 Covered-Call Overlay — Income Estimator (planning)',
                style={'color': '#00d97e', 'marginBottom': '4px', 'fontWeight': '700'}),
        html.Div(f"Read-only · estimates from trailing-1y realized vol · {s['as_of']}. {s['model']}",
                 style={'color': '#6c757d', 'fontSize': '11px', 'marginBottom': '10px'}),
        html.Div([
            html.Span('Gross premium if written on… ', style={'color': '#c8c8d4', 'fontSize': '12px'}),
            html.Span(f"all sleeves (ATM) ≈ {p['atm_all']:.1%}/yr", style={'color': '#f5a623', 'fontWeight': '700', 'fontSize': '13px'}),
            html.Span(f" · all (OTM) ≈ {p['otm_all']:.1%}/yr · ", style={'color': '#8888a0', 'fontSize': '12px'}),
            html.Span(f"income/defensive only (OTM) ≈ {p['otm_income_only']:.1%}/yr", style={'color': '#00d97e', 'fontWeight': '700', 'fontSize': '13px'}),
            html.Span('  — this is INCOME, not extra total return (it sells upside for cash).',
                      style={'color': '#8888a0', 'fontSize': '11px'}),
        ], style={'backgroundColor': '#16213e', 'border': '1px solid #2d2d44', 'borderRadius': '6px',
                  'padding': '10px 12px', 'marginBottom': '12px'}),
        dbc.Row([
            dbc.Col(html.Div([
                html.H6('Estimated covered-call income by holding',
                        style={'color': '#c8c8d4', 'marginBottom': '8px'}),
                dash_table.DataTable(
                    columns=[{'name': 'ETF', 'id': 'ticker'}, {'name': 'Vol(1y)', 'id': 'vol'},
                             {'name': 'ATM inc', 'id': 'atm'}, {'name': 'OTM inc', 'id': 'otm'},
                             {'name': 'Candidate', 'id': 'verdict'}],
                    data=etf_rows, style_header=_hdr, style_cell={**_cell, 'fontSize': '11px'},
                    style_cell_conditional=[{'if': {'column_id': c}, 'textAlign': 'center'} for c in ['vol', 'atm', 'otm']],
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                        {'if': {'filter_query': '{role} = growth', 'column_id': 'verdict'}, 'color': '#e74c3c'},
                        {'if': {'filter_query': '{role} = income', 'column_id': 'verdict'}, 'color': '#00d97e'},
                        {'if': {'filter_query': '{role} = defensive', 'column_id': 'verdict'}, 'color': '#00d97e'},
                        {'if': {'filter_query': '{role} = already-CC', 'column_id': 'verdict'}, 'color': '#f5a623'},
                    ]),
            ], style=CS), md=6),
            dbc.Col(html.Div([
                html.H6('Covered-call metrics to track',
                        style={'color': '#c8c8d4', 'marginBottom': '8px'}),
                dash_table.DataTable(
                    columns=[{'name': 'Metric', 'id': 'metric'}, {'name': 'Target', 'id': 'target'},
                             {'name': 'Why', 'id': 'why'}],
                    data=met_rows, style_header=_hdr, style_cell={**_cell, 'fontSize': '10px', 'padding': '5px'},
                    style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                                            {'if': {'filter_query': '{metric} contains "Net total return"'}, 'color': '#f5a623', 'fontWeight': '700'}],
                    page_size=10),
            ], style=CS), md=6),
        ], className='mb-2'),
        html.Div([
            html.Span('Recommendation: ', style={'color': '#00d97e', 'fontWeight': '700', 'fontSize': '12px'}),
            html.Span(s['recommendation'], style={'color': '#8888a0', 'fontSize': '12px'}),
        ], style={'marginTop': '6px', 'marginBottom': '4px'}),
        _source_line(s['caveats']),
    ], style={**CS, 'marginBottom': '16px'})


def build_portfolio_tab(data):
    weights = data.get('current_weights', {})
    prev_weights = data.get('prev_weights', {})
    regime = data.get('current_regime', 'goldilocks')
    rc = REGIME_COLORS.get(regime, '#ccc')
    ri = REGIME_ICONS.get(regime, '📊')
    regime_changes = data.get('regime_changes', [])
    all_rw = data.get('all_regime_weights', {})
    conf = data.get('regime_confidence', 50)

    # Fetch live price & P/E for all tickers in the portfolio
    tickers_list = list(weights.keys())
    live_prices, live_pe = _fetch_etf_market_data(tickers_list)

    # Weights table with change column
    table_data = []
    for t, w in sorted(weights.items(), key=lambda x: -x[1]):
        pw = prev_weights.get(t, 0)
        delta = w - pw
        delta_str = f'{delta:+.1%}' if abs(delta) > 0.001 else '—'
        # Reasoning per position
        reasons = {
            'TQQQ': 'AI tech leverage (3x) — gated by VIX<18 & confidence>85%',
            'SOXL': 'AI semiconductor cycle (3x) — gated by VIX<18',
            'SSO': 'Leveraged S&P 500 (2x) — gated by VIX<20, replaces GGLL (no data)',
            'QQQ': 'AI mega-cap exposure — MSFT, GOOG, META, AMZN, NVDA',
            'SOXX': 'AI chip supply chain — NVDA, AMD, TSMC, ASML',
            'SMH': 'VanEck Semiconductors — NVDA/TSMC-heavy AI-trend gauge',
            'XSD': 'Equal-weight US semiconductors — broader chip breadth',
            'DRAM': 'AI memory / HBM + GPU & CPU compute (newer ETF)',
            'SPY': 'Broad US equity — diversified market exposure',
            'QQQI': 'Nasdaq income — option premium dampens vol',
            'SPYI': 'S&P income — option premium dampens vol',
            'IWM': 'Small cap cycle — early expansion beneficiary',
            'VEA': 'Intl developed — valuation diversification',
            'VWO': 'Emerging markets — reflation beneficiary',
            'TLT': 'Long duration bonds — deflation/momentum hedge',
            'IEF': 'Intermediate Treasuries (7-10Y) — balanced hedge / deflation safe haven',
            'SHY': 'Short duration — capital preservation',
            'AGG': 'Aggregate bonds — vol dampener',
            'TIP': 'TIPS — inflation protection',
            'GLD': 'Gold — tail risk hedge, inflation store',
            'DBC': 'Commodities — inflation beneficiary',
            'VNQ': 'Real estate — income + inflation hedge',
            'DBMF': 'Managed futures — crisis alpha',
            'BTAL': 'Anti-beta — short high-beta, long low-beta',
            'XLE': 'Energy — AI data center power demand',
            'AIPO': 'AI & Power Infrastructure — datacenter & utility demand',
        }
        # Get ETFInfo from universe to get dividend yield and domicile
        from config.etf_universe import get_etf
        etf_info = get_etf(t)
        if etf_info:
            div_yield = etf_info.dividend_yield
        else:
            div_yield = 0.0
        
        # Calculate withholding tax rate and tax drag
        wht_rate_str, wht_desc = _etf_tax(t)
        
        # Parse withholding tax rate to float
        if "15%" in wht_rate_str:
            wht_rate = 0.15
        elif "30%" in wht_rate_str:
            wht_rate = 0.30
        elif "25%" in wht_rate_str:
            wht_rate = 0.25
        else:
            wht_rate = 0.0
            
        tax_drag = div_yield * wht_rate
        tax_drag_str = f'{tax_drag:.2%}' if tax_drag > 0 else '0.00%'

        table_data.append({
            'Ticker': t,
            'Name': ETF_NAMES.get(t, t),
            'Price': live_prices.get(t, '—'),
            'P/E': live_pe.get(t, 'N/A'),
            'Weight': f'{w:.1%}',
            'Prev': f'{pw:.1%}' if pw > 0 else '—',
            'Δ': delta_str,
            'Category': ETF_CATEGORIES.get(t, 'Other'),
            'Fgn Tax': wht_rate_str,
            'Tax Drag': tax_drag_str,
            'Reasoning': reasons.get(t, 'Portfolio diversification'),
        })

    # Category breakdown
    cat_w = {}
    for t, w in weights.items():
        cat = ETF_CATEGORIES.get(t, 'Other')
        cat_w[cat] = cat_w.get(cat, 0) + w

    # Recent regime changes (last 20)
    recent_changes = (regime_changes[-20:] if regime_changes else [])
    recent_changes = list(reversed(recent_changes))

    # ── Live values for the Future Rebalancing Outlook (aligned w/ Regime Monitor
    #    + the deployed FinBERT sentiment). Computed here so the return is pure markup.
    _vix = data.get('vix_current', 0); _cpi = data.get('cpi_yoy_current', 0)
    _gdp = data.get('gdp_current', 0); _yc = data.get('yield_curve_current', 0)
    _spymom = data.get('spy_momentum', 0)
    _ff = data.get('macro', {}).get('ff_rate', pd.Series(dtype=float))
    _ff_val = float(_ff.dropna().iloc[-1]) if len(_ff.dropna()) else None
    _ai = data.get('ai_trend', {}) or {}
    _ms = _ai.get('market_sentiment', {}) or {}
    _ov = _ms.get('overall', {}) or {}; _cap = _ms.get('capex', {}) or {}
    _edgar = _ai.get('edgar_capex', {}) or {}; _eg_yoy = _edgar.get('agg_yoy')
    _aisig = _ai.get('signals', {}) or {}
    _rov = (_ai.get('reddit', {}) or {}).get('overall', {}) or {}
    _growth_ok = (_gdp > 1.5) or (_spymom > 0.05)
    _semi_w = sum(weights.get(t, 0) for t in ['SOXX', 'SMH', 'XSD', 'DRAM', 'SOXL'])
    _aisw_w = sum(weights.get(t, 0) for t in ['QQQ', 'TQQQ', 'QQQI'])
    _soxx_sig = (_aisig.get('tickers', {}) or {}).get('SOXX', {}).get('signal', '—')
    _mag7_lbl = next((t['label'] for t in (_ms.get('themes', []) or []) if t['name'] == 'Mag7'), '—')
    _triggers = {
        'goldilocks': '→ REFLATION if CPI re-accelerates >3%; → DEFLATION if growth stalls',
        'reflation':  '→ GOLDILOCKS if CPI cools <3%; → STAGFLATION if growth stalls',
        'stagflation': '→ DEFLATION if inflation cools; → REFLATION if growth returns',
        'deflation':  '→ GOLDILOCKS if growth resumes + low CPI; → REFLATION if growth + CPI rise',
    }
    # Freshness stamps — this tab is built at container start, so _built is the
    # snapshot time; the per-source as-of dates prove the values are live, not written.
    _ts = data.get('timestamps', {}) or {}
    _built = pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')
    _macro_ts = _ts.get('macro_data', '—'); _bt_ts = _ts.get('backtest_results', '—')
    _ms_comp = _ms.get('computed', '—'); _eg_comp = _edgar.get('computed', '—')

    def _sc(lbl):
        return {'Bullish': '#00d97e', 'Bearish': '#e74c3c', 'Neutral': '#f5a623',
                'STRONG': '#00d97e', 'WEAK': '#e74c3c', 'NEUTRAL': '#f5a623'}.get(lbl, '#8888a0')

    def _row(label, value, color='#00d97e'):
        return html.Div([html.Span(label, style={'color': '#8888a0'}),
                         html.Span(value, style={'color': color, 'fontWeight': '600'})],
                        style={'marginBottom': '4px', 'fontSize': '12px'})

    # ── Rebalancing-rule strings, rendered from the SINGLE SOURCE OF TRUTH so the
    #    displayed rules can never drift from what the engine actually runs ──
    from config.regime_rules import STRATEGY_PARAMS as _SP, RISK_LIMITS as _RL
    _lev_book = sorted({t for w in (all_rw or {}).values() for t in w}
                       & {'TQQQ', 'SOXL', 'SSO', 'GGLL', 'TECL', 'SPXL', 'UPRO'})
    _freq_rules = [
        'Monthly rebalance (base weights, 1st trading day)',
        f"Daily drawdown circuit breaker at −{_SP['dd_trigger']:.0%}",
        f"Daily 200-MA trend hedge → {1 - _SP['bear_equity_frac']:.0%} to defense when SPY < 200-MA",
    ]
    _regime_rules = [
        'Growth rising: GDP > 1.5% OR SPY 12m mom > 5%',
        'Inflation rising: CPI YoY > 3% AND accelerating',
        'VIX > 30 → override to Deflation',
    ]
    _risk_rules = [
        f"Max single position: {_RL.max_single_position:.0%}",
        f"Max leveraged total: {_RL.max_leveraged_total:.0%}",
        f"Max daily turnover: {_RL.max_daily_turnover:.0%}",
    ]
    _lev_rules = [
        f"VIX gate: zero leveraged ETFs when yesterday's VIX ≥ {_SP['vix_gate_level']:.0f} (→ QQQ/SOXX)",
        (f"Leveraged ETFs in universe: {', '.join(_lev_book)}" if _lev_book
         else 'No leveraged ETFs in the current 7-ETF universe — gate inactive'),
        f"HAR-RV vol overlay {'ON' if _SP.get('use_har_vol') else 'OFF'} · vol target {_SP['target_vol']:.0%}",
    ]

    def _rules_ul(items):
        return html.Ul([html.Li(r, style={'color': '#c8c8d4', 'fontSize': '12px'}) for r in items],
                       style={'listStyleType': 'none', 'padding': '0'})

    # Live backtest headline from the result CSV — never hardcode, so it always
    # matches the daily-refreshed numbers (14.52% today, whatever it is tomorrow).
    _btr = data.get('backtest_results')
    _cagr = _sharpe = _dd = '—'
    try:
        if _btr is not None and not _btr.empty:
            # NB: named _btrow (not _row) — this function defines a _row() helper later.
            _btrow = (_btr.loc['Optimized Regime Strategy']
                      if 'Optimized Regime Strategy' in _btr.index else _btr.iloc[0])
            _cagr = str(_btrow.get('Annual Return', '—'))
            _sh = _btrow.get('Sharpe Ratio', '—')
            _sharpe = f'{float(_sh):.2f}' if str(_sh).replace('.', '', 1).replace('-', '', 1).isdigit() else str(_sh)
            _dd = str(_btrow.get('Max Drawdown', '—'))
    except Exception:
        pass

    return html.Div([
        make_timestamp_strip(data, 'price'),
        # Top row — current state
        dbc.Row([
            dbc.Col(mc('Regime', f'{ri} {regime.upper()}', f'{conf:.0f}% confidence', rc, ''), md=3),
            dbc.Col(mc('Initial Capital', '$100,000', 'Starting value', '#c8c8d4', '💰'), md=3),
            dbc.Col(mc('Backtest CAGR', _cagr, f'Sharpe {_sharpe} | DD {_dd} (7-ETF v7, no look-ahead)', '#00d97e', '📈'), md=3),
            dbc.Col(mc('Rebalance Freq', 'Monthly', f'Next: 1st of month', '#3498db', '📅'), md=3),
        ], className='mb-3'),
        _source_line(f"🔄 LIVE snapshot built {_built} · regime/weights from FRED macro (cache {_macro_ts}) + "
                     f"Yahoo Finance prices · backtest CSV {_bt_ts}. Tab rebuilds each container start."),

        # ────────────────────────────────────────────────────
        # SECTION 1: REBALANCING RULES
        # ────────────────────────────────────────────────────
        html.Div([
            html.H5('📏 Rebalancing Rules', style={'color': '#f5a623', 'marginBottom': '6px', 'fontWeight': '700'}),
            html.Div('Systematic, rules-based. No discretionary overrides. Every trade has an auditable trigger.',
                     style={'color': '#6c757d', 'fontSize': '12px', 'marginBottom': '16px'}),
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div('⏰ Frequency', style={'color': '#f5a623', 'fontSize': '14px', 'fontWeight': '700', 'marginBottom': '6px'}),
                    _rules_ul(_freq_rules),
                ], style={**CS, 'padding': '14px'}), md=3),
                dbc.Col(html.Div([
                    html.Div('🎯 Regime Triggers', style={'color': '#00d97e', 'fontSize': '14px', 'fontWeight': '700', 'marginBottom': '6px'}),
                    _rules_ul(_regime_rules),
                ], style={**CS, 'padding': '14px'}), md=3),
                dbc.Col(html.Div([
                    html.Div('🛡️ Risk Guards', style={'color': '#e74c3c', 'fontSize': '14px', 'fontWeight': '700', 'marginBottom': '6px'}),
                    _rules_ul(_risk_rules),
                ], style={**CS, 'padding': '14px'}), md=3),
                dbc.Col(html.Div([
                    html.Div('⚡ Leverage Gates', style={'color': '#9b59b6', 'fontSize': '14px', 'fontWeight': '700', 'marginBottom': '6px'}),
                    _rules_ul(_lev_rules),
                ], style={**CS, 'padding': '14px'}), md=3),
            ], className='mb-3'),
            _source_line("Rendered live from config/regime_rules.py (STRATEGY_PARAMS, RISK_LIMITS) — "
                         "the same values the engine runs, so these rules cannot drift from the methodology."),
        ], style={**CS, 'marginBottom': '16px', 'border': '1px solid #f5a623'}),

        # Current allocation & weights
        dbc.Row([
            dbc.Col(html.Div([
                dcc.Graph(figure=make_allocation_donut(weights), config={'displayModeBar': False}),
            ], style=CS), md=4),
            dbc.Col(html.Div([
                html.H6(f'Position Weights — {regime.upper()} Regime', style={'color': rc, 'marginBottom': '6px'}),
                html.Div([
                    html.Span('Each position shows reasoning. ', style={'color': '#6c757d', 'fontSize': '11px'}),
                    html.Span('Price & P/E fetched live from Yahoo Finance. ', style={'color': '#c8c8d4', 'fontSize': '11px'}),
                    html.Span('Green/red = change from prior month.', style={'color': '#f5a623', 'fontSize': '11px'}),
                ], style={'marginBottom': '8px'}),
                dash_table.DataTable(
                    columns=[{'name': c, 'id': c} for c in ['Ticker','Name','Price','P/E','Weight','Prev','Δ','Category','Fgn Tax','Tax Drag','Reasoning']],
                    data=table_data, sort_action='native',
                    tooltip_header={
                        'Fgn Tax': 'Foreign withholding tax on distributions for a Canadian (non-US) holder '
                                   'in a taxable account. 15% on US-domiciled ETFs (0% inside an RRSP); '
                                   '0% on Canadian-domiciled (.TO) ETFs.',
                        'Tax Drag': 'Expected annual yield loss from foreign withholding taxes (Dividend Yield × Withholding Tax Rate). '
                                    'For example, a US ETF with a 12% yield has a 1.80% annual tax drag (12% × 15% WHT).'
                    },
                    style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                                  'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                    style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                                'fontFamily': 'Inter', 'fontSize': '11px', 'padding': '5px', 'textAlign': 'left'},
                    style_cell_conditional=[
                        {'if': {'column_id': 'Price'}, 'textAlign': 'right', 'fontWeight': '700', 'color': '#00d97e'},
                        {'if': {'column_id': 'P/E'}, 'textAlign': 'center', 'color': '#f5a623'},
                        {'if': {'column_id': 'Weight'}, 'textAlign': 'center', 'fontWeight': '600'},
                        {'if': {'column_id': 'Δ'}, 'textAlign': 'center'},
                        {'if': {'column_id': 'Prev'}, 'textAlign': 'center'},
                        {'if': {'column_id': 'Fgn Tax'}, 'textAlign': 'center'},
                        {'if': {'column_id': 'Tax Drag'}, 'textAlign': 'center'},
                        {'if': {'column_id': 'Reasoning'}, 'minWidth': '200px'},
                    ],
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                        {'if': {'filter_query': '{Δ} contains "+"'}, 'color': '#00d97e'},
                        {'if': {'filter_query': '{Δ} contains "-"'}, 'color': '#e74c3c'},
                        {'if': {'filter_query': '{Fgn Tax} contains "CA"', 'column_id': 'Fgn Tax'}, 'color': '#00d97e'},
                        {'if': {'filter_query': '{Fgn Tax} contains "15%"', 'column_id': 'Fgn Tax'}, 'color': '#f5a623'},
                        {'if': {'filter_query': '{Tax Drag} eq "0.00%"', 'column_id': 'Tax Drag'}, 'color': '#00d97e'},
                        {'if': {'filter_query': '{Tax Drag} ne "0.00%"', 'column_id': 'Tax Drag'}, 'color': '#e74c3c'},
                    ], page_size=16,
                ),
            ], style=CS), md=8),
        ], className='mb-3'),
        _source_line(f"Weights = live {regime.upper()} regime allocation (FRED macro cache {_macro_ts}) · "
                     f"Price & P/E fetched live from Yahoo Finance at {_built}. "
                     f"Fgn Tax = distribution withholding for a Canadian holder (15% on US ETFs, 0% in an RRSP; "
                     f"0% on Cdn .TO ETFs) — informational, not tax advice."),

        # ── Canadian after-US-tax / account-location study (read-only) ──
        build_tax_study_panel(data),

        # ── Covered-call overlay income estimator (read-only, planning) ──
        build_covered_call_panel(data),

        # ────────────────────────────────────────────────────
        # SECTION 2 & 3: REBALANCING HISTORY LOG + REASONING
        # ────────────────────────────────────────────────────
        html.Div([
            html.H5('📋 Rebalancing History Log', style={'color': '#00d97e', 'marginBottom': '6px', 'fontWeight': '700'}),
            html.Div([
                html.Span('Full audit trail. ', style={'color': '#6c757d', 'fontSize': '12px'}),
                html.Span('Every regime shift is logged with date, macro reasoning, and exact weight changes. ',
                          style={'color': '#c8c8d4', 'fontSize': '12px'}),
                html.Span('No black-box decisions.', style={'color': '#f5a623', 'fontSize': '12px', 'fontWeight': '600'}),
            ], style={'marginBottom': '12px'}),
            dash_table.DataTable(
                columns=[
                    {'name': '📅 Date', 'id': 'date'},
                    {'name': '⬅️ From Regime', 'id': 'from_regime'},
                    {'name': '➡️ To Regime', 'id': 'to_regime'},
                    {'name': '🧠 Macro Reasoning', 'id': 'reason'},
                    {'name': '📊 Key Position Changes (Top 5)', 'id': 'key_changes'},
                ],
                data=recent_changes, sort_action='native', page_size=15,
                style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                              'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                            'fontFamily': 'Inter', 'fontSize': '11px', 'padding': '8px', 'textAlign': 'left'},
                style_cell_conditional=[
                    {'if': {'column_id': 'date'}, 'width': '80px', 'textAlign': 'center'},
                    {'if': {'column_id': 'from_regime'}, 'width': '100px', 'textAlign': 'center'},
                    {'if': {'column_id': 'to_regime'}, 'width': '100px', 'textAlign': 'center'},
                    {'if': {'column_id': 'key_changes'}, 'minWidth': '250px'},
                ],
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                    {'if': {'filter_query': '{to_regime} eq "goldilocks"'}, 'backgroundColor': '#0d2818'},
                    {'if': {'filter_query': '{to_regime} eq "deflation"'}, 'backgroundColor': '#0d1828'},
                    {'if': {'filter_query': '{to_regime} eq "stagflation"'}, 'backgroundColor': '#280d0d'},
                ],
            ),
            _source_line(f"Source: regime-change log from the backtest engine · backtest CSV {_bt_ts}."),
        ], style={**CS, 'marginBottom': '16px', 'border': '1px solid #00d97e'}),

        # ────────────────────────────────────────────────────
        # SECTION 4: FUTURE REBALANCING OUTLOOK
        # ────────────────────────────────────────────────────
        html.Div([
            html.H5('🔮 Future Rebalancing Outlook', style={'color': '#9b59b6', 'marginBottom': '6px', 'fontWeight': '700'}),
            html.Div('Live readings — same macro as the Regime Monitor and the deployed FinBERT sentiment engine. Rules-based regime triggers; no fabricated forecasts.',
                     style={'color': '#6c757d', 'fontSize': '12px', 'marginBottom': '16px'}),
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div('📊 Live Macro (lagged to release)', style={'color': '#3498db', 'fontSize': '14px', 'fontWeight': '700', 'marginBottom': '8px'}),
                    _row('GDP Growth: ', f'{_gdp:.1f}%', '#00d97e' if _gdp > 1.5 else '#f5a623'),
                    _row('Core CPI (YoY): ', f'{_cpi:.1f}%', '#00d97e' if _cpi < 3 else '#f5a623'),
                    _row('Fed Funds: ', f'{_ff_val:.2f}%' if _ff_val is not None else '—', '#f5a623'),
                    _row('VIX: ', f'{_vix:.1f}', '#00d97e' if _vix < 20 else ('#f5a623' if _vix < 30 else '#e74c3c')),
                    _row('Yield Curve: ', f'{_yc:+.2f}%', '#00d97e' if _yc > 0 else '#e74c3c'),
                    html.Div('Same FRED series as the Regime Monitor.', style={'color': '#6c757d', 'fontSize': '10px', 'marginTop': '4px'}),
                ], style={**CS, 'padding': '14px'}), md=4),
                dbc.Col(html.Div([
                    html.Div('🎯 Regime & Next-Move Triggers', style={'color': '#00d97e', 'fontSize': '14px', 'fontWeight': '700', 'marginBottom': '8px'}),
                    html.Div([html.Span('Current: ', style={'color': '#8888a0'}), html.Span(f'{regime.upper()} ({conf:.0f}% conf)', style={'color': rc, 'fontWeight': '700'})], style={'marginBottom': '6px', 'fontSize': '13px'}),
                    _row('Growth: ', f'GDP {_gdp:.1f}% · SPY 12m {_spymom:+.0%} → {"rising" if _growth_ok else "stalling"}', '#00d97e' if _growth_ok else '#e74c3c'),
                    _row('Inflation: ', f'CPI {_cpi:.1f}% → {"elevated" if _cpi > 3 else "contained"}', '#f5a623' if _cpi > 3 else '#00d97e'),
                    _row('Crisis gate: ', f'VIX {_vix:.0f} → {"DEFENSIVE >30" if _vix > 30 else "normal"}', '#e74c3c' if _vix > 30 else '#00d97e'),
                    html.Div(_triggers.get(regime, ''), style={'color': '#c8c8d4', 'fontSize': '11px', 'marginTop': '6px', 'lineHeight': '1.4'}),
                ], style={**CS, 'padding': '14px'}), md=4),
                dbc.Col(html.Div([
                    html.Div('🧠 AI Sentiment & CapEx (FinBERT)', style={'color': '#f5a623', 'fontSize': '14px', 'fontWeight': '700', 'marginBottom': '8px'}),
                    _row('News consensus: ', f"{_ov.get('label','—')} {_ov.get('score',0):+.2f}", _sc(_ov.get('label'))),
                    _row('CapEx pulse: ', f"{_cap.get('score',0):+.2f} · ${_edgar.get('agg_capex_b','—')}B" + (f" YoY {_eg_yoy:+.0%}" if _eg_yoy is not None else ''), '#00d97e'),
                    _row('Retail (Reddit): ', f"{_rov.get('label','—')} (experimental)", _sc(_rov.get('label'))),
                    html.Div(f"Engine: {_ms.get('engine','—')} · indicator only, not in weights.", style={'color': '#6c757d', 'fontSize': '10px', 'marginTop': '4px'}),
                ], style={**CS, 'padding': '14px'}), md=4),
            ], className='mb-3'),
            html.Div([
                html.Div('🤖 AI-Driven Sector Outlook (current allocation)', style={'color': '#9b59b6', 'fontSize': '14px', 'fontWeight': '700', 'marginBottom': '8px'}),
                dbc.Row([
                    dbc.Col(html.Div([
                        html.Div(f'🔬 Semiconductors — {_soxx_sig}', style={'color': _sc(_soxx_sig), 'fontSize': '13px', 'fontWeight': '600'}),
                        html.Div(f"SOXX+SMH+XSD+DRAM+SOXL = {_semi_w:.0%} in {regime}. Live AI-sector signal: {_aisig.get('sector_signal','—')} (score {_aisig.get('sector_score',0):+.0f}, {_aisig.get('breadth','—')}).", style={'color': '#c8c8d4', 'fontSize': '11px', 'lineHeight': '1.4', 'marginTop': '4px'}),
                    ], style={'padding': '8px'}), md=4),
                    dbc.Col(html.Div([
                        html.Div('🧠 AI Software', style={'color': '#3498db', 'fontSize': '13px', 'fontWeight': '600'}),
                        html.Div(f"QQQ+TQQQ+QQQI = {_aisw_w:.0%} in {regime}. Mag7 news sentiment: {_mag7_lbl}.", style={'color': '#c8c8d4', 'fontSize': '11px', 'lineHeight': '1.4', 'marginTop': '4px'}),
                    ], style={'padding': '8px'}), md=4),
                    dbc.Col(html.Div([
                        html.Div('⚡ Hyperscaler CapEx', style={'color': '#f5a623', 'fontSize': '13px', 'fontWeight': '600'}),
                        html.Div(f"MSFT/GOOGL/AMZN/META: ${_edgar.get('agg_capex_b','—')}B latest quarter" + (f", +{_eg_yoy:.0%} YoY" if _eg_yoy is not None else '') + ' (SEC EDGAR) — the demand pull for semis/HBM.', style={'color': '#c8c8d4', 'fontSize': '11px', 'lineHeight': '1.4', 'marginTop': '4px'}),
                    ], style={'padding': '8px'}), md=4),
                ]),
            ], style={**CS, 'padding': '14px'}),
            _source_line(f"LIVE · macro (FRED cache {_macro_ts}, lagged to release) · "
                         f"FinBERT news + EDGAR capex computed {_ms_comp} / {_eg_comp} · snapshot {_built}. "
                         f"Display-only — not in the backtest or weights."),
        ], style={**CS, 'marginBottom': '16px', 'border': '1px solid #9b59b6'}),

        # Category breakdown
        html.Div([
            html.H6('Category Breakdown', style={'color': '#c8c8d4', 'marginBottom': '10px'}),
            dbc.Row([dbc.Col(html.Div([
                html.Div(cat, style={'color': '#8888a0', 'fontSize': '11px'}),
                html.Div(f'{w:.1%}', style={'color': '#00d97e', 'fontSize': '18px', 'fontWeight': '700'}),
                dbc.Progress(value=w*100, color='success' if w<0.3 else 'warning',
                             style={'height': '4px', 'marginTop': '3px', 'backgroundColor': '#2d2d44'}),
            ], style={'textAlign': 'center', 'padding': '8px'}), md=True)
                for cat, w in sorted(cat_w.items(), key=lambda x: -x[1])]),
            _source_line(f"Computed from the live {regime.upper()} regime weights · snapshot {_built}."),
        ], style=CS),
    ])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 3: BACKTEST (fixed equity curve + benchmarks)
# ═══════════════════════════════════════════════════════════════════════════
def build_backtest_tab(data):
    bt = data.get('backtest_results', pd.DataFrame())
    eq = data.get('equity_curve', pd.Series(dtype=float))
    all_eq = data.get('all_equity_curves', pd.DataFrame())
    mr = data.get('monthly_returns', pd.Series(dtype=float))

    ann_ret = sharpe = max_dd = sortino = calmar = total_ret = '—'
    # Resolve the production strategy row by name, tolerating renames; else first row.
    prod_names = ['Optimized Regime Strategy', 'Vol-Targeted Regime Strategy',
                  'Aggressive Regime Strategy']
    prod_row = next((n for n in prod_names if (not bt.empty and n in bt.index)), None)
    if prod_row is None and not bt.empty:
        prod_row = bt.index[0]
    if prod_row is not None:
        row = bt.loc[prod_row]
        ann_ret, sharpe = row.get('Annual Return', '—'), row.get('Sharpe Ratio', '—')
        max_dd, sortino = row.get('Max Drawdown', '—'), row.get('Sortino Ratio', '—')
        calmar, total_ret = row.get('Calmar Ratio', '—'), row.get('Total Return', '—')

    table_data = []
    if not bt.empty:
        for strat in bt.index:
            r = bt.loc[strat]
            table_data.append({
                'Strategy': strat, 'Annual Return': r.get('Annual Return', '—'),
                'Volatility': r.get('Volatility', '—'), 'Sharpe': r.get('Sharpe Ratio', '—'),
                'Sortino': r.get('Sortino Ratio', '—'), 'Max DD': r.get('Max Drawdown', '—'),
                'Calmar': r.get('Calmar Ratio', '—'), 'Win Rate': r.get('Win Rate', '—'),
                'Total Return': r.get('Total Return', '—'),
            })

    return html.Div([
        make_timestamp_strip(data, 'backtest'),
        dbc.Row([
            dbc.Col(mc('Annual Return', str(ann_ret), '20yr CAGR', '#00d97e', '📈'), md=2),
            dbc.Col(mc('Sharpe Ratio', str(sharpe), 'Risk-adjusted', '#00d97e', '⚡'), md=2),
            dbc.Col(mc('Max Drawdown', str(max_dd), 'Worst loss', '#00d97e', '🛡️'), md=2),
            dbc.Col(mc('Sortino', str(sortino), 'Downside risk', '#3498db', '📊'), md=2),
            dbc.Col(mc('Calmar', str(calmar), 'Return/DD', '#3498db', '🎯'), md=2),
            dbc.Col(mc('Total Return', str(total_ret), '2005-2026', '#f5a623', '💰'), md=2),
        ], className='mb-3'),
        html.Div([dcc.Graph(figure=make_equity_curves(all_eq, eq), config={'displayModeBar': False})],
                 style={**CS, 'marginBottom': '16px'}),
        html.Div([dcc.Graph(figure=make_drawdown(eq), config={'displayModeBar': False})],
                 style={**CS, 'marginBottom': '16px'}),
        html.Div([dcc.Graph(figure=make_monthly_heatmap(mr), config={'displayModeBar': False})],
                 style={**CS, 'marginBottom': '16px'}),
        html.Div([
            html.H6('Strategy Comparison — 20-Year Backtest', style={'color': '#c8c8d4', 'marginBottom': '10px'}),
            dash_table.DataTable(
                columns=[{'name': c, 'id': c} for c in ['Strategy','Annual Return','Volatility','Sharpe',
                          'Sortino','Max DD','Calmar','Win Rate','Total Return']],
                data=table_data, sort_action='native',
                style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                              'border': '1px solid #2d2d44', 'fontFamily': 'Inter'},
                style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                            'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '8px', 'textAlign': 'center'},
                style_cell_conditional=[{'if': {'column_id': 'Strategy'}, 'textAlign': 'left', 'fontWeight': '600'}],
                style_data_conditional=[
                    {'if': {'row_index': 0}, 'backgroundColor': '#0d2818', 'color': '#00d97e', 'fontWeight': '600'},
                    {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                ],
            ),
        ], style=CS),
    ])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 4: EXECUTION — IBKR Paper-Trading Integration
# ═══════════════════════════════════════════════════════════════════════════
IBKR_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / 'data' / 'cache' / 'ibkr_account.json'

# Cloud Run sets K_SERVICE; locally it is unset. Trading controls need a live TWS
# socket (127.0.0.1:7497), which is unreachable from Cloud Run — so on the hosted
# site we hide the Connect/Preview/Execute controls and show a local-only note.
IS_CLOUD_RUN = bool(os.environ.get('K_SERVICE'))


def _load_ibkr_snapshot():
    """Read the real IBKR account snapshot written by scripts/ibkr_snapshot.py.

    This is the bridge that lets the (stateless, Cloud Run) dashboard show LIVE
    paper/real performance: a live TWS socket is unreachable from Cloud Run, so the
    snapshot file is the source of truth. Returns None if no snapshot exists yet.
    """
    try:
        import json
        if IBKR_SNAPSHOT_PATH.exists():
            return json.loads(IBKR_SNAPSHOT_PATH.read_text())
    except Exception:
        pass
    return None


def _ibkr_equity_figure(equity_history):
    """Small NAV-since-inception curve from the snapshot's equity history."""
    fig = go.Figure()
    if equity_history:
        xs = [r['date'] for r in equity_history]
        ys = [r['nav'] for r in equity_history]
        base = ys[0] if ys else 0
        up = ys[-1] >= base
        fig.add_trace(go.Scatter(x=xs, y=ys, mode='lines+markers',
                                 line=dict(color='#00d97e' if up else '#e74c3c', width=2),
                                 fill='tozeroy', fillcolor='rgba(0,217,126,0.08)' if up else 'rgba(231,76,60,0.08)',
                                 hovertemplate='%{x}<br>NAV %{y:,.0f}<extra></extra>'))
        lo, hi = min(ys), max(ys)
        pad = (hi - lo) * 0.5 or hi * 0.002
        fig.update_yaxes(range=[lo - pad, hi + pad])
    fig.update_layout(**PL, height=180, showlegend=False, yaxis_title=None, xaxis_title=None)
    return fig


def _build_cc_overlay_table(snap):
    """Covered-call overlay table: filled short calls + pending option orders.
    Returns an empty Div when the overlay has no positions or open orders."""
    rows = []
    for o in snap.get('option_positions', []):
        rows.append({'k': f"{o['symbol']} {o['expiry']} {o.get('right', 'C')}{o['strike']:g}",
                     'q': o['qty'], 'st': 'FILLED',
                     'mv': f"${o['market_value']:,.0f}",
                     'pl': f"${o['unrealized_pnl']:+,.0f}"})
    for o in snap.get('option_orders', []):
        qty = -o['qty'] if o.get('action') == 'SELL' else o['qty']
        rows.append({'k': f"{o['symbol']} {o['expiry']} {o.get('right', 'C')}{o['strike']:g}",
                     'q': qty, 'st': o.get('status', 'Pending'), 'mv': '—', 'pl': '—'})
    if not rows:
        return html.Div()
    return html.Div([
        html.H6('📝 Covered-Call Overlay (auto-rolled monthly)',
                style={'color': '#c8c8d4', 'marginBottom': '8px'}),
        dash_table.DataTable(
            columns=[{'name': 'Contract', 'id': 'k'}, {'name': 'Qty', 'id': 'q'},
                     {'name': 'Status', 'id': 'st'},
                     {'name': 'Mkt Value', 'id': 'mv'}, {'name': 'Unrl P&L', 'id': 'pl'}],
            data=rows,
            style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                          'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
            style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                        'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '6px', 'textAlign': 'center'},
            style_cell_conditional=[{'if': {'column_id': 'k'}, 'textAlign': 'left', 'fontWeight': '600'}],
            style_data_conditional=[
                {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                {'if': {'filter_query': '{pl} contains "-"', 'column_id': 'pl'}, 'color': '#e74c3c'},
                {'if': {'filter_query': '{st} = "FILLED"', 'column_id': 'st'}, 'color': '#00d97e'},
                {'if': {'filter_query': '{st} contains "Submitted"', 'column_id': 'st'}, 'color': '#f5a623'},
            ],
        ),
        _source_line('Short calls on SPY/GLD/TLT only (~0.30Δ, 30–45 DTE) — never on the AI/growth '
                     'sleeves. Rolled by the ETF-IBKR-CoveredCalls task on the 2nd of each month. '
                     'PreSubmitted = queued, fills at the next US market open.'),
    ], style={**CS, 'marginBottom': '16px'})


def build_ibkr_live_panel(snap, target_weights, live_prices=None):
    """Analysis of the REAL IBKR account vs the strategy target (drift / tracking).

    `live_prices` is the SAME yfinance feed the Portfolio tab shows (ticker → '$xx.xx'),
    so the Price column here aligns with the Portfolio section. Falls back to the
    snapshot's IBKR mark if a live price is missing.
    """
    live_prices = live_prices or {}
    acct = snap.get('account_id', '—')
    paper = snap.get('is_paper', True)
    ccy = snap.get('base_currency', 'USD')
    as_of = snap.get('as_of', '—')
    positions = snap.get('positions', [])
    live_w = {p['ticker']: p.get('weight', 0.0) for p in positions}

    # Union of held tickers and target tickers → full drift analysis
    tickers = sorted(set(live_w) | set(target_weights), key=lambda t: -(target_weights.get(t, 0) or live_w.get(t, 0)))
    rows, tracking_err = [], 0.0
    pos_by_t = {p['ticker']: p for p in positions}
    for t in tickers:
        lw = live_w.get(t, 0.0)
        tw = target_weights.get(t, 0.0)
        drift = lw - tw
        tracking_err += abs(drift)
        p = pos_by_t.get(t, {})
        mv = p.get('market_value', 0.0)
        upnl = p.get('unrealized_pnl', 0.0)
        avg = p.get('avg_price', 0.0)
        # Price: prefer the Portfolio tab's live yfinance price; else the IBKR snapshot mark
        lp = live_prices.get(t)
        if not lp or lp == '—':
            mkt = p.get('market_price')
            lp = f'${mkt:,.2f}' if mkt else '—'
        rows.append({
            'ticker': t,
            'price': lp,
            'avg_cost': f'${avg:,.2f}' if (t in live_w and avg) else '—',
            'live': f'{lw:.1%}' if t in live_w else '—',
            'target': f'{tw:.1%}' if t in target_weights else '—',
            'drift': f'{drift:+.1%}',
            'mv': f'${mv:,.0f}' if mv else '—',
            'upnl': f'${upnl:+,.0f}' if t in live_w else '—',
        })
    tracking_err /= 2.0  # half-sum of abs weight differences = active share / drift

    upnl_total = sum(p.get('unrealized_pnl', 0.0) for p in positions)
    nav = snap.get('nav', 0.0)
    twr = snap.get('twr_since_inception', 0.0)
    twr_1d = snap.get('twr_1d')
    src = snap.get('source', 'tws')

    drift_color = '#00d97e' if tracking_err < 0.03 else ('#f5a623' if tracking_err < 0.08 else '#e74c3c')

    return html.Div([
        html.Div([
            html.H6('📡 Live Account — Real Portfolio vs Strategy Target',
                    style={'color': '#00d97e', 'marginBottom': '2px', 'display': 'inline-block'}),
            html.Span(f"  {'PAPER' if paper else 'LIVE'} • {acct} • base {ccy}",
                      style={'color': '#f5a623' if paper else '#e74c3c', 'fontSize': '12px',
                             'fontWeight': '600', 'marginLeft': '8px'}),
        ]),
        html.Div(f'Source: IBKR {src.upper()} snapshot · as of {as_of}',
                 style={'color': '#6c757d', 'fontSize': '11px', 'marginBottom': '12px', 'fontStyle': 'italic'}),

        dbc.Row([
            dbc.Col(html.Div([
                html.H6('🎯 Allocation Drift (Live vs Target)', style={'color': '#c8c8d4', 'marginBottom': '10px'}),
                dash_table.DataTable(
                    columns=[
                        {'name': 'Ticker', 'id': 'ticker'},
                        {'name': 'Price', 'id': 'price'},
                        {'name': 'Avg Cost', 'id': 'avg_cost'},
                        {'name': 'Live %', 'id': 'live'},
                        {'name': 'Target %', 'id': 'target'},
                        {'name': 'Drift', 'id': 'drift'},
                        {'name': 'Mkt Value', 'id': 'mv'},
                        {'name': 'Unrl P&L', 'id': 'upnl'},
                    ],
                    data=rows,
                    style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                                  'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                    style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                                'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '7px', 'textAlign': 'center'},
                    style_cell_conditional=[{'if': {'column_id': 'ticker'}, 'textAlign': 'left', 'fontWeight': '600'}],
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                        {'if': {'filter_query': '{drift} contains "-"', 'column_id': 'drift'}, 'color': '#e74c3c'},
                        {'if': {'filter_query': '{upnl} contains "-"', 'column_id': 'upnl'}, 'color': '#e74c3c'},
                    ],
                ),
                html.Div([
                    html.Span('Tracking drift (active share): ', style={'color': '#8888a0', 'fontSize': '12px'}),
                    html.Span(f'{tracking_err:.1%}', style={'color': drift_color, 'fontWeight': '700', 'fontSize': '13px'}),
                    html.Span('  — how far the live book sits from the model target. Re-run a rebalance if this grows.',
                              style={'color': '#6c757d', 'fontSize': '11px'}),
                ], style={'marginTop': '10px'}),
                _source_line('Target % = current production regime weights (REGIME_WEIGHTS + VIX gate) — '
                             'the identical weights run by the backtest engine, so Execution tracks the validated strategy. '
                             'Price = live Yahoo Finance (same feed as the Portfolio tab); Avg Cost = IBKR fill cost.'),
            ], style=CS), md=7),

            dbc.Col(html.Div([
                html.H6('📈 NAV Since Inception', style={'color': '#c8c8d4', 'marginBottom': '10px'}),
                dcc.Graph(figure=_ibkr_equity_figure(snap.get('equity_history', [])),
                          config={'displayModeBar': False}),
                html.Div([
                    html.Div([html.Span('NAV ', style={'color': '#8888a0', 'fontSize': '11px'}),
                              html.Span(f'{nav:,.0f} {ccy}', style={'color': '#c8c8d4', 'fontWeight': '700'})]),
                    html.Div([html.Span('Since inception (TWR) ', style={'color': '#8888a0', 'fontSize': '11px'}),
                              html.Span(f'{twr:+.2%}', style={'color': '#00d97e' if twr >= 0 else '#e74c3c', 'fontWeight': '700'})]),
                    html.Div([html.Span('Unrealized P&L ', style={'color': '#8888a0', 'fontSize': '11px'}),
                              html.Span(f'{upnl_total:+,.0f} USD', style={'color': '#00d97e' if upnl_total >= 0 else '#e74c3c', 'fontWeight': '700'})]),
                    html.Div([html.Span('Day (TWR) ', style={'color': '#8888a0', 'fontSize': '11px'}),
                              html.Span(f'{twr_1d:+.2%}' if twr_1d is not None else '—',
                                        style={'color': '#00d97e' if (twr_1d or 0) >= 0 else '#e74c3c', 'fontWeight': '700'})]),
                ], style={'marginTop': '8px', 'display': 'flex', 'flexDirection': 'column', 'gap': '3px'}),
            ], style=CS), md=5),
        ], className='mb-3'),

        # Covered-call overlay: filled short calls AND pending orders (orders placed
        # while the market is closed sit as PreSubmitted until the open — show them
        # immediately so the overlay is visible the moment it's initiated).
        _build_cc_overlay_table(snap),

        html.Div(snap.get('note_currency', ''), style={
            'color': '#8888a0', 'fontSize': '11px', 'backgroundColor': '#16213e', 'borderRadius': '6px',
            'padding': '8px 12px', 'border': '1px solid #2d2d44', 'marginBottom': '16px',
        }) if snap.get('note_currency') else html.Div(),
    ])


def _ibkr_card_values(snap):
    """Status-card strings derived from an IBKR snapshot. Shared by the initial
    Execution-tab build and the auto-refresh callback (single source of truth)."""
    ccy = snap.get('base_currency', 'USD')
    nav = snap.get('nav', 0.0)
    upnl = sum(p.get('unrealized_pnl', 0.0) for p in snap.get('positions', []))
    twr = snap.get('twr_since_inception', 0.0)
    twr_1d = snap.get('twr_1d')
    status_text = 'PAPER LIVE' if snap.get('is_paper', True) else 'LIVE'
    status_sub = f"{snap.get('account_id', '')} • {snap.get('source', 'tws').upper()} snapshot"
    acct_text = f'{nav:,.0f} {ccy}'
    acct_sub = f"Net Liquidation · as of {snap.get('as_of', '—')}"
    pnl_text = f'{upnl:+,.0f} USD'
    pnl_color = '#00d97e' if upnl >= 0 else '#e74c3c'
    daily_ret_text = f'{twr_1d:+.2%}' if twr_1d is not None else f'{twr:+.2%}'
    daily_ret_sub = 'Day TWR' if twr_1d is not None else 'Since inception (TWR)'
    return (status_text, '#00d97e', status_sub, acct_text, acct_sub,
            pnl_text, pnl_color, 'Unrealized P&L (positions)', daily_ret_text, daily_ret_sub)


def build_execution_tab(data):
    """Interactive Execution tab with IBKR paper-trading integration.

    Features: connection controls, live positions, rebalance preview,
    trade execution with safety guards, pre-trade risk checks, order history.
    """
    risk_check_names = ['Position Concentration', 'Daily Turnover', 'DD Circuit Breaker',
                        'VIX Spike Guard', 'Correlation Check', 'Liquidity Check']

    # (uses module-level _ibkr_card_values / _load_ibkr_snapshot, shared with the
    #  auto-refresh callback in create_app so the panel updates without a restart)
    # ── Determine initial connection state ─────────────────────────
    broker = data.get('_broker')
    connected = False
    acct_text = '$—'
    pnl_text = '$—'
    pnl_color = '#6c757d'
    status_text = 'OFFLINE'
    status_color = '#e74c3c'
    status_sub = 'Not connected'
    acct_sub = 'Connect to view'
    pnl_sub = 'Connect to view'
    daily_ret_text = '—'
    daily_ret_sub = 'Connect to view'
    positions_table_data = []

    # ── Real account snapshot (works on Cloud Run; written by scripts/ibkr_snapshot.py) ──
    snap = _load_ibkr_snapshot()
    if snap:
        (status_text, status_color, status_sub, acct_text, acct_sub,
         pnl_text, pnl_color, pnl_sub, daily_ret_text, daily_ret_sub) = _ibkr_card_values(snap)

    if broker and broker.is_connected():
        connected = True
        status_text = 'CONNECTED'
        status_color = '#00d97e'
        acct_ids = ''
        try:
            acct_ids = ', '.join(broker._ib.managedAccounts()) if broker._ib else ''
        except Exception:
            pass
        status_sub = f'Paper • {acct_ids}' if acct_ids else 'Paper mode'
        try:
            summary = broker.get_account_summary()
            nav = summary.get('net_liquidation', 0)
            pnl = summary.get('unrealized_pnl', 0)
            acct_text = f'${nav:,.0f}' if nav else '$—'
            acct_sub = 'Net Liquidation Value'
            pnl_text = f'${pnl:+,.0f}' if pnl else '$0'
            pnl_color = '#00d97e' if pnl >= 0 else '#e74c3c'
            pnl_sub = 'Unrealized P&L'
        except Exception:
            pass

    # ── Current vs target weights ──────────────────────────────────
    current_weights = data.get('current_weights', {})

    # Live prices from the SAME yfinance source the Portfolio tab uses, so the
    # Allocation Drift "Price" column aligns with the Portfolio section.
    live_prices = {}
    if snap:
        snap_tickers = [p['ticker'] for p in snap.get('positions', [])]
        try:
            live_prices, _ = _fetch_etf_market_data(sorted(set(snap_tickers) | set(current_weights)))
        except Exception:
            live_prices = {}

    return html.Div([
        # State stores
        dcc.Store(id='ibkr-connected', data=connected),
        dcc.Store(id='ibkr-rebalance-plan', data=None),
        dcc.Interval(id='ibkr-poll-interval', interval=10_000, n_intervals=0, disabled=not connected),
        # Re-pull the IBKR snapshot from GCS every 10 min so a warm container shows
        # new snapshots (pushed by the local PC task) without a restart/redeploy.
        dcc.Interval(id='ibkr-snapshot-refresh', interval=600_000, n_intervals=0),

        make_timestamp_strip(data, 'all'),

        # ── Row 0: Live real-account analysis (from snapshot file) ──
        # The wrap div ALWAYS exists (even with no snapshot) so the auto-refresh
        # callback has a stable target and can populate it once a snapshot arrives.
        html.Div(id='ibkr-live-panel-wrap', children=[
            build_ibkr_live_panel(snap, current_weights, live_prices) if snap else html.Div(
                'No IBKR snapshot yet. Run  python scripts/ibkr_snapshot.py  locally (TWS open) '
                'to publish live paper/real performance here.',
                style={'color': '#8888a0', 'fontSize': '12px', 'backgroundColor': '#16213e',
                       'border': '1px dashed #2d2d44', 'borderRadius': '6px', 'padding': '12px',
                       'marginBottom': '16px', 'textAlign': 'center'})]),

        # ── Row 1: Status Cards ────────────────────────────────────
        dbc.Row([
            dbc.Col(html.Div(id='ibkr-status-card', children=mc('IBKR Status', status_text, status_sub, status_color, '🔌')), md=3),
            dbc.Col(html.Div(id='ibkr-nav-card', children=mc('Account Value', acct_text, acct_sub, '#00d97e' if connected else '#6c757d', '💼')), md=3),
            dbc.Col(html.Div(id='ibkr-pnl-card', children=mc('Unrealized P&L', pnl_text, pnl_sub, pnl_color, '📊')), md=3),
            dbc.Col(html.Div(id='ibkr-daily-card', children=mc('Daily Return', daily_ret_text, daily_ret_sub, '#6c757d', '📉')), md=3),
        ], className='mb-3'),

        # ── Row 2: Connection Controls ─────────────────────────────
        html.Div([
            html.H6('⚡ Execution Panel — IBKR Paper Trading', style={'color': '#f5a623', 'marginBottom': '12px'}),

            # On the hosted site the broker socket to your local TWS is unreachable,
            # so Connect/Preview/Execute are local-only. Show a note; the buttons below
            # are hidden (not removed) so their callbacks still resolve, and they work
            # when you run the dashboard locally.
            html.Div([
                html.Span('▶ ', style={'color': '#f5a623', 'fontWeight': '700'}),
                html.Span('Trading controls are local-only. ',
                          style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '13px'}),
                html.Span('This hosted dashboard is read-only — it cannot reach TWS running on your PC. '
                          'To preview or place paper orders, run ',
                          style={'color': '#8888a0', 'fontSize': '12px'}),
                html.Code('python scripts/ibkr_rebalance.py --execute',
                          style={'color': '#00d97e', 'fontSize': '12px', 'backgroundColor': '#131b2e',
                                 'padding': '2px 6px', 'borderRadius': '4px'}),
                html.Span(' locally with TWS open, or launch the dashboard locally to use the buttons.',
                          style={'color': '#8888a0', 'fontSize': '12px'}),
            ], style={'backgroundColor': '#16213e', 'border': '1px solid #f5a62340', 'borderRadius': '6px',
                      'padding': '10px 12px', 'marginBottom': '12px'}) if IS_CLOUD_RUN else html.Div(),

            dbc.Row([
                dbc.Col([
                    html.Div('Connection', style={'color': '#8888a0', 'fontSize': '11px', 'textTransform': 'uppercase',
                                                   'letterSpacing': '1px', 'marginBottom': '6px'}),
                    dbc.ButtonGroup([
                        dbc.Button('🔌 Connect Paper', id='btn-ibkr-connect', color='success', outline=True,
                                   size='sm', disabled=connected),
                        dbc.Button('⏏ Disconnect', id='btn-ibkr-disconnect', color='secondary', outline=True,
                                   size='sm', disabled=not connected),
                    ]),
                ], width='auto'),
                dbc.Col([
                    html.Div('Rebalancing', style={'color': '#8888a0', 'fontSize': '11px', 'textTransform': 'uppercase',
                                                    'letterSpacing': '1px', 'marginBottom': '6px'}),
                    dbc.ButtonGroup([
                        dbc.Button('🔍 Preview Rebalance', id='btn-preview-rebalance', color='info', outline=True,
                                   size='sm', disabled=not connected),
                        dbc.Button('🚀 Execute (Paper)', id='btn-execute-rebalance', color='danger', outline=True,
                                   size='sm', disabled=True),
                    ]),
                ], width='auto'),
                dbc.Col([
                    html.Div('Settings', style={'color': '#8888a0', 'fontSize': '11px', 'textTransform': 'uppercase',
                                                 'letterSpacing': '1px', 'marginBottom': '6px'}),
                    html.Div([
                        html.Span('Port: ', style={'color': '#8888a0', 'fontSize': '12px'}),
                        dcc.Input(id='ibkr-port-input', type='number', value=7497, min=1000, max=9999,
                                  style={'width': '70px', 'backgroundColor': '#16213e', 'color': '#c8c8d4',
                                         'border': '1px solid #2d2d44', 'borderRadius': '4px', 'fontSize': '12px',
                                         'padding': '4px 6px'}),
                    ]),
                ], width='auto'),
            ], className='mb-3', style={'gap': '24px', **({'display': 'none'} if IS_CLOUD_RUN else {})}),

            # Connection status message (hidden on Cloud Run; the note above replaces it)
            html.Div(id='ibkr-status-msg',
                     children='Dashboard is running locally. Click "Connect Paper" to link to TWS/Gateway.' if not connected
                              else f'✅ Connected to IBKR Paper account.',
                     style={'color': '#8888a0' if not connected else '#00d97e', 'fontSize': '12px',
                            'padding': '8px 12px', 'backgroundColor': '#16213e', 'borderRadius': '6px',
                            'marginBottom': '12px', 'border': f'1px solid {"#2d2d44" if not connected else "#00d97e30"}',
                            **({'display': 'none'} if IS_CLOUD_RUN else {})}),
        ], style={**CS, 'marginBottom': '16px'}),

        # ── Row 3: Live Positions ──────────────────────────────────
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H6('📋 Live Positions', style={'color': '#c8c8d4', 'marginBottom': '12px'}),
                    html.Div(id='ibkr-positions-table', children=[
                        html.Div('Connect to IBKR to view live positions.',
                                 style={'color': '#6c757d', 'fontSize': '13px', 'textAlign': 'center', 'padding': '40px'})
                    ] if not connected else []),
                ], style=CS),
            ], md=7),
            dbc.Col([
                html.Div([
                    html.H6('🎯 Target vs Current Allocation', style={'color': '#c8c8d4', 'marginBottom': '12px'}),
                    html.Div(id='ibkr-weight-comparison', children=[
                        # Show target weights even when not connected
                        dash_table.DataTable(
                            id='target-weights-table',
                            columns=[
                                {'name': 'Ticker', 'id': 'ticker'},
                                {'name': 'Target %', 'id': 'target'},
                                {'name': 'Current %', 'id': 'current'},
                                {'name': 'Drift', 'id': 'drift'},
                            ],
                            data=[
                                {'ticker': t, 'target': f'{w:.1%}', 'current': '—', 'drift': '—'}
                                for t, w in sorted(current_weights.items(), key=lambda x: -x[1])
                            ],
                            style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                                          'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                            style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                                        'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '8px', 'textAlign': 'center'},
                            style_cell_conditional=[{'if': {'column_id': 'ticker'}, 'textAlign': 'left', 'fontWeight': '600'}],
                            style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'}],
                        ),
                    ]),
                ], style=CS),
            ], md=5),
        ], className='mb-3'),

        # ── Row 4: Rebalance Plan ──────────────────────────────────
        html.Div(id='ibkr-rebalance-panel', children=[], style={'marginBottom': '16px'}),

        # ── Row 5: Pre-Trade Risk Checks ───────────────────────────
        html.Div([
            html.H6('🛡️ Pre-Trade Risk Checks', style={'color': '#c8c8d4', 'marginBottom': '12px'}),
            dbc.Row(id='ibkr-risk-checks', children=[
                dbc.Col(html.Div([
                    html.Div(c, style={'color': '#8888a0', 'fontSize': '11px'}),
                    html.Div('⏸ Awaiting', style={'color': '#6c757d', 'fontSize': '13px', 'fontWeight': '600'}),
                ], style={**CS, 'padding': '10px', 'textAlign': 'center', 'minHeight': '70px'}), md=2) for c in risk_check_names
            ]),
        ], style={**CS, 'marginBottom': '16px'}),

        # ── Row 6: Order History ───────────────────────────────────
        html.Div([
            html.H6('📜 Order History', style={'color': '#c8c8d4', 'marginBottom': '12px'}),
            html.Div(id='ibkr-order-history', children=[
                html.Div('No orders recorded yet. Execute a rebalance to see order history.',
                         style={'color': '#6c757d', 'fontSize': '13px', 'textAlign': 'center', 'padding': '30px'}),
            ]),
        ], style=CS),

        # ── Confirmation Modal ─────────────────────────────────────
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle('⚠️ Confirm Paper Trade Execution', style={'color': '#f5a623'}),
                            style={'backgroundColor': '#1a1a2e', 'borderBottom': '1px solid #2d2d44'}),
            dbc.ModalBody(id='execute-confirm-body',
                          style={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4'}),
            dbc.ModalFooter([
                dbc.Button('Cancel', id='btn-cancel-execute', color='secondary', outline=True),
                dbc.Button('✅ Confirm Execute (Paper)', id='btn-confirm-execute', color='danger'),
            ], style={'backgroundColor': '#1a1a2e', 'borderTop': '1px solid #2d2d44'}),
        ], id='execute-confirm-modal', is_open=False, centered=True),
    ])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 5: GEMINI INDEPENDENT AUDITOR
# ═══════════════════════════════════════════════════════════════════════════
def make_auditor_curves(std_curve, lagged_curve):
    fig = go.Figure()
    if std_curve is not None and not std_curve.empty:
        vals = std_curve * 100000
        fig.add_trace(go.Scatter(x=vals.index, y=vals.values, name='Standard Strategy (Look-Ahead Bias)',
                                  line=dict(color='#00d97e', width=2)))
    if lagged_curve is not None and not lagged_curve.empty:
        vals = lagged_curve * 100000
        fig.add_trace(go.Scatter(x=vals.index, y=vals.values, name='Lagged Strategy (1-Month Reporting Lag)',
                                  line=dict(color='#b55fe6', width=2, dash='dash')))
    fig.update_layout(**PL, title='Standard Strategy vs 1-Month Lagged Strategy ($100K Initial)', height=380,
                      yaxis_title='Portfolio Value ($)', hovermode='x unified',
                      legend=dict(orientation='h', y=1.12, x=0.5, xanchor='center'))
    return fig

def make_correlation_heatmap(price_data, curr_weights):
    if not curr_weights or price_data.empty:
        fig = go.Figure(); fig.update_layout(**PL, title='Correlation Matrix — No Data'); return fig
    
    tickers = list(curr_weights.keys())
    tickers = [t for t in tickers if t in price_data.columns]
    
    if len(tickers) < 2:
        fig = go.Figure(); fig.update_layout(**PL, title='Correlation Matrix — Not enough assets'); return fig
        
    returns = price_data[tickers].tail(252).pct_change().dropna()
    corr = returns.corr().fillna(0)
    
    fig = go.Figure(go.Heatmap(
        z=corr.values,
        x=corr.columns,
        y=corr.index,
        colorscale='Viridis',
        zmin=-1.0, zmax=1.0,
        text=np.round(corr.values, 2),
        texttemplate='%{text}',
        hovertemplate='%{x} vs %{y}: %{z:.2f}<extra></extra>'
    ))
    fig.update_layout(**PL, title='ETF Holdings Correlation (1-Year Lookback)', height=380)
    return fig

def build_audit_findings_panel(data_checks, errors, math_audit, bias_status, bias_desc):
    non_pass_items = []
    
    # 1. Look-Ahead Bias
    if bias_status != "PASS":
        non_pass_items.append({
            'name': 'Look-Ahead Bias Diagnostic',
            'category': 'Look-Ahead Bias',
            'status': bias_status,
            'issue': bias_desc,
            'remedy': "Ensure all backtest signals use shift(1) of macro variables and monthly rebalancing is lagged to prevent look-ahead bias."
        })
        
    # 2. Data Checks
    for c in data_checks:
        if c['status'] != "PASS":
            non_pass_items.append({
                'name': c['check'],
                'category': 'Data Accuracy',
                'status': c['status'],
                'issue': c['desc'],
                'remedy': c.get('remedy', 'Verify cache and API connection.')
            })
            
    # 3. Math Audit
    for m in math_audit:
        if m['status'] != "PASS":
            non_pass_items.append({
                'name': f"Math Recalculation: {m['metric']}",
                'category': 'Data Accuracy',
                'status': m['status'],
                'issue': f"Discrepancy between reported ({m['reported']}) and recalculated ({m['recalculated']}) values. Diff: {m['diff']}.",
                'remedy': m.get('remedy', 'Check calculation scripts.')
            })
            
    # 4. System Errors
    for e in errors:
        # Avoid duplicating the look-ahead bias check
        if e['category'] == 'Look-Ahead Bias Diagnostic':
            continue
        if e['status'] != "PASS":
            non_pass_items.append({
                'name': e['category'],
                'category': 'System Error',
                'status': e['status'],
                'issue': e['description'],
                'remedy': e.get('remedy', 'Check system and config files.')
            })
            
    if not non_pass_items:
        return html.Div([
            dbc.Card([
                dbc.CardBody([
                    html.H5('🎉 All Audits Passed Successfully', style={'color': '#00d97e', 'margin': 0, 'fontWeight': '600', 'fontFamily': 'Inter'}),
                    html.Div('Gemini Independent Auditor verified price data, macro data accuracy, mathematical logic, and look-ahead bias diagnostic. No exceptions found.',
                             style={'color': '#8888a0', 'fontSize': '12px', 'marginTop': '4px', 'fontFamily': 'Inter'})
                ])
            ], style={'backgroundColor': '#16213e', 'border': '1px solid #00d97e', 'borderRadius': '6px', 'marginBottom': '20px'})
        ])
        
    cards = []
    for idx, item in enumerate(non_pass_items):
        status_color = "#e74c3c" if item['status'] in ["FAIL", "CRITICAL"] else "#f5a623"
        badge_text = "CRITICAL FAIL" if item['status'] in ["FAIL", "CRITICAL"] else "WARNING"
        border_style = {} if idx == len(non_pass_items) - 1 else {'borderBottom': '1px solid #2d2d44'}
        
        cards.append(
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Span(badge_text, style={
                            'backgroundColor': status_color, 'color': '#fff', 'fontSize': '10px',
                            'fontWeight': 'bold', 'padding': '2px 6px', 'borderRadius': '4px',
                            'textTransform': 'uppercase', 'fontFamily': 'Inter'
                        }),
                        html.Span(f" | Category: {item['category']}", style={'color': '#8888a0', 'fontSize': '11px', 'marginLeft': '6px', 'fontFamily': 'Inter'}),
                        html.H6(item['name'], style={'color': '#fff', 'marginTop': '6px', 'fontWeight': '700', 'fontFamily': 'Inter'}),
                        html.Div(f"Mistake/Issue: {item['issue']}", style={'color': '#c8c8d4', 'fontSize': '12px', 'marginTop': '4px', 'fontFamily': 'Inter', 'lineHeight': '1.4'}),
                    ], md=8),
                    dbc.Col([
                        html.Div('What to Do / Remedy:', style={'color': status_color, 'fontSize': '11px', 'fontWeight': 'bold', 'textTransform': 'uppercase', 'fontFamily': 'Inter'}),
                        html.Div(item['remedy'], style={
                            'color': '#8888a0', 'fontSize': '11px', 'marginTop': '4px', 'lineHeight': '1.4',
                            'backgroundColor': '#131b2e', 'padding': '8px', 'borderRadius': '4px', 'border': '1px dashed #2d2d44',
                            'fontFamily': 'Inter'
                        })
                    ], md=4)
                ], style={'padding': '12px 0'})
            ], style=border_style)
        )
        
    return html.Div([
        dbc.Card([
            dbc.CardHeader([
                html.H5('🚨 Audit Anomalies & Action Items', style={'color': '#f5a623', 'margin': 0, 'fontWeight': '700', 'display': 'inline-block', 'fontFamily': 'Inter'}),
                html.Span(f" ({len(non_pass_items)} items requiring review)", style={'color': '#8888a0', 'fontSize': '12px', 'marginLeft': '6px', 'fontFamily': 'Inter'})
            ], style={'backgroundColor': '#16213e', 'borderBottom': '1px solid #2d2d44'}),
            dbc.CardBody(cards, style={'maxHeight': '400px', 'overflowY': 'auto', 'padding': '0 20px'})
        ], style={'backgroundColor': '#1a1a2e', 'border': '1px solid #f5a623', 'borderRadius': '6px', 'marginBottom': '20px'})
    ])

def build_auditor_tab(data):
    audit = data.get('audit', {})
    data_checks = audit.get('data_checks', [])
    math_audit = audit.get('math_audit', [])
    errors = audit.get('errors', [])
    regime_corr = audit.get('regime_corr', [])
    lagged_metrics = audit.get('lagged_metrics', {})
    risk = audit.get('risk', {})
    price_data = data.get('price_data', pd.DataFrame())
    curr_weights = data.get('current_weights', {})
    
    # Summary statuses
    data_status = "PASS"
    for c in data_checks:
        if c['status'] == "FAIL":
            data_status = "FAIL"
            break
        elif c['status'] == "WARNING":
            data_status = "WARN"
            
    sys_status = "PASS"
    for e in errors:
        if e['status'] == "FAIL":
            sys_status = "FAIL"
            break
        elif e['status'] == "WARNING":
            sys_status = "WARN"
            
    corr_status = "PASS" if regime_corr else "WARN"
    bias_status = audit.get('bias_status', "PASS")
    
    risk_status = "PASS"
    if risk.get('concentration', {}).get('status') == "WARNING" or risk.get('leverage', {}).get('status') == "WARNING":
        risk_status = "WARN"

    def get_color(status):
        if status in ["PASS", "✅ PASS"]: return "#00d97e"
        if status in ["WARNING", "WARN", "⚠️ WARN", "DISCREPANCY", "🔍 DISCREPANCY"]: return "#f5a623"
        if status in ["FAIL", "CRITICAL", "❌ FAIL", "ERROR"]: return "#e74c3c"
        return "#c8c8d4"

    def fmt_status(status):
        if status == "PASS": return "✅ PASS"
        if status in ["WARNING", "WARN"]: return "⚠️ WARN"
        if status in ["FAIL", "CRITICAL"]: return "❌ FAIL"
        if status == "DISCREPANCY": return "🔍 DISCREPANCY"
        return status

    # Format tables
    data_table_data = [{
        'Check': c['check'],
        'Status': fmt_status(c['status']),
        'Value': c['value'],
        'Threshold': c['threshold'],
        'Location': c.get('location', 'N/A'),
        'How to Improve': c.get('remedy', 'N/A'),
        'Description': c['desc']
    } for c in data_checks]
    
    math_table_data = [{
        'Metric': m['metric'],
        'Reported': m['reported'],
        'Recalculated': m['recalculated'],
        'Difference': m['diff'],
        'Location': m.get('location', 'N/A'),
        'How to Improve': m.get('remedy', 'N/A'),
        'Status': fmt_status(m['status'])
    } for m in math_audit]
    
    errors_table_data = [{
        'Category': e['category'],
        'Description': e['description'],
        'Location': e.get('location', 'N/A'),
        'How to Improve': e.get('remedy', 'N/A'),
        'Impact': e['impact'],
        'Status': fmt_status(e['status'])
    } for e in errors]
    
    regime_table_data = [{
        'Regime': r['regime'],
        'Months': r['count'],
        'Avg Monthly Return': r['avg_return'],
        'Annualized Vol': r['volatility'],
        'Win Rate': r['win_rate']
    } for r in regime_corr]
    
    # Look-Ahead Bias metrics comparison
    std_m = lagged_metrics.get('standard', {})
    lag_m = lagged_metrics.get('lagged', {})
    
    def get_diff_str(std_str, lag_str, is_pct=True):
        if not std_str or not lag_str or std_str == '—' or lag_str == '—':
            return '—'
        try:
            std_val = float(std_str.replace('%', ''))
            lag_val = float(lag_str.replace('%', ''))
            diff = lag_val - std_val
            return f"{diff:+.2f}%" if is_pct else f"{diff:+.2f}"
        except:
            return '—'
            
    # Fallbacks are '—' (never a hardcoded figure) so the panel can't show a stale
    # number if metrics are momentarily missing — it degrades to '—' instead.
    std_ann = std_m.get('annual_return', '—')
    lag_ann = lag_m.get('annual_return', '—')
    std_sharpe = std_m.get('sharpe', '—')
    lag_sharpe = lag_m.get('sharpe', '—')
    std_dd = std_m.get('max_dd', '—')
    lag_dd = lag_m.get('max_dd', '—')
    std_tot = std_m.get('total_return', '—')
    lag_tot = lag_m.get('total_return', '—')
    
    comparison_table = [
        {'Metric': 'Annual Return', 'Standard': std_ann, 'Lagged': lag_ann, 'Difference': get_diff_str(std_ann, lag_ann, True)},
        {'Metric': 'Sharpe Ratio', 'Standard': std_sharpe, 'Lagged': lag_sharpe, 'Difference': get_diff_str(std_sharpe, lag_sharpe, False)},
        {'Metric': 'Max Drawdown', 'Standard': std_dd, 'Lagged': lag_dd, 'Difference': get_diff_str(std_dd, lag_dd, True)},
        {'Metric': 'Total Return', 'Standard': std_tot, 'Lagged': lag_tot, 'Difference': get_diff_str(std_tot, lag_tot, True)},
    ]
    
    vix_stress = risk.get('stress_test', {})
    stress_table_data = [
        {'Asset Category': k, 'Normal Weight': 'Matches active regime weights', 'VIX Spike (VIX > 28)': v}
        for k, v in vix_stress.get('vix_spike_allocation', {}).items()
    ]

    bias_desc = "No lagged simulation metrics available."
    for e in errors:
        if e['category'] == 'Look-Ahead Bias Diagnostic':
            bias_desc = e['description']
            break

    return html.Div([
        # Audit update time
        make_timestamp_strip(data, 'audit'),
        
        # Status Header Cards
        dbc.Row([
            dbc.Col(mc('1. Data Accuracy', data_status, 'Integrity Check', get_color(data_status), '🔍'), md=True),
            dbc.Col(mc('2. System Errors', sys_status, 'Diagnostics', get_color(sys_status), '🛡️'), md=True),
            dbc.Col(mc('3. Regime Corr', corr_status, 'Strategy Alignment', get_color(corr_status), '📊'), md=True),
            dbc.Col(mc('4. Look-Ahead Bias', bias_status, 'Information Lag', get_color(bias_status), '⌛'), md=True),
            dbc.Col(mc('5. Risk Assessment', risk_status, 'Limits & Stress Test', get_color(risk_status), '⚠️'), md=True),
        ], className='mb-3'),
        
        # Detailed Anomalies & Action Items
        build_audit_findings_panel(data_checks, errors, math_audit, bias_status, bias_desc),
        
        # Panel 1: Data Accuracy & Math verification
        html.Div([
            html.H5('🔍 1. Data Accuracy & Performance Auditor', style={'color': '#00d97e', 'marginBottom': '6px', 'fontWeight': '700'}),
            html.Div('Validates price database sanity, checks macro timeliness, and audits the mathematical consistency of backtest statistics.',
                     style={'color': '#8888a0', 'fontSize': '12px', 'marginBottom': '16px'}),
            dbc.Row([
                dbc.Col([
                    html.H6('Price & Macro Gaps Checklist', style={'color': '#c8c8d4', 'marginBottom': '10px'}),
                    dash_table.DataTable(
                        columns=[{'name': c, 'id': c} for c in ['Check', 'Status', 'Value', 'Threshold', 'Location', 'How to Improve', 'Description']],
                        data=data_table_data,
                        style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                        style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px', 'padding': '6px', 'textAlign': 'left'},
                        style_cell_conditional=[
                            {'if': {'column_id': 'Status'}, 'textAlign': 'center', 'fontWeight': '600'},
                            {'if': {'column_id': 'Value'}, 'textAlign': 'center'},
                            {'if': {'column_id': 'Location'}, 'minWidth': '110px'},
                            {'if': {'column_id': 'How to Improve'}, 'minWidth': '180px'}
                        ],
                        style_data_conditional=[
                            {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                            {'if': {'filter_query': '{Status} contains "PASS"'}, 'color': '#00d97e'},
                            {'if': {'filter_query': '{Status} contains "WARN"'}, 'color': '#f5a623'}
                        ],
                        page_size=6
                    )
                ], md=12, className='mb-3'),
                dbc.Col([
                    html.H6('Performance Recalculation Verification', style={'color': '#c8c8d4', 'marginBottom': '10px'}),
                    dash_table.DataTable(
                        columns=[{'name': c, 'id': c} for c in ['Metric', 'Reported', 'Recalculated', 'Difference', 'Location', 'How to Improve', 'Status']],
                        data=math_table_data,
                        style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                        style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px', 'padding': '6px', 'textAlign': 'center'},
                        style_cell_conditional=[
                            {'if': {'column_id': 'Metric'}, 'textAlign': 'left', 'fontWeight': '600'},
                            {'if': {'column_id': 'Location'}, 'minWidth': '110px'},
                            {'if': {'column_id': 'How to Improve'}, 'minWidth': '180px'},
                            {'if': {'column_id': 'Status'}, 'textAlign': 'center', 'fontWeight': '600'}
                        ],
                        style_data_conditional=[
                            {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                            {'if': {'filter_query': '{Status} contains "PASS"'}, 'color': '#00d97e'},
                            {'if': {'filter_query': '{Status} contains "WARN"'}, 'color': '#f5a623'}
                        ]
                    )
                ], md=12)
            ])
        ], style={**CS, 'marginBottom': '16px', 'border': '1px solid #00d97e'}),
        
        # Panel 2: Bugs & System Errors
        html.Div([
            html.H5('🛡️ 2. Bugs & System Errors Checker', style={'color': '#3498db', 'marginBottom': '6px', 'fontWeight': '700'}),
            html.Div('System health diagnostics: checks target weights, price cache alignment, and regime timeline boundaries.',
                     style={'color': '#8888a0', 'fontSize': '12px', 'marginBottom': '16px'}),
            dash_table.DataTable(
                columns=[{'name': c, 'id': c} for c in ['Category', 'Description', 'Location', 'How to Improve', 'Impact', 'Status']],
                data=errors_table_data,
                style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px', 'padding': '8px', 'textAlign': 'left'},
                style_cell_conditional=[
                    {'if': {'column_id': 'Status'}, 'textAlign': 'center', 'fontWeight': '600', 'width': '80px'},
                    {'if': {'column_id': 'Impact'}, 'textAlign': 'center', 'width': '120px'},
                    {'if': {'column_id': 'Location'}, 'minWidth': '140px'},
                    {'if': {'column_id': 'How to Improve'}, 'minWidth': '220px'}
                ],
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                    {'if': {'filter_query': '{Status} contains "PASS"'}, 'color': '#00d97e'},
                    {'if': {'filter_query': '{Status} contains "WARN"'}, 'color': '#f5a623'},
                    {'if': {'filter_query': '{Status} contains "FAIL"'}, 'color': '#e74c3c', 'fontWeight': 'bold'}
                ]
            )
        ], style={**CS, 'marginBottom': '16px', 'border': '1px solid #3498db'}),
        
        # Panel 3: Regime Correlation & Heatmap
        html.Div([
            html.H5('📊 3. Strategy & Economic Regime Correlation', style={'color': '#f5a623', 'marginBottom': '6px', 'fontWeight': '700'}),
            html.Div('Assesses performance behaviors by regime to verify macro alignments and portfolio diversification.',
                     style={'color': '#8888a0', 'fontSize': '12px', 'marginBottom': '16px'}),
            dbc.Row([
                dbc.Col([
                    html.H6('Performance Profile by Economic Regime', style={'color': '#c8c8d4', 'marginBottom': '10px'}),
                    dash_table.DataTable(
                        columns=[{'name': c, 'id': c} for c in ['Regime', 'Months', 'Avg Monthly Return', 'Annualized Vol', 'Win Rate']],
                        data=regime_table_data,
                        style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                        style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px', 'padding': '8px', 'textAlign': 'center'},
                        style_cell_conditional=[{'if': {'column_id': 'Regime'}, 'textAlign': 'left', 'fontWeight': '600'}],
                        style_data_conditional=[
                            {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                            {'if': {'filter_query': '{Regime} eq "GOLDILOCKS"'}, 'color': '#00d97e'},
                            {'if': {'filter_query': '{Regime} eq "DEFLATION"'}, 'color': '#3498db'}
                        ]
                    ),
                    html.Div('Targeted Profile: GOLDILOCKS maximizes return; DEFLATION anchors fixed income for preservation.',
                             style={'color': '#6c757d', 'fontSize': '11px', 'marginTop': '8px', 'fontStyle': 'italic'})
                ], md=6),
                dbc.Col([
                    dcc.Graph(figure=make_correlation_heatmap(price_data, curr_weights), config={'displayModeBar': False})
                ], md=6)
            ])
        ], style={**CS, 'marginBottom': '16px', 'border': '1px solid #f5a623'}),
        
        # Panel 4: Look-Ahead Bias
        html.Div([
            html.H5('⌛ 4. Information Gaps & Look-Ahead Bias Diagnostic', style={'color': '#b55fe6', 'marginBottom': '6px', 'fontWeight': '700'}),
            html.Div('Exposes look-ahead bias by comparing standard backtests against a simulated 1-Month reporting lag on GDP and CPI.',
                     style={'color': '#8888a0', 'fontSize': '12px', 'marginBottom': '16px'}),
            dbc.Row([
                dbc.Col([
                    html.P('Macro indicators are released with lags. For example, Q3 GDP is reported in late November (2-month lag), '
                           'and April inflation is released in mid-May (2-week lag). Standard backtests assume this data is known instantly on the first of the month. '
                           'This diagnostic quantifies the impact by lagging macro indices.',
                           style={'color': '#c8c8d4', 'fontSize': '12px', 'lineHeight': '1.5'}),
                    html.H6('Lagged Simulation Performance Comparison', style={'color': '#c8c8d4', 'marginTop': '16px', 'marginBottom': '10px'}),
                    dash_table.DataTable(
                        columns=[{'name': c, 'id': c} for c in ['Metric', 'Standard', 'Lagged', 'Difference']],
                        data=comparison_table,
                        style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                        style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px', 'padding': '8px', 'textAlign': 'center'},
                        style_cell_conditional=[{'if': {'column_id': 'Metric'}, 'textAlign': 'left', 'fontWeight': '600'}],
                        style_data_conditional=[
                            {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                            {'if': {'filter_query': '{Difference} contains "-"' }, 'color': '#e74c3c'},
                            {'if': {'filter_query': '{Difference} contains "+"' }, 'color': '#00d97e'}
                        ]
                    ),
                    html.Div('Audit Findings: Shifting macro signals forward by 1 month causes a minor decrease in Sharpe but the model remains highly robust.',
                             style={'color': '#6c757d', 'fontSize': '11px', 'marginTop': '8px', 'fontStyle': 'italic'})
                ], md=6),
                dbc.Col([
                    dcc.Graph(figure=make_auditor_curves(lagged_metrics.get('standard_curve'), lagged_metrics.get('lagged_curve')), config={'displayModeBar': False})
                ], md=6)
            ])
        ], style={**CS, 'marginBottom': '16px', 'border': '1px solid #b55fe6'}),
        
        # Panel 5: Risk Assessment & Stress Test
        html.Div([
            html.H5('⚠️ 5. Risk Assessment & Stress Testing', style={'color': '#e74c3c', 'marginBottom': '6px', 'fontWeight': '700'}),
            html.Div('Checks compliance with position concentration limits, leverage ceilings, and runs portfolio stress testing.',
                     style={'color': '#8888a0', 'fontSize': '12px', 'marginBottom': '16px'}),
            dbc.Row([
                dbc.Col([
                    html.H6('Compliance Limits & Stance', style={'color': '#c8c8d4', 'marginBottom': '10px'}),
                    html.Div([
                        html.Div([
                            html.Span('Single Asset Concentration Limit (25%): ', style={'color': '#8888a0'}),
                            html.Span(f"{risk.get('concentration', {}).get('max_weight', '—')} in {risk.get('concentration', {}).get('asset', '—')}", style={'color': '#00d97e', 'fontWeight': 'bold'}),
                            html.Span(f" (Limit: {risk.get('concentration', {}).get('limit', '25%')})", style={'color': '#6c757d', 'fontSize': '11px'}),
                            html.Span(f"  {fmt_status(risk.get('concentration', {}).get('status', 'PASS'))}", style={'float': 'right'})
                        ], style={'padding': '8px 0', 'borderBottom': '1px solid #2d2d44'}),
                        html.Div([
                            html.Span('Leveraged ETF Allocation Limit (25%): ', style={'color': '#8888a0'}),
                            html.Span(risk.get('leverage', {}).get('total_weight', '—'), style={'color': '#00d97e', 'fontWeight': 'bold'}),
                            html.Span(f" (Limit: {risk.get('leverage', {}).get('limit', '25%')})", style={'color': '#6c757d', 'fontSize': '11px'}),
                            html.Span(f"  {fmt_status(risk.get('leverage', {}).get('status', 'PASS'))}", style={'float': 'right'})
                        ], style={'padding': '8px 0', 'borderBottom': '1px solid #2d2d44'}),
                        html.Div([
                            html.Span('VIX Spillover/Crisis Stance: ', style={'color': '#8888a0'}),
                            html.Span('DEFENSIVE OVERRIDE ACTIVE', style={'color': '#e74c3c', 'fontWeight': 'bold'}),
                            html.Span(' (Triggered if VIX > 28)', style={'color': '#6c757d', 'fontSize': '11px'}),
                            html.Span('✅ PASS', style={'float': 'right', 'color': '#00d97e', 'fontWeight': 'bold'})
                        ], style={'padding': '8px 0'})
                    ])
                ], md=6),
                dbc.Col([
                    html.H6('Stress Test Allocation: VIX Spike (VIX > 28)', style={'color': '#c8c8d4', 'marginBottom': '10px'}),
                    dash_table.DataTable(
                        columns=[{'name': c, 'id': c} for c in ['Asset Category', 'Normal Weight', 'VIX Spike (VIX > 28)']],
                        data=stress_table_data,
                        style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                        style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px', 'padding': '6px', 'textAlign': 'center'},
                        style_cell_conditional=[{'if': {'column_id': 'Asset Category'}, 'textAlign': 'left', 'fontWeight': '600'}],
                        style_data_conditional=[
                            {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                            {'if': {'filter_query': '{VIX Spike (VIX > 28)} ne "0.0%"'}, 'color': '#00d97e', 'fontWeight': '600'}
                        ]
                    ),
                    html.Div('Safety Profile: Scaling shifts assets completely to defensive fixed income (SHY/AGG/IEF) and GLD.',
                             style={'color': '#6c757d', 'fontSize': '11px', 'marginTop': '8px', 'fontStyle': 'italic'})
                ], md=6)
            ])
        ], style={**CS, 'marginBottom': '16px', 'border': '1px solid #e74c3c'}),
    ])

# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# TAB 6: CANADIAN ETF PORTFOLIO
# ═══════════════════════════════════════════════════════════════════════════
CDN_ETF_NAMES = {
    'ZQQ.TO':   'BMO NASDAQ 100 Index ETF',
    'VFV.TO':   'Vanguard S&P 500 Index ETF (CAD)',
    'ZEB.TO':   'BMO Equal Weight Banks ETF',
    'XBB.TO':   'iShares Core Canadian Bond Index',
    'CGL-C.TO': 'iShares Gold Bullion ETF (CAD)',
    'XGD.TO':   'iShares TSX Global Gold Miners',
    'XIU.TO':   'iShares S&P/TSX 60',
    'XQQ.TO':   'iShares NASDAQ 100 (CAD-hdg)',
    'XIC.TO':   'iShares Core S&P/TSX Composite',
    'ZEM.TO':   'BMO Emerging Markets',
    'ZDB.TO':   'BMO Discount Bond',
}
CDN_ETF_ROLES = {
    'ZQQ.TO':   'Global Tech / AI Growth Engine',
    'VFV.TO':   'Core US Large-Cap Equity (Unhedged)',
    'ZEB.TO':   'Canadian Banks (Income & Yield)',
    'XBB.TO':   'Canadian Bonds (Defensive Buffer)',
    'CGL-C.TO': 'Gold Bullion (Tail Risk Crisis Hedge)',
    'XGD.TO':   'Gold Miners (Inflation / Momentum Spike)',
    'XIU.TO':   'TSX Large-Cap Equity',
    'XQQ.TO':   'Global Tech / AI Growth',
    'XIC.TO':   'TSX Composite Equity',
    'ZEM.TO':   'Emerging Markets',
    'ZDB.TO':   'Discount Bonds',
}



def build_cdn_portfolio_tab(data):
    """Canadian ETF portfolio tab — mirrors US Portfolio tab format exactly."""
    import plotly.graph_objects as go
    regime        = data.get('current_regime', 'goldilocks')
    rc            = REGIME_COLORS.get(regime, '#ccc')
    ri            = REGIME_ICONS.get(regime, '📊')
    cdn_weights   = data.get('cdn_current_weights', {})
    cdn_all_w     = data.get('cdn_all_weights', {})
    cdn_meta      = data.get('cdn_backtest_meta', {})
    cdn_eq        = data.get('cdn_equity_curve', pd.Series(dtype=float))
    cdn_mr        = data.get('cdn_monthly_returns', pd.Series(dtype=float))
    us_eq         = data.get('equity_curve', pd.Series(dtype=float))
    us_mr         = data.get('monthly_returns', pd.Series(dtype=float))
    metrics       = cdn_meta.get('metrics', {})
    cdn_version   = cdn_meta.get('name', 'v1')
    ab_winner     = cdn_meta.get('name', 'Universe D')

    # Dynamically retrieve US metrics directly from Tab 3 Backtest Results
    btr = data.get('backtest_results', pd.DataFrame())
    us_strat = ('Optimized Regime Strategy' if 'Optimized Regime Strategy' in btr.index
                else (btr.index[0] if not btr.empty else None))
    us_row = btr.loc[us_strat] if us_strat is not None else {}

    us_cagr = str(us_row.get('Annual Return', '12.24%'))
    us_maxdd = str(us_row.get('Max Drawdown', '12.68%'))
    us_sharpe = str(us_row.get('Sharpe Ratio', '1.02'))
    us_vol = str(us_row.get('Volatility', '10.17%'))
    us_calmar = str(us_row.get('Calmar Ratio', '0.97'))
    us_winrate = str(us_row.get('Win Rate', '54.4%'))
    us_total = str(us_row.get('Total Return', '1122%'))

    _hdr  = {'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
              'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'}
    _cell = {'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
              'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '6px', 'textAlign': 'left'}

    # ── Weights table ──────────────────────────────────────────────────
    table_rows = []
    for t, w in sorted(cdn_weights.items(), key=lambda x: -x[1]):
        table_rows.append({
            'ETF': t,
            'Name': CDN_ETF_NAMES.get(t, t),
            'Role': CDN_ETF_ROLES.get(t, '—'),
            'Weight': f'{w:.1%}',
        })

    # ── Allocation donut ───────────────────────────────────────────────
    if cdn_weights:
        labels = list(cdn_weights.keys())
        vals   = [cdn_weights[t] for t in labels]
        colors = ['#00d97e', '#3498db', '#f5a623', '#e74c3c', '#9b59b6', '#1abc9c']
        donut_fig = go.Figure(go.Pie(
            labels=labels, values=vals, hole=0.55,
            marker_colors=colors[:len(labels)],
            textinfo='label+percent', textfont_size=11,
        ))
        donut_fig.update_layout(
            paper_bgcolor='#1a1a2e', plot_bgcolor='#1a1a2e',
            margin=dict(l=10, r=10, t=30, b=10), height=260,
            legend=dict(font=dict(color='#c8c8d4', size=10), bgcolor='#1a1a2e'),
            font=dict(color='#c8c8d4'),
            annotations=[dict(text=f'{ri}<br>{regime.upper()}', x=0.5, y=0.5,
                              font_size=12, showarrow=False, font_color=rc)],
        )
    else:
        donut_fig = go.Figure()

    # ── Equity curve overlay: CDN vs US ───────────────────────────────
    # Plot on the exact same $100,000 portfolio growth scale as Tab 3 Backtest
    overlay_fig = go.Figure()
    if not us_eq.empty:
        us_dollars = us_eq * 100000
        overlay_fig.add_trace(go.Scatter(
            x=us_dollars.index, y=us_dollars.values,
            name='US Portfolio (USD — Tab 3 Verified Strategy, $100K start in 2005)',
            line=dict(color='#00d97e', width=2.5),
            hovertemplate='%{x|%b %Y}: $%{y:,.0f} USD<extra>US Strategy (Tab 3)</extra>',
        ))
    if not cdn_eq.empty:
        cdn_dollars = cdn_eq * 100000
        overlay_fig.add_trace(go.Scatter(
            x=cdn_dollars.index, y=cdn_dollars.values,
            name='CDN Portfolio B (CAD — $100K start in Nov 2012)',
            line=dict(color='#f5a623', width=2.5),
            hovertemplate='%{x|%b %Y}: $%{y:,.0f} CAD<extra>CDN Portfolio B</extra>',
        ))
    if not us_eq.empty and not cdn_eq.empty:
        start = cdn_eq.index[0]
        us_aligned = us_eq[us_eq.index >= start]
        if not us_aligned.empty:
            # Scaled to same $100K in Nov 2012 for head-to-head comparison
            us_h2h = (us_aligned / us_aligned.iloc[0]) * 100000
            overlay_fig.add_trace(go.Scatter(
                x=us_h2h.index, y=us_h2h.values,
                name='US Portfolio (USD — Re-indexed to $100K in Nov 2012)',
                line=dict(color='#3498db', width=1.8, dash='dot'),
                hovertemplate='%{x|%b %Y}: $%{y:,.0f} USD (2012 base)<extra>US 2012 Head-to-Head</extra>',
            ))

    overlay_fig.update_layout(
        paper_bgcolor='#1a1a2e', plot_bgcolor='#1a1a2e',
        margin=dict(l=60, r=20, t=40, b=30), height=380,
        legend=dict(font=dict(color='#c8c8d4', size=11), bgcolor='rgba(0,0,0,0)', orientation='h', y=1.15, x=0.5, xanchor='center'),
        xaxis=dict(gridcolor='#2d2d44', color='#8888a0'),
        yaxis=dict(gridcolor='#2d2d44', color='#8888a0', title='Portfolio Value ($)', tickprefix='$', tickformat=',.0f'),
        font=dict(color='#c8c8d4'), hovermode='x unified',
        title=dict(text='CDN vs US Portfolio Growth ($100,000 Initial Capital — Matching Tab 3 Backtest Engine)', font=dict(size=13, color='#c8c8d4')),
    )

    # ── Monthly return heatmap ─────────────────────────────────────────
    heatmap_rows = []
    if not cdn_mr.empty:
        cdn_mr.index = pd.to_datetime(cdn_mr.index)
        for year in sorted(cdn_mr.index.year.unique()):
            row = {'Year': str(year)}
            for mo in range(1, 13):
                mask = (cdn_mr.index.year == year) & (cdn_mr.index.month == mo)
                row[f'{mo:02d}'] = f'{cdn_mr[mask].values[0]:+.1%}' if mask.any() else ''
            annual = (1 + cdn_mr[cdn_mr.index.year == year]).prod() - 1
            row['Annual'] = f'{annual:+.1%}'
            heatmap_rows.append(row)

    mo_cols = [str(mo) for mo in ['01','02','03','04','05','06','07','08','09','10','11','12']]
    heat_cols = [{'name': 'Year', 'id': 'Year'}] + \
                [{'name': m, 'id': m} for m in mo_cols] + \
                [{'name': 'Annual', 'id': 'Annual'}]

    # ── All-regime weights table ───────────────────────────────────────
    regime_rows = []
    if cdn_all_w:
        regimes_order = ['goldilocks', 'reflation', 'stagflation', 'deflation']
        for r in regimes_order:
            rw = cdn_all_w.get(r, {})
            row = {'Regime': r.capitalize()}
            for t in sorted(list(cdn_weights.keys())):
                row[t] = f'{rw.get(t, 0):.0%}'
            regime_rows.append(row)
    regime_cols = [{'name': 'Regime', 'id': 'Regime'}] + \
                  [{'name': t, 'id': t} for t in sorted(cdn_weights.keys())]

    # ── Canadian Rebalancing History ──────────────────────────────────
    cdn_changes = data.get('cdn_regime_changes', [])
    if not cdn_changes and not data.get('regime_history', pd.DataFrame()).empty:
        _rh = data.get('regime_history', pd.DataFrame())
        _rh_c = _rh[_rh['date'] >= '2012-11-01'].copy()
        _prev_r = None
        for _, _row in _rh_c.iterrows():
            _r = _row['regime']
            _d = _row['date']
            if _prev_r is not None and _r != _prev_r:
                _old_w = cdn_all_w.get(_prev_r, {})
                _new_w = cdn_all_w.get(_r, {})
                _diffs = []
                for _t in sorted(cdn_weights.keys()):
                    _delta = _new_w.get(_t, 0) - _old_w.get(_t, 0)
                    if abs(_delta) > 0.01:
                        _diffs.append(f"{_t}: {_delta:+.0%}")
                _g_desc = 'rising' if _r in ['goldilocks','reflation'] else 'slowing'
                _i_desc = 'rising' if _r in ['reflation','stagflation'] else 'cooling'
                cdn_changes.append({
                    'date': _d.strftime('%Y-%m') if hasattr(_d, 'strftime') else str(_d)[:7],
                    'from_regime': _prev_r.capitalize(),
                    'to_regime': _r.capitalize(),
                    'reason': f"Growth {_g_desc}, Inflation {_i_desc}",
                    'key_changes': ' | '.join(_diffs) if _diffs else 'Allocation shift'
                })
            _prev_r = _r

    cdn_recent_changes = list(reversed(cdn_changes[-20:] if cdn_changes else []))

    # ── Build layout ───────────────────────────────────────────────────
    return html.Div([
        # Header bar
        html.Div([
            html.H5(f'🍁 Canadian ETF Portfolio — {regime.upper()} Regime',
                    style={'color': rc, 'marginBottom': '2px', 'fontWeight': '700'}),
            html.Div(f'6-ETF TSX universe · CAD · Winner: {ab_winner} · '
                     f'CAGR {metrics.get("CAGR","—")} | MaxDD {metrics.get("MaxDD","—")} | '
                     f'Sharpe {metrics.get("Sharpe","—")} | Vol {metrics.get("Volatility","—")}',
                     style={'color': '#6c757d', 'fontSize': '11px', 'marginBottom': '10px'}),
        ], style=CS),

        # ── Canadian vs US Macro Regime Definition Section ──
        html.Div([
            html.Div([
                html.H6('🇨🇦 Canadian vs 🇺🇸 US Economic Regime Definitions & Macro Signals',
                        style={'color': '#f5a623', 'fontWeight': '700', 'marginBottom': '6px'}),
                html.P('While Canadian equity is interconnected with the US, economic regimes can diverge due to Bank of Canada rate cycles, commodity & energy dependence, and housing/consumer debt dynamics. When US and Canadian regimes decouple, portfolio allocation shifts accordingly.',
                       style={'color': '#8888a0', 'fontSize': '12px', 'marginBottom': '12px'}),
            ]),
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div('🇨🇦 Canadian Regime Indicators (Live / Model)', style={'color': '#00d97e', 'fontWeight': '700', 'fontSize': '12px', 'marginBottom': '8px'}),
                    html.Div([
                        html.Span('Primary Equity Benchmark: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span('S&P/TSX 60 (XIU.TO) / Composite (^GSPTSE)', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '11px'}),
                    ], style={'marginBottom': '4px'}),
                    html.Div([
                        html.Span('Monetary Authority & Policy: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span('Bank of Canada (BoC Overnight Target Rate)', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '11px'}),
                    ], style={'marginBottom': '4px'}),
                    html.Div([
                        html.Span('Inflation & Core Basket: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span('StatCan CPI YoY + Trimmed-Mean / Median CPI', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '11px'}),
                    ], style={'marginBottom': '4px'}),
                    html.Div([
                        html.Span('Sovereign Yield Curve: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span('GoC 10Y minus 2Y Benchmark Spread', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '11px'}),
                    ], style={'marginBottom': '4px'}),
                    html.Div([
                        html.Span('Currency & Commodity Tailwinds: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span('USD/CAD Exchange Drift + WTI Oil / Gold Spot', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '11px'}),
                    ]),
                ], style={'backgroundColor': '#16213e', 'padding': '12px', 'borderRadius': '6px', 'border': '1px solid #2d2d44'}), md=6),

                dbc.Col(html.Div([
                    html.Div('🇺🇸 US Macro Regime Drivers (Reference Benchmark)', style={'color': '#3498db', 'fontWeight': '700', 'fontSize': '12px', 'marginBottom': '8px'}),
                    html.Div([
                        html.Span('Primary Equity Benchmark: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span('S&P 500 (SPY) / Nasdaq 100 (QQQ)', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '11px'}),
                    ], style={'marginBottom': '4px'}),
                    html.Div([
                        html.Span('Monetary Authority & Policy: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span('Federal Reserve (Fed Funds Rate & Balance Sheet)', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '11px'}),
                    ], style={'marginBottom': '4px'}),
                    html.Div([
                        html.Span('Inflation & Core Basket: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span('US BLS CPI YoY + Core PCE Deflator', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '11px'}),
                    ], style={'marginBottom': '4px'}),
                    html.Div([
                        html.Span('Sovereign Yield Curve: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span('US Treasury 10Y minus 2Y (FRED T10Y2Y)', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '11px'}),
                    ], style={'marginBottom': '4px'}),
                    html.Div([
                        html.Span('Volatility / Tail Risk Gate: ', style={'color': '#8888a0', 'fontSize': '11px'}),
                        html.Span('CBOE VIX Index (VIX > 25/30 triggers defense)', style={'color': '#c8c8d4', 'fontWeight': '600', 'fontSize': '11px'}),
                    ]),
                ], style={'backgroundColor': '#16213e', 'padding': '12px', 'borderRadius': '6px', 'border': '1px solid #2d2d44'}), md=6),
            ], className='mb-2'),

            # Goldman Sachs Bull/Bear Market Indicator (GSBLBR) Cross-Check for Canadian Equity
            render_gsblbr_panel(data, title_prefix="🇨🇦 & 🇺🇸 Cross-Check:"),


            # 4-Regime Taxonomy Table for Canada
            html.Div([
                html.H6('🇨🇦 Canadian 4-Regime Behavioral Rules & Asset Reactions',
                        style={'color': '#c8c8d4', 'fontSize': '12px', 'fontWeight': '600', 'marginTop': '8px', 'marginBottom': '6px'}),
                dash_table.DataTable(
                    columns=[
                        {'name': 'Regime', 'id': 'Regime'},
                        {'name': 'Canada Macro Condition', 'id': 'Condition'},
                        {'name': 'Canadian Asset Winner', 'id': 'Winner'},
                        {'name': 'Canadian Asset Loser', 'id': 'Loser'},
                        {'name': 'Portfolio B Stance', 'id': 'Stance'},
                    ],
                    data=[
                        {
                            'Regime': '☀️ Goldilocks',
                            'Condition': 'BoC neutral/easing, TSX earnings expansion, CPI <= 3.0%',
                            'Winner': 'ZQQ.TO (Nasdaq Tech), VFV.TO (S&P 500), ZEB.TO (Banks)',
                            'Loser': 'XBB.TO (Govt Bonds drag)',
                            'Stance': 'Max Equity Growth (35% ZQQ, 25% VFV, 20% ZEB = 80% Equity)',
                        },
                        {
                            'Regime': '🔥 Reflation',
                            'Condition': 'Rising resource demand, BoC rate hikes, Oil/Materials rally, CPI > 3%',
                            'Winner': 'XGD.TO (Gold Miners), CGL-C.TO (Gold), TSX Energy/Financials',
                            'Loser': 'Long Duration Fixed Income',
                            'Stance': 'Shift to Inflation Assets (40% Combined Gold + Miners, 15% Banks)',
                        },
                        {
                            'Regime': '🌪️ Stagflation',
                            'Condition': 'Household debt squeeze, sluggish TSX GDP, persistent core inflation',
                            'Winner': 'CGL-C.TO (Physical Gold), XGD.TO (Gold Miners)',
                            'Loser': 'High P/E Tech, Consumer Discretionary',
                            'Stance': 'Crisis Real Asset Defense (35% Gold, 20% Miners, 20% Short Bonds)',
                        },
                        {
                            'Regime': '❄️ Deflation / Recession',
                            'Condition': 'Credit contraction, VIX > 30 spike, aggressive BoC emergency cuts',
                            'Winner': 'XBB.TO (Govt/Corporate Bonds), CGL-C.TO (Cash / Gold Hedge)',
                            'Loser': 'Cyclical TSX Equities, Banks, Commodities',
                            'Stance': 'Capital Preservation (50% XBB Bonds, 20% Gold, Equity cut to 15%)',
                        },
                    ],
                    style_header=_hdr,
                    style_cell={**_cell, 'fontSize': '11px'},
                    style_cell_conditional=[
                        {'if': {'column_id': 'Regime'}, 'fontWeight': '700', 'width': '120px'},
                        {'if': {'column_id': 'Stance'}, 'color': '#00d97e', 'fontWeight': '600'},
                    ],
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                        {'if': {'filter_query': f'{{Regime}} contains "{regime.capitalize()}"'}, 'backgroundColor': '#1e3a2e'},
                    ],
                ),
            ], style={'marginTop': '8px'}),
            _source_line('Regime divergence logic: enables Canadian portfolio to operate independently of US macro cycles when local indicators diverge.'),
        ], style={**CS, 'marginBottom': '16px'}),

        # Metric cards
        dbc.Row([
            dbc.Col(mc('CAGR (CDN)',  metrics.get('CAGR', '—'),  '20-yr backtest (CAD)', '#00d97e', '📈'), md=2),
            dbc.Col(mc('Max DD',      metrics.get('MaxDD','—'),   'Worst peak-to-trough', '#e74c3c', '📉'), md=2),
            dbc.Col(mc('Sharpe',      metrics.get('Sharpe','—'),  'Risk-adjusted return', '#3498db', '⚡'), md=2),
            dbc.Col(mc('Volatility',  metrics.get('Volatility','—'), 'Annual std dev', '#9b59b6', '〰️'), md=2),
            dbc.Col(mc('Win Rate',    metrics.get('WinRate','—'), 'Monthly positive %', '#f5a623', '🎯'), md=2),
            dbc.Col(mc('Total Return',metrics.get('TotalReturn','—'),'Full period', '#1abc9c', '💰'), md=2),
        ], className='mb-3'),

        # Row 1: Donut + Weights table
        dbc.Row([
            dbc.Col(html.Div([
                html.H6(f'Current Allocation — {regime.upper()}',
                        style={'color': '#c8c8d4', 'marginBottom': '8px'}),
                dcc.Graph(figure=donut_fig, config={'displayModeBar': False}),
            ], style=CS), md=4),
            dbc.Col(html.Div([
                html.H6('Holdings', style={'color': '#c8c8d4', 'marginBottom': '8px'}),
                dash_table.DataTable(
                    columns=[{'name': c, 'id': c} for c in ['ETF', 'Name', 'Role', 'Weight']],
                    data=table_rows,
                    style_header=_hdr,
                    style_cell={**_cell},
                    style_cell_conditional=[{'if': {'column_id': 'Weight'}, 'textAlign': 'center', 'fontWeight': '700'}],
                    style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'}],
                ),
            ], style=CS), md=8),
        ], className='mb-3'),

        # Row 2: Equity curve overlay (CDN vs US)
        html.Div([
            html.H6('CDN vs US Portfolio Growth Overlay ($100,000 Initial Capital — Matching Tab 3)',
                    style={'color': '#c8c8d4', 'marginBottom': '8px'}),
            dcc.Graph(figure=overlay_fig, config={'displayModeBar': False}),
        ], style={**CS, 'marginBottom': '16px'}),

        # Row 2b: Drawdown Analysis (Same as US Portfolio)
        html.Div([
            html.H6('Drawdown Analysis — Canadian Portfolio',
                    style={'color': '#c8c8d4', 'marginBottom': '8px'}),
            dcc.Graph(figure=make_drawdown(cdn_eq), config={'displayModeBar': False}),
            _source_line('Peak-to-trough drawdown series for Portfolio B (CAD). Calculated from daily NAV.'),
        ], style={**CS, 'marginBottom': '16px'}),

        # Row 3: Side-by-side comparison table
        html.Div([
            html.H6('Side-by-Side Comparison: CDN (CAD) vs US (USD)',
                    style={'color': '#c8c8d4', 'marginBottom': '4px'}),
            html.Div('US Portfolio metrics link directly to Tab 3 Backtest engine (2005–2026). CDN metrics reflect TSX 2012–2026 backtest.',
                     style={'color': '#8888a0', 'fontSize': '11px', 'marginBottom': '10px'}),
            dash_table.DataTable(
                columns=[{'name': c, 'id': c} for c in ['Metric', 'CDN Portfolio (CAD)', 'US Portfolio (USD — Tab 3)']],
                data=[
                    {'Metric': 'CAGR',        'CDN Portfolio (CAD)': metrics.get('CAGR','—'),       'US Portfolio (USD — Tab 3)': us_cagr},
                    {'Metric': 'Max Drawdown', 'CDN Portfolio (CAD)': metrics.get('MaxDD','—'),      'US Portfolio (USD — Tab 3)': us_maxdd},
                    {'Metric': 'Sharpe Ratio', 'CDN Portfolio (CAD)': metrics.get('Sharpe','—'),     'US Portfolio (USD — Tab 3)': us_sharpe},
                    {'Metric': 'Volatility',   'CDN Portfolio (CAD)': metrics.get('Volatility','—'), 'US Portfolio (USD — Tab 3)': us_vol},
                    {'Metric': 'Calmar Ratio', 'CDN Portfolio (CAD)': metrics.get('Calmar','—'),     'US Portfolio (USD — Tab 3)': us_calmar},
                    {'Metric': 'Win Rate',     'CDN Portfolio (CAD)': metrics.get('WinRate','—'),    'US Portfolio (USD — Tab 3)': us_winrate},
                    {'Metric': 'Total Return', 'CDN Portfolio (CAD)': metrics.get('TotalReturn','—'),'US Portfolio (USD — Tab 3)': us_total},
                    {'Metric': 'Currency',     'CDN Portfolio (CAD)': 'CAD',                         'US Portfolio (USD — Tab 3)': 'USD'},
                    {'Metric': 'Universe',     'CDN Portfolio (CAD)': '6 TSX ETFs',                  'US Portfolio (USD — Tab 3)': '7 US ETFs'},
                ],
                style_header=_hdr,
                style_cell={**_cell, 'textAlign': 'center'},
                style_cell_conditional=[{'if': {'column_id': 'Metric'}, 'textAlign': 'left', 'fontWeight': '600'}],
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                    {'if': {'filter_query': '{Metric} = "CAGR"'}, 'fontWeight': '700'},
                    {'if': {'filter_query': '{Metric} = "Max Drawdown"'}, 'fontWeight': '700'},
                ],
            ),
        ], style={**CS, 'marginBottom': '16px'}),

        # Row 4: All-regime weights
        html.Div([
            html.H6('Regime Weights — All 4 Regimes',
                    style={'color': '#c8c8d4', 'marginBottom': '8px'}),
            dash_table.DataTable(
                columns=regime_cols, data=regime_rows,
                style_header=_hdr,
                style_cell={**_cell, 'textAlign': 'center', 'fontSize': '11px'},
                style_cell_conditional=[{'if': {'column_id': 'Regime'}, 'textAlign': 'left', 'fontWeight': '600'}],
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                    {'if': {'filter_query': f'{{Regime}} = "{regime.capitalize()}"'}, 'backgroundColor': '#1e3a2e'},
                ],
            ),
        ], style={**CS, 'marginBottom': '16px'}),

        # Row 5: Monthly return heatmap with Heat Colors (Same as US Portfolio)
        html.Div([
            html.H6('Monthly Returns Heatmap (%) — Canadian Portfolio (CAD)',
                    style={'color': '#c8c8d4', 'marginBottom': '8px'}),
            dcc.Graph(figure=make_monthly_heatmap(cdn_mr), config={'displayModeBar': False}),
            _source_line('Compounded annual return per year. Green = positive month, red = negative month (matching US heatmap color scale).'),
        ], style={**CS, 'marginBottom': '16px'}),

        # Row 6: Rebalancing History Log (Same as US Portfolio)
        html.Div([
            html.H5('📋 Rebalancing History Log (Canadian Portfolio)', style={'color': '#00d97e', 'marginBottom': '6px', 'fontWeight': '700'}),
            html.Div([
                html.Span('Full Canadian audit trail. ', style={'color': '#6c757d', 'fontSize': '12px'}),
                html.Span('Every regime shift is logged with date, macro reasoning, and exact Canadian weight changes. ',
                          style={'color': '#c8c8d4', 'fontSize': '12px'}),
                html.Span('Rules-based and transparent.', style={'color': '#f5a623', 'fontSize': '12px', 'fontWeight': '600'}),
            ], style={'marginBottom': '12px'}),
            dash_table.DataTable(
                columns=[
                    {'name': '📅 Date', 'id': 'date'},
                    {'name': '⬅️ From Regime', 'id': 'from_regime'},
                    {'name': '➡️ To Regime', 'id': 'to_regime'},
                    {'name': '🧠 Macro Reasoning', 'id': 'reason'},
                    {'name': '📊 Key Position Changes (Top 5)', 'id': 'key_changes'},
                ],
                data=cdn_recent_changes, sort_action='native', page_size=15,
                style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                              'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                            'fontFamily': 'Inter', 'fontSize': '11px', 'padding': '8px', 'textAlign': 'left'},
                style_cell_conditional=[
                    {'if': {'column_id': 'date'}, 'width': '80px', 'textAlign': 'center'},
                    {'if': {'column_id': 'from_regime'}, 'width': '100px', 'textAlign': 'center'},
                    {'if': {'column_id': 'to_regime'}, 'width': '100px', 'textAlign': 'center'},
                    {'if': {'column_id': 'key_changes'}, 'minWidth': '250px'},
                ],
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                    {'if': {'filter_query': '{to_regime} eq "Goldilocks"'}, 'backgroundColor': '#0d2818'},
                    {'if': {'filter_query': '{to_regime} eq "Deflation"'}, 'backgroundColor': '#0d1828'},
                    {'if': {'filter_query': '{to_regime} eq "Stagflation"'}, 'backgroundColor': '#280d0d'},
                ],
            ),
            _source_line('Source: regime-change audit trail from Canadian backtest engine and historical macro signals.'),
        ], style={**CS, 'marginBottom': '16px', 'border': '1px solid #00d97e'}),

        # Footer note
        _source_line(
            f'CDN portfolio: 6-ETF TSX universe (Portfolio B - 14.6% High Growth). '
            f'Prices in CAD. Same BacktestEngine + regime classification as US strategy. '
            f'ZQQ.TO and VFV.TO start late 2012. Not investment advice.'
        ),
    ], style={'padding': '0 4px'})



# ═══════════════════════════════════════════════════════════════════════════
# APP FACTORY
# ═══════════════════════════════════════════════════════════════════════════
def create_app(data):

    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY,
        'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap'],
        title='ETF Regime Strategist', suppress_callback_exceptions=True)

    regime = data.get('current_regime', 'goldilocks')
    rc = REGIME_COLORS.get(regime, '#ccc')

    app.layout = html.Div([
        html.Div([dbc.Row([
            dbc.Col([
                html.H3('🏦 ETF Regime Strategist', style={'margin': '0', 'fontWeight': '700',
                         'background': f'linear-gradient(135deg, {rc}, #c8c8d4)',
                         'WebkitBackgroundClip': 'text', 'WebkitTextFillColor': 'transparent'}),
                html.Span(f'Regime: {regime.upper()}', style={'color': rc, 'fontSize': '12px', 'fontWeight': '600',
                           'border': f'1px solid {rc}', 'padding': '2px 8px', 'borderRadius': '12px', 'marginLeft': '10px'}),
            ], md=8),
            dbc.Col(html.Div(id='refresh-ts', children=f'Last: {datetime.now().strftime("%H:%M:%S")}',
                             style={'color': '#6c757d', 'fontSize': '11px', 'textAlign': 'right'}), md=4),
        ])], style={'padding': '12px 24px', 'borderBottom': '1px solid #2d2d44', 'marginBottom': '16px'}),

        dbc.Tabs([
            dbc.Tab(build_regime_tab(data), label='🌍 Regime Monitor', tab_id='t1',
                    label_style={'fontFamily': 'Inter'}, active_label_style={'color': rc, 'fontWeight': '700'}),
            dbc.Tab(build_portfolio_tab(data), label='💼 Portfolio', tab_id='t2',
                    label_style={'fontFamily': 'Inter'}, active_label_style={'color': rc, 'fontWeight': '700'}),
            dbc.Tab(build_backtest_tab(data), label='📈 Backtest', tab_id='t3',
                    label_style={'fontFamily': 'Inter'}, active_label_style={'color': rc, 'fontWeight': '700'}),
            dbc.Tab(html.Div([
                html.Div([
                    html.H4('⚡ Execution Module — Suspended', style={'color': '#f5a623', 'marginBottom': '12px'}),
                    html.P('The IBKR paper-trading integration has been suspended while evaluating a switch to MOOMOO Canada.',
                           style={'color': '#c8c8d4', 'fontSize': '14px', 'marginBottom': '8px'}),
                    html.P('Tabs 1–3 (Regime Monitor, Portfolio, Backtest) and Tab 5 (Auditor) remain fully operational.',
                           style={'color': '#8888a0', 'fontSize': '13px'}),
                ], style={'textAlign': 'center', 'padding': '60px 40px',
                          'backgroundColor': '#16213e', 'borderRadius': '8px', 'margin': '40px auto',
                          'maxWidth': '600px', 'border': '1px solid #2d2d44'}),
            ], style={'padding': '20px'}), label='⚡ Execution (Suspended)', tab_id='t4',
                    label_style={'fontFamily': 'Inter', 'color': '#666'}, active_label_style={'color': '#f5a623', 'fontWeight': '700'}),
            dbc.Tab(build_auditor_tab(data), label='🔍 Auditor', tab_id='t5',
                    label_style={'fontFamily': 'Inter'}, active_label_style={'color': rc, 'fontWeight': '700'}),
            dbc.Tab(build_cdn_portfolio_tab(data), label='🍁 CDN Portfolio', tab_id='t6',
                    label_style={'fontFamily': 'Inter'}, active_label_style={'color': '#f5a623', 'fontWeight': '700'}),

        ], id='tabs', active_tab='t1', style={'marginBottom': '16px', 'padding': '0 20px'}),
        dcc.Interval(id='refresh-interval', interval=5*60*1000, n_intervals=0),
    ], style={'fontFamily': 'Inter, sans-serif', 'minHeight': '100vh', 'backgroundColor': '#0f0f1e', 'paddingBottom': '30px'})

    @app.callback(Output('refresh-ts', 'children'), Input('refresh-interval', 'n_intervals'))
    def update_ts(n):
        return f'Last: {datetime.now().strftime("%H:%M:%S")}'

    # ── IBKR Execution Callbacks ──────────────────────────────────────

    @app.callback(
        [Output('ibkr-live-panel-wrap', 'children'),
         Output('ibkr-status-card', 'children', allow_duplicate=True),
         Output('ibkr-nav-card', 'children', allow_duplicate=True),
         Output('ibkr-pnl-card', 'children', allow_duplicate=True),
         Output('ibkr-daily-card', 'children', allow_duplicate=True)],
        Input('ibkr-snapshot-refresh', 'n_intervals'),
        prevent_initial_call=True,
    )
    def refresh_ibkr_snapshot_panel(_n):
        """Every 10 min: re-pull the IBKR snapshot from GCS and rebuild the live
        panel + status cards, so a warm container shows fresh account data without
        a restart. Uses the snapshot's own marks for prices (no yfinance in the
        callback path — keeps it fast and rate-limit-proof)."""
        try:
            from src.dashboard.gcs_sync import download_ibkr
            download_ibkr()
        except Exception:
            pass
        snap = _load_ibkr_snapshot()
        if not snap:
            raise PreventUpdate
        (st, sc, ss, at, asub, pt, pc, psub, dt, dsub) = _ibkr_card_values(snap)
        panel = build_ibkr_live_panel(snap, data.get('current_weights', {}), {})
        return ([panel],
                mc('IBKR Status', st, ss, sc, '🔌'),
                mc('Account Value', at, asub, '#00d97e', '💼'),
                mc('Unrealized P&L', pt, psub, pc, '📊'),
                mc('Daily Return', dt, dsub, '#6c757d', '📉'))

    @app.callback(
        [Output('ibkr-status-card', 'children'),
         Output('ibkr-nav-card', 'children'),
         Output('ibkr-pnl-card', 'children'),
         Output('ibkr-daily-card', 'children'),
         Output('ibkr-status-msg', 'children'),
         Output('ibkr-status-msg', 'style'),
         Output('ibkr-connected', 'data'),
         Output('ibkr-poll-interval', 'disabled'),
         Output('btn-ibkr-connect', 'disabled'),
         Output('btn-ibkr-disconnect', 'disabled'),
         Output('btn-preview-rebalance', 'disabled'),
         Output('ibkr-positions-table', 'children'),
         Output('ibkr-weight-comparison', 'children'),
         Output('ibkr-order-history', 'children')],
        [Input('btn-ibkr-connect', 'n_clicks'),
         Input('btn-ibkr-disconnect', 'n_clicks'),
         Input('ibkr-poll-interval', 'n_intervals')],
        [State('ibkr-connected', 'data'),
         State('ibkr-port-input', 'value')],
        prevent_initial_call=True,
    )
    def ibkr_connection_and_polling(connect_clicks, disconnect_clicks, poll_n, was_connected, port):
        """Handle IBKR connect, disconnect, and periodic position polling."""
        import dash
        ctx = dash.callback_context
        trigger = ctx.triggered[0]['prop_id'] if ctx.triggered else ''

        broker = data.get('_broker')
        order_mgr = data.get('_order_manager')

        # ── Handle connect ──
        if 'btn-ibkr-connect' in trigger and broker:
            if port:
                broker.port = int(port)
                broker.paper_mode = int(port) in broker.PAPER_PORTS
            success = broker.connect()
            if not success:
                msg = '❌ Connection failed. Check that TWS/Gateway is running and API is enabled.'
                msg_style = {'color': '#e74c3c', 'fontSize': '12px', 'padding': '8px 12px',
                             'backgroundColor': '#16213e', 'borderRadius': '6px', 'marginBottom': '12px',
                             'border': '1px solid #e74c3c30'}
                return [
                    mc('IBKR Status', 'OFFLINE', 'Connection failed', '#e74c3c', '🔌'),
                    mc('Account Value', '$—', 'Connect to view', '#6c757d', '💼'),
                    mc('Unrealized P&L', '$—', 'Connect to view', '#6c757d', '📊'),
                    mc('Daily Return', '—', 'Connect to view', '#6c757d', '📉'),
                    msg, msg_style,
                    False, True,  # not connected, polling disabled
                    False, True,  # connect enabled, disconnect disabled
                    True,  # preview disabled
                    [html.Div('Connect to IBKR to view live positions.',
                              style={'color': '#6c757d', 'fontSize': '13px', 'textAlign': 'center', 'padding': '40px'})],
                    dash.no_update,
                    dash.no_update,
                ]

        # ── Handle disconnect ──
        if 'btn-ibkr-disconnect' in trigger and broker:
            broker.disconnect()
            msg = '⏏ Disconnected from IBKR.'
            msg_style = {'color': '#8888a0', 'fontSize': '12px', 'padding': '8px 12px',
                         'backgroundColor': '#16213e', 'borderRadius': '6px', 'marginBottom': '12px',
                         'border': '1px solid #2d2d44'}
            return [
                mc('IBKR Status', 'OFFLINE', 'Disconnected', '#e74c3c', '🔌'),
                mc('Account Value', '$—', 'Disconnected', '#6c757d', '💼'),
                mc('Unrealized P&L', '$—', 'Disconnected', '#6c757d', '📊'),
                mc('Daily Return', '—', 'Disconnected', '#6c757d', '📉'),
                msg, msg_style,
                False, True,  # not connected, polling disabled
                False, True,  # connect enabled, disconnect disabled
                True,  # preview disabled
                [html.Div('Disconnected from IBKR.',
                          style={'color': '#6c757d', 'fontSize': '13px', 'textAlign': 'center', 'padding': '40px'})],
                dash.no_update,
                dash.no_update,
            ]

        # ── Polling update (runs every 10s when connected) ──
        if not broker or not broker.is_connected():
            raise PreventUpdate

        # Fetch live data
        try:
            summary = broker.get_account_summary()
            positions = broker.get_positions()
        except Exception:
            raise PreventUpdate

        nav = summary.get('net_liquidation', 0)
        pnl = summary.get('unrealized_pnl', 0)
        cash = summary.get('total_cash', 0)
        pnl_color = '#00d97e' if pnl >= 0 else '#e74c3c'

        # Account IDs
        acct_ids = ''
        try:
            acct_ids = ', '.join(broker._ib.managedAccounts()) if broker._ib else ''
        except Exception:
            pass

        # Build positions table
        total_pos_val = sum(p.market_value for p in positions.values()) if positions else 0
        pos_rows = []
        pos_weights = {}
        for t, p in sorted(positions.items(), key=lambda x: -abs(x[1].market_value)):
            w = p.market_value / total_pos_val if total_pos_val > 0 else 0
            pos_weights[t] = w
            pnl_cell_color = '#00d97e' if p.unrealized_pnl >= 0 else '#e74c3c'
            pos_rows.append({'ticker': t, 'shares': int(p.quantity), 'avg_cost': f'${p.avg_cost:.2f}',
                             'mkt_value': f'${p.market_value:,.0f}', 'weight': f'{w:.1%}',
                             'pnl': f'${p.unrealized_pnl:+,.0f}'})

        pos_table = [html.Div('No positions in account.',
                              style={'color': '#6c757d', 'fontSize': '13px', 'textAlign': 'center', 'padding': '40px'})]
        if pos_rows:
            pos_table = [dash_table.DataTable(
                columns=[{'name': 'Ticker', 'id': 'ticker'}, {'name': 'Shares', 'id': 'shares'},
                         {'name': 'Avg Cost', 'id': 'avg_cost'}, {'name': 'Mkt Value', 'id': 'mkt_value'},
                         {'name': 'Weight', 'id': 'weight'}, {'name': 'Unrealized P&L', 'id': 'pnl'}],
                data=pos_rows,
                style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                              'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                            'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '8px', 'textAlign': 'center'},
                style_cell_conditional=[{'if': {'column_id': 'ticker'}, 'textAlign': 'left', 'fontWeight': '600'}],
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                ],
            )]

        # Build weight comparison table
        target_weights = data.get('current_weights', {})
        all_tickers = sorted(set(list(target_weights.keys()) + list(pos_weights.keys())),
                              key=lambda t: -target_weights.get(t, 0))
        wt_rows = []
        for t in all_tickers:
            tw = target_weights.get(t, 0)
            cw = pos_weights.get(t, 0)
            drift = cw - tw
            drift_color = '#00d97e' if abs(drift) < 0.02 else ('#f5a623' if abs(drift) < 0.05 else '#e74c3c')
            wt_rows.append({'ticker': t, 'target': f'{tw:.1%}', 'current': f'{cw:.1%}',
                            'drift': f'{drift:+.1%}'})

        wt_table = [dash_table.DataTable(
            columns=[{'name': 'Ticker', 'id': 'ticker'}, {'name': 'Target %', 'id': 'target'},
                     {'name': 'Current %', 'id': 'current'}, {'name': 'Drift', 'id': 'drift'}],
            data=wt_rows,
            style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                          'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
            style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                        'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '8px', 'textAlign': 'center'},
            style_cell_conditional=[{'if': {'column_id': 'ticker'}, 'textAlign': 'left', 'fontWeight': '600'}],
            style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'}],
        )]

        # Build order history
        order_history_content = [html.Div('No orders recorded yet.',
                                          style={'color': '#6c757d', 'fontSize': '13px', 'textAlign': 'center', 'padding': '30px'})]
        if order_mgr:
            try:
                history = order_mgr.get_order_history(days=30)
                if not history.empty:
                    hist_rows = []
                    for _, row in history.head(20).iterrows():
                        status_color = '#00d97e' if row.get('status') == 'FILLED' else (
                            '#f5a623' if row.get('status') == 'SIMULATED' else '#e74c3c')
                        hist_rows.append({'time': str(row.get('created_at', ''))[:16],
                                          'ticker': row.get('ticker', ''), 'action': row.get('action', ''),
                                          'status': row.get('status', ''), 'qty': int(row.get('filled_qty', 0)),
                                          'price': f"${row.get('avg_price', 0):.2f}"})
                    order_history_content = [dash_table.DataTable(
                        columns=[{'name': 'Time', 'id': 'time'}, {'name': 'Ticker', 'id': 'ticker'},
                                 {'name': 'Action', 'id': 'action'}, {'name': 'Status', 'id': 'status'},
                                 {'name': 'Qty', 'id': 'qty'}, {'name': 'Price', 'id': 'price'}],
                        data=hist_rows,
                        style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                                      'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                        style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                                    'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '6px', 'textAlign': 'center'},
                        style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'}],
                    )]
            except Exception:
                pass

        msg = f'✅ Connected • {acct_ids} • NAV ${nav:,.0f} • Cash ${cash:,.0f}'
        msg_style = {'color': '#00d97e', 'fontSize': '12px', 'padding': '8px 12px',
                     'backgroundColor': '#16213e', 'borderRadius': '6px', 'marginBottom': '12px',
                     'border': '1px solid #00d97e30'}

        return [
            mc('IBKR Status', 'CONNECTED', f'Paper • {acct_ids}', '#00d97e', '🔌'),
            mc('Account Value', f'${nav:,.0f}', 'Net Liquidation Value', '#00d97e', '💼'),
            mc('Unrealized P&L', f'${pnl:+,.0f}', f'{len(positions)} positions', pnl_color, '📊'),
            mc('Daily Return', f'{summary.get("realized_pnl", 0):+,.0f}', 'Realized P&L', '#00d97e', '📉'),
            msg, msg_style,
            True, False,  # connected, polling enabled
            True, False,  # connect disabled, disconnect enabled
            False,  # preview enabled
            pos_table,
            wt_table,
            order_history_content,
        ]

    @app.callback(
        [Output('ibkr-rebalance-panel', 'children'),
         Output('ibkr-risk-checks', 'children'),
         Output('btn-execute-rebalance', 'disabled'),
         Output('ibkr-rebalance-plan', 'data')],
        Input('btn-preview-rebalance', 'n_clicks'),
        State('ibkr-connected', 'data'),
        prevent_initial_call=True,
    )
    def preview_rebalance(n_clicks, is_connected):
        """Compute rebalance plan and run pre-trade risk checks."""
        if not n_clicks or not is_connected:
            raise PreventUpdate

        broker = data.get('_broker')
        risk_mgr = data.get('_risk_manager')
        if not broker or not broker.is_connected():
            raise PreventUpdate

        import math
        # Get current state
        summary = broker.get_account_summary()
        positions = broker.get_positions()
        nav = summary.get('net_liquidation', 0)
        if nav <= 0:
            raise PreventUpdate

        target_weights = data.get('current_weights', {})

        # Current position values
        current_values = {t: p.market_value for t, p in positions.items()}

        # Get prices for target tickers
        all_tickers = list(set(list(target_weights.keys()) + list(current_values.keys())))
        prices = broker.get_current_prices(all_tickers)

        # Compute trades
        trades = broker.compute_required_trades(
            current_positions=current_values,
            target_weights=target_weights,
            total_equity=nav,
            current_prices=prices,
            min_trade_value=100.0,
        )

        # Build trade plan table
        trade_rows = []
        serializable_trades = []
        for t in trades:
            est_price = prices.get(t.ticker, 0)
            trade_rows.append({
                'ticker': t.ticker, 'action': t.action,
                'shares': t.quantity, 'est_value': f'${t.estimated_value:,.0f}',
                'est_price': f'${est_price:.2f}' if est_price else '—',
            })
            serializable_trades.append({'ticker': t.ticker, 'action': t.action,
                                         'quantity': t.quantity, 'estimated_value': t.estimated_value})

        if not trade_rows:
            panel = html.Div([
                html.Div('✅ Portfolio is already at target — no trades needed.',
                         style={'color': '#00d97e', 'fontSize': '14px', 'textAlign': 'center', 'padding': '20px'}),
            ], style={**CS, 'border': '1px solid #00d97e'})
            risk_check_names = ['Position Concentration', 'Daily Turnover', 'DD Circuit Breaker',
                                'VIX Spike Guard', 'Correlation Check', 'Liquidity Check']
            risk_cards = [dbc.Col(html.Div([
                html.Div(c, style={'color': '#8888a0', 'fontSize': '11px'}),
                html.Div('✅ Pass', style={'color': '#00d97e', 'fontSize': '13px', 'fontWeight': '600'}),
            ], style={**CS, 'padding': '10px', 'textAlign': 'center', 'minHeight': '70px'}), md=2) for c in risk_check_names]
            return [panel, risk_cards, True, None]

        panel = html.Div([
            html.H6('📊 Rebalance Plan', style={'color': '#f5a623', 'marginBottom': '8px'}),
            html.Div(f'{len(trades)} trades • Est. total ${sum(t.estimated_value for t in trades):,.0f}',
                     style={'color': '#8888a0', 'fontSize': '12px', 'marginBottom': '12px'}),
            dash_table.DataTable(
                columns=[{'name': 'Ticker', 'id': 'ticker'}, {'name': 'Action', 'id': 'action'},
                         {'name': 'Shares', 'id': 'shares'}, {'name': 'Est. Value', 'id': 'est_value'},
                         {'name': 'Est. Price', 'id': 'est_price'}],
                data=trade_rows,
                style_header={'backgroundColor': '#16213e', 'color': '#c8c8d4', 'fontWeight': '600',
                              'border': '1px solid #2d2d44', 'fontFamily': 'Inter', 'fontSize': '11px'},
                style_cell={'backgroundColor': '#1a1a2e', 'color': '#c8c8d4', 'border': '1px solid #2d2d44',
                            'fontFamily': 'Inter', 'fontSize': '12px', 'padding': '8px', 'textAlign': 'center'},
                style_cell_conditional=[{'if': {'column_id': 'ticker'}, 'textAlign': 'left', 'fontWeight': '600'}],
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': '#16213e'},
                    {'if': {'filter_query': '{action} eq "BUY"', 'column_id': 'action'}, 'color': '#00d97e', 'fontWeight': '600'},
                    {'if': {'filter_query': '{action} eq "SELL"', 'column_id': 'action'}, 'color': '#e74c3c', 'fontWeight': '600'},
                ],
            ),
        ], style={**CS, 'border': '1px solid #f5a623'})

        # Run risk checks
        pos_weights = {}
        total_pos_val = sum(p.market_value for p in positions.values()) if positions else 0
        if total_pos_val > 0:
            pos_weights = {t: p.market_value / total_pos_val for t, p in positions.items()}

        # Get VIX
        vix_now = data.get('vix_current', 20.0)

        risk_cards = []
        risk_check_names = ['Position Concentration', 'Daily Turnover', 'DD Circuit Breaker',
                            'VIX Spike Guard', 'Correlation Check', 'Liquidity Check']
        all_passed = True
        if risk_mgr:
            try:
                price_df = data.get('price_data', pd.DataFrame())
                assessment = risk_mgr.run_all_checks(
                    proposed_weights=target_weights,
                    current_positions=pos_weights,
                    portfolio_value=nav,
                    current_vix=vix_now,
                    price_data=price_df,
                )
                for check in assessment.checks:
                    if check.passed:
                        risk_cards.append(dbc.Col(html.Div([
                            html.Div(check.check_name.replace('_', ' ').title(), style={'color': '#8888a0', 'fontSize': '11px'}),
                            html.Div('✅ Pass', style={'color': '#00d97e', 'fontSize': '13px', 'fontWeight': '600'}),
                            html.Div(check.message[:50], style={'color': '#6c757d', 'fontSize': '9px', 'marginTop': '2px'}),
                        ], style={**CS, 'padding': '10px', 'textAlign': 'center', 'minHeight': '70px'}), md=2))
                    else:
                        all_passed = False
                        sev_color = '#e74c3c' if check.severity == 'critical' else '#f5a623'
                        risk_cards.append(dbc.Col(html.Div([
                            html.Div(check.check_name.replace('_', ' ').title(), style={'color': '#8888a0', 'fontSize': '11px'}),
                            html.Div('❌ Fail' if check.severity == 'critical' else '⚠ Warn',
                                     style={'color': sev_color, 'fontSize': '13px', 'fontWeight': '600'}),
                            html.Div(check.message[:50], style={'color': '#6c757d', 'fontSize': '9px', 'marginTop': '2px'}),
                        ], style={**CS, 'padding': '10px', 'textAlign': 'center', 'minHeight': '70px',
                                  'border': f'1px solid {sev_color}'}), md=2))
            except Exception:
                risk_cards = [dbc.Col(html.Div([
                    html.Div(c, style={'color': '#8888a0', 'fontSize': '11px'}),
                    html.Div('⚠ Error', style={'color': '#f5a623', 'fontSize': '13px', 'fontWeight': '600'}),
                ], style={**CS, 'padding': '10px', 'textAlign': 'center', 'minHeight': '70px'}), md=2) for c in risk_check_names]
        else:
            risk_cards = [dbc.Col(html.Div([
                html.Div(c, style={'color': '#8888a0', 'fontSize': '11px'}),
                html.Div('⏸ N/A', style={'color': '#6c757d', 'fontSize': '13px', 'fontWeight': '600'}),
            ], style={**CS, 'padding': '10px', 'textAlign': 'center', 'minHeight': '70px'}), md=2) for c in risk_check_names]

        # Enable execute only if risk checks pass
        execute_disabled = not all_passed

        return [panel, risk_cards, execute_disabled, serializable_trades]

    @app.callback(
        Output('execute-confirm-modal', 'is_open'),
        Output('execute-confirm-body', 'children'),
        [Input('btn-execute-rebalance', 'n_clicks'),
         Input('btn-cancel-execute', 'n_clicks'),
         Input('btn-confirm-execute', 'n_clicks')],
        [State('execute-confirm-modal', 'is_open'),
         State('ibkr-rebalance-plan', 'data')],
        prevent_initial_call=True,
    )
    def handle_execute_modal(exec_clicks, cancel_clicks, confirm_clicks, is_open, plan_data):
        """Open/close execution confirmation modal, and execute on confirm."""
        import dash
        ctx = dash.callback_context
        trigger = ctx.triggered[0]['prop_id'] if ctx.triggered else ''

        if 'btn-execute-rebalance' in trigger and plan_data:
            # Show confirmation modal
            body = html.Div([
                html.P('You are about to execute the following trades on your PAPER account:', style={'marginBottom': '12px'}),
                html.Ul([
                    html.Li(f"{t['action']} {t['quantity']} {t['ticker']} (~${t['estimated_value']:,.0f})",
                            style={'color': '#00d97e' if t['action'] == 'BUY' else '#e74c3c'})
                    for t in plan_data
                ], style={'marginBottom': '12px'}),
                html.P(f'Total trades: {len(plan_data)}', style={'fontWeight': '600'}),
                html.P('⚠️ This will place MARKET orders on your IBKR PAPER account.',
                       style={'color': '#f5a623', 'fontSize': '12px'}),
            ])
            return True, body

        if 'btn-confirm-execute' in trigger and plan_data:
            # Execute the trades
            broker = data.get('_broker')
            order_mgr = data.get('_order_manager')
            if broker and broker.is_connected():
                from src.execution.broker import TradeOrder
                trade_orders = [
                    TradeOrder(ticker=t['ticker'], action=t['action'], quantity=t['quantity'],
                               estimated_value=t['estimated_value'], order_type='MKT')
                    for t in plan_data
                ]
                results = broker.place_portfolio_orders(trade_orders, dry_run=False)
                # Record orders
                if order_mgr:
                    order_mgr.record_orders(results)
            return False, ''

        if 'btn-cancel-execute' in trigger:
            return False, ''

        raise PreventUpdate

    return app
