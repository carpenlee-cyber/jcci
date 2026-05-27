"""
Pydantic 数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class TaskSubmitRequest(BaseModel):
    """任务提交请求"""
    git_url: str = Field(..., description="Git 仓库地址")
    username: str = Field(..., description="Git 用户名")
    tag_old: str = Field(..., description="旧版本标签")
    tag_new: str = Field(..., description="新版本标签")
    max_depth: int = Field(default=5, ge=1, le=10, description="最大分析深度")
    password: Optional[str] = Field(None, description="Git 密码（可选）")
    
    # 埋点字段
    project_code: Optional[str] = Field("", description="项目编号")
    task_stage: Optional[str] = Field("", description="子任务阶段")
    user_ip: Optional[str] = Field("", description="用户IP")
    user_name: Optional[str] = Field("网页用户", description="用户名")
    user_id: Optional[str] = Field("web", description="用户ID")


class TaskResponse(BaseModel):
    """任务响应"""
    task_id: str
    status: str
    message: str
    queue_position: Optional[int] = None
    estimated_wait_minutes: Optional[int] = None


class TaskStatus(BaseModel):
    """任务状态"""
    task_id: str
    status: str
    git_url: str
    username: Optional[str] = None
    tag_old: str
    tag_new: str
    max_depth: int
    progress: float
    result_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    # 埋点字段
    project_code: Optional[str] = None
    task_stage: Optional[str] = None
    user_ip: Optional[str] = None
    user_name: Optional[str] = None
    user_id: Optional[str] = None


class TaskListResponse(BaseModel):
    """任务列表响应"""
    total: int
    tasks: list[TaskStatus]
