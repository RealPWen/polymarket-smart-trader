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

    def analyze_and_get_html(self, address: str, limit: int = 50000):
        print(f"📊 正在深度分析交易员: {address} ...")
        
        # 1. 使用 Analyzer 获取数据
        analysis_df, trades_df, active_df = self.analyzer.analyze_trader(address, limit)
        
        # 2. 获取 HTML 内容
        return self.get_professional_report_html(address, analysis_df, trades_df, active_df)

    def generate_professional_report(self, address, analysis_df, trades_df, active_df):
        """核心方法：接收数据并生成高度定制化的 HTML 文件"""
        html_content = self.get_professional_report_html(address, analysis_df, trades_df, active_df)
        filename = f"report_{address}.html"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        return filename

    def get_professional_report_html(self, address, analysis_df, trades_df, active_df):
        """生成并返回 HTML 字符串"""
        
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
            cursor: pointer;
            transition: transform 0.2s;
        }}
        .trade-log-card:hover {{
            transform: translateY(-2px);
            border-color: var(--accent-blue);
        }}

        .card-header-dark {{
            background: #1a1a1a;
            color: white;
            padding: 12px 20px;
            border-radius: 11px 11px 0 0;
            font-size: 16px;
            font-weight: 600;
            flex-shrink: 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
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

        /* Live Monitor Overlay */
        #live-monitor {{
            position: fixed;
            top: 0;
            right: -500px;
            width: 450px;
            height: 100vh;
            background: #fff;
            box-shadow: -5px 0 25px rgba(0,0,0,0.1);
            transition: right 0.3s ease-out;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            border-left: 1px solid var(--border-color);
        }}
        #live-monitor.open {{
            right: 0;
        }}
        .monitor-header {{
            background: #1a1a1a;
            color: white;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .close-btn {{
            cursor: pointer;
            font-size: 24px;
            line-height: 1;
        }}
        .live-badge {{
            background: #ff3d00;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            margin-left: 8px;
            animation: pulse 1.5s infinite;
        }}
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
            100% {{ opacity: 1; }}
        }}
        .stream-container {{
            flex: 1;
            overflow-y: auto;
            padding: 10px;
            background: #fcfcfc;
        }}
        .stream-item {{
            background: white;
            border: 1px solid #eee;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 10px;
            font-size: 13px;
            animation: slideIn 0.3s ease-out;
        }}
        @keyframes slideIn {{
            from {{ transform: translateX(20px); opacity: 0; }}
            to {{ transform: translateX(0); opacity: 1; }}
        }}
        .new-flash {{
            border: 2px solid var(--accent-blue) !important;
            background: #f0f7ff !important;
            animation: flashHighlight 2s ease-out;
        }}
        @keyframes flashHighlight {{
            0% {{ background: #e3f2fd; }}
            100% {{ background: white; }}
        }}
        /* Copy Trade Toggle Styles */
        .toggle-container {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 11px;
            font-weight: 600;
            color: #ccc;
            background: #2a2a2a;
            padding: 4px 10px;
            border-radius: 20px;
            margin-right: 15px;
        }}
        .switch {{
            position: relative;
            display: inline-block;
            width: 32px;
            height: 18px;
        }}
        .switch input {{
            opacity: 0;
            width: 0;
            height: 0;
        }}
        .slider {{
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #555;
            transition: .4s;
            border-radius: 34px;
        }}
        .slider:before {{
            position: absolute;
            content: "";
            height: 12px;
            width: 12px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }}
        input:checked + .slider {{
            background-color: #00c853;
        }}
        input:checked + .slider:before {{
            transform: translateX(14px);
        }}
        .copy-status-active {{ color: #00c853; }}
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
            <div class="trade-log-card" id="history-card" title="Double click to start real-time monitoring">
                <div class="card-header-dark">
                    <span>Order History</span>
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
                    <span>Current Positions</span>
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
                    <span>Market Performance</span>
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

    <!-- Audio for notifications -->
    <audio id="notif-sound" preload="auto">
        <source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg">
    </audio>

    <!-- Live Monitor Panel -->
    <div id="live-monitor">
        <div class="monitor-header">
            <div style="display: flex; align-items: center;">
                <strong>Live Monitor</strong>
                <span class="live-badge">LIVE</span>
            </div>
            
            <div style="display: flex; align-items: center;">
                <div class="toggle-container">
                    <span id="copy-trade-label">跟单 OFF</span>
                    <label class="switch">
                        <input type="checkbox" id="copy-trade-toggle" onchange="toggleCopyTradeProcess()">
                        <span class="slider"></span>
                    </label>
                </div>
                <div class="close-btn" onclick="toggleMonitor()">&times;</div>
            </div>
        </div>
        <div id="stream-content" class="stream-container">
            <div style="text-align:center; padding: 40px; color: #999;">
                Starting real-time feed...
            </div>
        </div>
    </div>

    <script>
        let topWins = {top_wins_json};
        let topLosses = {top_losses_json};
        let activePositions = {active_list_json};
        const traderAddress = "{address}";
        let monitorInterval = null;
        let lastSeenTx = null;
        const seenHashes = new Set();

        // Double click handler
        document.getElementById('history-card').addEventListener('dblclick', () => {{
            toggleMonitor();
        }});

        function toggleMonitor() {{
            const monitor = document.getElementById('live-monitor');
            monitor.classList.toggle('open');
            
            if (monitor.classList.contains('open')) {{
                startMonitoring();
                checkCopyTradeStatus(); // Check status when sidebar opens
            }} else {{
                stopMonitoring();
            }}
        }}

        async function checkCopyTradeStatus() {{
            try {{
                const res = await fetch(`/api/copy-trade/status/${{traderAddress}}`);
                const data = await res.json();
                const toggle = document.getElementById('copy-trade-toggle');
                const label = document.getElementById('copy-trade-label');
                
                toggle.checked = data.is_running;
                if (data.is_running) {{
                    label.innerText = '跟单 ON';
                    label.classList.add('copy-status-active');
                }} else {{
                    label.innerText = '跟单 OFF';
                    label.classList.remove('copy-status-active');
                }}
            }} catch (e) {{
                console.error("Failed to check status", e);
            }}
        }}

        async function toggleCopyTradeProcess() {{
            const toggle = document.getElementById('copy-trade-toggle');
            const label = document.getElementById('copy-trade-label');
            const endpoint = toggle.checked ? '/api/copy-trade/start' : '/api/copy-trade/stop';
            
            // Optimistic update
            label.innerText = toggle.checked ? '... 处理中' : '... 处理中';

            try {{
                const res = await fetch(endpoint, {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{address: traderAddress}})
                }});
                const result = await res.json();
                
                if (result.error) {{
                    alert("操作失败: " + result.error);
                    toggle.checked = !toggle.checked;
                }}
                
                // Final update after response
                await checkCopyTradeStatus();
            }} catch (e) {{
                alert("网络请求失败");
                toggle.checked = !toggle.checked;
                checkCopyTradeStatus();
            }}
        }}

        function startMonitoring() {{
            if (monitorInterval) return;
            fetchStream(); // Initial fetch
            monitorInterval = setInterval(fetchStream, 5000);
        }}

        function stopMonitoring() {{
            if (monitorInterval) {{
                clearInterval(monitorInterval);
                monitorInterval = null;
            }}
        }}

        async function fetchStream() {{
            try {{
                const res = await fetch(`/stream/${{traderAddress}}`);
                const trades = await res.json();
                renderStream(trades);
            }} catch (e) {{
                console.error("Failed to fetch stream:", e);
            }}
        }}

        async function refreshDashboardData() {{
            console.log("🔄 检测到新交易，正在同步全局数据...");
            try {{
                const res = await fetch(`/api/analysis/${{traderAddress}}`);
                const data = await res.json();
                
                // 1. 更新全局变量
                topWins = data.top_wins;
                topLosses = data.top_losses;
                activePositions = data.active_positions;

                // 2. 更新收益曲线图表 (Plotly)
                const chartDiv = document.querySelector('.js-plotly-plot');
                if (chartDiv && data.pnl_history.length > 0) {{
                    const x = data.pnl_history.map(d => d.date);
                    const y = data.pnl_history.map(d => d.cumulative_pnl);
                    Plotly.react(chartDiv, [{{
                        x: x,
                        y: y,
                        mode: 'lines',
                        fill: 'tozeroy',
                        line: {{color: '#2962ff', width: 3}},
                        fillcolor: 'rgba(41, 98, 255, 0.1)',
                        name: 'Equity'
                    }}], chartDiv.layout);
                }}

                // 3. 刷新底部卡片内容
                const perfTab = document.querySelector('.pro-card:nth-child(2) .tab.active');
                if (perfTab) {{
                    const subtype = perfTab.innerText.includes('Wins') ? 'wins' : 'losses';
                    renderPerf(document.getElementById('perf-content'), subtype === 'wins' ? topWins : topLosses, subtype === 'wins' ? 'win' : 'loss');
                }}

                const posTab = document.querySelector('.pro-card:nth-child(1) .tab.active');
                if (posTab) {{
                    renderPositions(document.getElementById('pos-content'), activePositions, posTab.innerText.includes('Value'));
                }}

            }} catch (e) {{
                console.error("Dashboard sync failed:", e);
            }}
        }}

        function renderStream(trades) {{
            const container = document.getElementById('stream-content');
            
            if (!trades || trades.length === 0) {{
                container.innerHTML = '<div style="text-align:center; padding: 40px; color: #999;">No recent trades found</div>';
                return;
            }}

            const latestTx = trades[0].transactionHash;
            if (latestTx === lastSeenTx) return;

            let html = '';
            let isFirstLoad = (lastSeenTx === null);
            let hasNewOrder = false;

            trades.forEach(t => {{
                const sideColor = t.side === 'BUY' ? 'var(--win-color)' : 'var(--loss-color)';
                const sideText = t.side === 'BUY' ? '买入' : '卖出';
                
                const isActuallyNew = !isFirstLoad && !seenHashes.has(t.transactionHash);
                if (isActuallyNew) hasNewOrder = true;

                const flashClass = isActuallyNew ? 'new-flash' : '';
                
                html += `
                    <div class="stream-item ${{flashClass}}">
                        <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                            <span style="color:#999; font-size:11px;">${{t.date_str}}</span>
                            <span style="color:${{sideColor}}; font-weight:700;">${{sideText}}</span>
                        </div>
                        <div style="font-weight:600; margin-bottom:6px; color:var(--accent-blue);">${{t.title}}</div>
                        <div style="display:flex; justify-content:space-between; font-size:12px;">
                            <span>数量: ${{t.size}}</span>
                            <span>价格: $${{t.price}}</span>
                        </div>
                        <div style="margin-top:4px; font-weight:700; text-align:right;">
                            合计: $${{(t.size * t.price).toFixed(2)}}
                        </div>
                    </div>
                `;
            }});
            
            // 触发音效和全局刷新
            if (hasNewOrder) {{
                const sound = document.getElementById('notif-sound');
                if (sound) sound.play().catch(e => {{}});
                refreshDashboardData(); // <--- 关键点：触发全局同步
            }}
            
            trades.forEach(t => seenHashes.add(t.transactionHash));
            lastSeenTx = latestTx;
            container.innerHTML = html;
        }}

        function formatCurrency(val) {{
            const absVal = Math.abs(val);
            const formatted = new Intl.NumberFormat('en-US', {{
                style: 'currency',
                currency: 'USD',
                maximumFractionDigits: 2
            }}).format(absVal);
            return val < 0 ? '-' + formatted : '+' + formatted;
        }}

        function switchTab(type, subtype, el) {{
            const tabs = el.parentElement.querySelectorAll('.tab');
            tabs.forEach(t => t.classList.remove('active'));
            el.classList.add('active');

            const content = document.getElementById(type + '-content');
            
            if (type === 'perf') {{
                const data = subtype === 'wins' ? topWins : topLosses;
                const mode = subtype === 'wins' ? 'win' : 'loss';
                renderPerf(content, data, mode);
            }} else {{
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
            if (!data || data.length === 0) {{
                container.innerHTML = '<div class="empty-state">No active positions</div>';
                return;
            }}
            
            const maxVal = Math.max(...data.map(a => Math.abs(isValue ? a.cost : a.size)));
            
            let html = '';
            data.slice(0, 8).forEach((a, i) => {{
                const val = isValue ? a.cost : a.size;
                const pct = (Math.abs(val) / maxVal) * 100;
                html += `
                    <div class="data-row">
                        <div class="rank-num">#${{i+1}}</div>
                        <div class="market-icon">💼</div>
                        <div class="market-info">
                            <a href="#" class="market-title">${{a.market}}</a>
                            <div class="progress-container">
                                <div class="progress-bar-win" style="width: ${{pct}}%; background: #2962ff;"></div>
                            </div>
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
                        <a href="#" class="market-title">{d.get('market')}</a>
                        <div class="progress-container">
                            <div class="{bar_cls}" style="width: {pct}%"></div>
                        </div>
                    </div>
                    <div class="pnl-val" style="color: {pnl_color}">{prefix}${abs(d.get('pnl', 0)):,.2f}</div>
                </div>
            """
        return html

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python visualize_trader.py <TRADER_ADDRESS>")
        demo_addr = "0xdb27bf2ac5d428a9c63dbc914611036855a6c56e"
        print(f"Running demo with: {demo_addr}")
        visualizer = TraderVisualizer()
        # 对于 CLI，仍然生成文件并提示
        analysis_df, trades_df, active_df = visualizer.analyzer.analyze_trader(demo_addr, limit=50000)
        filename = visualizer.generate_professional_report(demo_addr, analysis_df, trades_df, active_df)
        print(f"✅ Report generated: {filename}")
    else:
        address = sys.argv[1]
        visualizer = TraderVisualizer()
        analysis_df, trades_df, active_df = visualizer.analyzer.analyze_trader(address, limit=50000)
        filename = visualizer.generate_professional_report(address, analysis_df, trades_df, active_df)
        print(f"✅ Report generated: {filename}")
