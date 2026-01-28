from flask import Flask, render_template, request, jsonify
from visualize_trader import TraderVisualizer
from polymarket_data_fetcher import PolymarketDataFetcher
import os
import platform
import pandas as pd
import subprocess
import signal
import json
from datetime import datetime
from typing import Dict

app = Flask(__name__)
visualizer = TraderVisualizer()
fetcher = PolymarketDataFetcher()
tester = None # 提前声明，防止 NameError

# --- 启动时连接验证 ---
try:
    import config
    from polymarket_trader import PolymarketTrader
    print("🌐 [系统] 正在启动并验证 Polymarket 连接...")
    if config.PRIVATE_KEY and config.FUNDER_ADDRESS:
        # 尝试简单初始化验证
        tester = PolymarketTrader(config.PRIVATE_KEY, config.FUNDER_ADDRESS)
        print("✅ [系统] 凭证验证成功，API 已就绪")
    else:
        print("⚠️ [系统] 警告：未检测到完整配置，实盘跟单功能可能受限")
        
    # Start Daily Report Scheduler
    try:
        from daily_reporter import DailyReportScheduler
        scheduler = DailyReportScheduler()
        scheduler.start()
    except Exception as de:
        print(f"❌ [系统] 无法启动定时报告: {de}")

except Exception as e:
    print(f"❌ [系统] 启动连接验证失败: {e}")
# --------------------

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

    except Exception as e:
        print(f"Update error: {e}")
        return jsonify({"error": str(e)}), 500

def _kill_all_listeners():
    """强制终止所有监听进程"""
    try:
        if platform.system() == 'Windows':
            # Windows: Find processes by command line and kill them
            cmd = "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*account_listener.py*' } | Stop-Process -Force"
            subprocess.run(["powershell", "-Command", cmd], capture_output=True)
            return 1
        else:
            # macOS / Linux
            cmd = "ps aux | grep 'account_listener.py' | grep -v grep | awk '{print $2}'"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            pids = res.stdout.strip().split('\n')
            killed_count = 0
            
            for pid in pids:
                if pid:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        killed_count += 1
                    except: pass
            return killed_count
    except:
        return 0

@app.route('/api/copy-trade/update-clients', methods=['POST'])
def update_copy_trade_clients():
    try:
        new_addresses = request.json.get('addresses', [])
        if not new_addresses:
            return jsonify({"error": "No addresses provided"}), 400
            
        # 1. 终止旧进程
        _kill_all_listeners()
        
        # 2. 读取当前策略配置 (用于重启)
        strategy = {"mode": 1, "param": 1.0} # 默认兜底
        try:
            if os.path.exists("monitored_trades/strategy_config.json"):
                with open("monitored_trades/strategy_config.json", 'r') as f:
                    strategy = json.load(f)
        except: pass
        
        # 3. 准备启动参数
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        import base64
        strategy_json = json.dumps(strategy)
        strategy_b64 = base64.b64encode(strategy_json.encode('utf-8')).decode('utf-8')
        
        try:
            python_path = subprocess.check_output(['which', 'python3.9']).decode().strip()
        except:
            import sys
            python_path = sys.executable

        listener_script = os.path.join(project_root, 'user_listener', 'account_listener.py')
        combined_addresses = ",".join([a.lower().strip() for a in new_addresses])
        
        # 4. 启动新终端 (使用 caffeinate 防止休眠)
        # -d: Prevent display sleep
        # -i: Prevent idle sleep
        # -m: Prevent disk idle sleep
        # -s: Prevent system sleep
        # -u: Declare user is active
        if platform.system() == 'Windows':
            cmd = [python_path, listener_script, combined_addresses, strategy_b64]
            subprocess.Popen(cmd, cwd=project_root, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            applescript = f'''
            tell application "Terminal"
                do script "cd {project_root} && caffeinate -dimsu {python_path} {listener_script} {combined_addresses} {strategy_b64}"
                activate
            end tell
            '''
            subprocess.run(['osascript', '-e', applescript])
        
        return jsonify({
            "status": "restarted", 
            "message": f"服务已重启，正在监控 {len(new_addresses)} 个地址"
        })
        
    except Exception as e:
        print(f"Client update error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/copy-trade/start', methods=['POST'])
def start_copy_trade():
    address = request.json.get('address')
    if not address:
        return jsonify({"error": "Address is required"}), 400
    
    address = address.lower()
    
    # 先检查是否已经在运行
    try:
        if platform.system() == 'Windows':
            cmd = f"Get-WmiObject Win32_Process | Where-Object {{ $_.CommandLine -like '*account_listener.py* {address}*' }}"
            result = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True)
            if result.stdout.strip():
                return jsonify({
                    "status": "already_running",
                    "message": "监听器已经在运行中"
                }), 200
        else:
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
        try:
            python_path = subprocess.check_output(['which', 'python3.9']).decode().strip()
        except:
            import sys
            python_path = sys.executable
        
        # 构建启动命令（在项目根目录下执行）
        listener_script = os.path.join(project_root, 'user_listener', 'account_listener.py')
        
        # 使用 osascript 在新的 Terminal 窗口中启动（macOS）
        # 或 subprocess.Popen on Windows
        
        if platform.system() == 'Windows':
            cmd = [python_path, listener_script, address]
            subprocess.Popen(cmd, cwd=project_root, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
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
        # 验证监听器是否成功启动
        if platform.system() == 'Windows':
            verify_cmd = f"Get-WmiObject Win32_Process | Where-Object {{ $_.CommandLine -like '*account_listener.py* {address}*' }}"
            verify_result = subprocess.run(["powershell", "-Command", verify_cmd], capture_output=True, text=True)
            if not verify_result.stdout.strip():
                raise Exception("监听器启动失败，请检查终端输出")
        else:
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
            if platform.system() == 'Windows':
                cmd = f"Get-WmiObject Win32_Process | Where-Object {{ $_.CommandLine -like '*account_listener.py* {address}*' }} | Stop-Process -Force"
                subprocess.run(["powershell", "-Command", cmd], capture_output=True)
                print(f"成功终止监听进程 for {address}")
            else:
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
    # 通过查找进程来判断是否在运行
    try:
        if platform.system() == 'Windows':
            cmd = f"Get-WmiObject Win32_Process | Where-Object {{ $_.CommandLine -like '*account_listener.py* {address}*' }}"
            result = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True)
            if result.stdout.strip():
                is_running = True
        else:
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

@app.route('/copy-trade/setup')
def copy_trade_setup():
    return render_template('setup.html')

@app.route('/copy-trade/launch', methods=['POST'])
def launch_copy_trade():
    try:
        data = request.json
        addresses = data.get('addresses', []) # 获取地址列表
        strategy = data.get('strategy')
        
        if not addresses or not strategy:
            return jsonify({"error": "Missing parameters"}), 400
            
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        import base64
        import json # Added import for json
        strategy_json = json.dumps(strategy)
        strategy_b64 = base64.b64encode(strategy_json.encode('utf-8')).decode('utf-8')
        
        # 尝试获取 Python 路径
        try:
            python_path = subprocess.check_output(['which', 'python3.9']).decode().strip()
        except:
            import sys # Added import for sys
            python_path = sys.executable

        listener_script = os.path.join(project_root, 'user_listener', 'account_listener.py')
        
        # 构建多地址参数 (comma separated)
        combined_addresses = ",".join([a.lower().strip() for a in addresses])
        
        # 检查是否已有包含这组地址的监听器在运行
        # 简单检查：只要还在运行这个脚本，且包含其中一个地址，就视为冲突 (或者您可以设计更复杂的逻辑)
        # 这里为了简化，我们先 kill 掉旧的单一监听器，或者允许并行运行
        

        
        # [NEW] 同时初始化策略热更新文件
        try:
            os.makedirs("monitored_trades", exist_ok=True)
            with open("monitored_trades/strategy_config.json", "w") as f:
                json.dump(strategy, f)
        except Exception as e:
            print(f"⚠️ 无法写入策略初始配置文件: {e}")
            
        if platform.system() == "Windows":
            # Windows: 使用 subprocess.Popen 启动新终端
            cmd = [python_path, listener_script, combined_addresses, strategy_b64]
            subprocess.Popen(cmd, cwd=project_root, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            # macOS: 使用 AppleScript
            applescript = f'''
            tell application "Terminal"
                do script "cd {project_root} && caffeinate -dimsu {python_path} {listener_script} {combined_addresses} {strategy_b64}"
                activate
            end tell
            '''
            subprocess.run(['osascript', '-e', applescript])
        
        return jsonify({
            "status": "success",
            "message": f"成功启动多路监听进程，监控 {len(addresses)} 个地址: {combined_addresses}"
        })
    except Exception as e:
        print(f"Launch error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/copy-trade/update-strategy', methods=['POST'])
def update_strategy():
    try:
        new_strategy = request.json
        if not new_strategy:
            return jsonify({"error": "No data provided"}), 400
            
        # 简单验证
        if 'mode' not in new_strategy or 'param' not in new_strategy:
             return jsonify({"error": "Missing required fields (mode, param)"}), 400
             
        # 写入共享配置文件
        os.makedirs("monitored_trades", exist_ok=True)
        with open("monitored_trades/strategy_config.json", "w") as f:
            json.dump(new_strategy, f, indent=4)
            
        print(f"✅ 策略已通过 API 更新: {new_strategy}")
        return jsonify({"status": "updated", "strategy": new_strategy})
    except Exception as e:
        print(f"❌ 更新策略失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/copy-trade/dashboard')
def copy_trade_dashboard():
    address = request.args.get('address')
    return render_template('dashboard.html', address=address)

@app.route('/api/my-executions')
def get_my_executions():
    try:
        import config
        # 直接从 API 读取我的历史成交
        # limit=50: 获取最近 50 条
        trades_df = fetcher.get_trades(wallet_address=config.FUNDER_ADDRESS, limit=50, silent=True)
        
        if trades_df.empty:
            return jsonify([])
            
        trades = []
        for _, row in trades_df.iterrows():
            try:
                size = float(row.get('size', 0))
                price = float(row.get('price', 0))
                usd_val = size * price
                ts = row.get('timestamp', 0)
                
                trades.append({
                    "market_title": row.get('title', 'Unknown Market'),
                    "side": row.get('side', 'UNKNOWN'),
                    "size": f"{size:.2f}",
                    "my_target_amount": usd_val, # 复用前端字段名 (实际是 Total Value)
                    "date_str": datetime.fromtimestamp(ts).strftime('%m-%d %H:%M:%S'),
                    "timestamp": ts
                })
            except: continue
            
        return jsonify(trades)
    except Exception as e:
        print(f"❌ 获取成交历史失败: {e}")
        return jsonify([])

@app.route('/api/my-balance')
def get_my_balance():
    try:
        import config
        # 优先使用 CLOB Client (tester) 获取实时余额，它比 Data API (fetcher) 更准确
        if tester:
            cash = tester.get_balance()
            print(f"💰 [CLOB] 实时余额: ${cash:.2f}")
        else:
            # 兜底方案
            cash = fetcher.get_user_cash_balance(config.FUNDER_ADDRESS)
            print(f"⚠️ [DataAPI] 使用兜底余额: ${cash:.2f}")
            
        return jsonify({"cash": cash, "address": config.FUNDER_ADDRESS})
    except Exception as e:
        print(f"❌ 获取余额失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/my-positions')
def get_my_positions():
    try:
        import config
        positions_df = fetcher.get_user_positions(config.FUNDER_ADDRESS)
        if positions_df.empty:
            return jsonify([])
            
        # 数据清洗与过滤
        positions_df['size'] = pd.to_numeric(positions_df['size'], errors='coerce').fillna(0)
        positions_df['currentValue'] = pd.to_numeric(positions_df.get('currentValue', 0), errors='coerce').fillna(0)
        
        # 过滤掉极其微小的持仓 (Value < $0.01)
        # 这通常是已经归零的期权或者残留的灰尘
        valid_positions = positions_df[positions_df['currentValue'] > 0.01].copy()
        
        return jsonify(valid_positions.to_dict('records'))
    except Exception as e:
        return jsonify([])

if __name__ == '__main__':
    # Ensure templates directory exists
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True, port=5005)
