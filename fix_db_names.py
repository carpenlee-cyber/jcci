"""
修复数据库文件名格式
将 mall_baseline_XXX.db 重命名为 mall_XXX_baseline.db
"""
import os
import shutil

def fix_db_filenames():
    """修复数据库文件名"""
    result_dir = os.path.join(os.path.dirname(__file__), 'src', 'jcci', 'analyze_result')
    
    print("=" * 80)
    print("修复数据库文件名格式")
    print("=" * 80)
    print(f"目标目录: {result_dir}\n")
    
    # 遍历所有基线目录
    baseline_dirs = [d for d in os.listdir(result_dir) 
                     if os.path.isdir(os.path.join(result_dir, d)) and not d.startswith('.')]
    
    if not baseline_dirs:
        print("✅ 没有找到基线目录")
        return
    
    for baseline_dir_name in baseline_dirs:
        baseline_dir = os.path.join(result_dir, baseline_dir_name)
        print(f"📁 检查目录: {baseline_dir_name}")
        
        # 查找旧格式的数据库文件
        files = os.listdir(baseline_dir)
        old_db_files = [f for f in files if f.startswith('mall_baseline_') and f.endswith('.db')]
        
        for old_db_file in old_db_files:
            # 提取commit短标识符
            # 格式: mall_baseline_e0f029b9a6d.db
            commit_short = old_db_file.replace('mall_baseline_', '').replace('.db', '')
            
            # 构造新文件名
            new_db_file = f"mall_{commit_short}_baseline.db"
            
            old_path = os.path.join(baseline_dir, old_db_file)
            new_path = os.path.join(baseline_dir, new_db_file)
            
            if os.path.exists(new_path):
                print(f"   ⚠️  新文件已存在，跳过: {new_db_file}")
            else:
                try:
                    shutil.move(old_path, new_path)
                    print(f"   ✅ 重命名: {old_db_file} -> {new_db_file}")
                except Exception as e:
                    print(f"   ❌ 重命名失败: {e}")
                    print(f"      可能文件被占用，请关闭相关程序后重试")
        
        print()
    
    print("=" * 80)
    print("修复完成！")
    print("=" * 80)

if __name__ == "__main__":
    fix_db_filenames()
