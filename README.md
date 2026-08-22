# Public API Skill

一个基于 [public-apis/public-apis](https://github.com/public-apis/public-apis) 的 Codex Skill。
它把上游 API 目录转换为可检索、可配置认证、支持代理访问，并能通过 GitHub Actions 自动增量同步的 Python Skill。

当前生成快照包含 **1,695 个接口**和 **51 个分类**。

## 特性

- 三层结构：Skill 说明 → 分类目录 → 单接口 JSON 定义
- 支持 `apiKey`、OAuth、`X-Mashape-Key` 和 User-Agent 认证策略
- 支持全局代理、单接口代理覆盖、HTTP/HTTPS 分流和环境变量代理
- API Key 和代理凭据支持环境变量，`--dry-run` 自动脱敏
- 使用语义指纹和目录摘要实现增量同步，避免上游 README 行号变化造成全量文件变更
- GitHub Action 每日检查上游并自动创建或更新同步 Pull Request
- 纯 Python 标准库运行，无需第三方运行时依赖

## 三层目录

| 层级 | 内容 |
| --- | --- |
| 第一层 | [SKILL.md](SKILL.md)：调用路由、安全规则和命令入口 |
| 第二层 | [references/catalog/INDEX.md](references/catalog/INDEX.md)：51 个分类目录 |
| 第三层 | [references/apis](references/apis)：每个 API 一个 JSON 接口定义 |

## 快速使用

```bash
# 搜索接口
python3 scripts/api_client.py list --search "weather"

# 按认证类型筛选
python3 scripts/api_client.py list --auth apiKey

# 查看单个接口
python3 scripts/api_client.py show animals/adoptapet

# 配置 base_url 后发起请求；先使用 dry-run 检查 URL 和认证
python3 scripts/api_client.py --config /path/to/config.json \
  request animals/adoptapet --path /v1/pets --query limit=10 --dry-run
```

上游仓库只提供文档链接和认证元数据，不提供每个服务的 OpenAPI 路径。因此接口定义中的 `request.base_url` 默认是 `null`，需要根据服务商文档配置真实地址。

## API Key 配置

复制 [assets/api-config.example.json](assets/api-config.example.json) 后按需编辑。推荐把密钥放在环境变量，不要提交到 Git：

```json
{
  "apis": {
    "animals/adoptapet": {
      "base_url": "https://api.provider.example",
      "auth": {
        "location": "header",
        "name": "X-API-Key",
        "value_env": "ADOPTAPET_API_KEY"
      }
    }
  }
}
```

认证配置优先级为：API 配置中的 `auth.value`、`auth.value_env` 指向的环境变量、接口定义中的默认环境变量名。

列出所有需要标准 API Key 的接口：

```bash
python3 scripts/api_client.py list --auth apiKey --json
```

## 代理配置

在 `defaults` 中设置全局代理：

```json
{
  "defaults": {
    "proxy": "http://127.0.0.1:7890"
  }
}
```

也可以分别配置 HTTP/HTTPS，或者在单个 API 的配置中覆盖全局代理：

```json
{
  "defaults": {
    "proxy": {
      "http": "http://proxy.example:8080",
      "https": "http://proxy.example:8080"
    }
  },
  "apis": {
    "animals/adoptapet": {
      "proxy": false
    }
  }
}
```

含账号密码的代理建议使用 `proxy_env` 从环境变量读取。完整配置说明见 [references/configuration.md](references/configuration.md)。

## 自动增量同步

[`.github/workflows/sync-public-apis.yml`](.github/workflows/sync-public-apis.yml) 会定时执行：

1. 抓取上游仓库的原子快照并记录 commit。
2. 运行 [scripts/sync_catalog.py](scripts/sync_catalog.py) 生成目录。
3. 使用 [scripts/validate_catalog.py](scripts/validate_catalog.py) 验证来源等价性和文件覆盖率。
4. 运行全部 Python 测试。
5. 仅在语义目录变化时推送 `automation/public-apis-sync` 分支，并创建或更新 Pull Request。

相同语义目录会直接短路；接口 JSON 不保存易变化的 README 行号和全局 commit，因此新增接口不会导致无关接口文件被重写。需要强制重建时执行：

```bash
python3 scripts/sync_catalog.py \
  --source /path/to/public-apis/README.md \
  --revision <commit> \
  --force
```

## 本地验证

```bash
PYTHONPATH=scripts python3 -m unittest discover -s scripts/tests -v
python3 scripts/validate_catalog.py --source /path/to/public-apis/README.md
```

## 设计与实现

同步器使用 Source Adapter、Markdown 状态机解析器、确定性 Slug Registry 和事务式生成器；调用器使用 Registry Facade、凭据 Provider Chain、认证 Strategy 和代理策略。详细设计见 [references/architecture.md](references/architecture.md)。

## 许可

目录数据遵循上游 MIT License，详见 [LICENSE](LICENSE)。
