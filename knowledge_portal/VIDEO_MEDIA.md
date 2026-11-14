# 视频原件入库与表结构意见落实 · 2026-11-12

用户提供的JSON审阅意见位于reviews/知识库表结构审阅意见_20261112.json。8项均为“保留”，同时用户明确要求技能学习、技能数据库和技能页展示本轮不修改。

## 当前实现

- 16个原始MP4完整字节存入preview.videos.content（BYTEA），总计3,236,524字节。
- 原件保持原始HEVC编码，SHA256与既有视频身份一致。
- 使用服务器CPU、已有ffmpeg生成H.264/yuv420p/faststart MP4播放副本，存入同表playback_content，合计15,322,783字节。
- 原始文件没有替换或删除；临时转码文件在数据库入库成功后清理。
- “视频与操作图”标签顺序：视频MP4、操作图SVG、交互工作台、图结构JSON、节点七元组、完整分析、产物原件。
- 默认显示视频，可播放、拖动进度，下载原始MP4或H.264副本。
- 视频接口先验证项目账号，数据库查询使用只读事务。支持GET、HEAD、单段Range、ETag/If-Range、206和416响应。

## 数据结构

保留已有preview命名空间、数据库账号和访问规则。新增：

|表|当前记录|用途|
|---|---:|---|
|analysis_runs|16|关联视频与现有分析。status=imported；created_at是导入时间，不冒充原模型运行时间|
|operation_graph_versions|16|关联分析运行，保存现有语义图、内容哈希及未验证状态|
|reviews|8|记录用户对8项表结构方案的“保留”意见，不代表人工验证技能语义|

扩展videos的source_uri、split、原件、播放副本、大小与哈希字段；artifacts增加graph_version_id、renderer_version和dependencies；cases增加graph_version_id。未知的历史提示词版本和渲染器版本保持NULL，不编造来源。

兼容性：既有videos/artifacts的TEXT主键及cases短编号保留，避免破坏现有引用；新增运行、图版本和审核记录使用UUID。图版本当前没有历史父版本，parent_version_id为空。未迁移既有主键为UUID，后续若需统一应单独安排引用迁移。

reviews的reviewer=project_user_review只是来源标记；用户未提供实名，comment中明确记录该事实。正式审核、技能发布状态等机制仍待进一步落地。

## 技能冻结

skills、skill_versions、skill_evidence三项设计保留，但本轮不创建或迁移技能目录/证据表，不修改现有skill_versions字段和18条知识记录，也不修改skillPage/loadSkill前端代码、learn.py、video2op源码或文件知识库。

逐项比对结果保存在.runtime/knowledge_portal/migrations/video_media_20261112/before.json与迁移校验记录。网页的技能页、版本选择和技能API保持现有行为。

## 备份与验证

迁移前通过项目账号完成数据库备份：
.runtime/knowledge_portal/migrations/video_media_20261112/before.dump

迁移脚本migrate_video_media.py只对本项目进行已授权schema维护；数据回填使用videostudy_app。新表归videostudy_owner持有，项目账号仅获CRUD，无建库、建表或TRUNCATE能力。

verify_video_media.py验证16个原MP4往返、16个播放副本全片解码及持续时间、12项Range/HEAD场景、未登录访问拒绝、原件下载、审阅记录及技能冻结。

verify_preview.py继续核对160个原有产物、18个技能版本和4,975份原始证据；JavaScript语法与原394项测试均通过。

内置浏览器控制仍超时，未完成页面实际播放和视觉验收。API与文件解码通过不替代浏览器验收。
