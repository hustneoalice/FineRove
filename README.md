# FineRove · 研潮

基于 Octop 的 AI 投资工作台，接入驭潮行情与 NEO 核心指标服务。当前处于集成开发阶段，不是已完成的投资终端。

## 本地运行

需要 Python 3.12+、uv、Node.js 与 npm。

```sh
uv sync --frozen
cd dashboard
npm ci
npm run build
cd ..
uv run finerove paths
uv run finerove run
```

默认仅监听 `127.0.0.1:8098`，配置、数据库、专家工作区、插件与日志默认放在 `~/.finerove`。启动后按首次配置向导完成自己的账号和模型设置。

`FINEROVE_HOME` 可指定独立存储目录；`FINEROVE_PORT`、`FINEROVE_BIND_HOST` 可调整监听。继承的 `OCTOP_*` 设置会被清除，指向旧 `~/.octop` 的存储别名会被拒绝。不要复用原 Octop 的配置或数据库。这个隔离入口不等于操作系统文件访问沙箱。

```sh
FINEROVE_HOME="$PWD/.finerove" FINEROVE_PORT=8098 uv run finerove run
```

## NEO 核心指标

短线趋势、中线趋势、钱袋子、趋势柱线、主力吸筹、主力成本、核心标模型和六分段属于受保护能力。公开客户端不包含这些公式或模型权重；计算在独立授权的驭潮服务端执行。未配置或未接通的能力不会回退为本地计算，也不会生成演示值冒充结果。

投资研究页提供显式证券、日期与复权选择；首条接入能力为趋势柱线，其余指标保持未接通状态。该迁移公式尚未完成原模型逐点一致性验证。专家与 MCP 的身份桥接仍在逐步接入。微信、飞书和后台任务仍需完成各自的真实账号验收；底座具备接入机制不等于这些场景已全部交付。

## 私有计算服务配置

FineRove 进程需设置 `FINEROVE_NEO_BASE_URL`、至少 32 字符的 `FINEROVE_NEO_SIGNING_KEY` 与明确的实例标识 `FINEROVE_NEO_ISSUER`。远程服务必须使用 HTTPS；仅字面回环地址允许 HTTP。密钥仅保存在服务端环境中，不进入前端或仓库。

驭潮进程设置匹配的 `YUCHAO_NEO_SIGNING_KEY`、`YUCHAO_NEO_ISSUER`，以及 `YUCHAO_NEO_GRANTS_FILE` 指向独立授权 JSON 文件。文件按 FineRove 用户 ID 授权，例如：

```json
{
  "1": {
    "capabilities": ["neo.trend_histogram"],
    "expires_at": "2026-12-01T00:00:00+08:00"
  }
}
```

此处 ID 仅为结构示例，须对应实际账号。授权每次请求重读，撤销后下一次请求即拒绝；管理员也不绕过授权。只接受已结束日期的日线请求，最多返回 500 点。未配置服务时目录仍可查看，计算不可用。

## 来源与许可

FineRove 是独立项目，非腾讯云或 Octop 官方产品。平台源码来自 Octop 1.0.3b3，感谢 Octop 及其贡献者；原始 MIT 版权与完整许可保留在 [LICENSE](LICENSE)。上游说明见 [README.upstream.md](README.upstream.md)，来源记录见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

本仓库没有复制驭潮的核心算法。驭潮代码自身使用 AGPL-3.0-or-later；调用外部服务不改变该代码的既有许可，后续若复制其代码必须保留并核对相应义务。NEO 品牌不代表将公式移植或近似实现重新宣称为原创公式。
