"""
重建任务数据库表（新增埋点字段）

此脚本会删除旧的 analysis_tasks 表并创建新表，包含以下新字段：
- project_code: 项目编号
- task_stage: 子任务阶段
- user_ip: 用户IP
- user_name: 用户名
- user_id: 用户ID

⚠️ 警告：此操作会删除所有现有任务数据！
"""

import sqlite3
import os

# 数据库路径
db_path = os.path.join(os.path.dirname(__file__), "task_manager.db")

print(f"数据库路径: {db_path}")

if not os.path.exists(db_path):
    print("❌ 数据库文件不存在")
    exit(1)

print("\n⚠️  警告：此操作将删除所有现有任务数据！")
confirm = input("确认继续？(yes/no): ")

if confirm.lower() != 'yes':
    print("已取消")
    exit(0)

# 连接数据库
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 删除旧表
print("\n🗑️  删除旧表...")
cursor.execute("DROP TABLE IF EXISTS analysis_tasks")
conn.commit()
print("✓ 旧表已删除")

# 创建新表
print("\n📝 创建新表...")
cursor.execute('''
    CREATE TABLE analysis_tasks (
        task_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        git_url TEXT NOT NULL,
        username TEXT,
        tag_old TEXT,
        tag_new TEXT,
        max_depth INTEGER DEFAULT 5,
        progress REAL DEFAULT 0.0,
        result_url TEXT,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        output_dir TEXT,
        has_password BOOLEAN DEFAULT 0,
        project_code TEXT,
        task_stage TEXT,
        user_ip TEXT,
        user_name TEXT,
        user_id TEXT
    )
''')
conn.commit()
print("✓ 新表已创建")

# 验证表结构
print("\n🔍 验证表结构...")
cursor.execute("PRAGMA table_info(analysis_tasks)")
columns = cursor.fetchall()

print("\n表字段列表:")
for col in columns:
    print(f"  - {col[1]} ({col[2]})")

conn.close()

print("\n✅ 数据库重建完成！")
print("\n新增字段:")
print("  - project_code: 项目编号")
print("  - task_stage: 子任务阶段")
print("  - user_ip: 用户IP")
print("  - user_name: 用户名")
print("  - user_id: 用户ID")
