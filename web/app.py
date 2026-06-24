# app.py
# Flask Web 应用入口 - ETH K线展示（Replit 生产部署版）
import gzip
import os
from flask import Flask, jsonify, render_template, request
from api.kline_api import kline_bp
from api.structure_api import structure_bp
from api.backtest_api import backtest_bp
from api.cache_manager import kline_cache
from api.config import DEFAULT_LIMIT

app = Flask(__name__)
app.register_blueprint(kline_bp)
app.register_blueprint(structure_bp)
app.register_blueprint(backtest_bp)

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

# ── 生产入口（gunicorn 使用这个模块级 app 对象）──
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)

