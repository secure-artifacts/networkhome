# NetMonitor — 家用网络监控系统

> 实时监控家里所有电脑的上传/下载速度，网页可视化，支持 Windows 和 macOS

## 快速开始

### 第一步：在服务器电脑（选一台固定开机的 Windows）上安装服务器

```bat
双击 install_server.bat
# 安装完成后双击 start_server.bat 启动服务器
# 浏览器访问 http://本机IP:8866
```

### 第二步：在每台需要监控的电脑上安装客户端 Agent

**Windows 电脑：**
```bat
双击 install_agent.bat
# 安装完成后双击 start_agent.bat
# 首次运行输入服务器地址（例：http://192.168.1.100:8866）和本机名称
```

**macOS 电脑：**
```bash
bash install_agent.sh
bash start_agent.sh
# 首次运行同样会提示输入服务器地址和本机名称
```

---

## 功能

| 功能 | 说明 |
|------|------|
| 实时速度 | 每秒刷新，WebSocket 推送，零延迟 |
| 设备总览 | 所有电脑一页看，在线/离线状态 |
| 历史统计 | 日/周/月 上传下载总量及折线图 |
| 高峰分析 | 24小时热力图，直观看用网高峰 |

---

## 文件结构

```
网络检测/
├── server/              # 服务器（运行在一台电脑上）
│   ├── main.py          # FastAPI 主服务，端口 8866
│   ├── database.py      # SQLite 数据库操作
│   ├── scheduler.py     # 定时聚合（每小时）& 清理（每天）
│   ├── static/          # Web 前端
│   │   ├── index.html   # 总览页
│   │   ├── device.html  # 设备详情页
│   │   ├── style.css    # 样式
│   │   ├── app.js       # 总览页逻辑
│   │   └── device.js    # 详情页逻辑
│   └── requirements.txt
├── agent/               # 客户端（每台被监控电脑）
│   ├── agent.py         # 采集本机网速并上报
│   ├── config.json      # 配置（首次运行后自动生成）
│   └── requirements.txt
├── install_server.bat   # Windows 服务器一键安装
├── install_agent.bat    # Windows 客户端一键安装
└── install_agent.sh     # macOS 客户端一键安装
```

---

## 数据存储

- 数据库：`server/netmonitor.db`（SQLite，无需额外安装）
- 原始速度记录保留 **7 天**（自动清理）
- 小时聚合数据**永久保留**（用于历史统计）

---

## 安全说明

- 服务器仅在局域网内运行，**不暴露到公网**
- 建议在路由器防火墙上限制 8866 端口只允许 LAN 访问
- 如需外网访问，建议使用 VPN 或 SSH 隧道

---

## 依赖

- Python 3.9+
- 服务器：`fastapi`, `uvicorn`, `aiosqlite`, `apscheduler`, `psutil`
- 客户端：`psutil`, `requests`
