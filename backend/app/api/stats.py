"""
统计分析 API
"""
from fastapi import APIRouter, HTTPException
from app.config import settings

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/tracking")
async def get_tracking_stats():
    """获取埋点数据统计"""
    try:
        import sqlite3
        conn = sqlite3.connect(settings.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT project_code, COUNT(*) as count 
            FROM tasks 
            WHERE project_code != '' 
            GROUP BY project_code
            ORDER BY count DESC
        """)
        project_stats = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT user_name, COUNT(*) as count 
            FROM tasks 
            GROUP BY user_name
            ORDER BY count DESC
        """)
        user_stats = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT COUNT(*) as total FROM tasks")
        total_tasks = cursor.fetchone()['total']
        
        conn.close()
        
        return {
            "total_tasks": total_tasks,
            "by_project": project_stats,
            "by_user": user_stats
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
