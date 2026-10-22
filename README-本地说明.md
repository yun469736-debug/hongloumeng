# 红楼梦项目（按需下载）

来源：https://github.com/yun469736-debug/embedding
分支：main
目录清单对应提交：565a93970a12f936ea200fb3379a6deb4a59277a
下载日期：2026-10-22

保留了 200 个原仓库文件，已逐一通过 Git blob SHA-1 校验，文件内容未修改。
最初按独立文件快照下载，随后整理为独立 Git 仓库。

## 内容

- frontend/：Vue 前端及运行所需背景、建筑、人物 WebP 图片。
- agent/：人物 Agent 后端、配置示例和自检脚本。
- 《红楼梦》.txt：原著语料。
- my_milvus/：建表、导入、检索所需的四个共享工具。
- utils/：上述工具依赖的分块与文本处理模块。
- 项目架构、前端开发、林黛玉规格与验收文档。

未下载其他三部名著、实验与评估结果、bge_model，以及素材/里的重复原始 PNG。
前端已有可直接使用的图片；只有重新生成图片时，才需要另行下载原始素材。

## 安装和启动

先阅读 agent/README.md。当前仅下载文件，未安装依赖或启动服务。
后端需要 Python、Ollama 模型、MySQL 和 Milvus，连接信息在本地 .env 配置。

在本目录执行：

```powershell
python -m pip install -r agent/requirements.txt
Copy-Item agent/.env.example .env
# 按实际环境编辑 .env
python -m uvicorn agent.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

共享导入工具默认读取四部名著。本快照只含红楼梦；如需初始化原著检索，先配置好 Ollama/Milvus，
执行建表工具，再在项目根目录用以下命令限定只导入红楼梦：

```powershell
python my_milvus/create_four_classics_collection.py
python -c "import sys; sys.path.insert(0, 'my_milvus'); import import_four_classics as m; m.BOOK_FILES=('《红楼梦》.txt',); m.main()"
```
