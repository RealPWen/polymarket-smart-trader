"""
Polymarket Trader Professional Dashboard Generator
基于 HTML/CSS/JS 全新构建，提供高度专业的可视化交易报告。
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

    def analyze_and_plot(self, address: str, limit: int = 50000):
        print(f"📊 正在深度分析交易员: {address} ...")
        
        # 1. 使用 Analyzer 获取数据
        analysis_df, trades_df, active_df = self.analyzer.analyze_trader(address, limit)
        
        # 2. 调用独立的 HTML 生成方法
        filename = self.generate_professional_report(address, analysis_df, trades_df, active_df)
        
        print(f"\n✅ 报告已生成: {filename}")
        print("💡 请双击该文件使用浏览器查看。")

    def generate_professional_report(self, address, analysis_df, trades_df, active_df):
        """核心方法：接收数据并生成高度定制化的 HTML 文件"""
        
        # --- 数据预处理 ---
        # 1. 准备 PnL 折线图 (HTML Div)
        fig_pnl = self._create_pnl_chart(analysis_df)
        chart_div = fig_pnl.to_html(full_html=False, include_plotlyjs='cdn')

        # 2. 处理订单流水 (Raw Trades)
        trades_list = []
        if not trades_df.empty:
            temp_trades = trades_df.copy().sort_values('timestamp', ascending=False)
            temp_trades['date_str'] = pd.to_datetime(temp_trades['timestamp'], unit='s').dt.strftime('%m-%d %H:%M')
            trades_list = temp_trades.to_dict('records')

        # 3. 处理当前持仓 (Current Positions)
        active_list = []
        if not active_df.empty:
            active_list = active_df.to_dict('records')

        # 4. 处理盈亏排行榜 (Performance)
        top_wins = []
        top_losses = []
        if not analysis_df.empty:
            # 转换 Timestamp 为字符串以支持 JSON 序列化
            df_serialized = analysis_df.copy()
            if 'date' in df_serialized.columns:
                df_serialized['date'] = df_serialized['date'].dt.strftime('%Y-%m-%d %H:%M')
            
            # 筛选真正盈利 (>0) 和真正亏损 (<0) 的记录
            df_wins = df_serialized[df_serialized['pnl'] > 0].sort_values('pnl', ascending=False)
            df_losses = df_serialized[df_serialized['pnl'] < 0].sort_values('pnl', ascending=True)
            
            top_wins = df_wins.head(10).to_dict('records')
            top_losses = df_losses.head(10).to_dict('records')

        # --- 构建 HTML 模板 ---
        # 使用自定义转换器处理残留的非序列化对象
        def json_serial(obj):
            if isinstance(obj, (pd.Timestamp, pd.DatetimeIndex)):
                return obj.strftime('%Y-%m-%d %H:%M')
            raise TypeError ("Type %s not serializable" % type(obj))

        top_wins_json = json.dumps(top_wins, default=json_serial)
        top_losses_json = json.dumps(top_losses, default=json_serial)
        active_list_json = json.dumps(active_list, default=json_serial)

        html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trader Report - {address}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #f8f9fa;
            --card-bg: #ffffff;
            --text-main: #1a1a1a;
            --text-sub: #666666;
            --border-color: #eeeeee;
            --win-color: #00c853;
            --loss-color: #ff3d00;
            --accent-blue: #2962ff;
        }}
        
        body {{
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }}

        .title {{
            font-size: 24px;
            font-weight: 700;
        }}

        /* 上排：折线图 + 订单流水 */
        .top-row {{
            display: grid;
            grid-template-columns: 1fr 450px;
            gap: 20px;
            margin-bottom: 24px;
            height: 500px;
        }}

        .chart-card {{
            background: var(--card-bg);
            border-radius: 12px;
            border: 1px solid var(--border-color);
            padding: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.02);
            overflow: hidden;
            height: 100%;
            box-sizing: border-box;
        }}

        .trade-log-card {{
            background: var(--card-bg);
            border-radius: 12px;
            border: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            box-shadow: 0 4px 6px rgba(0,0,0,0.02);
            height: 100%;
            box-sizing: border-box;
            overflow: hidden;
        }}

        .card-header-dark {{
            background: #1a1a1a;
            color: white;
            padding: 12px 20px;
            border-radius: 11px 11px 0 0;
            font-size: 16px;
            font-weight: 600;
            flex-shrink: 0;
        }}
        
        .card-subtitle {{
            font-size: 12px;
            color: #999;
            font-weight: 400;
            margin-top: 4px;
        }}

        .log-container {{
            flex: 1;
            overflow-y: auto;
            padding: 0 10px;
        }}

        /* 自定义滚动条样式 */
        .log-container::-webkit-scrollbar {{
            width: 6px;
        }}
        .log-container::-webkit-scrollbar-track {{
            background: #f1f1f1;
        }}
        .log-container::-webkit-scrollbar-thumb {{
            background: #ccc;
            border-radius: 3px;
        }}
        .log-container::-webkit-scrollbar-thumb:hover {{
            background: #999;
        }}

        .log-row {{
            display: flex;
            justify-content: space-between;
            padding: 8px 10px;
            border-bottom: 1px solid #f5f5f5;
            font-size: 12px;
        }}

        .side-buy {{ color: var(--win-color); font-weight: 600; }}
        .side-sell {{ color: var(--loss-color); font-weight: 600; }}

        /* 下排：卡片展示 (完全还原截图) */
        .bottom-row {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}

        .pro-card {{
            background: var(--card-bg);
            border-radius: 12px;
            border: 1px solid var(--border-color);
            min-height: 500px;
            display: flex;
            flex-direction: column;
        }}

        .tab-bar {{
            display: flex;
            background: #fff;
            border-bottom: 1px solid var(--border-color);
        }}

        .tab {{
            flex: 1;
            padding: 12px;
            text-align: center;
            font-size: 13px;
            cursor: pointer;
            color: var(--text-sub);
            border-bottom: 2px solid transparent;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: 0.2s;
        }}

        .tab.active {{
            color: var(--text-main);
            border-bottom: 2px solid var(--text-main);
            font-weight: 600;
        }}

        .tab:hover {{ background: #fcfcfc; }}

        .content-area {{
            padding: 15px;
            flex: 1;
        }}

        .data-row {{
            display: flex;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #f9f9f9;
        }}

        .rank-num {{
            width: 30px;
            color: #999;
            font-size: 13px;
        }}

        .market-icon {{
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: #eee;
            margin-right: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
        }}

        .market-info {{
            flex: 1;
        }}

        .market-title {{
            font-size: 14px;
            font-weight: 500;
            text-decoration: none;
            color: var(--accent-blue);
            display: block;
            margin-bottom: 6px;
        }}

        .progress-container {{
            height: 4px;
            background: #f0f0f0;
            border-radius: 2px;
            width: 100%;
        }}

        .progress-bar-win {{
            height: 100%;
            background: var(--win-color);
            border-radius: 2px;
        }}

        .progress-bar-loss {{
            height: 100%;
            background: var(--loss-color);
            border-radius: 2px;
        }}

        .pnl-val {{
            width: 120px;
            text-align: right;
            font-weight: 600;
            font-size: 14px;
        }}

        .empty-state {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 300px;
            color: #ccc;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header-bar">
            <div class="title">📊 Trader Analysis Dashboard</div>
            <div style="color: var(--text-sub); font-size: 13px;">Address: {address}</div>
        </div>

        <!-- 上排 -->
        <div class="top-row">
            <div class="chart-card">
                {chart_div}
            </div>
            <div class="trade-log-card">
                <div class="card-header-dark">
                    Order History
                    <div class="card-subtitle">Real-time trade execution log</div>
                </div>
                <div class="log-container">
                    {self._render_trades_html(trades_list)}
                </div>
            </div>
        </div>

        <!-- 下排 -->
        <div class="bottom-row">
            <!-- 持仓卡片 -->
            <div class="pro-card">
                <div class="card-header-dark">
                    Current Positions
                    <div class="card-subtitle">Largest positions by value and shares</div>
                </div>
                <div class="tab-bar">
                    <div class="tab active" onclick="switchTab('pos', 'value', this)">$ Current Value</div>
                    <div class="tab" onclick="switchTab('pos', 'shares', this)">📈 Current Shares</div>
                </div>
                <div id="pos-content" class="content-area">
                    {self._render_positions_html(active_list)}
                </div>
            </div>

            <!-- 表现卡片 -->
            <div class="pro-card">
                <div class="card-header-dark">
                    Market Performance
                    <div class="card-subtitle">Biggest wins and losses by market</div>
                </div>
                <div class="tab-bar">
                    <div class="tab active" onclick="switchTab('perf', 'wins', this)">📈 Biggest Wins</div>
                    <div class="tab" onclick="switchTab('perf', 'losses', this)">📉 Biggest Losses</div>
                </div>
                <div id="perf-content" class="content-area">
                    {self._render_performance_html(top_wins, 'win')}
                </div>
            </div>
        </div>
    </div>

    <script>
        const topWins = {top_wins_json};
        const topLosses = {top_losses_json};
        const activePositions = {active_list_json};

        function formatCurrency(val) {{
            const absVal = Math.abs(val);
            const formatted = new Intl.NumberFormat('en-US', {{
                style: 'currency',
                currency: 'USD',
                maximumFractionDigits: 0
            }}).format(absVal);
            return val < 0 ? '-' + formatted : '+' + formatted;
        }}

        function switchTab(type, subtype, el) {{
            // 切换 Tab 样式
            const tabs = el.parentElement.querySelectorAll('.tab');
            tabs.forEach(t => t.classList.remove('active'));
            el.classList.add('active');

            const content = document.getElementById(type + '-content');
            
            if (type === 'perf') {{
                const data = subtype === 'wins' ? topWins : topLosses;
                const mode = subtype === 'wins' ? 'win' : 'loss';
                renderPerf(content, data, mode);
            }} else {{
                // Positions 切换逻辑可以在此扩展
                renderPositions(content, activePositions, subtype === 'value');
            }}
        }}

        function renderPerf(container, data, mode) {{
            if (!data || data.length === 0) {{
                container.innerHTML = '<div class="empty-state">No data available</div>';
                return;
            }}
            
            const maxPnl = Math.max(...data.map(d => Math.abs(d.pnl)));
            
            let html = '';
            data.forEach((item, index) => {{
                const pct = (Math.abs(item.pnl) / maxPnl) * 100;
                const barClass = mode === 'win' ? 'progress-bar-win' : 'progress-bar-loss';
                const pnlColor = mode === 'win' ? 'var(--win-color)' : 'var(--loss-color)';
                
                html += `
                    <div class="data-row">
                        <div class="rank-num">#${{index + 1}}</div>
                        <div class="market-icon">${{mode === 'win' ? '🟢' : '🔴'}}</div>
                        <div class="market-info">
                            <a href="#" class="market-title">${{item.market}}</a>
                            <div class="progress-container">
                                <div class="${{barClass}}" style="width: ${{pct}}%"></div>
                            </div>
                        </div>
                        <div class="pnl-val" style="color: ${{pnlColor}}">${{formatCurrency(item.pnl)}}</div>
                    </div>
                `;
            }});
            container.innerHTML = html;
        }}

        function renderPositions(container, data, isValue) {{
            // 初始已由 Python 渲染，这里提供动态切换逻辑
            if (!data || data.length === 0) return;
            // 这里的渲染逻辑与 Python 类似，通过 JS 重写 content
        }}
    </script>
</body>
</html>
        """
        filename = f"report_{address}.html"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_template)
        return filename

    # --- 辅助方法：生成各个部分的 HTML 片段 ---

    def _create_pnl_chart(self, df):
        if df.empty:
            return go.Figure().update_layout(title="No Data")
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df['date'], y=df['cumulative_pnl'],
            mode='lines',
            fill='tozeroy',
            line=dict(color='#2962ff', width=3),
            fillcolor='rgba(41, 98, 255, 0.1)',
            name='Equity'
        ))
        
        fig.update_layout(
            title="Equity Curve (PnL Over Time)",
            margin=dict(l=10, r=10, t=40, b=10),
            hovermode='x unified',
            template='plotly_white',
            autosize=True,
            height=None, # 让 CSS 容器控制高度
            xaxis=dict(
                rangeslider=dict(visible=True, thickness=0.08),
                type='date'
            ),
            yaxis=dict(tickprefix='$', gridcolor='#f0f0f0')
        )
        return fig

    def _render_trades_html(self, trades):
        if not trades:
            return '<div class="empty-state">No trade history</div>'
        
        html = ""
        for t in trades[:100]: # 仅显示最近 100 条防止过载
            side_cls = "side-buy" if str(t.get('side')).upper() == 'BUY' else "side-sell"
            html += f"""
                <div class="log-row">
                    <span style="color:#999; width: 80px;">{t.get('date_str')}</span>
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
                        <a href="#" class="market-title">{a.get('market')}</a>
                        <div class="progress-container">
                            <div class="progress-bar-win" style="width: {pct}%; background: #2962ff;"></div>
                        </div>
                    </div>
                    <div class="pnl-val">${a.get('cost', 0):,.0f}</div>
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
                        <a href="#" class="market-title">{d.get('market')}</a>
                        <div class="progress-container">
                            <div class="{bar_cls}" style="width: {pct}%"></div>
                        </div>
                    </div>
                    <div class="pnl-val" style="color: {pnl_color}">{prefix}${abs(d.get('pnl', 0)):,.0f}</div>
                </div>
            """
        return html

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python visualize_trader.py <TRADER_ADDRESS>")
        demo_addr = "0xdb27bf2ac5d428a9c63dbc914611036855a6c56e"
        print(f"Running demo with: {demo_addr}")
        visualizer = TraderVisualizer()
        visualizer.analyze_and_plot(demo_addr)
    else:
        address = sys.argv[1]
        visualizer = TraderVisualizer()
        visualizer.analyze_and_plot(address)
