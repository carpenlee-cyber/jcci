import json
import os
import sys
import time
import atexit
import logging
import datetime
import fnmatch
from . import config as config
from .database import SqliteHelper
from .java_parse import JavaParse, calculate_similar_score_method_params
from . import mapper_parse as mapper_parse
from . import diff_parse as diff_parse
from . import graph as graph
from . import constant as constant

# 导入变更类型分析器
try:
    from .change_type_analyzer import ChangeTypeAnalyzer
except ImportError:
    ChangeTypeAnalyzer = None

logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)


class JCCI(object):
    def __init__(self, git_url, username):
        self.git_url = git_url
        self.username: str = username
        self.branch_name: str = ''
        self.commit_or_branch_new: str = ''  # 用于Git操作的原始值（完整tag或commit hash）
        self.commit_or_branch_old: str = ''  # 用于Git操作的原始值（完整tag或commit hash）
        self.commit_short_new: str = ''      # 用于数据库和文件命名的短标识符
        self.commit_short_old: str = ''      # 用于数据库和文件命名的短标识符
        self.project_id: int = -1
        self.cci_filepath: str = ''
        self.project_name: str = ''
        self.file_path: str = ''
        self.sqlite = SqliteHelper(config.db_path + '/' + username + '_jcci.db')
        self.view = graph.Graph()
        self.t1 = datetime.datetime.now()
        self.need_analyze_obj_list = []
        self.analyzed_obj_set = []
        self.diff_parse_map = {}
        self.xml_parse_results_new = {}
        self.xml_parse_results_old = {}

    @staticmethod
    def _normalize_commit_or_tag(identifier: str) -> str:
        """
        标准化commit hash或tag标识符
        
        规则：
        - 如果是commit hash（40位十六进制字符串），截取前8位
        - 如果是长tag（长度>11且不是40位十六进制），取最后11个字符作为短标识符
        - 如果是短tag或短commit（长度<=11），保持不变
        
        例如：
        - dd6569c3558f79af5b21aad601349e0f029b9a6d -> dd6569c3 (commit hash，前8位)
        - MIX_LJ01.BUP_BUP3_UAT_UAT_00.00.01_SUMMER_20260403_01 -> 20260403_01 (tag，后11位)
        - d9501e9 -> d9501e9 (保持不变)
        
        Args:
            identifier: commit hash或tag字符串
            
        Returns:
            标准化后的标识符
        """
        import re
        
        # 判断是否为40位commit hash（十六进制字符串）
        if len(identifier) == 40 and re.match(r'^[0-9a-f]{40}$', identifier, re.IGNORECASE):
            # Commit hash：截取前8位
            return identifier[:8]
        elif len(identifier) > 11:
            # 长tag：取最后11个字符
            return identifier[-11:]
        else:
            # 短标识符：保持不变
            return identifier

    # Step 1.1
    def _can_analyze(self, filepath, cci_file_path):
        # 已有分析结果
        if os.path.exists(cci_file_path):
            logging.info('Has analyze result, skip!')
            with open(cci_file_path, 'r') as read:
                result = read.read()
                result_json = json.loads(result)
                # print(result, flush=True)
                print(f'Impacted api list: {result_json["impacted_api_list"]}', flush=True)
            sys.exit(0)

        # 正在分析
        wait_index = 0
        occupy_filepath = os.path.join(filepath, 'Occupy.ing')
        atexit.register(self._clean_occupy, occupy_filepath)
        while os.path.exists(occupy_filepath) and wait_index < 30:
            logging.info(f'Analyzing by others, waiting or clean occupying file manually at: {occupy_filepath} to continue')
            time.sleep(3)
            wait_index += 1
        if os.path.exists(occupy_filepath):
            logging.info('Analyzing by others, waiting timeout')
            sys.exit(0)

    # Step 1.2
    def _clean_occupy(self, occupy_path):
        if os.path.exists(occupy_path):
            os.remove(occupy_path)

    # Step 1.3
    def _occupy_project(self):
        # 占住项目分析
        logging.info('Start occupying project, and others can not analyze until released')
        occupy_filepath = os.path.join(self.file_path, 'Occupy.ing')
        with open(occupy_filepath, 'w') as ow:
            ow.write(f'Occupy by {self.username}')
        time.sleep(1)

    def _clone_dependents_project(self, dependents):
        for dependent in dependents:
            dependent_git_url = dependent.get('git_url')
            if not dependent_git_url:
                continue
            dependent_branch = dependent.get('branch', 'master')
            dependent_commit_id = dependent.get('commit_id', 'HEAD')
            dependent_project_name = dependent_git_url.split('/')[-1].split('.git')[0]
            dependent_file_path = os.path.join(self.file_path, dependent_project_name)
            if not os.path.exists(dependent_file_path):
                logging.info(f'Cloning dependent project: {dependent_git_url}')
                os.system(f'git clone -b {dependent_branch} {dependent_git_url} {dependent_file_path} && cd {dependent_file_path} && git reset --hard {dependent_commit_id}')
            else:
                os.system(f'cd {dependent_file_path} && git fetch --all && git checkout -b {dependent_branch} origin/{dependent_branch} && git reset --hard {dependent_commit_id}')
                os.system(f'cd {dependent_file_path} && git checkout -b {dependent_branch} && git reset --hard {dependent_commit_id}')

    # Step 2
    def _get_diff_parse_map(self, filepath, branch, commit_new, commit_old):
        logging.info('Git pull project to HEAD')
        os.system(f'cd {filepath} && git checkout {branch} && git pull')
        time.sleep(1)
        logging.info(f'Git diff between {commit_new} and {commit_old}')
        # 使用标准化后的短标识符命名diff文件
        commit_old_short = self._normalize_commit_or_tag(commit_old)
        commit_new_short = self._normalize_commit_or_tag(commit_new)
        diff_base = f'cd {self.file_path} && git diff {commit_old}..{commit_new} > diff_{commit_old_short}..{commit_new_short}.txt'
        os.system(diff_base)
        diff_txt = os.path.join(self.file_path, f'diff_{commit_old_short}..{commit_new_short}.txt')
        logging.info(f'Analyzing diff file, location: {diff_txt}')
        
        # 检查diff文件是否存在且有内容
        if os.path.exists(diff_txt):
            file_size = os.path.getsize(diff_txt)
            logging.info(f'Diff file size: {file_size} bytes')
            if file_size == 0:
                logging.warning(f'⚠️  Diff file is empty! No changes found between {commit_old} and {commit_new}')
                logging.warning(f'   Please verify that these commits/tags exist in the repository')
        else:
            logging.error(f'❌ Diff file not created: {diff_txt}')
        
        diff_parse_map = diff_parse.get_diff_info(diff_txt)
        logging.info(f'Diff parse result: {len(diff_parse_map)} files changed')
        if diff_parse_map:
            for filepath, diff_info in list(diff_parse_map.items())[:5]:  # 显示前5个文件
                added = len(diff_info.get('line_num_added', []))
                removed = len(diff_info.get('line_num_removed', []))
                logging.info(f'  - {filepath}: +{added} -{removed}')
            if len(diff_parse_map) > 5:
                logging.info(f'  ... and {len(diff_parse_map) - 5} more files')
        
        return diff_parse_map

    # Step 2
    def _get_branch_diff_parse_map(self, filepath, commit_new, commit_old):
        logging.info('Git pull project to HEAD')
        os.system(f'cd {filepath} && git fetch --all && git checkout -b {commit_old} origin/{commit_old} && git checkout {commit_old} && git pull')
        time.sleep(1)
        os.system(f'cd {filepath} && git fetch --all && git checkout -b {commit_new} origin/{commit_new} && git checkout {commit_new} && git pull')
        time.sleep(1)
        logging.info(f'Git diff between {commit_new} and {commit_old}')
        # 使用标准化后的短标识符命名diff文件
        commit_old_short = self._normalize_commit_or_tag(commit_old)
        commit_new_short = self._normalize_commit_or_tag(commit_new)
        diff_base = f'cd {self.file_path} && git diff {commit_old}..{commit_new} > diff_{commit_old_short}..{commit_new_short}.txt'
        os.system(diff_base)
        diff_txt = os.path.join(self.file_path, f'diff_{commit_old_short}..{commit_new_short}.txt')
        logging.info(f'Analyzing diff file, location: {diff_txt}')
        return diff_parse.get_diff_info(diff_txt)

    # Step 3
    def _parse_project(self, project_dir, commit_new, commit_old):
        # 解析最新的项目文件
        os.system(f'cd {project_dir} && git reset --hard {commit_new}')
        time.sleep(2)
        file_path_list = self._get_project_files(project_dir)
        diff_xml_file_path = [key for key in file_path_list if key.endswith('.xml') and any(key.endswith(diff_path) for diff_path in self.diff_parse_map.keys())]
        java_parse = JavaParse(self.sqlite.db_path, self.project_id)
        java_parse.parse_java_file_list(file_path_list, commit_new)
        xml_parse_result_new = self._parse_xml_file(diff_xml_file_path)
        xml_parse_result_old = {}
        if not commit_old:
            return xml_parse_result_new, xml_parse_result_old
        # 解析旧版本有差异的文件
        os.system(f'cd {project_dir} && git reset --hard {commit_old}')
        time.sleep(2)
        xml_parse_result_old = self._parse_xml_file(diff_xml_file_path)
        for key in self.diff_parse_map.keys():
            matched_file_path_list = [filepath for filepath in file_path_list if filepath.endswith(key)]
            if not matched_file_path_list:
                continue
            matched_file_path = matched_file_path_list[0]
            java_parse.parse_java_file(matched_file_path, commit_old, parse_import_first=False)
        return xml_parse_result_new, xml_parse_result_old

    # Step 3
    def _parse_branch_project(self, project_dir, new_branch, old_branch):
        # 解析最新的项目文件
        os.system(f'cd {project_dir} && git checkout {new_branch}')
        time.sleep(2)
        file_path_list = self._get_project_files(project_dir)
        diff_xml_file_path = [key for key in file_path_list if key.endswith('.xml') and any(key.endswith(diff_path) for diff_path in self.diff_parse_map.keys())]
        java_parse = JavaParse(self.sqlite.db_path, self.project_id)
        java_parse.parse_java_file_list(file_path_list, new_branch)
        xml_parse_result_new = self._parse_xml_file(diff_xml_file_path)
        # 解析旧版本有差异的文件
        os.system(f'cd {project_dir} && git checkout {old_branch}')
        time.sleep(2)
        xml_parse_result_old = self._parse_xml_file(diff_xml_file_path)
        for key in self.diff_parse_map.keys():
            matched_file_path_list = [filepath for filepath in file_path_list if filepath.endswith(key)]
            if not matched_file_path_list:
                continue
            matched_file_path = matched_file_path_list[0]
            java_parse.parse_java_file(matched_file_path, old_branch, parse_import_first=False)
        return xml_parse_result_new, xml_parse_result_old

    # Step 3.1 get all java files
    def _get_project_files(self, project_dir):
        file_lists = []
        for root, dirs, files in os.walk(project_dir):
            if '.git' in root or os.path.join('src', 'test') in root:
                continue
            for file in files:
                ignore = False
                filepath = os.path.join(root, file)
                for pattern in config.ignore_file:
                    if fnmatch.fnmatch(filepath, pattern):
                        ignore = True
                        break
                if ignore:
                    continue
                filepath = filepath.replace('\\', '/')
                file_lists.append(filepath)
        return file_lists

    # Step 3.3
    def _parse_xml_file(self, file_path_list):
        xml_parse_results = {}
        for filepath in file_path_list:
            if filepath.endswith('.xml'):
                xml_parse_result = mapper_parse.parse(filepath)
                if xml_parse_result:
                    xml_parse_results[filepath] = xml_parse_result
        return xml_parse_results

    # Step 4
    def _diff_analyze(self, patch_filepath: str, diff_parse_obj: dict):
        is_xml_file = patch_filepath.endswith('.xml')
        if is_xml_file:
            self._xml_diff_analyze(patch_filepath, diff_parse_obj)
        else:
            self._java_diff_analyze(patch_filepath, diff_parse_obj)

    # Step 4.1
    def _xml_diff_analyze(self, patch_filepath, diff_parse_obj: dict):
        xml_file_path_list = [filepath for filepath in self.xml_parse_results_new.keys() if filepath.endswith(patch_filepath)]
        if not xml_file_path_list:
            return
        xml_file_path = xml_file_path_list[0]
        xml_name = xml_file_path.split('/')[-1]
        xml_parse_result_new: mapper_parse.Mapper = self.xml_parse_results_new.get(xml_file_path)
        if xml_parse_result_new:
            methods = xml_parse_result_new.result_maps + xml_parse_result_new.sqls + xml_parse_result_new.statements
            self._xml_method_diff_analyze(methods, diff_parse_obj['line_num_added'], diff_parse_obj['line_content_added'], xml_parse_result_new, xml_name, xml_file_path, self.commit_or_branch_new)
        xml_parse_result_old = self.xml_parse_results_old.get(xml_file_path)
        if xml_parse_result_old:
            methods = xml_parse_result_old.result_maps + xml_parse_result_old.sqls + xml_parse_result_old.statements
            self._xml_method_diff_analyze(methods, diff_parse_obj['line_num_removed'], diff_parse_obj['line_content_removed'], xml_parse_result_old, xml_name, xml_file_path, self.commit_or_branch_old)

    # Step 4.1.1
    def _xml_method_diff_analyze(self, methods: list, line_num_list: list, line_content_list: list, xml_parse_result, xml_name, xml_file_path, commit_or_branch):
        namespace = xml_parse_result.namespace
        mapper_extend_dict = {
            'mapper_file_name': xml_name,
            'mapper_filepath': xml_file_path
        }
        for line_num in line_num_list:
            method_changed = [method for method in methods if self._is_line_num_in_xml_method_range(method, line_num)]
            method_changed_name = [method.name for method in method_changed]
            for method in method_changed:
                diff_content = line_content_list[line_num_list.index(line_num)]
                method_node_id = self.view.create_node_category(xml_name, method.name, method.type, constant.DIFF_TYPE_CHANGED, diff_content, xml_file_path, '', method.content, {})
                if method.type == constant.NODE_TYPE_MAPPER_STATEMENT:
                    mapper_extend_dict['method_node_id'] = method_node_id
                    self._add_to_need_analyze_obj_list('xml', namespace, None, method.name, commit_or_branch, mapper_extend_dict)
                    continue
                for statement in xml_parse_result.statements:
                    if statement.result_map in method_changed_name or statement.include_sql in method_changed_name:
                        statement_node_id = self.view.create_node_category(xml_name, statement.name, statement.type, constant.DIFF_TYPE_IMPACTED, '', xml_file_path, '', statement.content, {})
                        self.view.create_node_link(method_node_id, statement_node_id)
                        mapper_extend_dict['method_node_id'] = statement_node_id
                        self._add_to_need_analyze_obj_list('xml', namespace, None, statement.name, commit_or_branch, mapper_extend_dict)

    # Step 4.1.1.1
    def _is_line_num_in_xml_method_range(self, method, line_num):
        line_num_in_method = False
        if method.start <= line_num <= method.end:
            line_num_in_method = True
        return line_num_in_method

    # Step 4.2
    def _java_diff_analyze(self, patch_filepath: str, diff_parse_obj: dict):
        # new branch or commit（使用短标识符）
        class_db = self.sqlite.select_data(f'''SELECT * FROM class WHERE project_id = {self.project_id} and commit_or_branch = "{self.commit_short_new}" and filepath LIKE "%{patch_filepath}"''')
        for class_db_obj in class_db:
            self._java_field_method_diff_analyze(class_db_obj, diff_parse_obj['line_num_added'], diff_parse_obj['line_content_added'], self.commit_short_new)
        # old branch or commit
        if not self.commit_or_branch_old:
            return
        class_db = self.sqlite.select_data(f'SELECT * FROM class WHERE project_id = {self.project_id} and commit_or_branch = "{self.commit_short_old}" and filepath LIKE "%{patch_filepath}"')
        for class_db_obj in class_db:
            self._java_field_method_diff_analyze(class_db_obj, diff_parse_obj['line_num_removed'], diff_parse_obj['line_content_removed'], self.commit_short_old)

    # Step 4.2.1
    def _java_field_method_diff_analyze(self, class_db: dict, line_num_list: list, line_content_list: list, commit_or_branch: str or None):
        if not commit_or_branch:
            return
        class_name = class_db['class_name']
        class_filepath = class_db['filepath']
        is_controller = class_db['is_controller']
        data_in_annotation = [annotation for annotation in json.loads(class_db['annotations']) if annotation['name'] in ['Data', 'Getter', 'Setter', 'Builder', 'NoArgsConstructor', 'AllArgsConstructor']]
        for line_num in line_num_list:
            diff_content = line_content_list[line_num_list.index(line_num)]
            fields_list = self.sqlite.select_data(f'SELECT field_id, class_id, field_type, field_name, documentation, is_static FROM field WHERE class_id = {class_db["class_id"]} AND start_line <={line_num} AND end_line >= {line_num} order by start_line asc limit 1')
            methods_list = self.sqlite.select_data(f'SELECT method_id, class_id, method_name, parameters, return_type, is_api, api_path, documentation, body FROM methods WHERE class_id = {class_db["class_id"]} AND start_line <={line_num} AND end_line >= {line_num} order by start_line asc limit 1')
            class_node_id = None
            if fields_list:
                is_not_static_fields = [field for field in fields_list if field.get('is_static') == 'False']
                if is_not_static_fields and data_in_annotation:
                    self._add_to_need_analyze_obj_list('java', f'{class_db["package_name"]}.{class_name}', None, None, commit_or_branch, class_db)
                    class_node_id = self.view.create_node_category(class_name, 'entity', constant.NODE_TYPE_CLASS, constant.DIFF_TYPE_CHANGED, '', self.file_path, '', '', {})
                elif is_not_static_fields and not data_in_annotation:
                    field_method_name = []
                    for field in is_not_static_fields:
                        field_name = field['field_name']
                        field_name_capitalize = field_name[0].upper() + field_name[1:]
                        field_method_name += ['get' + field_name_capitalize, 'set' + field_name_capitalize, 'is' + field_name_capitalize]
                    field_method_name_str = '"' + '","'.join(field_method_name) + '"'
                    field_method_db = self.sqlite.select_data(f'SELECT method_id FROM methods WHERE class_id = {class_db["class_id"]} AND method_name in ({field_method_name_str})')
                    if field_method_db:
                        self._add_to_need_analyze_obj_list('java', f'{class_db["package_name"]}.{class_name}', None, None, commit_or_branch, class_db)
                        class_node_id = self.view.create_node_category(class_name, 'entity', constant.NODE_TYPE_CLASS, constant.DIFF_TYPE_CHANGED, '', self.file_path, '', '', {})
            for field_db in fields_list:
                node_id = self.view.create_node_category(class_name, field_db['field_name'], constant.NODE_TYPE_FIELD, constant.DIFF_TYPE_CHANGED, diff_content, class_filepath, field_db['documentation'], '', {})
                field_db['field_node_id'] = node_id
                self._add_to_need_analyze_obj_list('java', f'{class_db["package_name"]}.{class_name}', field_db['field_name'], None, commit_or_branch, field_db)
                if class_node_id:
                    self.view.create_node_link(node_id, class_node_id)
            for method_db in methods_list:
                node_extend_dict = {'is_api': False}
                if is_controller and method_db['is_api']:
                    node_extend_dict = {
                        'is_api': True,
                        'api_path': method_db['api_path']
                    }
                method_name_param = f'{method_db["method_name"]}({",".join([param["parameter_type"] for param in json.loads(method_db["parameters"])])})'
                node_id = self.view.create_node_category(class_name, method_name_param, constant.NODE_TYPE_METHOD, constant.DIFF_TYPE_CHANGED, diff_content, class_filepath, method_db.get('documentation'), method_db.get('body'), node_extend_dict)
                method_db['method_node_id'] = node_id
                self._add_to_need_analyze_obj_list('java', f'{class_db["package_name"]}.{class_name}', None, method_name_param, commit_or_branch, method_db)

    # Step 5
    def _impacted_analyze(self, need_analyze_obj: dict):
        file_type = need_analyze_obj['file_type']
        package_class = need_analyze_obj['package_class']
        commit_or_branch = need_analyze_obj['commit_or_branch']
        package_name = '.'.join(package_class.split('.')[0: -1])
        class_name = package_class.split('.')[-1]
        class_db_list = self.sqlite.select_data(f'SELECT class_id, filepath, commit_or_branch, is_controller, annotations, extends_class, implements '
                                                f' FROM class WHERE project_id = {self.project_id} and class_name="{class_name}" and package_name="{package_name}"')
        class_entity = self._get_right_class_entity(class_db_list, commit_or_branch)
        if not class_entity:
            return
        class_filepath = class_entity['filepath']
        class_id = class_entity["class_id"]
        # gengxin
        commit_or_branch = class_entity['commit_or_branch']
        is_controller = class_entity['is_controller']
        # todo 粗查，待细化
        if file_type == 'xml':
            method_name = need_analyze_obj['method_param']
            mapper_method_node_id = need_analyze_obj['method_node_id']
            impacted_methods = self.sqlite.select_data(f'SELECT method_id, class_id, method_name, parameters, return_type, is_api, api_path, documentation, body '
                                                       f'FROM methods WHERE class_id={class_id} and method_name="{method_name}"')
            if not impacted_methods:
                return
            for impacted_method in impacted_methods:
                node_extend_dict = {'is_api': False}
                if is_controller and impacted_method['is_api']:
                    node_extend_dict = {
                        'is_api': True,
                        'api_path': impacted_method['api_path']
                    }
                method_name_param = f'{impacted_method["method_name"]}({",".join([param["parameter_type"] for param in json.loads(impacted_method["parameters"])])})'
                impacted_method_node_id = self.view.create_node_category(class_name, method_name_param,
                                                                         constant.NODE_TYPE_METHOD, constant.DIFF_TYPE_IMPACTED,
                                                                         impacted_method.get('body'), class_filepath, impacted_method.get('documentation'),
                                                                         impacted_method.get('body'), node_extend_dict)
                self.view.create_node_link(mapper_method_node_id, impacted_method_node_id)
                extend_dict = {'method_node_id': impacted_method_node_id}
                extend_dict.update(impacted_method)
                self._add_to_need_analyze_obj_list('java', package_class, None, self._get_method_param_string(impacted_method), commit_or_branch, extend_dict)
        else:
            # analyze entity use
            entity_impacted_methods = []
            entity_impacted_fields = []
            source_node_id = None
            if not need_analyze_obj.get('field_name') and not need_analyze_obj.get('method_param'):
                class_node_id = self.view.create_node_category(class_name, 'entity', constant.NODE_TYPE_CLASS, constant.DIFF_TYPE_IMPACTED, '', self.file_path, '', '', {})
                entity_impacted_methods = self._get_entity_invocation_in_methods_table(package_class)
                entity_impacted_fields = self._get_entity_invocation_in_field_table(package_class)
                source_node_id = class_node_id
            elif need_analyze_obj.get('field_name'):
                annotations: list = json.loads(class_entity['annotations'])
                entity_impacted_methods = self._get_field_invocation_in_methods_table(package_class, need_analyze_obj, annotations, commit_or_branch, class_id)
                source_node_id = need_analyze_obj.get('field_node_id')
            elif need_analyze_obj.get('method_param'):
                method_param = need_analyze_obj.get('method_param')
                method_name: str = method_param.split('(')[0]
                method_node_id = need_analyze_obj.get('method_node_id')
                source_node_id = method_node_id
                entity_impacted_methods = self._get_method_invocation_in_methods_table(package_class, method_param, commit_or_branch)
                method_db = self.sqlite.select_data(f'SELECT annotations FROM methods WHERE method_id = {need_analyze_obj.get("method_id")}')[0]
                is_override_method = 'Override' in method_db['annotations']
                if is_override_method:

                    if class_entity['extends_class']:
                        abstract_package_class, method_params = self._is_method_param_in_extends_package_class(method_param, class_entity['extends_class'], 'True', commit_or_branch)
                        if abstract_package_class:
                            extends_methods = self._get_method_invocation_in_methods_table(abstract_package_class, method_params, commit_or_branch)
                            # for method in extends_methods:
                            #     method['class_id'] = class_id
                            entity_impacted_methods += extends_methods

                    if class_entity['implements']:
                        class_implements = class_entity['implements'].split(',')
                        class_implements_obj = self.sqlite.select_data(f'''select c.package_name , c.class_name from methods m left join class c on c.class_id = m.class_id 
                                                where c.project_id = {self.project_id} and m.method_name = '{method_name}' and c.class_name in ("{'","'.join(class_implements)}")''')
                        if class_implements_obj:
                            implements_package_class = class_implements_obj[0].get('package_name') + '.' + class_implements_obj[0].get('class_name')
                            implements_package_class, method_params = self._is_method_param_in_extends_package_class(method_param, implements_package_class, 'False', commit_or_branch)
                            if implements_package_class:
                                implements_methods = self._get_method_invocation_in_methods_table(implements_package_class, method_params, commit_or_branch)
                                # implements_methods = self._get_method_invocation_in_methods_table(implements_package_class, method_param, commit_or_branch)
                                entity_impacted_methods += implements_methods
                else:
                    class_method_db = self.sqlite.select_data(f'SELECT method_id FROM methods WHERE class_id = {class_id} and method_name = "{method_name}"')
                    if not class_method_db:
                        extends_package_class, method_params = self._is_method_param_in_extends_package_class(method_param, class_entity['extends_class'], 'False', commit_or_branch)
                        if extends_package_class:
                            extends_methods = self._get_method_invocation_in_methods_table(extends_package_class, method_params, commit_or_branch)
                            entity_impacted_methods += extends_methods
            self._handle_impacted_methods(entity_impacted_methods, source_node_id)
            self._handle_impacted_fields(entity_impacted_fields, source_node_id)

    def _is_method_param_in_extends_package_class(self, method_param, extends_package_class, is_abstract, commit_or_branch):
        if not extends_package_class:
            return None, None
        method_name: str = method_param.split('(')[0]
        method_arguments = method_param.split('(')[1].split(')')[0].split(',')
        method_arguments = [ma for ma in method_arguments if ma]
        extends_package = '.'.join(extends_package_class.split('.')[0: -1])
        extends_class_name = extends_package_class.split('.')[-1]
        extends_class_db = self.sqlite.select_data(f'SELECT class_id, extends_class FROM class WHERE package_name = "{extends_package}" and class_name = "{extends_class_name}" and project_id = {self.project_id} and commit_or_branch = "{commit_or_branch}"')
        if not extends_class_db:
            extends_class_db = self.sqlite.select_data(f'SELECT class_id, extends_class FROM class WHERE package_name = "{extends_package}" and class_name = "{extends_class_name}" and project_id = {self.project_id}')
            if not extends_class_db:
                return None, None
        extends_class_id = extends_class_db[0]['class_id']
        methods_db_list = self.sqlite.select_data(f'SELECT * FROM methods WHERE class_id = {extends_class_id} and method_name = "{method_name}" and is_abstract = "{is_abstract}"')
        filter_methods = [method for method in methods_db_list if len(json.loads(method.get('parameters', '[]'))) == len(method_arguments)]
        if not filter_methods:
            if extends_class_db[0]['extends_class']:
                return self._is_method_param_in_extends_package_class(method_param, extends_class_db[0]['extends_class'], is_abstract, commit_or_branch)
            else:
                return None, None
        if len(filter_methods) == 1:
            method_db = filter_methods[0]
            method_params = f'{method_db.get("method_name", method_name)}({",".join([param["parameter_type"] for param in json.loads(method_db.get("parameters", "[]"))])})'
            return extends_package_class, method_params
        else:
            max_score = -float('inf')
            max_score_method = None
            for method_db in filter_methods:
                method_db_params = [param["parameter_type"] for param in json.loads(method_db.get("parameters", "[]"))]
                score = calculate_similar_score_method_params(method_arguments, method_db_params)
                if score > max_score:
                    max_score = score
                    max_score_method = method_db
            if max_score_method is None:
                max_score_method = filter_methods[0]
            method_params = f'{max_score_method.get("method_name", method_name)}({",".join([param["parameter_type"] for param in json.loads(max_score_method.get("parameters", "[]"))])})'
            return extends_package_class, method_params

    def _get_extends_package_class(self, package_class):
        extends_package_class_list = []
        extends_package_class_db = self.sqlite.select_data(f'SELECT package_name, class_name FROM class WHERE project_id = {self.project_id} AND extends_class="{package_class}"')
        if extends_package_class_db:
            extends_package_class_list = [f'{class_item["package_name"]}.{class_item["class_name"]}' for class_item in extends_package_class_db]
            for extends_package_class in extends_package_class_list:
                extends_package_class_list += self._get_extends_package_class(extends_package_class)
        return extends_package_class_list

    # Step 5.1
    def _get_right_class_entity(self, class_db_list, commit_or_branch):
        right_class_entity = next((item for item in class_db_list if item.get("commit_or_branch") == commit_or_branch), None)
        if right_class_entity is None:
            right_class_entity = next((item for item in class_db_list if item.get("commit_or_branch") == self.commit_short_new), None)
        return right_class_entity

    # Step 5.2
    def _get_entity_invocation_in_methods_table(self, package_class: str):
        return self.sqlite.select_data(f'''SELECT method_id, class_id, method_name, parameters, return_type, is_api, api_path, documentation, body FROM methods WHERE project_id = {self.project_id} AND json_extract(method_invocation_map, '$."{package_class}".entity') IS NOT NULL''')

    # Step 5.2
    def _get_entity_invocation_in_field_table(self, package_class: str):
        return self.sqlite.select_data(f'''SELECT field_id, class_id, annotations, field_type, field_name, is_static, documentation FROM field WHERE project_id = {self.project_id} AND field_type = "{package_class}"''')

    # Step 5.3
    def _get_field_invocation_in_methods_table(self, package_class, field_obj, annotations, commit_or_branch, class_id):
        is_static = field_obj['is_static']
        field_name = field_obj['field_name']
        field_name_capitalize = field_name[0].upper() + field_name[1:]
        if not is_static:
            # todo static maybe has bug
            field_methods_set = set()
            for annotation in annotations:
                annotation_name = annotation.get('name')
                if annotation_name == 'Data':
                    field_methods_set.add(f'get{field_name_capitalize}(')
                    field_methods_set.add(f'set{field_name_capitalize}(')
                elif annotation_name == 'Getter':
                    field_methods_set.add(f'get{field_name_capitalize}(')
                elif annotation_name == 'Setter':
                    field_methods_set.add(f'set{field_name_capitalize}(')
                else:
                    continue
            if not field_methods_set:
                return []
            json_extract_sql_list = []
            for field_method in field_methods_set:
                sql_part = f'''json_extract(method_invocation_map, '$."{package_class}".methods.keys(@.startsWith("{field_method}"))') IS NOT NULL'''
                json_extract_sql_list.append(sql_part)
            sql = f'SELECT method_id, class_id, method_name, parameters, return_type, is_api, api_path, documentation, body FROM methods WHERE project_id = {self.project_id} AND (' + ' OR '.join(json_extract_sql_list) + ')'
        else:
            sql = f'''SELECT method_id, class_id, method_name, parameters, return_type, is_api, api_path, documentation, body FROM methods 
            WHERE project_id = {self.project_id} AND 
            (json_extract(method_invocation_map, '$."{package_class}".fields.{field_name}') IS NOT NULL OR json_extract(method_invocation_map, '$."{package_class}.{field_name}"') IS NOT NULL)'''
        methods = self.sqlite.select_data(sql)
        if not methods:
            field_method_name_list = ['get' + field_name_capitalize, 'set' + field_name_capitalize, 'is' + field_name_capitalize]
            field_method_name_str = '"' + '","'.join(field_method_name_list) + '"'
            methods = self.sqlite.select_data(f'SELECT method_id, class_id, method_name, parameters, return_type, is_api, api_path, documentation, body FROM methods WHERE class_id = {class_id} AND method_name in ({field_method_name_str})')
        class_ids = [str(method['class_id']) for method in methods]
        class_sql = f'SELECT class_id FROM class WHERE class_id in ({", ".join(class_ids)}) and commit_or_branch ="{commit_or_branch}"'
        class_db = self.sqlite.select_data(class_sql)
        class_db_id = [class_item['class_id'] for class_item in class_db]
        return [method for method in methods if method['class_id'] in class_db_id]

    # Step 5.4
    def _get_method_invocation_in_methods_table(self, package_class, method_param, commit_or_branch):
        all_possible_method_param_type_list = self._gen_all_possible_method_param_list(method_param)
        json_extract_sql_list = []
        for param_type in all_possible_method_param_type_list:
            sql_part = f'''json_extract(method_invocation_map, '$."{package_class}".methods."{param_type}"') IS NOT NULL'''
            json_extract_sql_list.append(sql_part)
        if len(json_extract_sql_list) > 1000:
            json_extract_sql_list = json_extract_sql_list[0: 995]
        sql = f'SELECT method_id, class_id, method_name, parameters, return_type, is_api, api_path, documentation, body FROM methods WHERE project_id = {self.project_id} AND (' + ' OR '.join(json_extract_sql_list) + ')'
        # logging.info(f'{package_class} {method_param} invocation sql: {sql}')
        methods = self.sqlite.select_data(sql)
        class_ids = [str(method['class_id']) for method in methods]
        class_sql = f'SELECT class_id FROM class WHERE class_id in ({", ".join(class_ids)}) and commit_or_branch ="{commit_or_branch}"'
        class_db = self.sqlite.select_data(class_sql)
        if not class_db:
            class_sql = f'SELECT class_id FROM class WHERE class_id in ({", ".join(class_ids)})'
            class_db = self.sqlite.select_data(class_sql)
        class_db_id = [class_item['class_id'] for class_item in class_db]
        return [method for method in methods if method['class_id'] in class_db_id]

    # Step 5.4.1
    def _gen_all_possible_method_param_list(self, method_param):
        method_param_list = []
        method_name = method_param.split('(')[0]
        param_type_str = method_param.split('(')[1].split(')')[0]
        param_type_list = param_type_str.split(',')
        if not param_type_list:
            return method_param_list
        all_possible_method_param_list = self._replace_with_null_unknown(param_type_list)
        for param_type_list in all_possible_method_param_list:
            method_param_list.append(f'{method_name}({",".join(param_type_list)})')
        return method_param_list

    def _replace_extends_class(self, new_lst, results):
        for i in range(0, len(new_lst)):
            if new_lst[i].lower() in constant.JAVA_BASIC_TYPE \
                    or new_lst[i] == constant.PARAMETER_TYPE_METHOD_INVOCATION_UNKNOWN \
                    or new_lst[i] == 'null':
                continue
            extends_package_class_list = self._get_extends_package_class(new_lst[i])
            for extends_package_class in extends_package_class_list:
                result_item = [item for item in new_lst]
                result_item[i] = extends_package_class
                results.append(result_item)

    # Step 5.4.1.1
    def _replace_with_null_unknown(self, lst: list):
        need_replace_list = []
        replaced_list = []
        results = set()
        self._replace_params_with_unknown(lst, results, 0, need_replace_list)
        for item in need_replace_list:
            if len(results) > 1000:
                break
            if item not in replaced_list:
                replaced_list.append(item)
                self._replace_params_with_unknown(item['list'], results, item['index'], need_replace_list)
        return list(results)

    def _replace_param_switch(self, param: str):
        if 'int' in param.lower():
            if param == 'int':
                param = 'Integer'
            else:
                param = 'int'
        else:
            if param[0].isupper():
                param = param[0].lower() + param[1:]
            else:
                param = param[0].upper() + param[1:]
        return param

    def _replace_params_with_unknown(self, lst: list, results: set, idx: int, need_replace_list: list):
        # data = [item.split('<')[0].replace('<', '').replace('>', '') for item in data]
        for i in range(idx, len(lst)):
            new_lst = lst[:]
            results.add(tuple(new_lst))
            new_lst2 = new_lst[:]
            if new_lst[i].lower() not in constant.JAVA_BASIC_TYPE:
                if new_lst[i].startswith('List'):
                    new_lst2[i] = 'ArrayList'
                elif new_lst[i].startswith('Map'):
                    new_lst2[i] = 'HashMap'
                elif new_lst[i].startswith('Set'):
                    new_lst2[i] = 'HashSet'
            else:
                if new_lst[i].lower() in constant.JAVA_BASIC_TYPE_SWITCH:
                    new_lst2 = new_lst[:]
                    param = self._replace_param_switch(new_lst[i])
                    new_lst2[i] = param
            if tuple(new_lst2) not in results:
                results.add(tuple(new_lst2))
                if {'list': new_lst2, 'index': idx} not in need_replace_list:
                    need_replace_list.append({'list': new_lst2, 'index': idx})

            for el in ['null', 'unknown']:
                new_lst_tmp = new_lst[:]
                new_lst_tmp[i] = el
                if tuple(new_lst_tmp) not in results:
                    results.add(tuple(new_lst_tmp))
                    if {'list': new_lst_tmp, 'index': min(idx, len(new_lst) - 1)} not in need_replace_list:
                        need_replace_list.append({'list': new_lst_tmp, 'index': min(idx, len(new_lst) - 1)})

    # Step 5.5
    def _get_method_param_string(self, method_db: dict):
        method_name: str = method_db['method_name']
        params: list = json.loads(method_db['parameters'])
        params_type_list = [param['parameter_type'] for param in params]
        return f'{method_name}({",".join(params_type_list)})'

    def _handle_impacted_fields(self, impacted_fields: list, source_node_id):
        for impacted_field in impacted_fields:
            class_id = impacted_field['class_id']
            class_entity = self.sqlite.select_data(f'SELECT package_name, class_name, commit_or_branch, filepath FROM class WHERE class_id={class_id}')[0]
            class_name = class_entity['class_name']
            package_name = class_entity['package_name']
            package_class = f'{package_name}.{class_name}'
            commit_or_branch = class_entity['commit_or_branch']
            class_filepath = class_entity['filepath']
            impacted_field_node_id = self.view.create_node_category(class_name, impacted_field['field_name'], constant.NODE_TYPE_FIELD, constant.DIFF_TYPE_IMPACTED, None, class_filepath, impacted_field['documentation'], '', {})
            self.view.create_node_link(source_node_id, impacted_field_node_id)
            extend_dict = {'field_node_id': impacted_field_node_id, 'class_filepath': class_filepath}
            extend_dict.update(impacted_field)
            self._add_to_need_analyze_obj_list('java', package_class, impacted_field['field_name'], None, commit_or_branch, extend_dict)
            if impacted_field['is_static'] == 'False':
                self._add_to_need_analyze_obj_list('java', package_class, None, None, commit_or_branch, class_entity)
                class_node_id = self.view.create_node_category(class_name, 'entity', constant.NODE_TYPE_CLASS, constant.DIFF_TYPE_IMPACTED, '', self.file_path, '', '', {})
                self.view.create_node_link(impacted_field_node_id, class_node_id)

    # Step 5.9
    def _handle_impacted_methods(self, impacted_methods: list, source_node_id):
        for impacted_method in impacted_methods:
            node_extend_dict = {'is_api': False}
            if impacted_method.get('is_api') == 'True':
                node_extend_dict = {
                    'is_api': True,
                    'api_path': impacted_method['api_path']
                }
            class_id = impacted_method['class_id']
            class_entity = self.sqlite.select_data(f'SELECT package_name, class_name, commit_or_branch, filepath FROM class WHERE class_id={class_id}')[0]
            class_name = class_entity['class_name']
            package_name = class_entity['package_name']
            package_class = f'{package_name}.{class_name}'
            commit_or_branch = class_entity['commit_or_branch']
            class_filepath = class_entity['filepath']
            method_name_param = f'{impacted_method["method_name"]}({",".join([param["parameter_type"] for param in json.loads(impacted_method["parameters"])])})'
            impacted_method_node_id = self.view.create_node_category(class_name, method_name_param, constant.NODE_TYPE_METHOD, constant.DIFF_TYPE_IMPACTED, impacted_method.get('body'), class_filepath, impacted_method.get('documentation'), impacted_method.get('body'), node_extend_dict)
            self.view.create_node_link(source_node_id, impacted_method_node_id)
            extend_dict = {'method_node_id': impacted_method_node_id, 'class_filepath': class_filepath}
            extend_dict.update(impacted_method)
            self._add_to_need_analyze_obj_list('java', package_class, None, self._get_method_param_string(impacted_method), commit_or_branch, extend_dict)

    def _add_to_need_analyze_obj_list(self, file_type: str, package_class: str, field_name: str or None, method_param: str or None, commit_or_branch: str, mapper_extend_dict: dict):
        need_analyze_entity: dict = {
            'file_type': file_type,
            'package_class': package_class,
            'field_name': field_name,
            'method_param': method_param,
            'commit_or_branch': commit_or_branch
        }
        is_exist = [obj for obj in self.need_analyze_obj_list if self.check_dict_keys_equal_values(need_analyze_entity, obj)]
        if not is_exist:
            need_analyze_entity.update(mapper_extend_dict)
            self.need_analyze_obj_list.append(need_analyze_entity)

    def check_dict_keys_equal_values(self, dict1, dict2):
        for key in dict1:
            if key in dict2 and dict1[key] != dict2[key]:
                return False
        return True

    def _collect_method_changes(self):
        """
        收集方法变更信息
        返回方法变更列表
        
        优先使用数据库中的 change_type 字段，如果不存在则基于行号推断
        """
        method_changes = []
        
        # 尝试从数据库中查询有变更的方法（使用 change_type 字段）
        try:
            methods_with_changes = self.sqlite.select_data(
                f'SELECT m.method_name, m.parameters, m.change_type, '
                f'c.class_name, c.package_name, c.filepath, '
                f'm.start_line as new_start_line '
                f'FROM methods m '
                f'JOIN class c ON m.class_id = c.class_id '
                f'WHERE m.project_id = {self.project_id} '
                f'AND m.change_type != "UNCHANGED" '
                f'ORDER BY c.class_name, m.start_line'
            )
            
            if methods_with_changes:
                # 如果数据库中有 change_type 信息，直接使用
                for method in methods_with_changes:
                    params = json.loads(method['parameters']) if method['parameters'] else []
                    param_types = ','.join([p['parameter_type'] for p in params])
                    method_signature = f"{method['class_name']}.{method['method_name']}({param_types})"
                    
                    method_changes.append({
                        'change_type': method['change_type'],
                        'method_signature': method_signature,
                        'file_path': method['filepath'],
                        'new_start_line': method['new_start_line'],
                        'old_start_line': None
                    })
                
                logging.info(f'从数据库获取到 {len(method_changes)} 个变更方法')
                return method_changes
        except Exception as e:
            logging.warning(f'查询 change_type 失败，使用行号推断: {e}')
        
        # 如果数据库中没有 change_type 信息，使用原有的行号推断逻辑
        logging.info('使用行号推断方法变更类型')
        
        # 遍历 diff_parse_map 获取所有变更的文件和方法
        for filepath, diff_info in self.diff_parse_map.items():
            # 跳过 XML 文件
            if filepath.endswith('.xml'):
                continue
            
            # 获取新增行的方法
            if diff_info.get('line_num_added'):
                for line_num in diff_info['line_num_added']:
                    # 查询新方法
                    methods_list = self.sqlite.select_data(
                        f'SELECT m.method_name, m.parameters, m.class_id, c.class_name, c.package_name '
                        f'FROM methods m '
                        f'JOIN class c ON m.class_id = c.class_id '
                        f'WHERE m.project_id = {self.project_id} '
                        f'AND m.start_line <= {line_num} AND m.end_line >= {line_num} '
                        f'AND c.commit_or_branch = "{self.commit_short_new}"'
                    )
                    
                    for method in methods_list:
                        params = json.loads(method['parameters']) if method['parameters'] else []
                        param_types = ','.join([p['parameter_type'] for p in params])
                        method_signature = f"{method['class_name']}.{method['method_name']}({param_types})"
                        
                        method_changes.append({
                            'change_type': 'ADDED',
                            'method_signature': method_signature,
                            'file_path': filepath,
                            'new_start_line': line_num,
                            'old_start_line': None
                        })
            
            # 获取删除行的方法(旧版本)
            if diff_info.get('line_num_removed') and self.commit_or_branch_old:
                for line_num in diff_info['line_num_removed']:
                    # 查询旧方法（使用短标识符）
                    methods_list = self.sqlite.select_data(
                        f'SELECT m.method_name, m.parameters, m.class_id, c.class_name, c.package_name '
                        f'FROM methods m '
                        f'JOIN class c ON m.class_id = c.class_id '
                        f'WHERE m.project_id = 0 '
                        f'AND m.start_line <= {line_num} AND m.end_line >= {line_num} '
                        f'AND c.commit_or_branch = "{self.commit_short_old}"'
                    )
                    
                    for method in methods_list:
                        params = json.loads(method['parameters']) if method['parameters'] else []
                        param_types = ','.join([p['parameter_type'] for p in params])
                        method_signature = f"{method['class_name']}.{method['method_name']}({param_types})"
                        
                        method_changes.append({
                            'change_type': 'DELETED',
                            'method_signature': method_signature,
                            'file_path': filepath,
                            'new_start_line': None,
                            'old_start_line': line_num
                        })
        
        return method_changes

    def _draw_and_write_result(self, write_file=True):
        """
        生成分析结果
        
        Args:
            write_file: 是否写入 CCI 文件,默认 True
        
        Returns:
            dict: 分析结果字典
        """
        if self.view.nodes:
            self.view.draw_graph(1200, 600)
        
        # 收集方法变更信息
        method_changes = self._collect_method_changes()
        
        logging.info('Analyze success, generating result...')
        result = {
            'nodes': self.view.nodes,
            'links': self.view.links,
            'categories': self.view.categories,
            'impacted_api_list': [node['api_path'] for node in self.view.nodes if node.get('is_api')],
            'method_changes': method_changes,
            'cci_file_path': self.cci_filepath if write_file else None
        }
        
        # 根据参数决定是否写入文件
        if write_file:
            print(json.dumps(result, ensure_ascii=False), flush=True)
            print(f'Impacted api list: {result["impacted_api_list"]}', flush=True)
            with open(self.cci_filepath, 'w') as w:
                w.write(json.dumps(result, ensure_ascii=False))
            logging.info(f'Generating cci result file success, location: {self.cci_filepath}')
        else:
            logging.info('CCI file output disabled, returning result only')
        
        return result

    def _start_analysis_diff_and_impact(self, write_file=True):
        """
        开始差异和影响分析
        
        Args:
            write_file: 是否写入 CCI 文件
        
        Returns:
            dict: 分析结果
        """
        for patch_path, patch_obj in self.diff_parse_map.items():
            self._diff_analyze(patch_path, patch_obj)

        # 遍历列表
        for obj in self.need_analyze_obj_list:
            if obj not in self.analyzed_obj_set:  # 判断对象是否已分析过
                self.analyzed_obj_set.append(obj)  # 标记为已分析过
                self._impacted_analyze(obj)  # 处理对象,返回新增对象列表

        result = self._draw_and_write_result(write_file=write_file)
        t2 = datetime.datetime.now()
        try:
            logging.info('Analyze done, remove occupy, others can analyze now')
            os.remove(os.path.join(self.file_path, 'Occupy.ing'))
        finally:
            pass
        logging.info(f'Analyze done, spend: {t2 - self.t1}')
        
        return result


    def analyze_two_commit_incremental(self, commit_new, commit_old, **kwargs):
        """
        基线增量分析策略:以基线为中心的增量分析
        
        Args:
            commit_new: 新的提交ID或tag（可以是完整tag或短标识符）
            commit_old: 基线提交ID或tag（可以是完整tag或短标识符）
            **kwargs: 其他参数(如 branch, dependents)
        """
        logging.info('*' * 10 + 'Incremental Analyze start' + '*' * 10)
        
        # 1. 初始化基本信息
        # 保存原始值用于Git操作（完整tag或commit hash）
        self.commit_or_branch_new = commit_new
        self.commit_or_branch_old = commit_old
        
        # 生成短标识符用于数据库和文件命名
        self.commit_short_new = self._normalize_commit_or_tag(commit_new)
        self.commit_short_old = self._normalize_commit_or_tag(commit_old)
        
        self.branch_name = kwargs.get('branch', 'master')
        
        logging.info(f'Original tags/commits: {commit_old}..{commit_new}')
        logging.info(f'Short identifiers: {self.commit_short_old}..{self.commit_short_new}')
        
        self.project_name = self.git_url.split('/')[-1].split('.git')[0]
        self.file_path = os.path.join(config.project_path, self.project_name)
        
        # 2. 构造输出目录（基线目录）
        output_dir = os.path.join(os.path.dirname(__file__), 'analyze_result', 
                                 f"{self.project_name}_{self.commit_short_old}")
        os.makedirs(output_dir, exist_ok=True)
        
        # 3. 构造基线数据库路径（使用短标识符，保存到output_dir）
        baseline_db_path = self.sqlite.get_baseline_db_path(
            self.username, self.project_name, self.commit_short_old, output_dir
        )
        
        # 4. 判断是否为首次运行
        is_first_run = not os.path.exists(baseline_db_path)
        
        if is_first_run:
            # === 场景 A: 首次运行(基线初始化) ===
            logging.info('First run detected, initializing baseline database')
            
            # 4.1 创建新的 SqliteHelper 实例指向基线数据库
            baseline_sqlite = SqliteHelper(baseline_db_path)
            self.sqlite = baseline_sqlite
            
            # 4.2 克隆项目(如果不存在)
            if not os.path.exists(self.file_path):
                logging.info(f'Cloning project: {self.git_url}')
                os.system(f'git clone -b {self.branch_name} {self.git_url} {self.file_path}')
            
            # 4.3 占住项目
            self._occupy_project()
            
            # 4.4 全量解析 commit_old → project_id = 0（使用短标识符）
            logging.info(f'Full parsing baseline commit: {self.commit_or_branch_old}')
            os.system(f'cd {self.file_path} && git reset --hard {self.commit_or_branch_old}')
            time.sleep(2)
            
            file_path_list = self._get_project_files(self.file_path)
            java_parse = JavaParse(self.sqlite.db_path, project_id=0)
            java_parse.parse_java_file_list(file_path_list, self.commit_short_old)
            
            # 3.5 记录基线分析到 project 表（使用短标识符）
            baseline_project_id = self.sqlite.add_project(
                self.project_name, self.git_url, self.branch_name,
                self.commit_short_old, self.commit_short_old,
                project_id=0
            )
            
            # 4.6 计算差异并增量解析 commit_new → project_id = 1（使用短标识符）
            logging.info(f'Incremental parsing new commit: {self.commit_or_branch_new}')
            self.diff_parse_map = self._get_diff_parse_map(
                self.file_path, self.branch_name, 
                self.commit_or_branch_new, self.commit_or_branch_old
            )
            
            # 切换到新提交（使用原始tag进行Git操作）
            os.system(f'cd {self.file_path} && git reset --hard {self.commit_or_branch_new}')
            time.sleep(2)
            
            # 只解析差异文件
            diff_files = list(self.diff_parse_map.keys())
            matched_java_files = [f for f in file_path_list 
                                 if any(f.endswith(diff_path) for diff_path in diff_files)]
            
            java_parse_new = JavaParse(self.sqlite.db_path, project_id=1)
            java_parse_new.parse_java_file_list(matched_java_files, self.commit_short_new)
            
            # 4.7 记录增量分析到 project 表（使用短标识符）
            self.project_id = self.sqlite.add_project(
                self.project_name, self.git_url, self.branch_name,
                self.commit_short_new, self.commit_short_old,
                project_id=1
            )
            
            # 3.8 解析 XML 文件
            diff_xml_files = [f for f in matched_java_files if f.endswith('.xml')]
            self.xml_parse_results_new = self._parse_xml_file(diff_xml_files)
            self.xml_parse_results_old = {}
            
        else:
            # === 场景 B/C: 数据库已存在 ===
            logging.info('Baseline database exists, checking for duplicate analysis')
            
            # 切换到基线数据库
            baseline_sqlite = SqliteHelper(baseline_db_path)
            self.sqlite = baseline_sqlite
            
            # 检查是否为重复运行(场景 B)（使用短标识符）
            is_duplicate = self.sqlite.check_duplicate_analysis(
                self.project_name, self.git_url, self.branch_name,
                self.commit_short_new, self.commit_short_old
            )
            
            if is_duplicate:
                logging.info('Duplicate analysis detected, trying to load from JSON cache')
                
                # 尝试从 JSON 缓存加载完整结果
                cached_result = self._load_analysis_cache()
                if cached_result:
                    logging.info('Successfully loaded complete result from JSON cache')
                    cached_result['is_duplicate'] = True
                    cached_result['message'] = 'Retrieved from JSON cache (full result with nodes/links/categories)'
                    return cached_result
                else:
                    logging.warning('JSON cache not found, will re-analyze')
            
            # === 场景 C: 相同基线,不同新提交 ===
            logging.info('New incremental analysis with existing baseline')
            
            # 获取下一个 project_id
            next_project_id = self.sqlite.get_next_project_id()
            self.project_id = next_project_id
            
            # 克隆/更新项目
            if not os.path.exists(self.file_path):
                logging.info(f'Cloning project: {self.git_url}')
                os.system(f'git clone -b {self.branch_name} {self.git_url} {self.file_path}')
            
            self._occupy_project()
            
            # 计算差异(相对于基线 commit_old)
            self.diff_parse_map = self._get_diff_parse_map(
                self.file_path, self.branch_name,
                self.commit_or_branch_new, self.commit_or_branch_old
            )
            
            # 切换到新提交
            os.system(f'cd {self.file_path} && git reset --hard {self.commit_or_branch_new}')
            time.sleep(2)
            
            # 获取当前项目文件列表
            file_path_list = self._get_project_files(self.file_path)
            
            # 只解析差异文件
            diff_files = list(self.diff_parse_map.keys())
            matched_java_files = [f for f in file_path_list 
                                 if any(f.endswith(diff_path) for diff_path in diff_files)]
            
            java_parse = JavaParse(self.sqlite.db_path, project_id=next_project_id)
            java_parse.parse_java_file_list(matched_java_files, self.commit_short_new)
            
            # 解析 XML 文件
            diff_xml_files = [f for f in matched_java_files if f.endswith('.xml')]
            self.xml_parse_results_new = self._parse_xml_file(diff_xml_files)
            self.xml_parse_results_old = {}
            
            # 记录分析到 project 表（使用短标识符）
            self.sqlite.add_project(
                self.project_name, self.git_url, self.branch_name,
                self.commit_short_new, self.commit_short_old,
                project_id=next_project_id
            )
        
        # 4. 依赖项目处理
        dependents: list[dict] = kwargs.get('dependents', [])
        self._clone_dependents_project(dependents)
        
        # 5. 设置 CCI 文件路径（使用短标识符）
        self.cci_filepath = os.path.join(
            self.file_path, 
            f'{self.commit_short_old}..{self.commit_short_new}_incremental.cci'
        )
        
        # 6. 执行变更类型分析（如果 ChangeTypeAnalyzer 可用）
        if ChangeTypeAnalyzer is not None:
            logging.info('开始执行变更类型分析...')
            try:
                analyzer = ChangeTypeAnalyzer(self.sqlite.db_path)
                
                # 6.1 先处理基线中的 DELETED 方法（project_id=0）
                if not is_first_run:
                    logging.info('处理基线中被删除的方法 (project_id=0)...')
                    analyzer.analyze_and_mark_changes(
                        diff_parse_map=self.diff_parse_map,
                        commit_new=self.commit_short_new,  # 使用短标识符
                        commit_old=self.commit_short_old,  # 使用短标识符
                        project_id=0  # 基线 project_id
                    )
                
                # 6.2 再处理增量中的 ADDED/MODIFIED 方法
                analyzer.analyze_and_mark_changes(
                    diff_parse_map=self.diff_parse_map,
                    commit_new=self.commit_short_new,  # 使用短标识符
                    commit_old=self.commit_short_old,  # 使用短标识符
                    project_id=self.project_id
                )
                
                # 获取变更摘要（从增量中获取）
                changed_classes = analyzer.get_changed_classes(self.project_id)
                changed_methods = analyzer.get_changed_methods(self.project_id)
                
                logging.info(f'变更类型分析完成: {len(changed_classes)} 个类变更, {len(changed_methods)} 个方法变更')
                
                analyzer.close()
            except Exception as e:
                logging.error(f'变更类型分析失败: {e}')
                import traceback
                traceback.print_exc()
        else:
            logging.warning('ChangeTypeAnalyzer 不可用，跳过变更类型分析')
        
        # 7. 开始差异和影响分析（不输出 CCI 文件）
        result = self._start_analysis_diff_and_impact(write_file=False)
        
        # 8. 在结果中添加变更摘要信息
        if ChangeTypeAnalyzer is not None:
            try:
                # 重新创建分析器以查询结果
                analyzer = ChangeTypeAnalyzer(self.sqlite.db_path)
                result['change_summary'] = {
                    'classes': analyzer.get_changed_classes(self.project_id),
                    'methods': analyzer.get_changed_methods(self.project_id)
                }
                analyzer.close()
            except Exception as e:
                logging.error(f'获取变更摘要失败: {e}')
                result['change_summary'] = {
                    'classes': [],
                    'methods': []
                }
        
        # 9. 保存分析结果到 JSON 缓存（用于幂等性）
        result['is_duplicate'] = False
        result['message'] = 'New analysis completed (full result cached to JSON)'
        self._save_analysis_cache(result)
        
        return result
    
    def _get_cache_file_path(self) -> str:
        """
        获取缓存文件路径
        
        Returns:
            str: 缓存文件的完整路径
        """
        import os
        from src.jcci import config
        
        # 创建基线目录和版本子目录
        base_dir = os.path.join(os.path.dirname(__file__), 'analyze_result', 
                                f"{self.project_name}_{self.commit_short_old}")
        cache_dir = os.path.join(base_dir, self.commit_short_new)
        os.makedirs(cache_dir, exist_ok=True)
        
        # JSON文件名不再包含项目名和commit范围（因为已经在目录名中）
        filename = f"analysis_result.json"
        return os.path.join(cache_dir, filename)
    
    def _save_analysis_cache(self, result: dict):
        """
        保存分析结果到 JSON 缓存
        
        Args:
            result: 分析结果字典
        """
        import json
        
        cache_file = self._get_cache_file_path()
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            logging.info(f'Analysis result saved to cache: {cache_file}')
        except Exception as e:
            logging.error(f'Failed to save analysis cache: {e}')
    
    def _load_analysis_cache(self) -> dict:
        """
        从 JSON 缓存加载分析结果
        
        Returns:
            dict: 分析结果，如果加载失败返回 None
        """
        import json
        import os
        
        cache_file = self._get_cache_file_path()
        
        if not os.path.exists(cache_file):
            logging.warning(f'Cache file not found: {cache_file}')
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                result = json.load(f)
            logging.info(f'Analysis result loaded from cache: {cache_file}')
            return result
        except Exception as e:
            logging.error(f'Failed to load analysis cache: {e}')
            return None
