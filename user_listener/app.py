from flask import Flask, render_template, request, jsonify
from visualize_trader import TraderVisualizer
from strategy_analysis import FixedBetStrategyAnalyzer
from polymarket_data_fetcher import PolymarketDataFetcher
import os
import platform
import pandas as pd
import subprocess
import signal
import json
import sys
from datetime import datetime
from typing import Dict

app = Flask(__name__)
visualizer = TraderVisualizer()
fixed_analyzer = FixedBetStrategyAnalyzer()
fetcher = PolymarketDataFetcher()

# --- 服务器/桌面环境检测 ---
def _is_server_mode():
    """
    检测是否运行在服务器环境（无图形界面）
    服务器环境下返回 True，桌面环境返回 False
    """
    # 方法1: 检查 DISPLAY 环境变量 (Linux无头服务器通常没有)
    if platform.system() == 'Linux' and not os.environ.get('DISPLAY'):
        return True
    
    # 方法2: 检查是否可以使用 osascript (macOS 桌面专有)
    if platform.system() == 'Darwin':
        try:
            # 快速测试 osascript 是否可用
            result = subprocess.run(
                ['osascript', '-e', 'return "test"'],
                capture_output=True,
                timeout=2
            )
            if result.returncode != 0:
                return True  # osascript 失败，可能是无头环境
        except Exception:
            return True
        return False  # macOS 桌面模式
    
    # 方法3: Windows 目前默认为桌面模式
    if platform.system() == 'Windows':
        return False
    
    # 默认: Linux 服务器模式
    return True

def _get_python_path():
    """
    获取 Python 解释器路径，优先级：
    1. python3.9 (如果存在)
    2. python3 (通用)
    3. 当前解释器 (sys.executable)
    """
    for cmd in ['python3.9', 'python3', 'python']:
        try:
            result = subprocess.run(
                ['which', cmd] if platform.system() != 'Windows' else ['where', cmd],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split('\n')[0]  # 取第一个结果
        except Exception:
            continue
    return sys.executable  # 兜底方案

def _start_listener_process(project_root, listener_script, python_path, 
                              combined_addresses, strategy_b64, exec_args):
    """
    统一的监听器启动函数，自动适配服务器/桌面环境
    返回: (success: bool, message: str)
    """
    is_server = _is_server_mode()
    
    if platform.system() == 'Windows':
        # Windows: 使用 cmd 启动新窗口
        cmd_str = f'cmd /c start "Polymarket Listener" cmd /k "cd /d {project_root} && {python_path} "{listener_script}" "{combined_addresses}" "{strategy_b64}" {exec_args}"'
        subprocess.Popen(cmd_str, shell=True)
        return True, "Windows 终端窗口已启动"
    
    elif is_server:
        # Linux 服务器模式: 使用 nohup 后台运行
        log_dir = os.path.join(project_root, 'user_listener', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'listener_nohup.log')
        
        # 构建完整命令
        cmd_parts = [
            python_path, listener_script, 
            combined_addresses, strategy_b64
        ]
        # 添加可选的执行参数
        if exec_args:
            cmd_parts.extend(exec_args.split())
        
        # 使用 nohup 启动，输出重定向到日志文件
        with open(log_file, 'a') as log_f:
            log_f.write(f"\n\n{'='*60}\n")
            log_f.write(f"[{datetime.now().isoformat()}] 启动监听器\n")
            log_f.write(f"命令: {' '.join(cmd_parts)}\n")
            log_f.write(f"{'='*60}\n")
        
        # 启动后台进程
        with open(log_file, 'a') as out_f:
            process = subprocess.Popen(
                cmd_parts,
                stdout=out_f,
                stderr=subprocess.STDOUT,
                cwd=project_root,
                start_new_session=True  # 脱离父进程，确保后台运行
            )
        
        return True, f"服务器后台进程已启动 (PID: {process.pid})，日志: {log_file}"
    
    else:
        # macOS 桌面模式: 使用 AppleScript 打开新 Terminal
        applescript = f'''
        tell application "Terminal"
            do script "cd {project_root} && caffeinate -dimsu {python_path} {listener_script} {combined_addresses} {strategy_b64} {exec_args}"
            activate
        end tell
        '''
        subprocess.run(['osascript', '-e', applescript])
        return True, "macOS Terminal 窗口已启动"

tester = None # 提前声明，防止 NameError

# --- Session 配置 ---
app.secret_key = os.urandom(24)  # 用于加密 session

def login_required(f):
    """登录验证装饰器"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import session, redirect, url_for
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

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

# --- 登录相关路由 ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    from flask import session, redirect, url_for
    
    if request.method == 'POST':
        password = request.form.get('password', '')
        correct_password = config.WEB_ACCESS_PASSWORD if hasattr(config, 'WEB_ACCESS_PASSWORD') else ''
        
        if password == correct_password and correct_password:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='密码错误，请重试')
    
    # 如果未设置密码，直接放行
    if not hasattr(config, 'WEB_ACCESS_PASSWORD') or not config.WEB_ACCESS_PASSWORD:
        session['logged_in'] = True
        return redirect(url_for('index'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    from flask import session, redirect, url_for
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('main.html')

@app.route('/api/env-wallet')
def get_env_wallet():
    """Return wallet information from environment variables for auto-binding"""
    try:
        private_key = os.environ.get('POLYMARKET_PRIVATE_KEY', '')
        funder_address = os.environ.get('POLYMARKET_FUNDER_ADDRESS', '')
        
        if private_key and funder_address:
            # 只返回地址，私钥通过单独的安全方式处理
            return jsonify({
                'hasWallet': True,
                'address': funder_address,
                'privateKey': private_key  # 注意：这是本地开发用，生产环境需要更安全的方式
            })
        else:
            return jsonify({'hasWallet': False})
    except Exception as e:
        return jsonify({'hasWallet': False, 'error': str(e)})

@app.route('/api/health')
def health_check():
    """Health check endpoint to verify backend and API connection"""
    try:
        status = {
            'backend': True,
            'timestamp': datetime.now().isoformat(),
            'polymarket_api': False,
            'copy_trade_running': False,
            'copy_trade_count': 0
        }
        
        # Test Polymarket API connection
        if tester:
            try:
                # Simple API call to verify connection
                balance = tester.get_balance()
                status['polymarket_api'] = True
                status['balance'] = float(balance) if balance else 0
            except Exception as api_err:
                status['polymarket_api'] = False
                status['api_error'] = str(api_err)
        
        # Check if copy trade process is running
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'account_listener.py'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                pids = [p for p in result.stdout.strip().split('\n') if p]
                status['copy_trade_running'] = len(pids) > 0
                status['copy_trade_count'] = len(pids)
        except Exception:
            pass
        
        return jsonify(status)
    except Exception as e:
        return jsonify({'backend': False, 'error': str(e)})

@app.route('/api/server-info')
def server_info():
    """Server environment diagnostic endpoint for deployment debugging"""
    try:
        info = {
            'platform': platform.system(),
            'platform_version': platform.version(),
            'python_version': platform.python_version(),
            'python_path': _get_python_path(),
            'server_mode': _is_server_mode(),
            'display_env': os.environ.get('DISPLAY', 'Not Set'),
            'working_directory': os.getcwd(),
            'listener_processes': [],
            'timestamp': datetime.now().isoformat()
        }
        
        # 获取所有运行中的监听器进程
        try:
            cmd = "ps aux | grep 'account_listener.py' | grep -v grep"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
            if result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 11:
                        info['listener_processes'].append({
                            'pid': parts[1],
                            'cpu': parts[2],
                            'mem': parts[3],
                            'start_time': parts[8],
                            'command': ' '.join(parts[10:])[:100]  # 截断过长的命令
                        })
        except Exception as e:
            info['process_error'] = str(e)
        
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)})

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

@app.route('/api/logs')
def get_logs():
    try:
        log_file = os.path.join(os.path.dirname(__file__), 'logs', 'copy_trade.log')
        if not os.path.exists(log_file):
            return jsonify(["日志文件不存在"])
            
        # 读取最后 50 行
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return jsonify(lines[-50:])
    except Exception as e:
        return jsonify([f"读取日志失败: {str(e)}"])

@app.route('/api/analysis/<address>')
def get_analysis_data(address):
    try:
        # 清除市场缓存，确保获取最新的市场状态（包括结算信息）
        visualizer.analyzer.market_cache.clear()
        
        # Perform full analysis
        analysis_df, trades_df, active_df = visualizer.analyzer.analyze_trader(address, limit=5000)
        
        # 1. 真实盈亏数据 (Actual PnL)
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

        # 2. 模拟策略盈亏数据 (Strategy PnL)
        strat_pnl_data = []
        try:
            if not trades_df.empty:
                # 复用 trades_df 避免二次请求
                strat_pnl_df, _, _ = fixed_analyzer._simulate_strategy(trades_df)
                if not strat_pnl_df.empty:
                    df_strat = strat_pnl_df.copy()
                    df_strat['date'] = df_strat['date'].dt.strftime('%Y-%m-%d %H:%M')
                    strat_pnl_data = df_strat[['date', 'cumulative_pnl']].to_dict('records')
        except Exception as e:
            print(f"Strategy simulation error: {e}")

        # Prepare positions
        active_list = []
        if not active_df.empty:
            active_list = active_df.to_dict('records')

        return jsonify({
            "pnl_history": pnl_data,          # 真实
            "strategy_pnl_history": strat_pnl_data, # 模拟
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
        
        python_path = _get_python_path()
        listener_script = os.path.join(project_root, 'user_listener', 'account_listener.py')
        combined_addresses = ",".join([a.lower().strip() for a in new_addresses])
        
        # 获取钱包配置
        wallet_info = request.json.get('wallet', {})
        exec_address = wallet_info.get('address', '')
        exec_private_key = wallet_info.get('privateKey', '')
        
        exec_args = ""
        if exec_address and exec_private_key:
             exec_address = exec_address.replace("'", "")
             exec_private_key = exec_private_key.replace("'", "")
             exec_args = f"--exec-address {exec_address} --exec-key {exec_private_key}"
        
        # 使用统一的启动函数
        success, msg = _start_listener_process(
            project_root, listener_script, python_path,
            combined_addresses, strategy_b64, exec_args
        )
        
        return jsonify({
            "status": "started" if success else "error",
            "message": f"多路监听器启动成功，监听: {combined_addresses}。{msg}",
            "server_mode": _is_server_mode()
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
        # 获取钱包配置
        wallet_info = request.json.get('wallet', {})
        exec_address = wallet_info.get('address', '')
        exec_private_key = wallet_info.get('privateKey', '')
        
        exec_args = ""
        if exec_address and exec_private_key:
             exec_args = f"--exec-address {exec_address} --exec-key {exec_private_key}"
        
        # 获取项目根目录和 Python 路径
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        python_path = _get_python_path()
        listener_script = os.path.join(project_root, 'user_listener', 'account_listener.py')
        
        # 使用统一的启动函数 (strategy_b64 为空字符串使用默认策略)
        success, msg = _start_listener_process(
            project_root, listener_script, python_path,
            address, "", exec_args  # address 单一地址, 无策略配置
        )
        
        # 等待一小会儿，确保监听器进程已经启动
        import time
        time.sleep(2)
        
        # 验证监听器是否成功启动
        if platform.system() == 'Windows':
            verify_cmd = f"Get-WmiObject Win32_Process | Where-Object {{ $_.CommandLine -like '*account_listener.py* {address}*' }}"
            verify_result = subprocess.run(["powershell", "-Command", verify_cmd], capture_output=True, text=True)
            if not verify_result.stdout.strip():
                raise Exception("监听器启动失败，请检查终端输出")
        else:
            verify_cmd = f"ps aux | grep 'account_listener.py' | grep '{address}' | grep -v grep"
            verify_result = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True)
            
            if not verify_result.stdout.strip():
                # 在服务器模式下不报错，可能进程在后台运行
                if not _is_server_mode():
                    raise Exception("监听器启动失败，请检查终端输出")
        
        return jsonify({
            "status": "started",
            "message": f"监听器已启动，监听地址: {address}。{msg}",
            "server_mode": _is_server_mode()
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
@login_required
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
        strategy_json = json.dumps(strategy)
        strategy_b64 = base64.b64encode(strategy_json.encode('utf-8')).decode('utf-8')
        
        python_path = _get_python_path()
        listener_script = os.path.join(project_root, 'user_listener', 'account_listener.py')
        
        # 构建多地址参数 (comma separated)
        combined_addresses = ",".join([a.lower().strip() for a in addresses])
        
        # [NEW] 同时初始化策略热更新文件
        try:
            os.makedirs("monitored_trades", exist_ok=True)
            with open("monitored_trades/strategy_config.json", "w") as f:
                json.dump(strategy, f)
        except Exception as e:
            print(f"⚠️ 无法写入策略初始配置文件: {e}")
            
        # 获取钱包配置
        wallet_info = data.get('wallet', {})
        exec_address = wallet_info.get('address', '')
        exec_private_key = wallet_info.get('privateKey', '')
        
        exec_args = ""
        if exec_address and exec_private_key:
             exec_address = exec_address.replace("'", "")
             exec_private_key = exec_private_key.replace("'", "")
             exec_args = f"--exec-address {exec_address} --exec-key {exec_private_key}"

        # 使用统一的启动函数
        success, msg = _start_listener_process(
            project_root, listener_script, python_path,
            combined_addresses, strategy_b64, exec_args
        )
        
        return jsonify({
            "status": "success" if success else "error",
            "message": f"成功启动多路监听进程，监控 {len(addresses)} 个地址: {combined_addresses}。{msg}",
            "server_mode": _is_server_mode()
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

# ====== 多设备同步 API ======
SYNC_DATA_DIR = os.path.join(os.path.dirname(__file__), 'sync_data')
os.makedirs(SYNC_DATA_DIR, exist_ok=True)

@app.route('/api/sync/strategies', methods=['GET', 'POST'])
def sync_strategies():
    """同步策略数据 - 支持多设备共享"""
    filepath = os.path.join(SYNC_DATA_DIR, 'strategies.json')
    
    if request.method == 'GET':
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return jsonify(json.load(f))
            return jsonify([])
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.json
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return jsonify({"status": "saved", "count": len(data) if isinstance(data, list) else 1})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/api/sync/targets', methods=['GET', 'POST'])
def sync_targets():
    """同步跟踪目标 - 支持多设备共享"""
    filepath = os.path.join(SYNC_DATA_DIR, 'targets.json')
    
    if request.method == 'GET':
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return jsonify(json.load(f))
            return jsonify([])
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.json
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return jsonify({"status": "saved", "count": len(data) if isinstance(data, list) else 1})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/api/sync/wallets', methods=['GET', 'POST'])
def sync_wallets():
    """同步钱包数据 - 支持多设备共享 (注意: 私钥会存储在服务器)"""
    filepath = os.path.join(SYNC_DATA_DIR, 'wallets.json')
    
    if request.method == 'GET':
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return jsonify(json.load(f))
            return jsonify([])
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.json
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return jsonify({"status": "saved", "count": len(data) if isinstance(data, list) else 1})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@app.route('/copy-trade/dashboard')
def copy_trade_dashboard():
    address = request.args.get('address')
    return render_template('dashboard.html', address=address)

@app.route('/api/my-executions')
def get_my_executions():
    try:
        import config
        # 优先从请求参数获取地址
        target_address = request.args.get('address')
        if not target_address:
            target_address = config.FUNDER_ADDRESS
            
        # 直接从 API 读取我的历史成交
        # limit=50: 获取最近 50 条
        trades_df = fetcher.get_trades(wallet_address=target_address, limit=50, silent=True)
        
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
                    "market_slug": row.get('slug', row.get('market_slug', '')),
                    "condition_id": row.get('conditionId', row.get('market', '')),
                    "side": row.get('side', 'UNKNOWN'),
                    "size": size,  # 股数 (float)
                    "shares": size,  # 别名
                    "price": price,  # 每股价格
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
        # 优先从请求参数获取地址
        target_address = request.args.get('address')
        if not target_address:
            target_address = config.FUNDER_ADDRESS

        # 优先使用 CLOB Client (tester) 获取实时余额，它比 Data API (fetcher) 更准确
        # 注意：如果查询的是非默认钱包，只能用 Data API
        if target_address and target_address.lower() != config.FUNDER_ADDRESS.lower():
             cash = fetcher.get_user_cash_balance(target_address)
        elif tester:
            cash = tester.get_balance()
            # print(f"💰 [CLOB] 实时余额: ${cash:.2f}")
        else:
            # 兜底方案
            cash = fetcher.get_user_cash_balance(target_address)
            # print(f"⚠️ [DataAPI] 使用兜底余额: ${cash:.2f}")
            
        return jsonify({"cash": cash, "address": target_address})
    except Exception as e:
        print(f"❌ 获取余额失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/my-positions')
def get_my_positions():
    try:
        import config
        # 优先从请求参数获取地址
        target_address = request.args.get('address')
        if not target_address:
            target_address = config.FUNDER_ADDRESS
            
        # print(f"🔍 查询持仓: {target_address}")
        positions_df = fetcher.get_user_positions(target_address)
        
        if positions_df.empty:
            # print("❌ API 返回空持仓数据")
            return jsonify([])
            
        # print(f"✅ API 返回原始持仓数: {len(positions_df)}")
            
        # 数据清洗与过滤
        positions_df['size'] = pd.to_numeric(positions_df['size'], errors='coerce').fillna(0)
        positions_df['currentValue'] = pd.to_numeric(positions_df.get('currentValue', 0), errors='coerce').fillna(0)
        
        # 过滤掉极其微小的持仓 (Value < $0.01)
        valid_positions = positions_df[positions_df['currentValue'] > 0.01].copy()
        
        # print(f"✅ 过滤后有效持仓数: {len(valid_positions)}")
        
        return jsonify(valid_positions.to_dict('records'))
    except Exception as e:
        print(f"❌ 获取持仓异常: {e}")
        return jsonify([])

if __name__ == '__main__':
    # Ensure templates directory exists
    os.makedirs('templates', exist_ok=True)
    app.run(host='0.0.0.0', debug=True, port=5005)
