# 依赖协议审计报告

**项目：** NetMonitor  
**审计日期：** 2026-03-01  
**审计范围：** 直接依赖（server/requirements.txt + agent/requirements.txt）  
**审计方法：** WebSearch 查询 PyPI 官方页面交叉验证

---

## 审计结论

> ✅ **合规通过** — 所有依赖均为宽松协议，无风险项，可安全发布

---

## 依赖协议汇总

| 包名 | 协议 | 风险 | 分类 |
|------|------|------|------|
| fastapi | MIT | ✅ | server |
| uvicorn\[standard\] | BSD-3-Clause | ✅ | server |
| psutil | BSD-3-Clause | ✅ | server + agent |
| aiosqlite | MIT | ✅ | server |
| apscheduler | MIT | ✅ | server |
| python-multipart | Apache-2.0 | ✅ | server |
| websockets | BSD-3-Clause | ✅ | server |
| requests | Apache-2.0 | ✅ | agent |

**合计：** 8 个直接依赖 | ✅ 低风险: 8 | ⚠️ 需关注: 0 | ❌ 需确认: 0

---

## 协议兼容性

所有依赖协议（MIT、BSD-3-Clause、Apache-2.0）均属于**宽松协议（Permissive License）**，与项目采用的 MIT 协议完全兼容，无 Copyleft 传染风险。

| 协议 | 商用 | 修改 | 分发 | 包含版权声明 |
|------|------|------|------|------|
| MIT | ✅ | ✅ | ✅ | 必须 |
| BSD-3-Clause | ✅ | ✅ | ✅ | 必须 |
| Apache-2.0 | ✅ | ✅ | ✅ | 必须 |

**分发要求：** 分发本项目时需在文档或软件中保留各依赖的版权声明（已在 `LICENSE` 文件中列出）。

---

## 生成的合规文件

| 文件 | 说明 |
|------|------|
| `LICENSE.LIST` | 依赖协议清单（含版本、协议、来源 URL） |
| `LICENSE` | 合规参考报告（项目协议 + 第三方声明） |
| `.agent/skills/license-audit/SKILL.md` | 持续检查 Skill，当 requirements.txt 变更时自动触发 |

---

## 后续建议

1. **固定版本号** — 建议将 requirements.txt 中的依赖固定到具体版本（如 `fastapi==0.115.0`），以便审计结果可溯源
2. **定期重审** — 建议每季度或依赖升级时重新执行本审计流程
3. **自动触发** — 已安装 Skill，今后修改 requirements.txt 时会自动提醒检查协议合规性

---

*本报告由依赖协议审计工具生成，参考标准：https://tpscsm-docs.pages.dev/license-audit/*
