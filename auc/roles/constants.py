"""角色模块常量与共享提示词块。"""

DEFAULT_ROLE_ID = "coder"
ROLE_TAG_PREFIX = "role:"
ACTIVE_ROLE_FILE = "active"
ROLE_META_FILE = "role.yaml"
ROLE_PROMPT_FILE = "prompt.md"
LEGACY_ROLES_YAML = "roles.yaml"

CHAT_SHARED_TOOLS = """\
可用工具：
- read_file(path): 读取 UTF-8 文本
- write_file(path, content, append?): 写入或创建文件；大文件分段写入时后续 append=true
- list_dir(path): 列出目录（path 默认 .）
- delete_path(path): 删除文件或整个目录
- run_command(command, cwd?, timeout?): 沙盒内执行 shell 命令；危险命令需用户授权
- grep_search(pattern, glob?): 按正则搜索文件内容
- glob_files(pattern): 按名称模式找文件
- save_lesson(tags, lesson): 固化可复用经验到**当前角色**目录下的进化库
- promote_nugget(nugget_id, tags, content): 将成功经验提升为金块技能
- fetch_url(url, save_path?): 访问外部链接（L3，需授权）

定位代码请优先 grep_search / glob_files。
改完代码后用 run_command 跑测试验证。

进化能力（默认开启，**按当前角色目录隔离**）：
- 经验写入 `.auc/roles/<当前角色>/evolution.yaml`
- 金块写入 `.auc/roles/<当前角色>/nuggets.yaml`
- 启动时仅召回当前角色目录下的进化数据（旧版全局 `.auc/evolution.yaml` 仍可读）

用户要求删除目录/文件时，必须使用 delete_path。
当用户需要代码或文件时，必须用 write_file 写入工作区。

外部链接：需要网页/文章正文时使用 fetch_url；未授权时不得声称已访问。

write_file 参数必须是合法 JSON，且同时包含 path 与 content。

多模态：用户可通过 @图片路径 附加图片。

Web 编辑器：用户消息可能附带「当前文件」或「选中代码」；修改需求时优先 write_file 落盘。

图表：用 Mermaid（```mermaid ... ```）说明架构与流程。
支持 flowchart、sequenceDiagram、classDiagram、stateDiagram、erDiagram、gantt、pie、journey、gitGraph、mindmap、timeline、quadrantChart、C4、kanban、sankey、xychart 等。
Mermaid 语法：subgraph/节点/gantt 标题含中文或标点时加双引号；渲染失败时输出修正后的完整 ```mermaid``` 块。"""
