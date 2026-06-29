# app.py
# Flask Web 应用入口 - ETH K线展示（支持WebSocket实时推送）
import gzip
import os
import threading
import time
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from api.kline_api import kline_bp
from api.structure_api import structure_bp
from api.backtest_api import backtest_bp
from api.realtime_kline_api import realtime_bp, get_bybit_latest
from api.cache_manager import kline_cache
from api.config import DEFAULT_LIMIT

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

# ── WebSocket 事件处理 ──
@socketio.on('connect')
def handle_connect():
    print('[WebSocket] 客户端已连接')

@socketio.on('disconnect')
def handle_disconnect():
    print('[WebSocket] 客户端已断开')

@socketio.on('subscribe_kline')
def handle_subscribe_kline(data):
    """客户端订阅K线实时推送"""
    interval = data.get('interval', '1m')
    print(f'[WebSocket] 客户端订阅 {interval} K线')
    
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

# ── 后台线程：定时推送最新K线 ──
def kline_pusher():
    """后台线程：每秒检查并推送最新K线"""
    last_klines = {}
    
    while True:
        try:
            socketio.sleep(1)  # 每秒检查一次
            
            for interval in ['1m', '5m', '15m', '1h', '4h', '1d']:
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
                    print(f'[Kline Pusher Error] {interval}: {e}')
                    
        except Exception as e:
            print(f'[Kline Pusher Error] {e}')
            time.sleep(5)  # 出错后等待5秒再重试

# ── 启动后台推送线程 ──
pusher_thread = None

@socketio.on('connect')
def start_pusher():
    global pusher_thread
    if pusher_thread is None or not pusher_thread.is_alive():
        pusher_thread = socketio.start_background_task(kline_pusher)
        print('[WebSocket] 启动K线推送线程')

# ── 生产入口 ──
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)