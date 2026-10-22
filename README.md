# 红楼梦人物 Agent

基于《红楼梦》的大观园互动项目，包含十二位人物、房间探索、逐句对话、人物立绘和入梦剧情。

从 [embedding](https://github.com/yun469736-debug/embedding) 中单独整理，保留项目所需代码与运行素材。

## 技术与依赖

- 前端：Vue 3、TypeScript、Vite。
- 后端：Python 3.12、FastAPI。
- 服务：MySQL、Milvus、Ollama（qwen3.5:4b 和 bge-m3）；前端也支持填写 DeepSeek 密钥。

## 本地启动

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r agent/requirements.txt
Copy-Item agent/.env.example .env
# 修改 .env 中的数据库、模型及向量库配置
.\.venv\Scripts\python.exe -m uvicorn agent.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

打开 http://localhost:5173 。完整对话需要配置好数据库和模型服务。
本地 .env、日志、虚拟环境、node_modules 与构建产物不提交到仓库。

## 文档

- [后端说明](agent/README.md)
- [架构](ARCHITECTURE.md)
- [前端开发](FRONTEND_DEVELOPMENT.md)
- [原著检索初始化与文件范围](README-本地说明.md)

运行图片已包含在 frontend/public/assets 中；重新生成图片的脚本需要原仓库的 PNG 源素材。
