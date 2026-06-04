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
    """提交分析任务（含去重检查）"""
    try:
        # 第零步：验证 Git tag/commit 是否在远程仓库中真实存在
        is_valid, validation_error = task_service.validate_git_refs(
            request.git_url, request.tag_old, request.tag_new
        )
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Git 引用验证失败: {validation_error}"
            )
        
        # 第一步：检查是否有相同参数的活跃任务（pending 或 running）
        active = task_service.find_active_task(
            git_url=request.git_url,
            tag_old=request.tag_old,
            tag_new=request.tag_new,
            max_depth=request.max_depth,
            project_code=request.project_code or "",
            task_stage=request.task_stage or ""
        )
        
        if active and active.get('task_id'):
            status_label = "排队中" if active['status'] == 'pending' else "执行中"
            return TaskResponse(
                task_id=active['task_id'],
                status=active['status'],
                message=f"相同的分析任务正在{status_label}（{active['task_id']}），请勿重复提交",
                duplicate=True,
                result_url=None
            )
        
        # 第二步：检查是否有相同参数的已完成任务
        duplicate = task_service.find_duplicate_task(
            git_url=request.git_url,
            tag_old=request.tag_old,
            tag_new=request.tag_new,
            max_depth=request.max_depth,
            project_code=request.project_code or "",
            task_stage=request.task_stage or ""
        )
        
        if duplicate and duplicate.get('result_url'):
            return TaskResponse(
                task_id=duplicate['task_id'],
                status=duplicate['status'],
                message="已存在相同的分析结果，可直接查看",
                duplicate=True,
                result_url=duplicate['result_url']
            )
        
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=TaskListResponse)
async def list_tasks(limit: int = 20, offset: int = 0):
    """获取任务列表"""
    tasks = task_service.list_tasks(limit=limit, offset=offset)
    total = task_service.count_tasks()
    
    return TaskListResponse(
        total=total,
        tasks=[TaskStatusModel(**task) for task in tasks]
    )


@router.get("/{task_id}", response_model=TaskStatusModel)
async def get_task_status(task_id: str):
    """获取任务状态"""
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskStatusModel(**task)


@router.delete("/{task_id}")
async def cancel_task(task_id: str):
    """取消任务"""
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task['status'] != TaskStatus.PENDING:
        raise HTTPException(status_code=400, detail="Can only cancel pending tasks")
    
    task_service.update_task_status(
        task_id=task_id,
        status=TaskStatus.FAILED,
        error_message="用户主动取消"
    )
    
    return {"message": "Task cancelled"}
