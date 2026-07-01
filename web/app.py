# app.py
# Flask Web 应用入口 - ETH K线展示（支持WebSocket实时推送）
import gzip
import os
import sys
import threading
import time
from pathlib import Path
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from api.kline_api import kline_bp
from api.structure_api import structure_bp
from api.backtest_api import backtest_bp
from api.realtime_kline_api import realtime_bp, get_bybit_latest
from api.cache_manager import kline_cache
from api.config import DEFAULT_LIMIT
from api.logger import setup_logging, get_logger

# 添加 scripts 目录到 sys.path，以便导入数据流水线模块
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "bybit_eth_data" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# 初始化日志
setup_logging()
logger = get_logger("web.app")

app = Flask(__name__)
app.register_blueprint(kline_bp)
app.register_blueprint(structure_bp)
app.register_blueprint(backtest_bp)
app.register_blueprint(realtime_bp)

# 初始化 SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ── gzip 压缩中间件：对 API 响应自动压缩 ──
MIN_GZIP_SIZE = 1024

@app.after_request
def gzip_response(response):
    if (response.content_type == 'application/json'
            and len(response.data) > MIN_GZIP_SIZE
            and 'gzip' in request.headers.get('Accept-Encoding', '')):
        compressed = gzip.compress(response.data)
        response.data = compressed
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Content-Length'] = str(len(compressed))
    return response

@app.route('/')
def index():
    return render_template('index.html', config={"DEFAULT_LIMIT": DEFAULT_LIMIT})

@app.route('/structure')
def structure():
    return render_template('structure.html', config={"DEFAULT_LIMIT": DEFAULT_LIMIT})

@app.route('/api/cache/clear')
def clear_cache():
    kline_cache.clear_all()
    return jsonify({"status": "ok", "message": "缓存已清除"})

# ── 订阅管理 ──
# 记录每个客户端订阅的时间级别: {sid: set(intervals)}
client_subscriptions = {}

# ── WebSocket 事件处理 ──
@socketio.on('connect')
def handle_connect():
    logger.info("WebSocket 客户端已连接: %s", request.sid)
    client_subscriptions[request.sid] = set()

@socketio.on('disconnect')
def handle_disconnect():
    logger.info("WebSocket 客户端已断开: %s", request.sid)
    client_subscriptions.pop(request.sid, None)

@socketio.on('subscribe_kline')
def handle_subscribe_kline(data):
    """客户端订阅K线实时推送"""
    interval = data.get('interval', '1m')
    # 确保 sid 存在（connect 事件可能晚于 subscribe）
    if request.sid not in client_subscriptions:
        client_subscriptions[request.sid] = set()
    client_subscriptions[request.sid].add(interval)
    logger.info("WebSocket 客户端 %s 订阅 %s K线", request.sid, interval)
    
    # 立即发送一次当前最新数据
    latest_klines = get_bybit_latest(interval, limit=1)
    if latest_klines:
        k = latest_klines[0]
        emit('kline_update', {
            'time': k['start_time'] // 1000,
            'open': k['open'],
            'high': k['high'],
            'low': k['low'],
            'close': k['close'],
            'volume': k['volume'],
            'interval': interval,
            'is_new': False
        })

@socketio.on('unsubscribe_kline')
def handle_unsubscribe_kline(data):
    """客户端取消订阅"""
    interval = data.get('interval', '1m')
    if request.sid in client_subscriptions:
        client_subscriptions[request.sid].discard(interval)
        logger.info("WebSocket 客户端 %s 取消订阅 %s K线", request.sid, interval)

def get_active_intervals():
    """获取所有客户端订阅的时间级别集合"""
    active = set()
    for intervals in client_subscriptions.values():
        active.update(intervals)
    return active

# ── 后台线程：定时推送最新K线 ──
def kline_pusher():
    """后台线程：每秒检查并推送最新K线（只推送有订阅的）"""
    last_klines = {}
    
    while True:
        try:
            socketio.sleep(1)  # 每秒检查一次
            
            # 只查询有客户端订阅的时间级别
            active_intervals = get_active_intervals()
            
            for interval in active_intervals:
                try:
                    latest = get_bybit_latest(interval, limit=1)
                    if not latest:
                        continue
                    
                    k = latest[0]
                    k_time = k['start_time']
                    
                    # 检查是否有更新（时间变化或价格变化）
                    prev_key = f"{interval}_{k_time}"
                    if prev_key not in last_klines:
                        # 新K线或首次推送
                        last_klines[prev_key] = k['close']
                        
                        socketio.emit('kline_update', {
                            'time': k_time // 1000,
                            'open': k['open'],
                            'high': k['high'],
                            'low': k['low'],
                            'close': k['close'],
                            'volume': k['volume'],
                            'interval': interval,
                            'is_new': True
                        })
                    elif last_klines[prev_key] != k['close']:
                        # 价格有变化，推送更新
                        last_klines[prev_key] = k['close']
                        
                        socketio.emit('kline_update', {
                            'time': k_time // 1000,
                            'open': k['open'],
                            'high': k['high'],
                            'low': k['low'],
                            'close': k['close'],
                            'volume': k['volume'],
                            'interval': interval,
                            'is_new': False
                        })
                except Exception as e:
                    logger.error("Kline Pusher Error [%s]: %s", interval, e)

        except Exception as e:
            logger.error("Kline Pusher Error: %s", e)
            time.sleep(5)  # 出错后等待5秒再重试

# ── 启动后台推送线程 ──
pusher_thread = None

@socketio.on('connect')
def start_pusher():
    global pusher_thread
    if pusher_thread is None or not pusher_thread.is_alive():
        pusher_thread = socketio.start_background_task(kline_pusher)
        logger.info("WebSocket 启动K线推送线程")

# ── 数据流水线：拉取原始K线 → 全量更新结构K线 ──
def run_data_pipeline():
    """后台数据流水线：启动时自动执行 fetch_range → structure_engine"""
    logger.info("=" * 50)
    logger.info("数据Pipeline启动: Step 1/2 拉取原始K线数据...")
    try:
        from fetch_range import main as fetch_main
        fetch_main()
        logger.info("数据Pipeline: 原始K线拉取完成")
    except Exception as e:
        logger.error("数据Pipeline: 拉取原始K线失败: %s", e)
        return

    logger.info("数据Pipeline: Step 2/2 全量更新结构K线...")
    try:
        from structure_engine import process_all_intervals
        process_all_intervals()
        logger.info("数据Pipeline: 结构K线更新完成")
    except Exception as e:
        logger.error("数据Pipeline: 结构K线更新失败: %s", e)
        return

    logger.info("数据Pipeline全部完成!")
    logger.info("=" * 50)

# ── 生产入口 ──
if __name__ == '__main__':
    # 启动后台数据流水线（daemon线程，不阻塞Web服务启动）
    pipeline_thread = threading.Thread(target=run_data_pipeline, daemon=True, name="data-pipeline")
    pipeline_thread.start()
    logger.info("后台数据流水线已启动（fetch_range → structure_engine）")

    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)