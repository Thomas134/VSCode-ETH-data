# bybit_client.py - 使用 requests 库
import requests
import pandas as pd
import time
import hmac
import hashlib
from urllib.parse import urlencode
from bybit_config import BYBIT_API_KEY, BYBIT_API_SECRET

class BybitClient:
    def __init__(self):
        self.base_url = "https://api.bybit.com"
        self.api_key = BYBIT_API_KEY
        self.api_secret = BYBIT_API_SECRET
        self.session = requests.Session()
        print("✓ Bybit客户端初始化成功 (使用requests)")

    def _generate_signature(self, params, timestamp, recv_window="5000"):
        """生成API签名"""
        param_str = f"{timestamp}{self.api_key}{recv_window}{params}"
        signature = hmac.new(
            bytes(self.api_secret, "utf-8"),
            param_str.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature

    def get_klines(self, symbol, interval, start_time=None, end_time=None, limit=200):
        """
        获取K线数据 - 使用公共接口，不需要认证
        """
        try:
            url = f"{self.base_url}/v5/market/kline"
            params = {
                "category": "linear",  # 永续合约
                "symbol": symbol,
                "interval": interval,
                "limit": str(limit)
            }
            
            if start_time:
                params["start"] = str(start_time)
            if end_time:
                params["end"] = str(end_time)
            
            response = self.session.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get('retCode') == 0:
                kline_list = data.get('result', {}).get('list', [])
                # API返回的数据是从最新到最旧，我们需要反转它
                return list(reversed(kline_list))
            else:
                print(f"API错误: {data.get('retMsg', 'Unknown error')}")
                return None
                
        except Exception as e:
            print(f"获取K线数据失败: {e}")
            return None

    def get_klines_batch(self, symbol, interval, total_limit=1000):
        """
        分页获取K线（带频率保护）
        Bybit限制: 50次/秒/IP
        保守策略: 每秒最多5次请求
        """
        all_klines = []
        end_time = None
        request_count = 0
        MAX_RPS = 45  # 每秒45次，接近Bybit 50次限制
        
        while len(all_klines) < total_limit:
            # 频率保护: 每45次请求暂停1秒
            if request_count >= MAX_RPS:
                time.sleep(1)
                request_count = 0
            
            # 计算本次需要获取的数量
            remaining = total_limit - len(all_klines)
            batch_limit = min(200, remaining)
            
            batch = self.get_klines(
                symbol=symbol,
                interval=interval,
                end_time=end_time,
                limit=batch_limit
            )
            
            request_count += 1
            
            if not batch:
                break
            
            all_klines.extend(batch)
            
            # 下一批从最早时间之前开始
            earliest_time = int(batch[0][0])
            end_time = earliest_time - 1
            
            # 如果返回少于200条，说明数据到头了
            if len(batch) < 200:
                break
        
        return all_klines

    def test_connection(self):
        """测试API连接"""
        try:
            url = f"{self.base_url}/v5/market/time"
            response = self.session.get(url, timeout=10)
            data = response.json()
            
            if data.get('retCode') == 0:
                print("✓ Bybit API连接测试成功")
                return True
            else:
                print(f"✗ Bybit API连接测试失败: {data.get('retMsg', 'Unknown error')}")
                return False
        except Exception as e:
            print(f"✗ 连接测试异常: {e}")
            return False

def get_bybit_client():
    return BybitClient()

if __name__ == "__main__":
    client = get_bybit_client()
    if client.test_connection():
        # 测试获取少量数据
        print("测试获取K线数据...")
        klines = client.get_klines("ETHUSDT", "1", limit=5)
        if klines:
            print(f"✓ 成功获取 {len(klines)} 条K线数据")
            for kline in klines:
                print(f"  时间: {kline[0]}, 开: {kline[1]}, 高: {kline[2]}, 低: {kline[3]}, 收: {kline[4]}, 量: {kline[5]}")
        else:
            print("✗ 获取K线数据失败")
    else:
        print("✗ API连接测试失败")