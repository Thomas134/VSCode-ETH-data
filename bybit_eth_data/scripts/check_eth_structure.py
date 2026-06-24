# check_eth_structure.py
import sqlite3
import pandas as pd
from config import DB_PATH, init_directories

def check_eth_database_structure():
    """检查ETH数据库的详细结构"""
    print("=== ETH数据库结构详细检查 ===")
    print(f"数据库文件: {DB_PATH}")
    
    # 检查数据库文件是否存在
    if not DB_PATH.exists():
        print(f"✗ 数据库文件不存在: {DB_PATH}")
        return
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        
        # 1. 查看所有表
        tables_query = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        tables_df = pd.read_sql(tables_query, conn)
        
        print(f"\n1. 数据库中的表 ({len(tables_df)} 个):")
        for i, row in tables_df.iterrows():
            print(f"   {i+1}. {row['name']}")
        
        # 2. 专门检查K线数据表
        print("\n2. K线数据表详细结构:")
        kline_tables = tables_df[tables_df['name'].str.contains('kline')]
        
        if len(kline_tables) == 0:
            print("   未找到K线数据表!")
            return
        
        for table_name in kline_tables['name']:
            print(f"\n   📊 表: {table_name}")
            
            # 查看表结构
            structure_query = f"PRAGMA table_info({table_name});"
            structure_df = pd.read_sql(structure_query, conn)
            
            print(f"   字段数: {len(structure_df)}")
            print("   字段详情:")
            for _, field in structure_df.iterrows():
                not_null = "NOT NULL" if field['notnull'] else ""
                primary_key = f"PRIMARY KEY({field['pk']})" if field['pk'] > 0 else ""
                print(f"     - {field['name']} ({field['type']}) {not_null} {primary_key}".strip())
            
            # 查看记录数
            count_query = f"SELECT COUNT(*) as count FROM {table_name};"
            count_df = pd.read_sql(count_query, conn)
            record_count = count_df.iloc[0]['count']
            print(f"   记录数: {record_count}")
            
            # 查看时间范围
            if record_count > 0:
                time_query = f"""
                SELECT 
                    MIN(open_time) as first_time,
                    MAX(open_time) as last_time,
                    COUNT(*) as total
                FROM {table_name};
                """
                time_df = pd.read_sql(time_query, conn)
                
                if time_df.iloc[0]['first_time']:
                    first_dt = pd.to_datetime(time_df.iloc[0]['first_time'], unit='ms')
                    last_dt = pd.to_datetime(time_df.iloc[0]['last_time'], unit='ms')
                    print(f"   时间范围: {first_dt} 到 {last_dt}")
                    print(f"   覆盖天数: {(last_dt - first_dt).days} 天")
            
            # 查看索引
            indexes_query = f"PRAGMA index_list({table_name});"
            indexes_df = pd.read_sql(indexes_query, conn)
            
            if not indexes_df.empty:
                print(f"   索引 ({len(indexes_df)} 个):")
                for _, index in indexes_df.iterrows():
                    unique = "唯一" if index['unique'] else "非唯一"
                    print(f"     - {index['name']} ({unique})")
                    
                    # 查看索引字段
                    index_info_query = f"PRAGMA index_info({index['name']});"
                    index_info_df = pd.read_sql(index_info_query, conn)
                    if not index_info_df.empty:
                        fields = ", ".join(index_info_df['name'].tolist())
                        print(f"       字段: {fields}")
        
        # 3. 查看表关系（如果有的话）
        print("\n3. 数据库关系信息:")
        foreign_keys_query = "SELECT * FROM sqlite_master WHERE sql LIKE '%FOREIGN KEY%';"
        foreign_keys_df = pd.read_sql(foreign_keys_query, conn)
        
        if not foreign_keys_df.empty:
            print("   发现外键约束:")
            for _, fk in foreign_keys_df.iterrows():
                print(f"     - {fk['name']}: {fk['sql'][:100]}...")
        else:
            print("   无外键约束")
        
        # 4. 数据库信息
        print("\n4. 数据库基本信息:")
        page_size_query = "PRAGMA page_size;"
        page_count_query = "PRAGMA page_count;"
        encoding_query = "PRAGMA encoding;"
        
        page_size = pd.read_sql(page_size_query, conn).iloc[0, 0]
        page_count = pd.read_sql(page_count_query, conn).iloc[0, 0]
        encoding = pd.read_sql(encoding_query, conn).iloc[0, 0]
        
        db_size_kb = (page_size * page_count) / 1024
        print(f"   页面大小: {page_size} bytes")
        print(f"   总页数: {page_count}")
        print(f"   数据库大小: {db_size_kb:.2f} KB")
        print(f"   编码: {encoding}")
        
        # 5. 查看触发器（如果有的话）
        triggers_query = "SELECT name FROM sqlite_master WHERE type='trigger';"
        triggers_df = pd.read_sql(triggers_query, conn)
        
        if not triggers_df.empty:
            print(f"\n5. 触发器 ({len(triggers_df)} 个):")
            for _, trigger in triggers_df.iterrows():
                print(f"   - {trigger['name']}")
        else:
            print("\n5. 触发器: 无")
        
    except Exception as e:
        print(f"检查数据库时出错: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    check_eth_database_structure()