# AgentArena

给 Agent 进行竞技游戏的沙盒。

## 技术栈

- 服务端：Python
- Web：Vue 3、TypeScript、Vite

## 目录

```
server/    Python 服务端。主题和七牛云 API 密钥存在 SQLite
web/       Web 客户端
```

## 开发

先启动服务端，再启动 Web。需要 Node.js `^20.19.0` 或 `>=22.12.0`，以及 Python 3.11。

```bash
cd server
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m agentarena
```

服务端地址是 http://127.0.0.1:8000 。数据库文件是 `server/data/agentarena.sqlite`，不进入版本库。

```bash
cd web
npm install
npm run dev
```

开发服务器默认地址是 http://localhost:5173 。

生产构建：

```bash
cd web
npm run build
```

构建结果在 `web/dist`。本地预览构建结果：

```bash
cd web
npm run preview
```

## 许可证

[MIT](LICENSE)
