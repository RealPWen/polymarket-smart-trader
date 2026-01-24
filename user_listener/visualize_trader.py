"""
Polymarket Trader Professional Dashboard Generator
支持单交易员或多交易员对比分析。
"""

import sys
import os
import pandas as pd
import json
import plotly.graph_objects as go
from trader_analyzer import TraderAnalyzer

class TraderVisualizer:
    def __init__(self):
        self.analyzer = TraderAnalyzer()

    def analyze_and_get_html(self, address_input: str, limit: int = 50000):
        # 支持逗号分隔的多地址分析
        addresses = [a.strip() for a in address_input.split(',') if a.strip()]
        
        if len(addresses) == 1:
            addr = addresses[0]
            print(f"📊 正在深度分析交易员: {addr} ...")
            analysis_df, trades_df, active_df = self.analyzer.analyze_trader(addr, limit)
            return self.get_professional_report_html([addr], {addr: (analysis_df, trades_df, active_df)})
        else:
            print(f"📊 正在并行分析 {len(addresses)} 个交易员 ...")
            data_map = {}
            for addr in addresses:
                data_map[addr] = self.analyzer.analyze_trader(addr, limit)
            return self.get_professional_report_html(addresses, data_map)

    def get_professional_report_html(self, addresses, data_map):
        """生成支持多交易员对比的 HTML 报告"""
        
        # 1. 准备聚合 PnL 图表
        fig_pnl = go.Figure()
        colors = ['#2962ff', '#00c853', '#ff3d00', '#ff9100', '#9c27b0']
        
        all_traders_html = ""
        
        for i, addr in enumerate(addresses):
            analysis_df, trades_df, active_df = data_map[addr]
            color = colors[i % len(colors)]
            
            # 添加到聚合图表
            if not analysis_df.empty:
                fig_pnl.add_trace(go.Scatter(
                    x=analysis_df['date'], y=analysis_df['cumulative_pnl'],
                    mode='lines',
                    line=dict(color=color, width=2),
                    name=f"Trader {addr[:8]}..."
                ))

            # 准备每个人的 JSON 数据用于前端渲染交互
            top_wins = []
            top_losses = []
            if not analysis_df.empty:
                df_serialized = analysis_df.copy()
                if 'date' in df_serialized.columns:
                    df_serialized['date'] = df_serialized['date'].dt.strftime('%Y-%m-%d %H:%M')
                df_wins = df_serialized[df_serialized['pnl'] > 0].sort_values('pnl', ascending=False)
                df_losses = df_serialized[df_serialized['pnl'] < 0].sort_values('pnl', ascending=True)
                top_wins = df_wins.head(10).to_dict('records')
                top_losses = df_losses.head(10).to_dict('records')

            active_list = active_df.to_dict('records') if not active_df.empty else []
            
            # 序列化辅助
            def json_serial(obj):
                import pandas as pd
                if isinstance(obj, (pd.Timestamp, pd.DatetimeIndex)):
                    return obj.strftime('%Y-%m-%d %H:%M')
                raise TypeError ("Type %s not serializable" % type(obj))

            top_wins_json = json.dumps(top_wins, default=json_serial)
            top_losses_json = json.dumps(top_losses, default=json_serial)
            active_list_json = json.dumps(active_list, default=json_serial)

            # 为每个交易员构建独立的 UI 区块
            all_traders_html += f"""
            <div class="trader-section" id="section-{addr}">
                <div class="section-title">📊 Detail Analysis: {addr}</div>
                
                <div class="bottom-row">
                    <div class="pro-card">
                        <div class="card-header-dark">
                            <span>Current Positions</span>
                        </div>
                        <div class="tab-bar">
                            <div class="tab active" onclick="switchTab('{addr}', 'pos', 'value', this)">$ Current Value</div>
                            <div class="tab" onclick="switchTab('{addr}', 'pos', 'shares', this)">📈 Current Shares</div>
                        </div>
                        <div id="pos-content-{addr}" class="content-area">
                            {self._render_positions_html(active_list)}
                        </div>
                    </div>

                    <div class="pro-card">
                        <div class="card-header-dark">
                            <span>Performance</span>
                        </div>
                        <div class="tab-bar">
                            <div class="tab active" onclick="switchTab('{addr}', 'perf', 'wins', this)">📈 Biggest Wins</div>
                            <div class="tab" onclick="switchTab('{addr}', 'perf', 'losses', this)">📉 Biggest Losses</div>
                        </div>
                        <div id="perf-content-{addr}" class="content-area">
                            {self._render_performance_html(top_wins, 'win')}
                        </div>
                    </div>

                    <div class="trade-log-card pro-card">
                        <div class="card-header-dark">
                            <span>Order History</span>
                            <div class="card-subtitle">Execution log</div>
                        </div>
                        <div class="log-container">
                            {self._render_trades_html(trades_df.to_dict('records') if not trades_df.empty else [])}
                        </div>
                    </div>
                </div>
                
                <script>
                    window['data_{addr}'] = {{
                        topWins: {top_wins_json},
                        topLosses: {top_losses_json},
                        activePositions: {active_list_json}
                    }};
                </script>
            </div>
            """

        # 整理聚合图表布局
        fig_pnl.update_layout(
            title="Comparative Equity Curves (PnL Over Time)",
            margin=dict(l=10, r=10, t=40, b=10),
            hovermode='x unified',
            template='plotly_white',
            height=450,
            xaxis=dict(rangeslider=dict(visible=True, thickness=0.08), type='date'),
            yaxis=dict(tickprefix='$', gridcolor='#f0f0f0')
        )
        chart_div = fig_pnl.to_html(full_html=False, include_plotlyjs='cdn')

        # 最终 HTML 模板
        html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Trader Analysis Comparison Report</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #f1f5f9;
            --card-bg: #ffffff;
            --text-main: #0f172a;
            --text-sub: #64748b;
            --border-color: #e2e8f0;
            --win-color: #10b981;
            --loss-color: #ef4444;
            --accent-blue: #3b82f6;
        }}
        body {{ font-family: 'Inter', sans-serif; background: var(--bg-color); color: var(--text-main); margin: 0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header-bar {{ margin-bottom: 24px; }}
        .main-chart-card {{ 
            background: #fff; 
            border-radius: 16px; 
            border: 1px solid var(--border-color); 
            padding: 20px; 
            box-shadow: 0 4px 12px rgba(0,0,0,0.05); 
            margin-bottom: 30px;
            position: relative;
        }}
        
        .monitor-btn {{
            position: absolute;
            top: 20px;
            right: 20px;
            background: var(--accent-blue);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            z-index: 100;
            transition: all 0.2s;
            box-shadow: 0 4px 6px rgba(59, 130, 246, 0.2);
        }}
        .monitor-btn:hover {{
            background: #2563eb;
            transform: translateY(-1px);
        }}

        .trader-section {{ margin-top: 50px; border-top: 2px dashed #cbd5e1; padding-top: 30px; }}
        .section-title {{ font-size: 20px; font-weight: 700; margin-bottom: 20px; color: var(--accent-blue); }}
        
        .top-row {{ display: none; }}
        .chart-card {{ background: var(--card-bg); border-radius: 12px; border: 1px solid var(--border-color); height: 100%; }}
        .trade-log-card {{ background: var(--card-bg); border-radius: 12px; border: 1px solid var(--border-color); display: flex; flex-direction: column; height: 100%; overflow: hidden; }}
        .card-header-dark {{ background: #1e293b; color: white; padding: 12px 20px; font-weight: 600; }}
        .card-subtitle {{ font-size: 11px; opacity: 0.7; font-weight: 400; }}
        .log-container {{ flex: 1; overflow-y: auto; padding: 10px; }}
        .log-row {{ display: flex; justify-content: space-between; padding: 6px 10px; border-bottom: 1px solid #f1f5f9; font-size: 11px; }}
        .side-buy {{ color: var(--win-color); font-weight: 700; }}
        .side-sell {{ color: var(--loss-color); font-weight: 700; }}
        
        .bottom-row {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }}
        .pro-card {{ background: var(--card-bg); border-radius: 12px; border: 1px solid var(--border-color); height: 400px; display: flex; flex-direction: column; overflow: hidden; }}
        .tab-bar {{ display: flex; border-bottom: 1px solid var(--border-color); }}
        .tab {{ flex: 1; padding: 10px; text-align: center; font-size: 12px; cursor: pointer; color: var(--text-sub); border-bottom: 2px solid transparent; }}
        .tab.active {{ color: var(--text-main); border-bottom: 2px solid var(--accent-blue); font-weight: 600; }}
        .content-area {{ padding: 15px; flex: 1; overflow-y: auto; }}
        
        .data-row {{ display: flex; align-items: center; padding: 10px 0; border-bottom: 1px solid #f8fafc; }}
        .rank-num {{ width: 25px; color: #94a3b8; font-size: 11px; }}
        .market-icon {{ margin-right: 10px; }}
        .market-info {{ flex: 1; }}
        .market-title {{ font-size: 13px; font-weight: 500; color: var(--accent-blue); text-decoration: none; display: block; }}
        .progress-container {{ height: 3px; background: #f1f5f9; border-radius: 2px; width: 100%; margin-top: 4px; }}
        .progress-bar-win {{ height: 100%; background: var(--win-color); border-radius: 2px; }}
        .progress-bar-loss {{ height: 100%; background: var(--loss-color); border-radius: 2px; }}
        .pnl-val {{ width: 100px; text-align: right; font-weight: 600; font-size: 13px; }}
        .empty-state {{ text-align: center; padding: 40px; color: #94a3b8; font-size: 13px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header-bar">
            <h1 style="margin: 0; font-size: 28px;">Multi-Trader Comparison Report</h1>
            <p style="color: var(--text-sub); margin-top: 5px;">Analyzing {len(addresses)} traders performance side-by-side.</p>
        </div>

        <div class="main-chart-card">
            <button class="monitor-btn" onclick="startMonitor()">🚀 Start Live Monitor</button>
            {chart_div}
        </div>

        {all_traders_html}
    </div>

    <script>
        const traderAddresses = {json.dumps(addresses)};

        function startMonitor() {{
            // 聚合所有正在分析的地址进行批量监控启动
            const addrQuery = traderAddresses.join(',');
            window.top.location.href = `/copy-trade/setup?address=${{addrQuery}}`;
        }}

        function formatCurrency(val) {{
            return (val < 0 ? '-' : '+') + '$' + Math.abs(val).toLocaleString(undefined, {{minimumFractionDigits: 2}});
        }}

        function switchTab(addr, type, subtype, el) {{
            const tabs = el.parentElement.querySelectorAll('.tab');
            tabs.forEach(t => t.classList.remove('active'));
            el.classList.add('active');

            const content = document.getElementById(type + '-content-' + addr);
            const dataObj = window['data_' + addr];
            
            if (type === 'perf') {{
                const data = subtype === 'wins' ? dataObj.topWins : dataObj.topLosses;
                renderPerf(content, data, subtype === 'wins' ? 'win' : 'loss');
            }} else {{
                renderPositions(content, dataObj.activePositions, subtype === 'value');
            }}
        }}

        function renderPerf(container, data, mode) {{
            if (!data || data.length === 0) {{
                container.innerHTML = '<div class="empty-state">No performance data</div>';
                return;
            }}
            const maxPnl = Math.max(...data.map(d => Math.abs(d.pnl)));
            let html = '';
            data.forEach((item, index) => {{
                const pct = (Math.abs(item.pnl) / maxPnl) * 100;
                const pnlColor = mode === 'win' ? 'var(--win-color)' : 'var(--loss-color)';
                html += `
                    <div class="data-row">
                        <div class="rank-num">#${{index + 1}}</div>
                        <div class="market-icon">${{mode === 'win' ? '🟢' : '🔴'}}</div>
                        <div class="market-info">
                            <span class="market-title">${{item.market}}</span>
                            <div class="progress-container">
                                <div class="${{mode === 'win' ? 'progress-bar-win' : 'progress-bar-loss'}}" style="width: ${{pct}}%"></div>
                            </div>
                        </div>
                        <div class="pnl-val" style="color: ${{pnlColor}}">${{formatCurrency(item.pnl)}}</div>
                    </div>
                `;
            }});
            container.innerHTML = html;
        }}

        function renderPositions(container, data, isValue) {{
            if (!data || data.length === 0) {{
                container.innerHTML = '<div class="empty-state">No active positions</div>';
                return;
            }}
            const maxVal = Math.max(...data.map(a => Math.abs(isValue ? a.cost : a.size)));
            let html = '';
            data.slice(0, 10).forEach((a, i) => {{
                const val = isValue ? a.cost : a.size;
                const pct = (Math.abs(val) / maxVal) * 100;
                html += `
                    <div class="data-row">
                        <div class="rank-num">#${{i+1}}</div>
                        <div class="market-icon">💼</div>
                        <div class="market-info">
                            <span class="market-title">${{a.market}}</span>
                            <div class="progress-container"><div class="progress-bar-win" style="width: ${{pct}}%; background: var(--accent-blue);"></div></div>
                        </div>
                        <div class="pnl-val">${{isValue ? '$' : ''}}${{val.toLocaleString(undefined, {{minimumFractionDigits: isValue?2:0}})}}</div>
                    </div>
                `;
            }});
            container.innerHTML = html;
        }}
    </script>
</body>
</html>
        """
        return html_template

    def _render_trades_html(self, trades):
        if not trades:
            return '<div class="empty-state">No trade history</div>'
        
        html = ""
        for t in trades[:100]:
            side_cls = "side-buy" if str(t.get('side')).upper() == 'BUY' else "side-sell"
            timestamp = t.get('timestamp')
            date_str = pd.to_datetime(timestamp, unit='s').strftime('%m-%d %H:%M') if timestamp else 'N/A'
            html += f"""
                <div class="log-row">
                    <span style="color:#64748b; width: 80px;">{date_str}</span>
                    <span class="{side_cls}" style="width: 40px;">{str(t.get('side')).upper()}</span>
                    <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-right: 10px;">{t.get('title', 'Market')}</span>
                    <span style="font-weight: 500;">${float(t.get('size', 0)) * float(t.get('price', 0)):,.2f}</span>
                </div>
            """
        return html

    def _render_positions_html(self, active_list):
        if not active_list:
            return '<div class="empty-state">No active positions</div>'
        
        max_cost = max([abs(a.get('cost', 0)) for a in active_list]) if active_list else 1
        html = ""
        for i, a in enumerate(active_list[:8]):
            pct = (abs(a.get('cost', 0)) / max_cost) * 100
            html += f"""
                <div class="data-row">
                    <div class="rank-num">#{i+1}</div>
                    <div class="market-icon">💼</div>
                    <div class="market-info">
                        <span class="market-title">{a.get('market')}</span>
                        <div class="progress-container">
                            <div class="progress-bar-win" style="width: {pct}%; background: var(--accent-blue);"></div>
                        </div>
                    </div>
                    <div class="pnl-val">${a.get('cost', 0):,.2f}</div>
                </div>
            """
        return html

    def _render_performance_html(self, data, mode):
        if not data:
            return '<div class="empty-state">No performance data</div>'
        
        max_pnl = max([abs(d.get('pnl', 0)) for d in data]) if data else 1
        html = ""
        for i, d in enumerate(data[:8]):
            pct = (abs(d.get('pnl', 0)) / max_pnl) * 100
            bar_cls = "progress-bar-win" if mode == 'win' else "progress-bar-loss"
            pnl_color = "var(--win-color)" if mode == 'win' else "var(--loss-color)"
            prefix = "+" if mode == 'win' else ""
            html += f"""
                <div class="data-row">
                    <div class="rank-num">#{i+1}</div>
                    <div class="market-icon">{'🟢' if mode == 'win' else '🔴'}</div>
                    <div class="market-info">
                        <span class="market-title">{d.get('market')}</span>
                        <div class="progress-container">
                            <div class="{bar_cls}" style="width: {pct}%"></div>
                        </div>
                    </div>
                    <div class="pnl-val" style="color: {pnl_color}">{prefix}${abs(d.get('pnl', 0)):,.2f}</div>
                </div>
            """
        return html

    def generate_professional_report(self, address, analysis_df, trades_df, active_df):
        html_content = self.get_professional_report_html([address], {address: (analysis_df, trades_df, active_df)})
        filename = f"report_{address}.html"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        return filename

if __name__ == "__main__":
    if len(sys.argv) > 1:
        address = sys.argv[1]
        visualizer = TraderVisualizer()
        analysis_df, trades_df, active_df = visualizer.analyzer.analyze_trader(address, limit=50000)
        filename = visualizer.generate_professional_report(address, analysis_df, trades_df, active_df)
        print(f"✅ Report generated: {filename}")
