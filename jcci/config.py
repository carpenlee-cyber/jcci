# -*- coding: UTF-8 -*-
import os
from jcci.utils.path_utils import PROJECT_ROOT

# Git 项目克隆根目录（默认在项目根目录下的 projects/ 子目录）
# 可以通过环境变量 JCCI_PROJECTS_DIR 覆盖
project_path = os.environ.get('JCCI_PROJECTS_DIR', os.path.join(PROJECT_ROOT, 'projects'))

# 用户数据库存储目录（默认在项目根目录下的 databases/ 子目录）
# 可以通过环境变量 JCCI_DB_DIR 覆盖
db_dir = os.environ.get('JCCI_DB_DIR', os.path.join(PROJECT_ROOT, 'databases'))
os.makedirs(db_dir, exist_ok=True)

# ignore file pattern
ignore_file = ['*/pom.xml', '*/test/*', '*.sh', '*.md', '*/checkstyle.xml', '*.yml', '.git/*']
# project package startswith
package_prefix = ['com.', 'cn.', 'net.']
# Whether to reparse the class when there is class data in the database
reparse_class = True
