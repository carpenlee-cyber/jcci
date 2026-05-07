"""
创建LLM分析结果缓存表

此脚本会在数据库中创建llm_analysis_cache表，用于存储AI分析结果
"""

import sqlite3
import os
from datetime import datetime

# 数据库路径
DB_PATH = r"C:\Users\carpe\VisualStudioProject\TestPlatform\jcci\src\jcci\carpenlee-cyber_mall_baseline_d9501e9.db"

def create_llm_cache_table():
    """创建LLM分析结果缓存表"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 检查表是否已存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llm_analysis_cache'")
        if cursor.fetchone():
            print("✅ LLM分析缓存表已存在")
            return True
        
        # 创建LLM分析缓存表
        create_table_sql = """
        CREATE TABLE llm_analysis_cache (
            analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            -- 分析类型：method（方法分析）或 chain（调用链分析）
            analysis_type TEXT NOT NULL CHECK(analysis_type IN ('method', 'chain')),
            
            -- 方向：upwards（向上）或 downwards（向下）
            direction TEXT NOT NULL CHECK(direction IN ('upwards', 'downwards')),
            
            -- 方法标识
            class_name TEXT NOT NULL,
            method_name TEXT NOT NULL,
            method_signature TEXT,
            
            -- 变更类型
            change_type TEXT,
            
            -- 调用链索引（仅chain类型使用）
            chain_index INTEGER,
            
            -- 输入参数（JSON格式，用于去重和追溯）
            input_params TEXT,
            
            -- LLM分析结果
            analysis_result TEXT NOT NULL,
            
            -- 使用的模型
            model_name TEXT DEFAULT 'moonshotai/kimi-k2.6',
            
            -- Token使用情况
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            
            -- 分析耗时（秒）
            analysis_duration REAL,
            
            -- 是否为全新分析（false表示从缓存读取）
            is_fresh_analysis BOOLEAN DEFAULT 1,
            
            -- 用户会话ID（可选，用于追踪）
            session_id TEXT,
            
            -- 时间戳
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            -- 唯一约束：相同类型+方向+方法+变更类型+chain_index的组合只存储一次
            UNIQUE(analysis_type, direction, class_name, method_name, change_type, chain_index)
        )
        """
        
        cursor.execute(create_table_sql)
        
        # 创建索引以提高查询性能
        indexes = [
            "CREATE INDEX idx_llm_cache_type_direction ON llm_analysis_cache(analysis_type, direction)",
            "CREATE INDEX idx_llm_cache_method ON llm_analysis_cache(class_name, method_name)",
            "CREATE INDEX idx_llm_cache_created ON llm_analysis_cache(created_at)",
            "CREATE INDEX idx_llm_cache_session ON llm_analysis_cache(session_id)"
        ]
        
        for index_sql in indexes:
            try:
                cursor.execute(index_sql)
            except sqlite3.OperationalError as e:
                print(f"⚠️  索引创建警告: {e}")
        
        conn.commit()
        print("✅ LLM分析缓存表创建成功")
        print("\n表结构:")
        print("-" * 80)
        
        # 显示表结构
        cursor.execute("PRAGMA table_info(llm_analysis_cache)")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  {col[1]:20s} {col[2]:15s} {'NOT NULL' if col[3] else 'NULL':10s} {'DEFAULT ' + str(col[4]) if col[4] else '':20s}")
        
        return True
        
    except Exception as e:
        print(f"❌ 创建表失败: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()


def verify_table():
    """验证表是否正确创建"""
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llm_analysis_cache'")
        if not cursor.fetchone():
            print("❌ 表不存在")
            return False
        
        # 检查记录数
        cursor.execute("SELECT COUNT(*) FROM llm_analysis_cache")
        count = cursor.fetchone()[0]
        print(f"\n✅ 表验证成功，当前记录数: {count}")
        
        return True
        
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        return False
        
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 80)
    print("创建LLM分析结果缓存表")
    print("=" * 80)
    print(f"数据库路径: {DB_PATH}")
    print()
    
    # 创建表
    success = create_llm_cache_table()
    
    if success:
        # 验证表
        verify_table()
        
        print("\n" + "=" * 80)
        print("完成！现在可以在streamlit_app.py中使用LLM缓存功能")
        print("=" * 80)
    else:
        print("\n❌ 创建失败，请检查错误信息")
