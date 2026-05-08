
create_tables = '''
CREATE TABLE project (
    project_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    git_url TEXT NOT NULL,
    branch TEXT NOT NULL,
    commit_or_branch_new TEXT NOT NULL,
    commit_or_branch_old TEXT,
    create_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE class (
    class_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    filepath TEXT,
    access_modifier TEXT,
    class_type TEXT NOT NULL,
    class_name TEXT NOT NULL,
    package_name TEXT NOT NULL,
    extends_class TEXT,
    implements TEXT,
    annotations TEXT,
    documentation TEXT,
    is_controller REAL,
    controller_base_url TEXT,
    commit_or_branch TEXT,
    change_type TEXT DEFAULT 'UNCHANGED',
    create_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE import (
    import_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    import_path TEXT,
    is_static REAL,
    is_wildcard REAL,
    create_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE field (
    field_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER,
    project_id INTEGER NOT NULL,
    annotations TEXT,
    access_modifier TEXT,
    field_type TEXT,
    field_name TEXT,
    is_static REAL,
    start_line INTEGER,
    end_line INTEGER,
    documentation TEXT,
    change_type TEXT DEFAULT 'UNCHANGED',
    create_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))
);


CREATE TABLE methods (
    method_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    annotations TEXT,
    access_modifier TEXT,
    return_type TEXT,
    method_name TEXT NOT NULL,
    parameters TEXT,
    body TEXT,
    method_invocation_map TEXT,
    is_static REAL,
    is_abstract REAL,
    is_api REAL,
    api_path TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    documentation TEXT,
    change_type TEXT DEFAULT 'UNCHANGED',
    create_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))
);


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
);

-- v3.2新增：方法字段访问记录表
CREATE TABLE method_field_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    access_type TEXT NOT NULL CHECK(access_type IN ('READ', 'WRITE', 'METHOD_CALL')),
    line_number INTEGER,
    field_type TEXT,
    project_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (method_id) REFERENCES methods(method_id) ON DELETE CASCADE
);

-- v3.2新增：优化索引
CREATE INDEX idx_mfa_method ON method_field_access(method_id);
CREATE INDEX idx_mfa_field ON method_field_access(field_name, project_id);
CREATE INDEX idx_mfa_project ON method_field_access(project_id);

-- v3.2新增：字段影响关联表
CREATE TABLE field_impact (
    impact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id INTEGER NOT NULL,
    method_id INTEGER NOT NULL,
    impact_type TEXT NOT NULL, -- 'DIRECT_READ', 'DIRECT_WRITE', 'SERIALIZATION', 'REFLECTION'
    impact_level TEXT NOT NULL DEFAULT 'MEDIUM', -- 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    project_id INTEGER NOT NULL,
    FOREIGN KEY (field_id) REFERENCES field(field_id),
    FOREIGN KEY (method_id) REFERENCES methods(method_id)
);

'''