---
name: qpc
description: Read and write the user's QPC personal knowledge base in Lark Bitable. Use for QPC, 知识库, 记一下, or requests to record knowledge. A successful write requires a record_id and matching API read-back.
---

# QPC 知识库

QPC 保存跨项目、跨机器的长期知识。用户要求记入 QPC 时，必须进入 Lark Bitable 流程；Mem0 和本地文件不能作为 QPC 写入回执。

## 写入流程

1. 将知识整理为独立可读、带来源和日期的记录；保留原始数据，不自行修正无法确认的数字。发现合计不符时明确标注。
2. 在工作区准备 UTF-8 JSON，恰好包含四个字段：`个人知识类型`（问题Q / 实践P / 事实C）、`标题`（最多 50 字）、`原始记录`、`状态`（已整理 / 待整理）。不改表头，不创建字段或选项。
3. 使用发布版本附带的助手脚本，凭据由脚本从受限文件读取，不复制到代码或输出：

```bash
cd /home/caozuohua99/.hermes-lite/hermes-agent
/home/caozuohua99/.hermes-lite/venv/bin/python -m scripts.qpc_receipt --env-file /home/caozuohua99/.hermes-lite/.env.lark --record-file /绝对路径/record.json
```

`--dry-run` 仅验证字段和权限相关读取，不创建记录。脚本校验实际 schema，使用持久意图记录，创建后按 `record_id` 回读四个字段。

4. 只有结果为 `status=confirmed`、具有 `record_id` 且回读匹配，才能回复“已记入 QPC”，并附记录 ID。`validated` 只是预检通过。
5. 若返回 `pending_confirmation`，告知“结果待确认”，保留请求 ID。再次运行同一 JSON 会先查找结果；禁止另写 POST 脚本绕过意图记录。权限不足、接口错误、读取失败和超时均不能宣称完成。

## 查询与治理

用 Lark Bitable API 分页读取记录，搜索标题与原始记录；遇到筛选错误可全量分页后本地匹配。不要推断平台普遍不支持中文筛选。当前账户使用国际版 `open.larksuite.com`。

保留自研项目的历史知识。纠错、合并须保存原文及原 ID 映射，默认不硬删除。研究笔记放知识库，操作方法放技能；不把助手建议或未完成的计划描述成用户事实或已完成事项。

不得降低凭据文件权限、打印访问令牌、关闭 TLS 校验，或将运行日志和临时状态当作长期知识。
