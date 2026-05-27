"""
任务管理 API
"""
from fastapi import APIRouter, HTTPException
from app.models import TaskSubmitRequest, TaskResponse, TaskStatus as TaskStatusModel, TaskListResponse
from app.services.task_service import TaskService, TaskStatus
from app.config import settings

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# 创建任务服务实例
task_service = TaskService(settings.DB_PATH)


@router.post("/submit", response_model=TaskResponse)
async def submit_task(request: TaskSubmitRequest):
    """
    提交分析任务
    
    Args:
        request: 任务提交请求
        
    Returns:
        任务响应
    """
    try:
        # 创建任务
        task_id = task_service.create_task(
            git_url=request.git_url,
            username=request.username,
            tag_old=request.tag_old,
            tag_new=request.tag_new,
            max_depth=request.max_depth,
            password=request.password,
            project_code=request.project_code,
            task_stage=request.task_stage,
            user_ip=request.user_ip,
            user_name=request.user_name,
            user_id=request.user_id
        )
        
        return TaskResponse(
            task_id=task_id,
            status="pending",
            message="任务已提交",
            queue_position=1,
            estimated_wait_minutes=5
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}", response_model=TaskStatusModel)
async def get_task_status(task_id: str):
    """
    获取任务状态
    
    Args:
        task_id: 任务 ID
        
    Returns:
        任务状态
    """
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskStatusModel(**task)


@router.get("/", response_model=TaskListResponse)
async def list_tasks(limit: int = 20, offset: int = 0):
    """
    获取任务列表
    
    Args:
        limit: 返回数量限制
        offset: 偏移量
        
    Returns:
        任务列表
    """
    tasks = task_service.list_tasks(limit=limit, offset=offset)
    total = task_service.count_tasks()
    
    return TaskListResponse(
        total=total,
        tasks=[TaskStatusModel(**task) for task in tasks]
    )


@router.delete("/{task_id}")
async def cancel_task(task_id: str):
    """
    取消任务
    
    Args:
        task_id: 任务 ID
        
    Returns:
        操作结果
    """
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 只能取消 pending 状态的任务
    if task['status'] != TaskStatus.PENDING:
        raise HTTPException(status_code=400, detail="Can only cancel pending tasks")
    
    # 更新状态为 failed
    task_service.update_task_status(
        task_id=task_id,
        status=TaskStatus.FAILED,
        error_message="用户主动取消"
    )
    
    return {"message": "Task cancelled"}
