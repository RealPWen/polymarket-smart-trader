from flask import Flask, render_template, request, jsonify
from visualize_trader import TraderVisualizer
from polymarket_data_fetcher import PolymarketDataFetcher
import os
import pandas as pd
import subprocess
import signal
import json
from datetime import datetime
from typing import Dict

app = Flask(__name__)
visualizer = TraderVisualizer()
fetcher = PolymarketDataFetcher()


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    address = request.json.get('address')
    if not address:
        return jsonify({"error": "Address is required"}), 400
    
    try:
        # analyze_and_get_html returns the HTML string
        html_content = visualizer.analyze_and_get_html(address)
        return jsonify({"html": html_content})
    except Exception as e:
        print(f"Error analyzing trader: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/stream/<address>')
def stream_trades(address):
    try:
        # Get the 20 most recent trades for the address
        trades_df = fetcher.get_trades(wallet_address=address, limit=20, silent=True)
        if trades_df.empty:
            return jsonify([])
        
        # Prepare data for frontend
        trades_df['date_str'] = pd.to_datetime(trades_df['timestamp'], unit='s').dt.strftime('%m-%d %H:%M:%S')
        trades_list = trades_df.to_dict('records')
        return jsonify(trades_list)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analysis/<address>')
def get_analysis_data(address):
    try:
        # Perform full analysis
        analysis_df, trades_df, active_df = visualizer.analyzer.analyze_trader(address, limit=5000)
        
        # Prepare PnL data for chart
        pnl_data = []
        if not analysis_df.empty:
            df_temp = analysis_df.copy()
            df_temp['date'] = df_temp['date'].dt.strftime('%Y-%m-%d %H:%M')
            pnl_data = df_temp[['date', 'cumulative_pnl']].to_dict('records')
            
            # Prepare wins/losses
            df_wins = df_temp[df_temp['pnl'] > 0].sort_values('pnl', ascending=False).head(10)
            df_losses = df_temp[df_temp['pnl'] < 0].sort_values('pnl', ascending=True).head(10)
            top_wins = df_wins.to_dict('records')
            top_losses = df_losses.to_dict('records')
        else:
            top_wins = []
            top_losses = []

        # Prepare positions
        active_list = []
        if not active_df.empty:
            active_list = active_df.to_dict('records')

        return jsonify({
            "pnl_history": pnl_data,
            "top_wins": top_wins,
            "top_losses": top_losses,
            "active_positions": active_list
        })
    except Exception as e:
        print(f"Update error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/copy-trade/start', methods=['POST'])
def start_copy_trade():
    address = request.json.get('address')
    if not address:
        return jsonify({"error": "Address is required"}), 400
    
    address = address.lower()
    
    # 先检查是否已经在运行
    try:
        find_cmd = f"ps aux | grep 'account_listener.py {address}' | grep -v grep"
        result = subprocess.run(find_cmd, shell=True, capture_output=True, text=True)
        if result.stdout.strip():
            return jsonify({
                "status": "already_running",
                "message": "监听器已经在运行中"
            }), 200
    except Exception as e:
        print(f"检查进程状态失败: {e}")

    try:
        # 获取项目根目录和 Python 路径
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        python_path = subprocess.check_output(['which', 'python3.9']).decode().strip()
        
        # 构建启动命令（在项目根目录下执行）
        listener_script = os.path.join(project_root, 'user_listener', 'account_listener.py')
        
        # 使用 osascript 在新的 Terminal 窗口中启动（macOS）
        applescript = f'''
        tell application "Terminal"
            do script "cd {project_root} && {python_path} {listener_script} {address}"
            activate
        end tell
        '''
        
        # 启动进程，但不等待它结束
        subprocess.Popen(
            ['osascript', '-e', applescript],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # 等待一小会儿，确保监听器进程已经启动
        import time
        time.sleep(2)
        
        # 验证监听器是否成功启动
        verify_cmd = f"ps aux | grep 'account_listener.py {address}' | grep -v grep"
        verify_result = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True)
        
        if not verify_result.stdout.strip():
            raise Exception("监听器启动失败，请检查终端输出")
        
        return jsonify({
            "status": "started",
            "message": f"监听器已在新终端窗口中启动，监听地址: {address}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/copy-trade/stop', methods=['POST'])
def stop_copy_trade():
    address = request.json.get('address')
    if not address:
        return jsonify({"error": "Address is required"}), 400
    
    address = address.lower()
    
    try:
        # 1. 终止监听进程
        try:
            find_cmd = f"ps aux | grep 'account_listener.py {address}' | grep -v grep | awk '{{print $2}}'"
            result = subprocess.run(
                find_cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            
            pids = result.stdout.strip().split('\n')
            pids = [pid for pid in pids if pid]
            
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    print(f"成功终止监听进程 PID: {pid}")
                except Exception as e:
                    print(f"终止进程 {pid} 失败: {e}")
        except Exception as e:
            print(f"查找监听进程时出错: {e}")
        
        return jsonify({
            "status": "stopped",
            "message": f"跟单已停止"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/copy-trade/status/<address>')
def get_copy_trade_status(address):
    address = address.lower()
    is_running = False
    
    # 通过查找进程来判断是否在运行
    try:
        find_cmd = f"ps aux | grep 'account_listener.py {address}' | grep -v grep"
        result = subprocess.run(
            find_cmd,
            shell=True,
            capture_output=True,
            text=True
        )
        
        # 如果找到进程，说明正在运行
        if result.stdout.strip():
            is_running = True
    except Exception as e:
        print(f"检查状态时出错: {e}")
    
    return jsonify({
        "is_running": is_running
    })

if __name__ == '__main__':
    # Ensure templates directory exists
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True, port=5005)
