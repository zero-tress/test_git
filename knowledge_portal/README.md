# PostgreSQL 视频知识工作台

服务地址：http://192.168.137.102:18773，可直接访问或由VS Code端口转发 。需登录项目专属账号videostudy_app。

完整身份、权限、密码设置与连接说明见 [ACCESS.md](ACCESS.md)。

## 功能和范围

- 视频与操作图：16段案例的数据库MP4播放/原件下载、SVG、HTML、结构JSON、节点七元组与完整分析。
- 技能知识：6类技能、18个既有版本，保留待验证状态。
- 表结构审阅：用户8项“保留”意见已导入。视频侧已落实，技能侧暂缓；浏览器可继续记录和导出意见。
- 数据库浏览：8张现有preview表，只有本项目内容。
- 登录后界面仅提供业务读取；项目数据库账号具备本项目CRUD，日常脚本默认使用此账号验证，不使用管理员回退。
- 原始文件和已有知识库不变；学习流水线仍保留文件输出，尚未自动将全部新增知识写进数据库。

数据库：videostudy_preview。当前schema：preview。表为imports、videos、cases、skill_versions、artifacts、analysis_runs、operation_graph_versions、reviews；产物原始字节实际存入BYTEA，结构及知识存入JSONB。

## 服务

复用服务器已有PostgreSQL18.1，项目独立实例位于.runtime/knowledge_portal/pgdata。未修改其他数据库、5432实例或系统服务。数据库无TCP监听；网页监听0.0.0.0:18773，仅允许本机与192.168.137.0/24访问；旧18772已关闭。原先本机独立SSH转发已停止，由用户通过VS Code管理转发。

在服务器终端使用study环境：

    cd /home/wj/codex-workspace/videostudy_operation
    conda run --no-capture-output -n study python -B knowledge_portal/service.py start
    conda run --no-capture-output -n study python -B knowledge_portal/service.py status
    conda run --no-capture-output -n study python -B knowledge_portal/service.py restart-web
    conda run --no-capture-output -n study python -B knowledge_portal/verify_preview.py

start保持已有数据；缺少预览表时要求显式维护，不自动用普通账号创建schema。restart-web只重启命令行匹配本项目server.py的网页进程。

权限初始化account.py仅用于已授权的管理员维护；普通存取使用db.py默认模式。正式迁移前先备份并确认schema；不通过提高日常账号权限来绕过拒绝。

## 验证

- 原394项测试通过；JavaScript语法检查通过。
- PostgreSQL密码认证和权限隔离、登录/退出会话、只读网页请求已实测。
- 160份产物往返字节一致；18份版本JSON一致；4,975份原始证据SHA256一致。
- 权限报告：.runtime/knowledge_portal/account_verification.json。
- 数据报告：.runtime/knowledge_portal/verification.json。
- 内置浏览器此前控制超时，页面视觉渲染未完成验收。

本轮视频与审阅迁移细节见 [VIDEO_MEDIA.md](VIDEO_MEDIA.md)。
